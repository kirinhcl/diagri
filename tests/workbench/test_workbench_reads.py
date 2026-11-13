import pytest

from growbridge.archive.models import Budget, ResearchTask, SampleRecord
from growbridge.sim.clock import FakeClock
from growbridge.sim.fixtures import make_safety
from growbridge.workbench.reads import ReadingsCache
from growbridge.workflow.states import StageState, TaskState

READS = [
    "/wb/inbox",
    "/wb/projects",
    "/wb/projects/p",
    "/wb/stages/s/readings",
    "/wb/stages/s/measurements",
    "/wb/stages/s/history",
    "/wb/safety",
]


@pytest.mark.parametrize("path", READS)
def test_reads_need_a_logged_in_operator(bench, path):
    response = bench.lan.get(path)
    assert response.status_code == 401 and response.json()["detail"]["code"] == "session"


@pytest.mark.parametrize("path", READS)
def test_reads_refuse_model_tokens(bench, path):
    response = bench.lan.get(path, headers=bench.model())
    assert response.status_code == 403 and response.json()["detail"]["code"] == "model_role"


def test_inbox_shows_a_stage_waiting_for_review(bench, operator):
    bench.pending()
    kinds = {(i["kind"], i["id"]) for i in operator.get("/wb/inbox").json()["items"]}
    assert ("stage_review", "stage-1") in kinds


def test_inbox_caps_each_kind_at_fifty(bench, operator):
    bench.seed_round()
    protocol_id = bench.workflow.store.db.one("SELECT id FROM wf_protocols")["id"]
    for _ in range(51):
        round_id = bench.workflow.create_round(bench.project_id, protocol_id, bench.designer)
        bench.workflow.store.update_round(round_id, awaiting_choice="stage-1")
    body = operator.get("/wb/inbox").json()
    assert sum(i["kind"] == "round_choice" for i in body["items"]) == 50
    assert body["truncated"]["round_choice"] == 1


def test_projects_and_project_detail(bench, operator):
    bench.seed_round()
    assert operator.get("/wb/projects").json()["projects"][0]["project_id"] == bench.project_id
    detail = operator.get(f"/wb/projects/{bench.project_id}").json()
    assert detail["rounds"][0]["round_id"] == bench.round_id and detail["budget"] is None
    assert detail["tasks"] == []


def test_an_unknown_project_is_a_state_refusal(operator):
    response = operator.get("/wb/projects/nope")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "state"


def test_readings_of_a_stage_not_started_are_empty(bench, operator):
    bench.pending()
    body = operator.get("/wb/stages/stage-1/readings").json()
    assert body["samples"] == [] and body["window"] is None


@pytest.mark.parametrize("points", [1, 2001])
def test_readings_points_out_of_range_are_rejected(bench, operator, points):
    bench.pending()
    assert operator.get(f"/wb/stages/stage-1/readings?points={points}").status_code == 422


def test_readings_cover_only_the_stage_window(bench, operator):
    bench.pending()
    store = bench.workflow.store
    store.update_stage(store.find_stage("stage-1"), started_at=100.0)
    for name, at in (("a", 50.0), ("b", 150.0)):
        bench.archive.append_sample(
            SampleRecord(
                id=name,
                experiment_id="experiment-stage-1",
                stage_id="stage-1",
                device_id="d1",
                captured_at=at,
                received_at=at,
                clock_synced=True,
                data={"temperature_c": 20.0},
            )
        )
    bench.clock.wall = 200.0
    stamps = [s["timestamp"] for s in operator.get("/wb/stages/stage-1/readings").json()["samples"]]
    assert stamps == [150]


def _sample(bench, name, at):
    bench.archive.append_sample(
        SampleRecord(
            id=name,
            experiment_id="experiment-stage-1",
            stage_id="stage-1",
            device_id="d1",
            captured_at=at,
            received_at=at,
            clock_synced=True,
            data={"temperature_c": 20.0},
        )
    )


def _stamps(operator, points=600):
    body = operator.get(f"/wb/stages/stage-1/readings?points={points}").json()
    return [sample["timestamp"] for sample in body["samples"]]


