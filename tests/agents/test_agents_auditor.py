"""The auditor role's tools: read a stage's records, raise only an advisory finding."""

from __future__ import annotations

import json

import pytest
from dispatch_env import Env
from pydantic import ValidationError

from growbridge.agents.handlers_auditor import FindingInput
from growbridge.agents.handlers_common import bind_task
from growbridge.agents.handlers_researcher import InspectInput, _inspect, stage_preview
from growbridge.agents.tools import build_toolset
from growbridge.archive.db import Database
from growbridge.archive.models import ManualMeasurement, ManualTask
from growbridge.observer.alerts import AlertBook
from growbridge.research.holdout import HoldoutRegistry
from growbridge.sim.clock import START, FakeClock
from growbridge.sim.control import FakeControl


@pytest.fixture
def env(tmp_path):
    clock = FakeClock()
    db = Database(tmp_path / "auditor.db")
    env = Env(db, clock, FakeControl(clock), tmp_path / "work", tmp_path / "archive")
    env.book = AlertBook(db, clock)
    env.audit_deps = env.make_deps(alerts=env.book)
    yield env
    db.close()


async def _start(env) -> None:
    tasks = (ManualTask(id="photo-am", kind="photo", at="06:00"),)
    sheet = env.sheet(duration_seconds=10, manual_tasks=tasks)
    env.workflow.submit_run_sheet(env.round_id, sheet, env.operator)
    env.workflow.approve("stage-1", env.operator)
    await env.workflow.start_stage("stage-1", env.operator)


async def _call(env, name, deps=None, bound=None, **fields):
    deps = deps or env.audit_deps
    task_id = bound or env.task("auditor", "ev-aud").id
    toolset = build_toolset("auditor", env.tools(deps)["auditor"])
    with bind_task(task_id):
        return await toolset.call(name, {"task_id": task_id, **fields})


def _body(outcome) -> dict:
    assert not outcome.is_error, outcome.content
    return json.loads(outcome.content)


def _measure(env, mid: str, measured_at: float, metric="height", batch="b", value=3.0) -> None:
    env.archive.add_measurement(
        ManualMeasurement(
            id=mid,
            experiment_id="experiment-stage-1",
            batch=batch,
            plant_id="p1",
            layout_version="v1",
            measured_at=measured_at,
            position="t1",
            method="ruler",
            metric=metric,
            value=value,
            unit="cm",
            operator="op-1",
        )
    )


def _held_out_deps(env):
    """Deps with a holdout of batch ``batch-h``'s ``yield`` outcomes registered."""
    registry = HoldoutRegistry(env.db, env.clock)
    registry.register(env.project_id, "hold-1", ["batch-h"], ["yield"], ["d-1", "d-2", "d-3"])
    return env.make_deps(alerts=env.book, holdout=registry)


async def test_get_stage_records_lists_tasks_measurements_and_open_alerts(env):
    await _start(env)
    _measure(env, "m-in", START + 1)
    env.book.raise_alert("stage_gap", "stage-1:x", "warning", "gap")
    env.book.raise_alert("stage_gap", "stage-2:x", "warning", "other stage")
    env.book.raise_alert("stage_gap", "stage-10:x", "warning", "a stage that shares the prefix")
    env.book.raise_alert("stage_gap", "stage-1b:x", "warning", "another one")
    env.book.raise_alert("stage_gap", "stage-b:x", "warning", "a stage of another project")
    env.clock.advance(5)

    body = _body(await _call(env, "get_stage_records", stage_id="stage-1"))

    assert body["stage"]["id"] == "stage-1" and body["window"][0] == START
    assert body["run_sheet"]["manual_tasks"]
    assert [m["id"] for m in body["measurements"]] == ["m-in"]
    assert body["measurements"][0]["in_window"] is True
    assert body["measurements_before_stage"] == 0
    assert [a["key"] for a in body["open_alerts"]] == ["stage-1:x"]
    for row in body["manual_tasks"]:
        assert {"status", "record"} <= set(row)


async def test_get_stage_records_counts_an_earlier_stages_measurements_without_listing_them(env):
    await _start(env)
    _measure(env, "m-earlier", START - 3600)  # the round's earlier stage shares the experiment
    _measure(env, "m-in", START + 1)
    _measure(env, "m-late", START + 10 + 3 * 3600)

    body = _body(await _call(env, "get_stage_records", stage_id="stage-1"))

    assert [(m["id"], m["in_window"]) for m in body["measurements"]] == [
        ("m-in", True),
        ("m-late", False),
    ]
    assert body["measurements_before_stage"] == 1
    assert "m-earlier" not in json.dumps(body)


