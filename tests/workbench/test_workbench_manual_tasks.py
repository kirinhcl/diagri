"""Manual tasks of a stage: the list, done and skipped records, and the planned irrigation."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from growbridge.archive.models import (
    ActionRecord,
    ActionState,
    Channel,
    ManualTask,
    RightKind,
    RuleAction,
    TaskRecord,
)
from growbridge.planning.manual_tasks import ON_TIME_SECONDS
from growbridge.sim.fixtures import make_run_sheet
from growbridge.workbench.manual_tasks import planned_request_id
from growbridge.workflow.states import StageState

ZONE = ZoneInfo("Europe/Helsinki")
STARTED = datetime(2026, 11, 14, 8, 0, tzinfo=ZONE).timestamp()
WATER_DUE = datetime(2026, 11, 14, 9, 0, tzinfo=ZONE).timestamp()
PHOTO_DUE = datetime(2026, 11, 14, 12, 0, tzinfo=ZONE).timestamp()
TASKS = (
    ManualTask(id="water", kind="irrigation", at="09:00", seconds=5),
    ManualTask(id="photo", kind="photo", at="12:00"),
)
PATH = "/wb/stages/stage-1/manual-tasks"


def detail(response) -> dict:
    return response.json()["detail"]


def running(bench, state=StageState.RUNNING, right_number=7):
    bench.seed_round()
    sheet = make_run_sheet(
        id="sheet-stage-1",
        project_id=bench.project_id,
        experiment_id="experiment-stage-1",
        stage_id="stage-1",
        duration_seconds=2 * 86400,
        manual_tasks=TASKS,
        end_actions=(RuleAction(channel=Channel.LIGHT, level=0),),
    )
    bench.workflow.submit_run_sheet(bench.round_id, sheet, bench.designer)
    store = bench.workflow.store
    store.update_stage(
        store.find_stage("stage-1"), state=state, started_at=STARTED, right_number=right_number
    )


def done(bench, client, task_id="water", due_at=WATER_DUE, **fields):
    body = {"task_id": task_id, "due_at": due_at, "outcome": "done", **fields}
    return bench.post(client, PATH, body)


def irrigate(bench, client, due_at=WATER_DUE, **fields):
    body = {"task_id": "water", "due_at": due_at, **fields}
    return bench.post(client, f"{PATH}/irrigate", body)


def run_id(attempt=1, due_at=WATER_DUE):
    return planned_request_id("stage-1", "water", due_at, attempt)


def test_the_list_shows_each_occurrence_with_its_state(bench, operator):
    running(bench)
    bench.clock.wall = WATER_DUE + 3 * 3600  # the watering is overdue, the photo is open

    body = operator.get(PATH).json()

    rows = body["occurrences"]
    assert [(r["task_id"], r["status"]) for r in rows[:3]] == [
        ("water", "missed"),
        ("photo", "open"),
        ("water", "upcoming"),
    ]
    assert len(rows) == 4 and rows[0]["seconds"] == 5 and rows[0]["record"] is None
    assert body["timezone"] == "Europe/Helsinki" and body["stage_state"] == "running"


def test_a_stage_that_has_not_started_has_nothing_due(bench, operator):
    bench.pending()

    assert operator.get(PATH).json()["occurrences"] == []
    assert done(bench, operator).status_code == 409


def test_done_and_skipped_are_recorded_and_the_latest_counts(bench, operator):
    running(bench)
    bench.clock.wall = PHOTO_DUE + 600

    first = done(bench, operator, "photo", PHOTO_DUE, note="tray 3")
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "done"
    assert first.json()["record"]["operator"] == "alice"
    assert first.json()["record"]["done_at"] == PHOTO_DUE + 600

    skipped = bench.post(
        operator, PATH, {"task_id": "water", "due_at": WATER_DUE, "outcome": "skipped"}
    )
    assert skipped.json()["status"] == "skipped"
    corrected = done(bench, operator, done_at=WATER_DUE + 300)
    assert corrected.json()["status"] == "done"
    records = bench.archive.task_records("experiment-stage-1")
    assert [(r.task_id, r.outcome) for r in records] == [
        ("photo", "done"),
        ("water", "skipped"),
        ("water", "done"),
    ]


@pytest.mark.parametrize(
    "fields, code",
    [
        ({"task_id": "nothing"}, "scope"),
        ({"due_at": WATER_DUE + 60}, "scope"),  # no occurrence at that time
        ({"done_at": WATER_DUE + 7200}, "param"),  # in the future
        ({"done_at": WATER_DUE - 7200}, "param"),  # long before it was due
    ],
)
def test_a_record_must_name_a_planned_occurrence_and_a_past_time(bench, operator, fields, code):
    running(bench)
    bench.clock.wall = WATER_DUE + 600

    response = done(bench, operator, **fields)

    assert detail(response)["code"] == code
    assert bench.archive.task_records("experiment-stage-1") == ()


def test_a_task_far_in_the_future_cannot_be_recorded(bench, operator):
    running(bench)
    bench.clock.wall = STARTED

    assert detail(done(bench, operator, "photo", PHOTO_DUE))["code"] == "state"


def test_models_cannot_record_manual_tasks(bench, operator):
    running(bench)
    bench.clock.wall = WATER_DUE

    response = bench.post(
        bench.lan,
        PATH,
        {"task_id": "water", "due_at": WATER_DUE, "outcome": "done"},
        headers=bench.model(),
    )

    assert response.status_code == 403


def test_a_planned_irrigation_runs_under_the_stage_right_and_is_recorded(bench, operator):
    running(bench, right_number=7)
    bench.clock.wall = WATER_DUE + 60

    response = irrigate(bench, operator)

    assert response.status_code == 200, response.text
    ((request, seconds, kind),) = bench.control.irrigated
    assert (request.channel, request.level, seconds, kind) == (Channel.PUMP, 1, 5, "planned")
    assert request.right_number == 7 and request.stage_id == "stage-1"
    task = response.json()["task"]
    assert task["status"] == "done"
    assert task["record"]["irrigation_request_id"] == request.request_id == run_id()
    assert task["record"]["ran_seconds"] == 5
    assert bench.state() == "running"  # no takeover, no intervention
    assert bench.workflow.interventions("experiment-stage-1") == ()

    again = irrigate(bench, operator)
    assert detail(again)["code"] == "state" and len(bench.control.irrigated) == 1


def test_a_planned_irrigation_needs_the_lan_entry(bench, operator):
    running(bench)
    bench.clock.wall = WATER_DUE
    assert bench.login(bench.overlay).status_code == 200

    response = irrigate(bench, bench.overlay)

    assert detail(response)["code"] == "entry" and bench.control.irrigated == []


def test_only_a_planned_irrigation_of_a_running_stage_can_be_started(bench, operator):
    running(bench, state=StageState.PAUSED, right_number=None)
    bench.clock.wall = PHOTO_DUE

    photo = bench.post(
        operator,
        f"{PATH}/irrigate",
        {"task_id": "photo", "due_at": PHOTO_DUE},
    )
    paused = irrigate(bench, operator)

    assert detail(photo)["code"] == "scope"
    assert detail(paused)["code"] == "state"
    assert bench.control.irrigated == []


def test_a_planned_irrigation_runs_the_pump_once_per_occurrence_even_after_a_skip(bench, operator):
    running(bench)
    bench.clock.wall = WATER_DUE + 60
    assert irrigate(bench, operator).status_code == 200
    skipped = {"task_id": "water", "due_at": WATER_DUE, "outcome": "skipped"}
    assert bench.post(operator, PATH, skipped).status_code == 200  # the latest record counts

    again = irrigate(bench, operator)

    assert detail(again)["code"] == "state"
    assert len(bench.control.irrigated) == 1


@pytest.mark.parametrize("late", [ON_TIME_SECONDS + 1, 30 * 3600])
def test_a_planned_irrigation_past_its_deadline_does_not_run(bench, operator, late):
    running(bench)
    bench.clock.wall = WATER_DUE + late

    response = irrigate(bench, operator)

    assert detail(response)["code"] == "state"
    assert bench.control.irrigated == []


def test_a_planned_irrigation_runs_up_to_its_deadline(bench, operator):
    running(bench)
    bench.clock.wall = WATER_DUE + ON_TIME_SECONDS

    response = irrigate(bench, operator)

    assert response.status_code == 200, response.text
    assert response.json()["task"]["status"] == "done"


def test_a_planned_irrigation_cut_short_is_recorded_as_partial(bench, operator):
    running(bench)
    bench.clock.wall = WATER_DUE + 60
    bench.control.irrigation_update = {"ran_seconds": 2.0, "ended_early": "hand-over: paused"}

    task = irrigate(bench, operator).json()["task"]

    assert task["status"] == "partial"
    assert task["record"]["outcome"] == "partial"
    assert task["record"]["ran_seconds"] == 2.0
    assert task["record"]["ended_early"] == "hand-over: paused"
    assert detail(irrigate(bench, operator))["code"] == "state"
    assert len(bench.control.irrigated) == 1


def test_an_unconfirmed_planned_irrigation_is_partial(bench, operator):
    running(bench)
    bench.clock.wall = WATER_DUE + 60
    unknown = {"state": ActionState.UNKNOWN, "error": "read-back unavailable", "ran_seconds": None}
    bench.control.irrigation_update = unknown

    record = irrigate(bench, operator).json()["task"]["record"]

    assert record["outcome"] == "partial" and record["ran_seconds"] is None
    assert record["ended_early"] == "the run was not confirmed (unknown): read-back unavailable"


def _left_behind(bench, attempt, state):
    """A run of an earlier request whose answer never came back (the request was cut off)."""
    bench.control.receipts[run_id(attempt)] = ActionRecord(
        request_id=run_id(attempt),
        state=state,
        channel=Channel.PUMP,
        planned_level=1,
        right_number=7,
        right_kind=RightKind.STAGE,
        trigger="planned irrigation water",
        created_at=WATER_DUE,
        sent_at=WATER_DUE,
    )


def test_a_retry_after_a_lost_answer_records_the_first_run_and_does_not_water_again(
    bench, operator
):
    running(bench)
    bench.clock.wall = WATER_DUE + 60
    _left_behind(bench, 1, ActionState.MAYBE_SENT)

    response = irrigate(bench, operator)

    assert bench.control.irrigated == []
    assert response.json()["action"]["request_id"] == run_id(1)
    assert response.json()["task"]["record"]["outcome"] == "partial"


def test_an_attempt_that_never_reached_the_pump_makes_way_for_the_next(bench, operator):
    running(bench)
    bench.clock.wall = WATER_DUE + 60
    _left_behind(bench, 1, ActionState.VOID)

    response = irrigate(bench, operator)

    ((request, _, _),) = bench.control.irrigated
    assert request.request_id == run_id(2)
    assert response.json()["task"]["status"] == "done"


def test_a_run_that_was_never_sent_is_not_recorded_and_may_be_tried_again(bench, operator):
    running(bench)
    bench.clock.wall = WATER_DUE + 60
    bench.control.irrigation_update = {"state": ActionState.FAILED, "error": "not sent: offline"}

    first = irrigate(bench, operator)
    bench.control.irrigation_update = {}
    again = irrigate(bench, operator)

    assert first.status_code == 200 and first.json()["task"] is None
    assert again.json()["task"]["status"] == "done"
    assert [r.request_id for r, *_ in bench.control.irrigated] == [run_id(1), run_id(2)]


def test_a_run_whose_read_back_failed_may_have_watered_and_is_partial(bench, operator):
    running(bench)
    bench.clock.wall = WATER_DUE + 60
    failed = {"state": ActionState.FAILED, "error": "read-back level differs from 1"}
    bench.control.irrigation_update = failed

    record = irrigate(bench, operator).json()["task"]["record"]

    assert record["outcome"] == "partial"
    assert detail(irrigate(bench, operator))["code"] == "state"
    assert len(bench.control.irrigated) == 1


def test_a_stage_stopped_early_lists_no_task_due_after_the_stop(bench, operator):
    """The list uses the stage's actual window, as a snapshot of it does."""
    running(bench, state=StageState.STOPPED, right_number=None)
    store = bench.workflow.store
    store.update_stage(store.find_stage("stage-1"), state_at=WATER_DUE + 3600)  # stopped 10:00
    bench.clock.wall = WATER_DUE + 4 * 3600

    rows = operator.get(PATH).json()["occurrences"]

    assert [(row["task_id"], row["due_at"]) for row in rows] == [("water", WATER_DUE)]


