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


async def test_get_stage_records_lists_tasks_measurements_and_open_alerts(env):
    await _start(env)
    env.archive.add_measurement(
        ManualMeasurement(
            id="m-in",
            experiment_id="experiment-stage-1",
            batch="b",
            plant_id="p1",
            layout_version="v1",
            measured_at=START + 1,
            position="t1",
            method="ruler",
            metric="height",
            value=3.0,
            unit="cm",
            operator="op-1",
        )
    )
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
    assert [a["key"] for a in body["open_alerts"]] == ["stage-1:x"]
    for row in body["manual_tasks"]:
        assert {"status", "record"} <= set(row)


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
    assert env.workflow.stage("stage-1").state == before


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
