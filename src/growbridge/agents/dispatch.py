"""Runs a model role for one research task (architecture doc §5.1, §5.2).

Only a task that is in progress and owned by a model role is run, and each trigger event is run
once. A model that is unavailable, errors, refuses, is truncated or runs out of budget never
takes anything else down: the task goes to needs-attention with the reason and that is all.
"""

from __future__ import annotations

import inspect
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from growbridge.agents.llm import DEFAULT_PRICE, ModelClient, TokenPrice
from growbridge.agents.loop import AgentRun, run_agent
from growbridge.agents.roles import ROLES, Handoff
from growbridge.agents.tools import ROLE_TOOLS, Tool, Toolset, build_toolset
from growbridge.archive.db import Database
from growbridge.archive.models import ResearchTask
from growbridge.config import RoleModel
from growbridge.ports import Denied
from growbridge.workflow.states import TaskState
from growbridge.workflow.tasks import TaskBoard

log = logging.getLogger(__name__)

REPORT_TOOL = "publish_research_report"
NAMESPACE = "dispatch"
STEPS = (
    "CREATE TABLE dispatch_claims("
    "trigger_event_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, claimed_at REAL NOT NULL)",
)
INTRO = "Your task record (JSON). Do the work it describes with your tools:\n"


def role_price(config: RoleModel) -> TokenPrice:
    """What the cost budget is charged per token: the role's own price when it states one."""
    if config.input_per_mtok is None or config.output_per_mtok is None:
        return DEFAULT_PRICE  # only the default model may leave the price out (config.py)
    return TokenPrice(input_per_mtok=config.input_per_mtok, output_per_mtok=config.output_per_mtok)


def _watching(handler: Any, reviews: list[bool]) -> Any:
    """Wrap the report tool so this run learns whether the report needs a human review."""

    async def watched(args: Any) -> Any:
        result = handler(args)
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, dict) and result.get("needs_review") is True:
            reviews.append(True)
        return result

    return watched


def task_message(task: ResearchTask) -> str:
    handoff = Handoff(
        goal=task.question,
        budget=task.budget,
        trigger_event_id=task.trigger_event_id,
        correlation_id=task.correlation_id,
        constraints=task.constraints,
        evidence_refs=task.input_refs,
        expected_artifacts=task.expected_artifacts,
        parent_task_id=task.parent_task_id,
    )
    record = {"task_id": task.id, **handoff.model_dump(mode="json")}
    return INTRO + json.dumps(record, ensure_ascii=False, sort_keys=True)


class Dispatcher:
    def __init__(
        self,
        client: ModelClient,
        roles: Mapping[str, RoleModel],
        tools: Mapping[str, Sequence[Tool]],
        tasks: TaskBoard,
        budget: Any,
        clock: Any,
        db: Database,
    ):
        self.client = client
        self.roles = roles
        self.tools = tools
        self.tasks = tasks
        self.budget = budget
        self.clock = clock
        self.db = db
        db.migrate(NAMESPACE, STEPS)

    async def run_task(self, task_id: str) -> AgentRun | None:
        task = self._claim(task_id)
        if task is None:
            return None
        reviews: list[bool] = []
        try:
            run = await self._run(task, reviews)
        except Denied as exc:
            self._hand_back(task, f"{exc.code}: {exc}")
            return None
        except Exception as exc:  # the model or its client failed; nothing else is affected
            log.exception("model run for task %s failed", task.id)
            self._hand_back(task, f"model unavailable: {type(exc).__name__}: {exc}")
            return None
        if run.stop_reason != "end_turn":
            self._hand_back(task, f"model stopped without finishing: {run.stop_reason}")
        else:
            self._move(task, TaskState.NEEDS_REVIEW if reviews else TaskState.DONE, "run finished")
        return run

    def _claim(self, task_id: str) -> ResearchTask | None:
        try:
            task = self.tasks.get(task_id)
        except Denied:
            return None
        if task.state is not TaskState.IN_PROGRESS or task.owner_role not in ROLE_TOOLS:
            return None
        return task if self._claim_trigger(task) else None

    def _claim_trigger(self, task: ResearchTask) -> bool:
        """Record the trigger before the model runs; a crash afterwards is never re-run here
        (``TaskBoard.expire`` hands the open task to the user at its deadline)."""
        with self.db.transaction():
            cursor = self.db.execute(
                "INSERT OR IGNORE INTO dispatch_claims VALUES (?, ?, ?)",
                (task.trigger_event_id, task.id, self.clock.now()),
            )
            return cursor.rowcount == 1

    async def _run(self, task: ResearchTask, reviews: list[bool]) -> AgentRun:
        role = task.owner_role
        config = self.roles.get(role)
        if config is None:
            raise Denied("model_role", f"no model configured for role {role!r}")
        toolset = self._toolset(role, config, reviews)
        return await run_agent(
            self.client,
            config,
            ROLES[role].system,
            task_message(task),
            toolset,
            self.budget,
            task.project_id,
            max_turns=config.max_calls,
            price=role_price(config),
        )

    def _toolset(self, role: str, config: RoleModel, reviews: list[bool]) -> Toolset:
        tools = [
            replace(tool, handler=_watching(tool.handler, reviews))
            if tool.name == REPORT_TOOL
            else tool
            for tool in self.tools.get(role, ())
        ]
        return build_toolset(role, tools, config.tools)

    def _hand_back(self, task: ResearchTask, reason: str) -> None:
        self._move(task, TaskState.NEEDS_ATTENTION, reason)

    def _move(self, task: ResearchTask, state: TaskState, reason: str) -> None:
        """Move the task from in progress; a task someone else already moved stays where it is."""
        try:
            if self.tasks.get(task.id).state is not TaskState.IN_PROGRESS:
                return
            event = f"dispatch:{task.trigger_event_id}:{state.value}"
            self.tasks.transition(task.id, state, event, reason)
        except Denied:
            log.exception("task %s could not move to %s", task.id, state.value)
