from pathlib import Path
from types import SimpleNamespace

import pytest

from growbridge import runtime_agents
from growbridge.agents.budget import CallBudget
from growbridge.archive.db import Database
from growbridge.archive.models import Budget
from growbridge.config import RoleModel
from growbridge.ports import StageRuntime
from growbridge.runtime_agents import (
    AUDIT_DAY_SECONDS,
    AUDIT_DEADLINE_SECONDS,
    AUDIT_MAX_CALLS,
    make_dispatcher,
    schedule_audits,
)
from growbridge.sim.clock import FakeClock
from growbridge.sim.fixtures import make_run_sheet
from growbridge.workflow.states import StageState, TaskState
from growbridge.workflow.tasks import TaskBoard

STAGE = "st1"
PROJECT = "p1"


class Stages:
    def __init__(self, started_at: float | None, state=StageState.RUNNING):
        self.started_at, self.state = started_at, state

    def active_stage(self):
        return StageRuntime(
            stage_id=STAGE,
            experiment_id="e1",
            project_id=PROJECT,
            state=self.state,
            run_sheet=make_run_sheet(duration_seconds=5 * 86400),
            started_at=self.started_at,
            ended_at=None if self.state is not StageState.ENDED else self.started_at + 86400,
        )


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "audit.db")
    yield database
    database.close()


def rig(db, state=StageState.RUNNING, budget=True, started=True):
    clock = FakeClock()
    board = TaskBoard(db, clock)
    calls = CallBudget(db, clock)
    if budget:
        calls.set(PROJECT, Budget(max_calls=50, max_cost=100.0))
    stages = Stages(clock.now() if started else None, state)
    runtime = SimpleNamespace(workflow=stages, tasks=board, budget=calls, clock=clock)
    return runtime


def audits(runtime):
    return runtime.tasks.list(PROJECT)


def test_no_audit_before_the_first_stage_day_has_passed(db):
    runtime = rig(db)
    runtime.clock.wall += AUDIT_DAY_SECONDS - 1

    assert schedule_audits(runtime) == 0
    assert audits(runtime) == ()


def test_one_audit_per_passed_stage_day(db):
    runtime = rig(db)
    runtime.clock.wall += AUDIT_DAY_SECONDS + 5

    assert schedule_audits(runtime) == 1
    assert schedule_audits(runtime) == 0

    (task,) = audits(runtime)
    assert task.trigger_event_id == f"audit:{STAGE}:day1"
    assert task.owner_role == "auditor"
    assert task.deadline == runtime.clock.now() + AUDIT_DEADLINE_SECONDS
    assert task.budget.max_calls == AUDIT_MAX_CALLS
    assert task.input_refs == (f"stage:{STAGE}",)
    assert STAGE in task.question and "stage day 1" in task.question


def test_no_new_audit_while_one_of_the_stage_is_open(db):
    runtime = rig(db)
    runtime.clock.wall += AUDIT_DAY_SECONDS + 5
    schedule_audits(runtime)
    runtime.clock.wall += 2 * AUDIT_DAY_SECONDS

    assert schedule_audits(runtime) == 0
    assert len(audits(runtime)) == 1


def test_a_closed_audit_lets_the_next_day_through(db):
    runtime = rig(db)
    runtime.clock.wall += AUDIT_DAY_SECONDS + 5
    schedule_audits(runtime)
    (first,) = audits(runtime)
    runtime.tasks.transition(first.id, TaskState.DONE, "done-1")
    runtime.clock.wall += AUDIT_DAY_SECONDS

    assert schedule_audits(runtime) == 1

    assert [t.trigger_event_id for t in audits(runtime)] == [
        f"audit:{STAGE}:day1",
        f"audit:{STAGE}:day2",
    ]


def test_an_ended_stage_gets_one_end_audit(db):
    runtime = rig(db, state=StageState.ENDED)

    assert schedule_audits(runtime) == 1
    assert schedule_audits(runtime) == 0

    (task,) = audits(runtime)
    assert task.trigger_event_id == f"audit:{STAGE}:end"
    assert "end" in task.question


def test_no_audit_for_a_project_without_a_call_budget(db):
    runtime = rig(db, budget=False)
    runtime.clock.wall += 2 * AUDIT_DAY_SECONDS

    assert schedule_audits(runtime) == 0
    assert audits(runtime) == ()


def test_no_audit_for_a_stage_not_started(db):
    runtime = rig(db, started=False)
    runtime.clock.wall += 2 * AUDIT_DAY_SECONDS

    assert schedule_audits(runtime) == 0


def test_no_audit_while_paused(db):
    runtime = rig(db, state=StageState.PAUSED)
    runtime.clock.wall += 2 * AUDIT_DAY_SECONDS

    assert schedule_audits(runtime) == 0


def test_the_auditor_runs_at_most_audit_max_calls_by_default(monkeypatch, db):
    monkeypatch.setattr(runtime_agents, "role_tools", lambda *_: {})
    settings = SimpleNamespace(roles={}, report_timezone="UTC")
    runtime = SimpleNamespace(settings=settings, tasks=None, budget=None, clock=None, agents_db=db)

    dispatcher = make_dispatcher(runtime, object(), Path("unused"))

    assert dispatcher.roles["auditor"].max_calls == AUDIT_MAX_CALLS
    assert dispatcher.roles["planner"].max_calls == RoleModel().max_calls


def test_a_configured_auditor_keeps_its_own_limit(monkeypatch, db):
    monkeypatch.setattr(runtime_agents, "role_tools", lambda *_: {})
    settings = SimpleNamespace(roles={"auditor": RoleModel(max_calls=2)}, report_timezone="UTC")
    runtime = SimpleNamespace(settings=settings, tasks=None, budget=None, clock=None, agents_db=db)

    dispatcher = make_dispatcher(runtime, object(), Path("unused"))

    assert dispatcher.roles["auditor"].max_calls == 2
