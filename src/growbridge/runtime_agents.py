"""Model roles on the runtime's real services (architecture doc §4, §5.2).

Nothing here is reachable from ``Runtime.tick``: a model is only called when something calls
``run_agents``. A model failure is a task that needs attention and an alert, never a tick failure.
"""

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from growbridge.agents.context import project_context, task_language
from growbridge.agents.dispatch import Dispatcher, TraceSettings
from growbridge.agents.handlers import Deps, build_role_tools
from growbridge.agents.handlers_common import local_time
from growbridge.agents.llm import ModelClient
from growbridge.agents.memory import build_history
from growbridge.agents.memory_sources import MemorySources
from growbridge.agents.tools import ROLE_TOOLS, Tool
from growbridge.agents.trace import TRACE_DIR
from growbridge.archive.ids import new_id
from growbridge.archive.models import Budget, ResearchTask
from growbridge.config import RoleModel
from growbridge.observer.stage_checks import AUDIT_TASK, audit_task_key
from growbridge.planning.window import data_window
from growbridge.ports import Denied, StageRuntime
from growbridge.workflow.states import StageState, TaskState

log = logging.getLogger(__name__)

AUDIT_MAX_CALLS = 8
AUDIT_DAY_SECONDS = 86400.0
AUDIT_DEADLINE_SECONDS = 86400.0
AUDIT_ROLE = "auditor"
STAGE_REF = "stage:"  # an audit task's input reference to its stage


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
        timezone=runtime.settings.report_timezone,
        memory=memory_sources(runtime),
    )
    return build_role_tools(deps)


def memory_sources(runtime: Any) -> MemorySources:
    """What the memory of a model task is computed from."""
    return MemorySources(
        workflow=runtime.workflow,
        archive=runtime.archive,
        book=runtime.book,
        notes=getattr(runtime, "notes", None),
        holdout=runtime.holdout,
        clock=runtime.clock,
        timezone=runtime.settings.report_timezone,
        device_id=runtime.settings.device,
        multi_user=getattr(runtime, "access_parts", None) is not None,
    )


def make_dispatcher(
    runtime: Any,
    client: ModelClient,
    work_root: Path,
    *,
    roles: Mapping[str, RoleModel] | None = None,
    budget: Any = None,
    tracing: bool = True,
) -> Dispatcher:
    defaults = {AUDIT_ROLE: RoleModel(max_calls=AUDIT_MAX_CALLS)}
    if roles is None:
        roles = {
            name: runtime.settings.roles.get(name, defaults.get(name, RoleModel()))
            for name in ROLE_TOOLS
        }
    tools = role_tools(runtime, work_root)
    args = (client, roles, tools, runtime.tasks, budget or runtime.budget, runtime.clock)
    timezone = runtime.settings.report_timezone

    def context(task):
        base = project_context(runtime.workflow, runtime.control, timezone, task)
        shown = {item["round_id"] for item in base["rounds"]}
        history = build_history(memory_sources(runtime), task.project_id, shown)
        return {**base, "history": history}

    conversation = getattr(runtime, "conversation", None)
    return Dispatcher(
        *args,
        runtime.agents_db,
        context=context,
        conversation=conversation,
        trace=trace_settings(runtime) if tracing else None,
    )


