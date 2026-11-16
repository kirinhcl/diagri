"""Model roles on the runtime's real services (architecture doc §4, §5.2).

Nothing here is reachable from ``Runtime.tick``: a model is only called when something calls
``run_agents``. A model failure is a task that needs attention and an alert, never a tick failure.
"""

import logging
from pathlib import Path
from typing import Any

from growbridge.agents.context import project_context
from growbridge.agents.dispatch import Dispatcher
from growbridge.agents.handlers import Deps, build_role_tools
from growbridge.agents.llm import ModelClient
from growbridge.agents.tools import ROLE_TOOLS, Tool
from growbridge.archive.ids import new_id
from growbridge.archive.models import Budget, ResearchTask
from growbridge.config import RoleModel
from growbridge.planning.window import data_window
from growbridge.ports import Denied, StageRuntime
from growbridge.workflow.states import StageState, TaskState

log = logging.getLogger(__name__)

AUDIT_MAX_CALLS = 6
AUDIT_DAY_SECONDS = 86400.0
AUDIT_DEADLINE_SECONDS = 86400.0
AUDIT_ROLE = "auditor"


def role_tools(runtime: Any, work_root: Path) -> dict[str, list[Tool]]:
    deps = Deps(
        workflow=runtime.workflow,
        control=runtime.control,
        archive=runtime.archive,
        tasks=runtime.tasks,
        clock=runtime.clock,
        work_root=work_root,
        compute=runtime.compute,
        runner=runtime.runner,
        sandbox=runtime.sandbox,
        search=None,
        holdout=runtime.holdout,
        alerts=runtime.book,
    )
    return build_role_tools(deps)


def make_dispatcher(runtime: Any, client: ModelClient, work_root: Path) -> Dispatcher:
    defaults = {AUDIT_ROLE: RoleModel(max_calls=AUDIT_MAX_CALLS)}
    roles = {
        name: runtime.settings.roles.get(name, defaults.get(name, RoleModel()))
        for name in ROLE_TOOLS
    }
    tools = role_tools(runtime, work_root)
    args = (client, roles, tools, runtime.tasks, runtime.budget, runtime.clock)
    timezone = runtime.settings.report_timezone

    def context(task):
        return project_context(runtime.workflow, runtime.control, timezone, task)

    conversation = getattr(runtime, "conversation", None)
    return Dispatcher(*args, runtime.agents_db, context=context, conversation=conversation)


def _audit_trigger(stage: StageRuntime, now: float) -> tuple[str, str] | None:
    """``(trigger, label)`` of the audit this stage is due, or None."""
    if stage.state in (StageState.ENDED, StageState.STOPPED):
        return f"audit:{stage.stage_id}:end", "the stage's end"
    if stage.state is not StageState.RUNNING or stage.started_at is None:
        return None
    day = int((now - stage.started_at) // AUDIT_DAY_SECONDS)
    if day < 1:
        return None
    return f"audit:{stage.stage_id}:day{day}", f"stage day {day}"


def _has_budget(runtime: Any, project_id: str) -> bool:
    try:
        calls, _cost = runtime.budget.remaining(project_id)
    except Denied:
        return False
    return calls > 0


def schedule_audits(runtime: Any) -> int:
    """Open an auditor task for the running stage once per passed stage day and once at its end.

    Only the model loop calls this, so a stage is only audited while a model is configured.
    Returns how many tasks were newly created."""
    stage = runtime.workflow.active_stage()
    if stage is None:
        return 0
    now = runtime.clock.now()
    due = _audit_trigger(stage, now)
    if due is None or not _has_budget(runtime, stage.project_id):
        return 0
    trigger, label = due
    prefix = f"audit:{stage.stage_id}:"
    open_audits = runtime.tasks.open_tasks((AUDIT_ROLE,))
    if any(t.trigger_event_id.startswith(prefix) for t in open_audits):
        return 0
    start, end = data_window(stage)
    task = ResearchTask(
        id=new_id("task"),
        project_id=stage.project_id,
        question=(
            f"Audit stage {stage.stage_id} at {label}. Data window {start:.0f} to {end:.0f} "
            "(epoch seconds). Compare the run sheet with the records since the last audit."
        ),
        owner_role=AUDIT_ROLE,
        budget=Budget(max_calls=AUDIT_MAX_CALLS, max_cost=1.0),
        trigger_event_id=trigger,
        correlation_id=new_id("audit"),
        input_refs=(f"stage:{stage.stage_id}",),
        deadline=now + AUDIT_DEADLINE_SECONDS,
    )
    stored = runtime.tasks.create(task)
    return int(stored.id == task.id)


async def run_agents(runtime: Any, dispatcher: Any) -> int:
    """Run every open task owned by a model role once; returns how many runs finished."""
    try:
        schedule_audits(runtime)
    except Exception as error:
        log.exception("audit scheduling failed")
        runtime.alert("audit_schedule", "schedule", f"{type(error).__name__}: {error}")
    finished = 0
    for task in runtime.tasks.open_tasks(ROLE_TOOLS):
        try:
            run = await dispatcher.run_task(task.id)
        except Exception as error:
            log.exception("agent task %s failed", task.id)
            runtime.alert("agent_task", task.id, f"{task.id}: {type(error).__name__}: {error}")
            continue
        finished += run is not None
        # whether the run raised, was refused or ended without delivering: a top-level task gets
        # no follow-up, so the alert is what keeps the round from stalling silently
        if runtime.tasks.get(task.id).state is TaskState.NEEDS_ATTENTION:
            runtime.alert("agent_task", task.id, f"model task {task.id} needs attention")
    return finished