def test_a_cut_short_run_keeps_its_end_code_and_params_on_the_task_record(bench, operator):
    running(bench)
    bench.clock.wall = WATER_DUE + 60
    bench.control.irrigation_update = {
        "ran_seconds": 2.0,
        "ended_early": "protection write: rule",
        "ended_early_code": "protection_write",
        "ended_early_params": {"channel": "light"},
    }

    record = irrigate(bench, operator).json()["task"]["record"]

    assert record["ended_early"] == "protection write: rule"
    assert record["ended_early_code"] == "protection_write"
    assert record["ended_early_params"] == {"channel": "light"}


def test_a_run_that_was_not_confirmed_says_which_state_it_reached(bench, operator):
    running(bench)
    bench.clock.wall = WATER_DUE + 60
    unknown = {"state": ActionState.UNKNOWN, "error": "no receipt: x", "ran_seconds": None}
    bench.control.irrigation_update = unknown

    record = irrigate(bench, operator).json()["task"]["record"]

    assert record["ended_early"] == "the run was not confirmed (unknown): no receipt: x"
    assert record["ended_early_code"] == "not_confirmed"
    assert record["ended_early_params"] == {"action_state": "unknown"}


PUMP_OFF_UNCONFIRMED = {
    "state": ActionState.UNKNOWN,
    "error": "pump off unconfirmed; interlock set",
    "error_code": "pump_off_unconfirmed",
}
CUT_SHORT = {"ran_seconds": 2.0, "ended_early": "hand-over: paused", "ended_early_code": "handover"}


