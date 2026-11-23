"""Workbench writes need the project's owner (and, on a stage, the greenhouse lock).

Another operator's request for an object they may not see is answered exactly as the same
request is answered where the object does not exist at all (the absent twin)."""

import pytest
from workbench_support import Bench

from growbridge.archive.models import Budget, ResearchTask
from growbridge.sim.fixtures import make_protocol

DIGEST = "0" * 64


@pytest.fixture
def world(tmp_path):
    bench = Bench.full(tmp_path)
    for name, role in (("alice", "user"), ("bob", "user"), ("root", "admin")):
        bench.user(name, role)
    bench.pending_as("alice")
    bench.tasks.create(
        ResearchTask(
            id="task-alice",
            project_id=bench.project_id,
            question="q",
            owner_role="researcher",
            budget=Budget(max_calls=1, max_cost=1.0),
            trigger_event_id="ev-alice",
            correlation_id="c",
        )
    )
    alert = bench.alerts.raise_alert(
        "task_missed", "stage-1:x", "warning", "m", ("stage", "stage-1")
    )
    return bench, alert.event_id


def writes(bench: Bench, event_id: str) -> list[tuple[str, dict]]:
    project, round_id = bench.project_id, bench.round_id
    protocol = make_protocol(project_id=project, id="protocol-b").model_dump(mode="json")
    measurement = {
        "experiment_id": "experiment-stage-1",
        "batch": "b",
        "plant_id": "p",
        "layout_version": "v",
        "measured_at": 1.0,
        "position": "x",
        "method": "m",
        "metric": "height",
        "value": 1.0,
        "unit": "cm",
    }
    return [
        ("/wb/stages/stage-1/approve", {"expected_digest": DIGEST}),
        ("/wb/stages/stage-1/start", {}),
        ("/wb/stages/stage-1/pause", {"reason": "x"}),
        ("/wb/stages/stage-1/resume", {}),
        ("/wb/stages/stage-1/stop", {}),
        ("/wb/stages/stage-1/takeover", {}),
        ("/wb/stages/stage-1/handback", {}),
        ("/wb/stages/stage-1/onsite-check", {"note": "x"}),
        ("/wb/manual/light", {"stage_id": "stage-1", "request_id": "req-0000001", "level": 10}),
        ("/wb/irrigation", {"stage_id": "stage-1", "request_id": "req-0000002", "seconds": 1}),
        ("/wb/stages/stage-1/manual-tasks", {"task_id": "t", "due_at": 0, "outcome": "done"}),
        ("/wb/stages/stage-1/manual-tasks/irrigate", {"task_id": "t", "due_at": 0}),
        ("/wb/measurements", measurement),
        ("/wb/protocols", {"protocol": protocol}),
        ("/wb/rounds", {"project_id": project, "protocol_id": "protocol-1"}),
        (f"/wb/rounds/{round_id}/choice", {"choice": "redo"}),
        (f"/wb/rounds/{round_id}/abort", {}),
        (f"/wb/rounds/{round_id}/evidence", {}),
        (f"/wb/projects/{project}/budget", {"max_calls": 1, "max_cost": 1.0}),
        ("/wb/goals", {"project_id": project, "goal": "grow"}),
        ("/wb/drafts/run-sheet", {"round_id": round_id, "run_sheet": _sheet(bench)}),
        ("/wb/protocols/protocol-1/analysis", {"project_id": project, "script": "print(1)"}),
        (
            "/wb/analysis/runs",
            {"project_id": project, "protocol_id": "protocol-1", "snapshot_id": "snap-1"},
        ),
        (
            "/wb/holdouts",
            {
                "project_id": project,
                "batch_ids": ["h"],
                "development_batch_ids": ["d"],
                "outcome_fields": ["y"],
            },
        ),
        ("/wb/compute/tasks/task-alice/budget", {"cpu_hours": 1, "storage_gb": 1}),
        (f"/wb/alerts/{event_id}/read", {}),
    ]


def _sheet(bench: Bench) -> dict:
    return bench.sheet("stage-9").model_dump(mode="json")


def answer(response) -> tuple[int, object]:
    return response.status_code, response.json()