def trace_settings(runtime: Any) -> TraceSettings | None:
    """Where and how runs are traced; None while ``model_trace`` is off, or when the trace
    directory cannot be made (runs then go untraced: a trace must never stop the agents)."""
    from growbridge.runtime import private_dir  # runtime imports this module

    settings = runtime.settings
    if not getattr(settings, "model_trace", False):
        return None
    data_dir = Path(settings.data_dir).absolute()  # the header holds an absolute path
    try:
        root = private_dir(data_dir / TRACE_DIR)
    except Exception:
        log.exception("cannot make the model trace directory in %s; runs go untraced", data_dir)
        return None
    recorded = settings.model_dump(mode="json", exclude={"token"})  # the token is the secret
    return TraceSettings(root, data_dir, getattr(runtime, "pre_run_copies", False), recorded)


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
        calls, cost = runtime.budget.remaining(project_id)
    except Denied:
        return False
    return calls > 0 and cost > 0  # with either spent the first model call would be refused


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
    zone = runtime.settings.report_timezone
    task = ResearchTask(
        id=new_id("task"),
        project_id=stage.project_id,
        question=(
            f"Audit stage {stage.stage_id} at {label}. Data window {local_time(start, zone)} to "
            f"{local_time(end, zone)} ({zone}). "
            "Compare the run sheet with the records since the last audit."
        ),
        owner_role=AUDIT_ROLE,
        budget=Budget(max_calls=AUDIT_MAX_CALLS, max_cost=1.0),
        trigger_event_id=trigger,
        correlation_id=new_id("audit"),
        input_refs=(f"{STAGE_REF}{stage.stage_id}",),
        deadline=now + AUDIT_DEADLINE_SECONDS,
        language=task_language(None, runtime.tasks, stage.project_id),
    )
    stored = runtime.tasks.create(task)
    return int(stored.id == task.id)


def _report_failure(runtime: Any, task: ResearchTask, message: str, *, failed: bool) -> None:
    """Alert on a model task that failed (``failed``: it raised) or needs attention. A top-level
    task gets no follow-up, so the alert is what keeps a round from stalling silently: critical.
    An audit is advisory and repeats every stage day, so its failures merge into one warning per
    stage."""
    outcome = "failed" if failed else "attention"
    if task.owner_role != AUDIT_ROLE:
        code = f"agent_task_{outcome}"  # agent_task_failed / agent_task_attention
        params = {"task_id": task.id, "project_id": task.project_id, "role": task.owner_role}
        scope = ("project", task.project_id)
        runtime.alert("agent_task", task.id, message, "critical", scope, code=code, params=params)
        return
    code = f"audit_task_{outcome}"  # audit_task_failed / audit_task_attention
    params = {"stage_id": _audit_stage(task), "task_id": task.id}
    scope = _audit_scope(task)
    runtime.alert(AUDIT_TASK, _audit_key(task), message, "warning", scope, code=code, params=params)


def _audit_stage(task: ResearchTask) -> str | None:
    """The stage an audit task names, or ``None``."""
    stages = (ref[len(STAGE_REF) :] for ref in task.input_refs if ref.startswith(STAGE_REF))
    return next(stages, None)


def _audit_key(task: ResearchTask) -> str:
    """The failed-audit warning an audit task reports to: its stage's, or its own when it names
    no stage."""
    return audit_task_key(_audit_stage(task) or task.id)


def _audit_scope(task: ResearchTask) -> tuple[str, str]:
    """The stage the audit was for, or its project when it names no stage."""
    stage = _audit_stage(task)
    return ("stage", stage) if stage is not None else ("project", task.project_id)


async def run_agents(runtime: Any, dispatcher: Any) -> int:
    """Run every open task owned by a model role once; returns how many runs finished."""
    try:
        schedule_audits(runtime)
    except Exception as error:
        log.exception("audit scheduling failed")
        message = f"{type(error).__name__}: {error}"
        runtime.alert("audit_schedule", "schedule", message, code="audit_schedule")
    else:
        runtime.resolve_alert("audit_schedule", "schedule")
    finished = 0
    for task in runtime.tasks.open_tasks(ROLE_TOOLS):
        try:
            run = await dispatcher.run_task(task.id)
        except Exception as error:
            log.exception("agent task %s failed", task.id)
            message = f"{task.id}: {type(error).__name__}: {error}"
            _report_failure(runtime, task, message, failed=True)
            continue
        finished += run is not None
        state = runtime.tasks.get(task.id).state
        # whether the run was refused or ended without delivering
        if state is TaskState.NEEDS_ATTENTION:
            _report_failure(runtime, task, f"model task {task.id} needs attention", failed=False)
        elif state is TaskState.DONE and task.owner_role == AUDIT_ROLE:
            # an audit that finished shows the stage's audits work again
            runtime.resolve_alert(AUDIT_TASK, _audit_key(task), _audit_scope(task))
    return finished
