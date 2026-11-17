"""The inbox, alerts, environment, safety limits and compute overview show each operator their
own; administrators see everything."""

import json

import pytest
from workbench_support import Bench

from growbridge.archive.models import Budget, ResearchTask
from growbridge.ports import Actor
from growbridge.workflow.states import TaskState


@pytest.fixture
def bench(tmp_path):
    bench = Bench.full(tmp_path)
    for name, role in (("alice", "user"), ("bob", "user"), ("root", "admin")):
        bench.user(name, role)
    return bench


def _waiting_round(bench: Bench, owner: str, index: int) -> None:
    project = bench.workflow.create_project(f"{owner}-{index}", bench.actor(owner))
    bench.db.execute(
        "INSERT INTO wf_rounds(id, project_id, protocol_id, protocol_version, state, stages_done,"
        " awaiting_choice, created_at) VALUES (?, ?, 'p', 1, 'stage_review', 0, 'stage-x', ?)",
        (f"round-{owner}-{index}", project, float(index)),
    )
    task = ResearchTask(
        id=f"task-{owner}-{index}",
        project_id=project,
        question="q",
        owner_role="researcher",
        budget=Budget(max_calls=1, max_cost=1.0),
        trigger_event_id=f"ev-{owner}-{index}",
        correlation_id="c",
    )
    bench.tasks.create(task)
    bench.tasks.transition(task.id, TaskState.NEEDS_ATTENTION, f"ev-na-{task.id}", "stuck")


def _ids(client, kind: str) -> set[str]:
    return {item["id"] for item in client.get("/wb/inbox").json()["items"] if item["kind"] == kind}


def test_inbox_filters_before_sql_limit(bench):
    for index in range(60):
        _waiting_round(bench, "bob", index)
    _waiting_round(bench, "alice", 0)

    inbox = bench.user("alice").get("/wb/inbox").json()

    assert _ids(bench.user("alice"), "round_choice") == {"round-alice-0"}
    assert _ids(bench.user("alice"), "task") == {"task-alice-0"}
    assert inbox["truncated"] == {}
    assert len(_ids(bench.user("root"), "round_choice")) == 50  # the administrator's cap


def test_inbox_stage_items_are_the_owners(bench):
    bench.pending_as("alice")

    assert _ids(bench.user("alice"), "stage_review") == {"stage-1"}
    assert _ids(bench.user("bob"), "stage_review") == set()


def test_system_alerts_admin_only(bench):
    bench.alerts.raise_alert("backup_unconfigured", "backup", "warning", "no backup")

    assert bench.user("alice").get("/wb/alerts").json()["alerts"] == []
    assert [a["kind"] for a in bench.user("root").get("/wb/alerts").json()["alerts"]] == [
        "backup_unconfigured"
    ]
    assert _ids(bench.user("alice"), "alert") == set()


def test_device_alerts_follow_lock(bench):
    bench.lock("alice", "gh-01")
    alert = bench.alerts.raise_alert("frozen_reading", "temp", "warning", "frozen")

    assert [a["event_id"] for a in bench.user("alice").get("/wb/alerts").json()["alerts"]] == [
        alert.event_id
    ]
    assert bench.user("bob").get("/wb/alerts").json()["alerts"] == []


def _sample(bench: Bench, at: float, experiment_id: str | None = None) -> None:
    body = {"data": {"sensor": {"temp": 21.5}}, "experiment_id": experiment_id}
    bench.archive.db.execute("INSERT INTO samples(at, body) VALUES (?, ?)", (at, json.dumps(body)))


def test_environment_needs_lock(bench):
    response = bench.user("bob").get("/wb/environment")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "not_lock_holder"
    assert bench.user("root").get("/wb/environment").status_code == 200


def test_environment_starts_at_lock_time(bench):
    now = bench.clock.now()
    _sample(bench, now - 600)  # before alice locked the greenhouse
    bench.clock.advance(1)
    bench.lock("alice", "gh-01")

    body = bench.user("alice").get("/wb/environment").json()

    assert body["latest"] is None
    assert body["readings"]["total_samples"] == 0


def test_environment_hides_previous_stage_and_experiment(bench):
    bench.pending_as("bob")
    bench.workflow.approve("stage-1", bench.actor("bob"))
    bench.run(bench.workflow.start_stage("stage-1", bench.actor("bob")))
    bench.run(bench.workflow.stop_stage("stage-1", bench.actor("bob")))
    bench.run(bench.locks.release("gh-01", "bob"))
    bench.lock("alice", "gh-01")
    bench.clock.advance(5)
    _sample(bench, bench.clock.now(), "experiment-stage-1")  # still filed under bob's experiment

    body = bench.user("alice").get("/wb/environment").json()

    assert body["stage"] is None
    assert body["latest"]["experiment_id"] is None
    assert "experiment-stage-1" not in json.dumps(body)


def test_safety_needs_lock(bench):
    assert bench.user("bob").get("/wb/safety").json()["detail"]["code"] == "not_lock_holder"
    bench.lock("bob", "gh-01")
    assert bench.user("bob").get("/wb/safety").status_code == 200


def test_compute_overview_scoped(bench):
    bench.pending_as("alice")
    for owner in ("alice",):
        bench.tasks.create(
            ResearchTask(
                id=f"task-{owner}",
                project_id=bench.project_id,
                question="q",
                owner_role="researcher",
                budget=Budget(max_calls=1, max_cost=1.0),
                trigger_event_id=f"ev-c-{owner}",
                correlation_id="c",
            )
        )
    bench.compute.set_task_budget("task-alice", 2.0, 1.0)
    bench.compute.record_balance(100.0, "root", "granted")

    mine = bench.user("alice").get("/wb/compute").json()
    other = bench.user("bob").get("/wb/compute").json()
    admin = bench.user("root").get("/wb/compute").json()

    assert [t["task_id"] for t in mine["tasks"]] == ["task-alice"]
    assert mine["balance"] is None and mine["service"] is None
    assert other["tasks"] == []
    assert admin["balance"]["cpu_hours"] == 100.0


def test_admin_actor_is_unrestricted(bench):
    assert bench.access.is_admin(Actor(kind="operator", id="root", role="admin"))
