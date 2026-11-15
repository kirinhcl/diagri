"""Manual tasks of a stage: the list, done and skipped records, and the planned irrigation."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from growbridge.archive.models import Channel, ManualTask, RuleAction
from growbridge.sim.fixtures import make_run_sheet
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


def irrigate(bench, client, request_id="planned-0001", due_at=WATER_DUE, **fields):
    body = {"task_id": "water", "due_at": due_at, "request_id": request_id, **fields}
    return bench.post(client, f"{PATH}/irrigate", body)


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
    assert task["record"]["irrigation_request_id"] == "planned-0001"
    assert bench.state() == "running"  # no takeover, no intervention
    assert bench.workflow.interventions("experiment-stage-1") == ()

    again = irrigate(bench, operator, request_id="planned-0002")
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
        {"task_id": "photo", "due_at": PHOTO_DUE, "request_id": "planned-0001"},
    )
    paused = irrigate(bench, operator)

    assert detail(photo)["code"] == "scope"
    assert detail(paused)["code"] == "state"
    assert bench.control.irrigated == []
