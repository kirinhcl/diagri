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
from growbridge.config import RoleModel
from growbridge.workflow.states import TaskState

log = logging.getLogger(__name__)


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
    )
    return build_role_tools(deps)


def make_dispatcher(runtime: Any, client: ModelClient, work_root: Path) -> Dispatcher:
    roles = {name: runtime.settings.roles.get(name, RoleModel()) for name in ROLE_TOOLS}
    tools = role_tools(runtime, work_root)
    args = (client, roles, tools, runtime.tasks, runtime.budget, runtime.clock)
    timezone = runtime.settings.report_timezone

    def context(task):
        return project_context(runtime.workflow, runtime.control, timezone, task)

    conversation = getattr(runtime, "conversation", None)
    return Dispatcher(*args, runtime.agents_db, context=context, conversation=conversation)


async def run_agents(runtime: Any, dispatcher: Any) -> int:
    """Run every open task owned by a model role once; returns how many runs finished."""
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