def test_a_finished_stage_shows_readings_only_up_to_when_it_finished(bench, operator):
    bench.pending()
    store = bench.workflow.store
    row = store.find_stage("stage-1")
    store.update_stage(row, started_at=100.0, state=StageState.ENDED, state_at=200.0)
    for name, at in (("a", 150.0), ("b", 250.0)):
        _sample(bench, name, at)
    bench.clock.wall = 300.0
    assert _stamps(operator) == [150]


def test_readings_are_kept_for_fifteen_seconds_per_stage_and_points(bench, operator):
    bench.pending()
    store = bench.workflow.store
    store.update_stage(store.find_stage("stage-1"), started_at=100.0)
    _sample(bench, "a", 150.0)
    bench.clock.wall = 200.0
    assert _stamps(operator) == [150]
    _sample(bench, "b", 190.0)
    bench.clock.advance(14)
    assert _stamps(operator) == [150]  # the same answer within the poll interval
    assert _stamps(operator, points=2000) == [150, 190]  # another point count is its own entry
    bench.clock.advance(1)
    assert _stamps(operator) == [150, 190]  # fresh once fifteen seconds have passed


def test_the_readings_cache_holds_a_bounded_number_of_entries():
    clock = FakeClock()
    cache = ReadingsCache(clock, seconds=15.0, size=2)
    computed = []

    def compute(key):
        def run():
            computed.append(key)
            return {"key": key}

        return run

    for key in (("s1", 600), ("s2", 600), ("s1", 600), ("s3", 600), ("s1", 600), ("s2", 600)):
        cache.get(key, compute(key))
    assert computed == [("s1", 600), ("s2", 600), ("s3", 600), ("s2", 600)]
    assert len(cache) == 2


def test_round_choice_is_dated_by_when_its_stage_stopped(bench, operator):
    bench.pending()
    store = bench.workflow.store
    store.update_stage(store.find_stage("stage-1"), state=StageState.STOPPED, state_at=4321.0)
    store.update_round(bench.round_id, awaiting_choice="stage-1")
    items = [i for i in operator.get("/wb/inbox").json()["items"] if i["kind"] == "round_choice"]
    assert [(i["since"], i["detail"]["since_from"]) for i in items] == [(4321.0, "stage_stopped")]


def test_round_choice_without_a_stopped_stage_is_dated_by_the_round_and_says_so(bench, operator):
    bench.seed_round()
    created = store_round_created(bench)
    bench.workflow.store.update_round(bench.round_id, awaiting_choice="stage-gone")
    items = [i for i in operator.get("/wb/inbox").json()["items"] if i["kind"] == "round_choice"]
    assert [(i["since"], i["detail"]["since_from"]) for i in items] == [(created, "round_created")]


def store_round_created(bench):
    return bench.workflow.store.db.one(
        "SELECT created_at FROM wf_rounds WHERE id = ?", (bench.round_id,)
    )["created_at"]


def test_history_of_a_stage_lists_its_transitions(bench, operator):
    bench.pending()  # a submitted stage has no transition yet; record one
    bench.workflow.store.add_history("stage-1", 5.0, "pending_review", "running", "start", {})
    body = operator.get("/wb/stages/stage-1/history").json()
    assert [entry["to"] for entry in body["history"]] == ["running"]
    assert body["interventions"] == []


def test_an_unknown_stage_is_a_state_refusal(operator):
    response = operator.get("/wb/stages/nope/history")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "state"


def test_safety_is_null_until_approved(bench, operator):
    bench.control.safety_config = None  # the recording control starts out approved
    assert operator.get("/wb/safety").json() == {"safety": None}
    bench.control.approve_safety(make_safety(), "alice")
    assert operator.get("/wb/safety").json()["safety"] is not None


def test_me_reports_the_timezone(operator):
    assert operator.get("/wb/me").json()["timezone"] == "UTC"


def test_reads_work_on_the_overlay_entry(bench):
    assert bench.login(bench.overlay).status_code == 200
    assert bench.overlay.get("/wb/inbox").status_code == 200