@pytest.mark.parametrize(
    ("early", "english"),
    [
        ({}, "the run was not confirmed (unknown): pump off unconfirmed; interlock set"),
        (CUT_SHORT, "hand-over: paused"),
    ],
    ids=["run-not-cut-short", "run-also-cut-short"],
)
def test_a_run_whose_pump_off_was_unconfirmed_says_the_pump_may_still_be_on(
    bench, operator, early, english
):
    """The pump may still be on and is locked: that wins over the early end and not confirmed."""
    running(bench)
    bench.clock.wall = WATER_DUE + 60
    bench.control.irrigation_update = {**PUMP_OFF_UNCONFIRMED, **early}

    record = irrigate(bench, operator).json()["task"]["record"]

    assert record["outcome"] == "partial"
    assert record["ended_early_code"] == "pump_off_unconfirmed"
    assert record["ended_early_params"] == {}
    assert record["ended_early"] == english  # the English stays as it was


def test_a_stored_task_record_without_the_early_end_code_still_reads():
    old = (
        '{"id": "t", "experiment_id": "e", "stage_id": "s", "task_id": "w", "kind": "irrigation",'
        ' "due_at": 1.0, "outcome": "partial", "done_at": 1.0, "operator": "a",'
        ' "recorded_at": 2.0, "ended_early": "hand-over: paused"}'
    )

    record = TaskRecord.model_validate_json(old)

    assert record.ended_early == "hand-over: paused"
    assert record.ended_early_code is None and record.ended_early_params == {}


def test_an_old_action_without_a_code_is_still_judged_by_its_english_text(bench, operator):
    running(bench)
    bench.clock.wall = WATER_DUE + 60
    bench.control.irrigation_update = {"state": ActionState.FAILED, "error": "not sent: offline"}

    assert irrigate(bench, operator).json()["task"] is None
