from pathlib import Path
from types import SimpleNamespace

import pytest
from dispatch_helpers import make_task

from growbridge import runtime_agents
from growbridge.agents.budget import CallBudget
from growbridge.archive.db import Database
from growbridge.archive.models import Budget
from growbridge.config import RoleModel
from growbridge.observer.alerts import AlertBook
from growbridge.ports import StageRuntime
from growbridge.runtime_agents import (
    AUDIT_DAY_SECONDS,
    AUDIT_DEADLINE_SECONDS,
    AUDIT_MAX_CALLS,
    make_dispatcher,
    run_agents,
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
    book = AlertBook(db, clock)

    def resolve_alert(kind, key):
        # Runtime.resolve_alert's contract: never raises, False when not stored
        try:
            book.resolve(kind, key)
        except Exception:
            return False
        return True

    return SimpleNamespace(
        workflow=stages,
        tasks=board,
        budget=calls,
        clock=clock,
        book=book,
        alert=lambda kind, key, message, severity="critical", *, code=None, params=None: (
            book.raise_alert(kind, key, severity, message, code=code, params=params)
        ),
        resolve_alert=resolve_alert,
    )


def open_alerts(runtime):
    return {(a.kind, a.key): a for a in runtime.book.open()}


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


def test_no_audit_once_the_cost_budget_is_spent(db):
    runtime = rig(db)
    runtime.budget.charge(PROJECT, 100.0)
    runtime.clock.wall += 2 * AUDIT_DAY_SECONDS

    assert schedule_audits(runtime) == 0
    assert audits(runtime) == ()


def test_no_audit_once_no_call_is_left(db):
    runtime = rig(db)
    runtime.budget.reserve(PROJECT, 50)
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


async def test_the_schedule_alert_resolves_after_a_scheduling_that_did_not_raise(monkeypatch, db):
    runtime = rig(db)

    def broken(_runtime):
        raise RuntimeError("board is locked")

    monkeypatch.setattr(runtime_agents, "schedule_audits", broken)
    assert await run_agents(runtime, dispatcher=None) == 0
    assert ("audit_schedule", "schedule") in open_alerts(runtime)
    schedule = open_alerts(runtime)[("audit_schedule", "schedule")]
    assert (schedule.code, schedule.params) == ("audit_schedule", {})

    monkeypatch.undo()
    assert await run_agents(runtime, dispatcher=None) == 0

    assert open_alerts(runtime) == {}


class NeedsAttention:
    """A dispatcher whose every run ends in needs-attention, as a refused model call does."""

    def __init__(self, board):
        self.board = board

    async def run_task(self, task_id):
        self.board.transition(task_id, TaskState.NEEDS_ATTENTION, f"refused-{task_id}", "refused")
        return None


class Raises:
    async def run_task(self, task_id):
        raise RuntimeError("model unreachable")


class Finishes:
    """A dispatcher whose every run ends done, as a model run that finished does."""

    def __init__(self, board):
        self.board = board

    async def run_task(self, task_id):
        return self.board.transition(task_id, TaskState.DONE, f"done-{task_id}", "run finished")


async def test_an_alert_store_that_cannot_close_the_schedule_alert_does_not_stop_the_runs(db):
    runtime = rig(db, started=False)
    task = runtime.tasks.create(make_task("planner", "ev-plan", project_id=PROJECT))

    def locked(kind, key):
        raise RuntimeError("database is locked")

    runtime.book.resolve = locked

    await run_agents(runtime, NeedsAttention(runtime.tasks))

    assert runtime.tasks.get(task.id).state is TaskState.NEEDS_ATTENTION


async def test_an_audit_that_fails_on_two_stage_days_is_one_warning(db):
    runtime = rig(db)
    dispatcher = NeedsAttention(runtime.tasks)
    for _day in range(2):
        runtime.clock.wall += AUDIT_DAY_SECONDS + 5
        await run_agents(runtime, dispatcher)

    assert len(audits(runtime)) == 2
    (alert,) = runtime.book.open()
    assert (alert.kind, alert.key) == ("audit_task", f"audit:{STAGE}")
    assert (alert.severity, alert.count) == ("warning", 2)
    assert alert.code == "audit_task_attention"
    assert alert.params == {"stage_id": STAGE, "task_id": audits(runtime)[-1].id}


async def test_an_audit_that_ends_done_closes_its_stages_failed_audit_warning(db):
    runtime = rig(db)
    runtime.clock.wall += AUDIT_DAY_SECONDS + 5
    await run_agents(runtime, NeedsAttention(runtime.tasks))
    assert ("audit_task", f"audit:{STAGE}") in open_alerts(runtime)

    runtime.clock.wall += AUDIT_DAY_SECONDS
    await run_agents(runtime, Finishes(runtime.tasks))

    assert len(audits(runtime)) == 2
    assert open_alerts(runtime) == {}


async def test_an_audit_run_that_raises_is_a_warning_not_a_critical_alert(db):
    runtime = rig(db)
    runtime.clock.wall += AUDIT_DAY_SECONDS + 5

    await run_agents(runtime, Raises())

    (alert,) = runtime.book.open()
    assert (alert.kind, alert.key, alert.severity) == ("audit_task", f"audit:{STAGE}", "warning")
    assert alert.code == "audit_task_failed"
    assert alert.params == {"stage_id": STAGE, "task_id": audits(runtime)[-1].id}


async def test_an_audit_task_without_a_stage_reference_is_keyed_by_its_task(db):
    runtime = rig(db, started=False)
    task = runtime.tasks.create(make_task("auditor", "ev-loose", project_id=PROJECT))

    await run_agents(runtime, Raises())

    (alert,) = runtime.book.open()
    assert (alert.kind, alert.key, alert.severity) == ("audit_task", f"audit:{task.id}", "warning")
    assert alert.code == "audit_task_failed"
    assert alert.params == {"stage_id": None, "task_id": task.id}


async def test_another_roles_failing_task_is_still_a_critical_agent_task_alert(db):
    runtime = rig(db, started=False)
    task = runtime.tasks.create(make_task("planner", "ev-plan", project_id=PROJECT))

    await run_agents(runtime, NeedsAttention(runtime.tasks))

    (alert,) = runtime.book.open()
    assert (alert.kind, alert.key, alert.severity) == ("agent_task", task.id, "critical")


def test_an_audit_has_eight_model_calls_by_default():
    # raised from 6 after the final review, to leave slack for a refused or repeated call
    assert AUDIT_MAX_CALLS == 8


def test_an_audit_uses_the_projects_latest_goal_language_or_chinese(db):
    runtime = rig(db)
    runtime.clock.wall += AUDIT_DAY_SECONDS + 5
    schedule_audits(runtime)
    (first_audit,) = audits(runtime)
    runtime.tasks.transition(first_audit.id, TaskState.DONE, "done-1")
    runtime.tasks.create(
        make_task("orchestrator", "goal:p1:alice:1", project_id=PROJECT, language="en")
    )
    runtime.tasks.create(
        make_task("orchestrator", "goal:other:alice:1", project_id="other", language="zh")
    )
    runtime.clock.wall += AUDIT_DAY_SECONDS
    schedule_audits(runtime)

    first, second = (t for t in audits(runtime) if t.owner_role == "auditor")

    assert (first.language, second.language) == ("zh", "en")