async def test_get_stage_records_leaves_a_held_out_outcome_out(env):
    deps = _held_out_deps(env)
    await _start(env)
    _measure(env, "m-in", START + 1)
    _measure(env, "m-hold", START + 2, metric="yield", batch="batch-h", value=987.5)
    _measure(env, "m-hold-early", START - 60, metric="yield", batch="batch-h", value=986.5)

    outcome = await _call(env, "get_stage_records", deps, stage_id="stage-1")

    body = _body(outcome)
    assert [m["id"] for m in body["measurements"]] == ["m-in"]
    assert body["measurements_left_out"] == 0 and body["measurements_before_stage"] == 0
    assert "m-hold" not in outcome.content and "98" not in outcome.content


async def test_get_stage_records_hides_the_outside_window_alert_of_a_held_out_outcome(env):
    deps = _held_out_deps(env)
    await _start(env)
    late = START + 10 + 3 * 3600
    _measure(env, "m-late", late)
    _measure(env, "m-hold", late, metric="yield", batch="batch-h", value=987.5)
    for mid, metric in (("m-late", "height"), ("m-hold", "yield")):
        text = f"Measurement {mid} ({metric}) is dated outside the stage's data window"
        env.book.raise_alert("measurement_outside_window", f"stage-1:{mid}", "warning", text)

    outcome = await _call(env, "get_stage_records", deps, stage_id="stage-1")

    assert [a["key"] for a in _body(outcome)["open_alerts"]] == ["stage-1:m-late"]
    assert "m-hold" not in outcome.content and "yield" not in outcome.content


async def test_auditor_tools_refuse_another_project_and_an_unbound_run(env):
    env.other_project()
    await _start(env)

    foreign = await _call(env, "get_stage_records", stage_id="stage-b")
    wrong = await _call(
        env, "inspect_stage_data", stage_id="stage-1", bound=env.task("auditor", "ev-2").id
    )
    toolset = build_toolset("auditor", env.tools(env.audit_deps)["auditor"])
    unbound = await toolset.call("get_stage_records", {"task_id": "task-x", "stage_id": "stage-1"})

    assert foreign.is_error and "denied (scope)" in foreign.content
    assert not wrong.is_error  # its own bound task, started stage
    assert unbound.is_error and "denied (scope)" in unbound.content


async def test_inspect_refuses_a_stage_that_never_started(env):
    env.workflow.submit_run_sheet(env.round_id, env.sheet(), env.operator)

    outcome = await _call(env, "inspect_stage_data", stage_id="stage-1")

    assert outcome.is_error and "never started" in outcome.content


async def test_raise_audit_finding_records_a_warning_that_pauses_nothing(env):
    await _start(env)
    before = env.workflow.stage("stage-1").state

    body = _body(
        await _call(
            env,
            "raise_audit_finding",
            stage_id="stage-1",
            severity="warning",
            summary="light schedule not followed",
            evidence=("no light-on action at 06:00",),
        )
    )

    (alert,) = env.book.open()
    assert (alert.kind, alert.severity) == ("audit_finding", "warning")
    assert alert.key.startswith("stage-1:") and "no light-on action" in alert.message
    assert body["key"] == alert.key
    assert alert.code == "audit_finding"
    assert alert.params == {
        "stage_id": "stage-1",
        "summary": "light schedule not followed",
        "evidence": ["no light-on action at 06:00"],
    }
    assert alert.message == "light schedule not followed\nno light-on action at 06:00"
    assert env.workflow.stage("stage-1").state == before


async def test_raise_audit_finding_refuses_a_stage_of_another_project(env):
    env.other_project()
    await _start(env)

    outcome = await _call(
        env, "raise_audit_finding", stage_id="stage-b", severity="warning", summary="not mine"
    )

    assert outcome.is_error and "denied (scope)" in outcome.content
    assert env.book.open() == ()


async def test_raise_audit_finding_is_refused_without_an_alert_book(env):
    await _start(env)

    outcome = await _call(
        env,
        "raise_audit_finding",
        env.make_deps(),
        stage_id="stage-1",
        severity="info",
        summary="s",
    )

    assert outcome.is_error and "denied (state)" in outcome.content


def test_a_critical_finding_is_refused_by_the_input_model():
    with pytest.raises(ValidationError):
        FindingInput(task_id="t", stage_id="s", severity="critical", summary="x")


async def test_the_researcher_inspect_still_returns_the_same_preview(env):
    await _start(env)
    task = env.task("researcher", "ev-res")
    stage = env.workflow.stage("stage-1")
    with bind_task(task.id):
        viewed = _inspect(env.audit_deps, InspectInput(task_id=task.id, stage_id="stage-1"))

    assert viewed == stage_preview(env.audit_deps, stage)