def test_inbox_drops_alerts_an_operator_has_read(bench, operator):
    alert = bench.alerts.raise_alert("threshold", "too_hot", "critical", "31 C")
    kinds = [i["kind"] for i in operator.get("/wb/inbox").json()["items"]]
    assert kinds.count("alert") == 1
    assert bench.post(operator, f"/wb/alerts/{alert.event_id}/read").status_code == 200
    kinds = [i["kind"] for i in operator.get("/wb/inbox").json()["items"]]
    assert "alert" not in kinds


def test_a_task_item_is_dated_by_its_last_state_change(bench, operator):
    task = ResearchTask(
        id="task-1",
        project_id="p1",
        question="does more light help?",
        owner_role="researcher",
        budget=Budget(max_calls=5, max_cost=1.0),
        trigger_event_id="ev-1",
        correlation_id="corr-1",
    )
    bench.tasks.create(task)
    bench.clock.wall = 777.0
    bench.tasks.transition("task-1", TaskState.NEEDS_ATTENTION, "ev-2", "stuck")
    bench.clock.wall = 900.0
    items = [i for i in operator.get("/wb/inbox").json()["items"] if i["kind"] == "task"]
    assert [(i["id"], i["since"]) for i in items] == [("task-1", 777.0)]


def test_inbox_shows_an_alert_raised_again_after_it_was_read(bench, operator):
    alert = bench.alerts.raise_alert("threshold", "too_hot", "warning", "31 C")
    assert bench.post(operator, f"/wb/alerts/{alert.event_id}/read").status_code == 200
    assert "alert" not in [i["kind"] for i in operator.get("/wb/inbox").json()["items"]]
    bench.clock.advance(60)
    bench.alerts.raise_alert("threshold", "too_hot", "critical", "35 C")
    items = operator.get("/wb/inbox").json()["items"]
    assert [i["id"] for i in items if i["kind"] == "alert"] == [alert.event_id]


def test_inbox_keeps_a_read_alert_hidden_while_it_is_raised_again_at_the_same_severity(
    bench, operator
):
    alert = bench.alerts.raise_alert("data_gap", "temperature", "warning", "no data")
    assert bench.post(operator, f"/wb/alerts/{alert.event_id}/read").status_code == 200
    for _ in range(3):  # the observer raises an ongoing gap again on every tick
        bench.clock.advance(5)
        bench.alerts.raise_alert("data_gap", "temperature", "warning", "no data")
    assert "alert" not in [i["kind"] for i in operator.get("/wb/inbox").json()["items"]]


def test_inbox_keeps_a_new_critical_alert_when_alerts_overflow(bench, operator):
    for number in range(50):
        bench.alerts.raise_alert("threshold", f"key-{number}", "warning", "warm")
    bench.clock.advance(60)
    critical = bench.alerts.raise_alert("threshold", "fresh", "critical", "35 C")
    body = operator.get("/wb/inbox").json()
    alerts = [i["id"] for i in body["items"] if i["kind"] == "alert"]
    assert len(alerts) == 50 and critical.event_id in alerts
    assert body["truncated"] == {"alert": 1}


def test_inbox_reports_no_truncation_when_nothing_is_cut(bench, operator):
    bench.pending()
    assert operator.get("/wb/inbox").json()["truncated"] == {}


def test_inbox_lists_fifty_tasks_counts_the_rest_and_dates_only_those(bench, operator, monkeypatch):
    for number in range(60):
        task = ResearchTask(
            id=f"task-{number}",
            project_id="p1",
            question="does more light help?",
            owner_role="researcher",
            budget=Budget(max_calls=5, max_cost=1.0),
            trigger_event_id=f"ev-{number}",
            correlation_id="corr-1",
        )
        bench.tasks.create(task)
        bench.tasks.transition(task.id, TaskState.NEEDS_ATTENTION, f"mv-{number}", "stuck")
    asked: list[int] = []
    original = bench.tasks.state_since
    monkeypatch.setattr(
        bench.tasks, "state_since", lambda ids: asked.append(len(list(ids))) or original(ids)
    )
    body = operator.get("/wb/inbox").json()
    assert sum(i["kind"] == "task" for i in body["items"]) == 50
    assert body["truncated"]["task"] == 10
    assert asked and max(asked) <= 50
