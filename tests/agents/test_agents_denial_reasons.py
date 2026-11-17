"""Refusals of the model tools and the budget carry a reason and params; models still read only
``denied (<code>): <message>``."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from agent_helpers import make_tool
from dispatch_env import Env

from growbridge.agents.handlers_common import (
    bind_task,
    bound_task,
    require_bound,
    require_project,
    require_round,
    scoped_snapshot,
    unavailable,
)
from growbridge.agents.handlers_report import own_task
from growbridge.agents.handlers_researcher import _end, _started_stage
from growbridge.agents.tools import build_toolset
from growbridge.archive.db import Database
from growbridge.archive.models import Budget
from growbridge.ports import Denied
from growbridge.sim.clock import FakeClock
from growbridge.sim.control import FakeControl
from growbridge.workflow.states import RoundState


@pytest.fixture
def env(tmp_path):
    clock = FakeClock()
    db = Database(tmp_path / "denials.db")
    yield Env(db, clock, FakeControl(clock), tmp_path / "work", tmp_path / "archive")
    db.close()


def _denied(call) -> Denied:
    with pytest.raises(Denied) as caught:
        call()
    return caught.value


def test_budget_calls_exhausted_carries_the_project(env):
    env.budget.set(env.project_id, Budget(max_calls=1, max_cost=50.0))
    env.budget.reserve(env.project_id)

    exc = _denied(lambda: env.budget.reserve(env.project_id))

    assert (exc.code, exc.reason) == ("budget", "budget_calls_exhausted")
    assert exc.params == {"project_id": env.project_id}


def test_budget_cost_exhausted_carries_the_project(env):
    env.budget.charge(env.project_id, 60.0)

    exc = _denied(lambda: env.budget.reserve(env.project_id))

    assert (exc.code, exc.reason) == ("budget", "budget_cost_exhausted")
    assert exc.params == {"project_id": env.project_id}


def test_budget_not_set_carries_the_project(env):
    exc = _denied(lambda: env.budget.reserve("project-none"))

    assert (exc.code, exc.reason) == ("budget", "budget_not_set")
    assert exc.params == {"project_id": "project-none"}


async def test_no_model_carries_the_role(env):
    task = env.task("planner")
    del env.roles["planner"]

    with pytest.raises(Denied) as caught:
        await env.dispatcher(None)._run(task, [], [])

    assert (caught.value.code, caught.value.reason) == ("model_role", "no_model")
    assert caught.value.params == {"role": "planner"}


def test_unknown_role_carries_the_role():
    exc = _denied(lambda: build_toolset("executor", [make_tool("get_project_state")]))

    assert (exc.code, exc.reason, exc.params) == (
        "model_role",
        "unknown_role",
        {"role": "executor"},
    )


def test_tool_not_allowed_carries_the_role():
    registry = [make_tool("freeze_dataset")]
    exc = _denied(lambda: build_toolset("orchestrator", registry, allowed=["freeze_dataset"]))

    assert (exc.code, exc.reason) == ("model_role", "tool_not_allowed")
    assert exc.params == {"role": "orchestrator"}


def test_no_run_has_no_params(env):
    exc = _denied(lambda: bound_task(env.deps))

    assert (exc.code, exc.reason, exc.params) == ("scope", "no_run", {})


def test_not_this_run_has_no_params(env):
    task = env.task("auditor")

    def call():
        with bind_task(task.id):
            require_bound(env.deps, "task-other")

    exc = _denied(call)
    assert (exc.code, exc.reason, exc.params) == ("scope", "not_this_run", {})


def test_a_snapshot_that_is_not_there_is_not_this_run(env):
    task = env.task("researcher")
    exc = _denied(lambda: scoped_snapshot(env.deps, task, "snap-none"))

    assert (exc.code, exc.reason, exc.params) == ("scope", "not_this_run", {})


def test_not_this_project_carries_the_project_named(env):
    other, _ = env.other_project()
    task = env.task("researcher")

    def call():
        with bind_task(task.id):
            require_project(env.deps, other)

    exc = _denied(call)
    assert (exc.code, exc.reason, exc.params) == (
        "scope",
        "not_this_project",
        {"project_id": other},
    )


def test_a_round_of_another_project_is_not_this_project(env):
    other, other_round = env.other_project()
    exc = _denied(lambda: require_round(env.deps, other_round, RoundState.ANALYSIS, env.project_id))

    assert (exc.code, exc.reason) == ("scope", "not_this_project")
    assert exc.params == {"project_id": env.project_id}


def test_round_wrong_phase_carries_both_states(env):
    exc = _denied(
        lambda: require_round(env.deps, env.round_id, RoundState.ANALYSIS, env.project_id)
    )

    assert (exc.code, exc.reason) == ("state", "round_wrong_phase")
    assert exc.params == {
        "round_id": env.round_id,
        "state": env.workflow.round_state(env.round_id).value,
        "needed_state": "analysis",
    }


def test_wrong_task_kind_does_not_know_the_kind(env):
    task = env.task("planner")

    def call():
        with bind_task(task.id):
            own_task(env.deps, task.id)

    exc = _denied(call)
    assert (exc.code, exc.reason, exc.params) == ("scope", "wrong_task_kind", {"task_kind": None})


def test_unavailable_has_no_params():
    exc = _denied(lambda: unavailable("sandbox"))

    assert (exc.code, exc.reason, exc.params) == ("unavailable", "unavailable", {})


async def test_a_stage_that_never_started_carries_the_stage(env):
    env.workflow.submit_run_sheet(env.round_id, env.sheet(), env.operator)

    exc = await env.refusal("auditor", "inspect_stage_data", stage_id="stage-1")

    assert (exc.code, exc.reason) == ("state", "stage_not_started")
    assert exc.params == {"stage_id": "stage-1"}


def test_a_stage_without_a_window_end_never_started(env):
    stage = SimpleNamespace(stage_id="stage-1", window_end=lambda: None)

    exc = _denied(lambda: _end(stage))

    assert (exc.reason, exc.params) == ("stage_not_started", {"stage_id": "stage-1"})


def test_a_stage_of_another_project_is_not_this_run(env):
    env.other_project()
    task = env.task("researcher")

    def call():
        with bind_task(task.id):
            _started_stage(env.deps, task.id, "stage-b")

    exc = _denied(call)
    assert (exc.code, exc.reason, exc.params) == ("scope", "not_this_run", {})


async def test_alert_book_unavailable_keeps_the_state_code(env):
    env.workflow.submit_run_sheet(env.round_id, env.sheet(), env.operator)

    exc = await env.refusal(
        "auditor",
        "raise_audit_finding",
        stage_id="stage-1",
        severity="info",
        summary="s",
    )

    assert (exc.code, exc.reason, exc.params) == ("state", "alert_book_unavailable", {})


async def test_a_tool_result_for_a_model_has_no_reason_in_it(env):
    toolset = build_toolset("auditor", env.tools()["auditor"])

    outcome = await toolset.call("get_stage_records", {"task_id": "task-x", "stage_id": "stage-1"})

    assert outcome.is_error
    assert outcome.content == (
        "Error: denied (scope): no task is running: tools only work inside a dispatched run"
    )
    assert "no_run" not in outcome.content and "reason" not in outcome.content