@pytest.mark.parametrize("index", range(26))
def test_b_cannot_write_a(world, index):
    bench, event_id = world
    path, body = writes(bench, event_id)[index]
    twin = bench.absent_twin()

    seen = answer(bench.post(bench.user("bob"), path, body))
    absent = answer(twin.post(twin.user("bob"), path, body))

    assert seen == absent, path
    assert seen[0] >= 400


def test_a_can_write_own(world):
    bench, _event = world
    alice = bench.user("alice")
    project = bench.project_id

    assert (
        bench.post(
            alice, f"/wb/projects/{project}/budget", {"max_calls": 5, "max_cost": 1}
        ).status_code
        == 200
    )
    assert (
        bench.post(alice, "/wb/goals", {"project_id": project, "goal": "grow"}).status_code == 200
    )
    assert bench.approve(alice).status_code == 200


def test_compute_balance_admin_only(world):
    bench, _event = world
    body = {"cpu_hours": 10, "note": "granted"}

    refused = bench.post(bench.user("alice"), "/wb/compute/balance", body)

    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "admin_only"
    assert bench.post(bench.user("root"), "/wb/compute/balance", body).status_code == 200


def test_manual_write_and_irrigation_need_lock(world):
    bench, _event = world
    alice = bench.user("alice")
    bench.approve(alice)
    assert bench.post(alice, "/wb/stages/stage-1/start").status_code == 200
    assert bench.post(alice, "/wb/stages/stage-1/takeover").status_code == 200
    bench.db.execute("DELETE FROM greenhouse_locks")  # the lock is gone

    manual = {"stage_id": "stage-1", "request_id": "req-0000003", "level": 10}
    refused = bench.post(alice, "/wb/manual/light", manual)

    assert refused.json()["detail"]["code"] == "not_lock_holder"
    pump = {"stage_id": "stage-1", "request_id": "req-0000004", "seconds": 1}
    assert bench.post(alice, "/wb/irrigation", pump).json()["detail"]["code"] == "not_lock_holder"


def test_model_token_draft_refused_when_multi_user(world):
    bench, _event = world
    body = {"round_id": bench.round_id, "run_sheet": _sheet(bench)}

    response = bench.lan.post("/wb/drafts/run-sheet", json=body, headers=bench.model())

    assert response.json()["detail"]["code"] == "model_role"


def test_corrects_other_experiment_refused(world):
    bench, _event = world
    bob = bench.user("bob")
    bench.round_id = ""
    bench.lock("bob", "gh-02")
    bench.seed_round_as("bob", protocol_id="protocol-bob")
    sheet = bench.sheet("stage-b").model_copy(
        update={"device_id": "AC5-2", "protocol_id": "protocol-bob"}
    )
    bench.workflow.submit_run_sheet(bench.round_id, sheet, bench.actor("bob"))
    alice_record = {"id": "m-alice", "experiment_id": "experiment-stage-1", "batch": "b"}
    bench.archive.add_measurement(_measurement(**alice_record))

    body = _measurement(experiment_id="experiment-stage-b", corrects="m-alice").model_dump()
    response = bench.post(bob, "/wb/measurements", {**body, "id": None})

    assert response.status_code == 422
    assert [m.id for m in bench.archive.measurements("experiment-stage-1")] == ["m-alice"]


def test_goal_with_foreign_round_hidden(world):
    bench, _event = world
    alice_round = bench.round_id
    bob = bench.user("bob")
    bench.round_id = ""
    bench.lock("bob", "gh-02")
    bench.seed_round_as("bob", protocol_id="protocol-bob")
    body = {"project_id": bench.project_id, "goal": "x", "round_id": alice_round}

    response = bench.post(bob, "/wb/goals", body)
    unknown = bench.post(bob, "/wb/goals", {**body, "round_id": "round-nothing"})

    assert response.status_code == unknown.status_code
    assert response.json()["detail"]["message"] == f"unknown round {alice_round}"


def _measurement(**fields):
    from growbridge.archive.models import ManualMeasurement

    values = {
        "id": "m-1",
        "experiment_id": "experiment-stage-1",
        "batch": "b",
        "plant_id": "p",
        "layout_version": "v",
        "measured_at": 1.0,
        "position": "x",
        "method": "m",
        "metric": "height",
        "value": 1.0,
        "unit": "cm",
        "operator": "alice",
    }
    return ManualMeasurement(**{**values, **fields})
