"""Runs a model role for one research task (architecture doc §5.1, §5.2).

Only a task that is in progress and owned by a model role is run, and each trigger event is run
once. A model that is unavailable, errors, refuses, is truncated or runs out of budget never
takes anything else down: the task goes to needs-attention with the reason and that is all.

A planner or researcher run counts as finished only when it delivered (a saved draft, a published
report); one that ends with only text has given up or is asking something, and the task goes to
needs-attention with that text. When a task the orchestrator delegated ends, the orchestrator gets
a follow-up task, so the round moves on without the orchestrator waiting inside its own run.
"""

from __future__ import annotations

import inspect
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any

from growbridge.agents.context import task_language
from growbridge.agents.conversation import ConversationLog, clip_json
from growbridge.agents.handlers_common import bind_task
from growbridge.agents.llm import DEFAULT_PRICE, ModelClient, ModelReply, TokenPrice
from growbridge.agents.loop import AgentRun, run_agent
from growbridge.agents.roles import ROLES, Handoff
from growbridge.agents.run_end import (
    DELIVERABLES,
    REPORT_TOOL,
    RunEnd,
    RunInterrupted,
    end_of_denied,
    end_of_error,
    end_of_run,
)
from growbridge.agents.tools import ROLE_TOOLS, Tool, ToolOutcome, Toolset, build_toolset
from growbridge.archive.db import Database
from growbridge.archive.ids import new_id
from growbridge.archive.models import Model, ResearchTask
from growbridge.codes import checked
from growbridge.config import RoleModel
from growbridge.ports import Denied
from growbridge.research.notes import TEXT_LANGUAGE
from growbridge.workflow.states import TaskState
from growbridge.workflow.tasks import TaskBoard

log = logging.getLogger(__name__)

NAMESPACE = "dispatch"
STEPS = (
    "CREATE TABLE dispatch_claims("
    "trigger_event_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, claimed_at REAL NOT NULL)",
)
INTRO = "Your task record (JSON). Do the work it describes with your tools:\n"
LEAD = "orchestrator"
HISTORY_KINDS = ("message", "reply")
HISTORY_ENTRIES = 12
HISTORY_CHARS = 1500
OUTCOME_CHARS = 6000  # the ended task's final text, handed to the follow-up in full
TOOL_INPUT_CHARS = 1500
TOOL_RESULT_CHARS = 2500
TASK_REF = "task:"
ContextOf = Callable[[ResearchTask], dict]
ToolsetWrap = Callable[[Toolset], Toolset]


def _unwrapped(toolset: Toolset) -> Toolset:
    return toolset


class ReplayedRun(Model):
    """What a replayed run was asked and how it ended."""

    user: str
    end: RunEnd


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


def delivered(role: str, outcome: ToolOutcome) -> bool:
    """Whether a tool outcome is a deliverable of ``role``'s run."""
    wanted = DELIVERABLES.get(role, {})
    if outcome.name not in wanted or outcome.is_error:
        return False
    field = wanted[outcome.name]
    if field is None:
        return True
    try:
        return json.loads(outcome.content).get(field) is True
    except (ValueError, AttributeError):
        return False


def task_message(
    task: ResearchTask,
    context: dict | None = None,
    history: Sequence[dict] = (),
    language: str = TEXT_LANGUAGE,
) -> str:
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
    # The project id is stated: the tools ask for it, and a model left to dig it out of the
    # trigger id gets it wrong (seen with a local model on the simulator).
    record = {"task_id": task.id, "project_id": task.project_id, **handoff.model_dump(mode="json")}
    if context:  # the ids a draft must name (round, protocol version, device): never guessed
        record["context"] = context
    record["language"] = language  # the console language: the one to write for the operator
    if history:  # the conversation so far, oldest first; data, like everything in the record
        record["conversation"] = list(history)
    return INTRO + json.dumps(record, ensure_ascii=False, sort_keys=True)


def follow_up(task: ResearchTask, state: TaskState, outcome: str) -> ResearchTask:
    """The orchestrator task that picks up after ``task`` ended in ``state``."""
    question = (
        f"The {task.owner_role} task {task.id} has ended: {state.value}. Its goal was: "
        f"{task.question}\nOutcome: {outcome}\nTell the user in a few sentences where the work "
        "stands and what they need to do next (a saved run sheet waits for their review and "
        "approval in the workbench). Read the task with get_task_status if you need its "
        "artifacts. Do not redo its work; delegate again only if something is clearly missing."
    )
    return ResearchTask(
        id=new_id("task"),
        project_id=task.project_id,
        question=question,
        owner_role=LEAD,
        budget=task.budget,
        trigger_event_id=f"followup:{task.id}",
        correlation_id=task.correlation_id,
        input_refs=(*task.input_refs, f"{TASK_REF}{task.id}"),
        language=task.language,
    )


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
        context: ContextOf | None = None,
        conversation: ConversationLog | None = None,
    ):
        self.client = client
        self.roles = roles
        self.tools = tools
        self.tasks = tasks
        self.budget = budget
        self.clock = clock
        self.db = db
        self.context = context
        self.conversation = conversation
        db.migrate(NAMESPACE, STEPS)

    async def run_task(self, task_id: str) -> AgentRun | None:
        task = self._claim(task_id)
        if task is None:
            return None
        reviews: list[bool] = []
        deliveries: list[str] = []
        try:
            user = self.message_for(task)
            run = await self._run(
                task, user, reviews, deliveries, client=self.client, wrap=_unwrapped
            )
        except Denied as exc:
            self._finish(task, end_of_denied(exc))
            return None
        except Exception as exc:  # the model or its client failed; nothing else is affected
            log.exception("model run for task %s failed", task.id)
            self._finish(task, end_of_error(exc))
            return None
        self._finish(task, end_of_run(run, task.owner_role, reviews, deliveries))
        return run

    async def replay_run(self, task_id: str, client: ModelClient, wrap: ToolsetWrap) -> ReplayedRun:
        """Run a task again with ``client`` and a wrapped toolset, in any state: it is not
        claimed and not ended, so nothing about the task or its claims changes."""
        task = self.tasks.get(task_id)
        reviews: list[bool] = []
        deliveries: list[str] = []
        user = self.message_for(task)
        try:
            run = await self._run(task, user, reviews, deliveries, client=client, wrap=wrap)
        except RunInterrupted:
            raise
        except Denied as exc:
            return ReplayedRun(user=user, end=end_of_denied(exc))
        except Exception as exc:
            return ReplayedRun(user=user, end=end_of_error(exc))
        return ReplayedRun(user=user, end=end_of_run(run, task.owner_role, reviews, deliveries))

    def _finish(self, task: ResearchTask, end: RunEnd) -> None:
        self._end(task, end.state, end.reason, end.said, code=end.code, params=end.params)

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

    async def _run(
        self,
        task: ResearchTask,
        user: str,
        reviews: list[bool],
        deliveries: list[str],
        *,
        client: ModelClient,
        wrap: ToolsetWrap,
    ) -> AgentRun:
        role = task.owner_role
        config = self.roles.get(role)
        if config is None:
            raise Denied(
                "model_role",
                f"no model configured for role {role!r}",
                reason="no_model",
                params={"role": role},
            )
        toolset = wrap(self._toolset(role, config, reviews))

        def observe(reply: ModelReply, outcomes: list[ToolOutcome]) -> None:
            deliveries.extend(o.name for o in outcomes if delivered(role, o))
            self._record_turn(task, reply, outcomes)

        with bind_task(task.id):  # the tools learn their task here, never from model output
            return await run_agent(
                client,
                config,
                ROLES[role].system,
                user,
                toolset,
                self.budget,
                task.project_id,
                max_turns=config.max_calls,
                price=role_price(config),
                observe=observe,
            )

    def schemas_for(self, role: str) -> list[dict] | None:
        """The tool definitions a run of ``role`` is offered; ``None`` when the role has no
        model configured or its tool list cannot be built. Calls no handler."""
        config = self.roles.get(role)
        if config is None:
            return None
        try:
            return self._toolset(role, config, []).schemas()
        except Denied:
            return None

    def message_for(self, task: ResearchTask) -> str:
        context = self.context(task) if self.context is not None else None
        history: list[dict] = []
        if self.conversation is not None and task.owner_role == LEAD:
            entries = self.conversation.recent(task.project_id, HISTORY_KINDS, HISTORY_ENTRIES + 1)
            history = [
                {"role": e.role, "text": e.text[:HISTORY_CHARS]}
                for e in entries
                if e.task_id != task.id
            ][-HISTORY_ENTRIES:]
        return task_message(task, context, history, task_language(task, self.tasks))

    def _record(self, task: ResearchTask, kind: Any, text: str, **detail: Any) -> None:
        if self.conversation is None:
            return
        try:
            self.conversation.add(task.project_id, task.owner_role, kind, text, task.id, detail)
        except Exception:  # the record is for reading; it never stops a run
            log.exception("conversation entry for task %s failed", task.id)

    def _record_turn(
        self, task: ResearchTask, reply: ModelReply, outcomes: list[ToolOutcome]
    ) -> None:
        if reply.text.strip():
            self._record(task, "reply", reply.text.strip(), final=not reply.tool_calls)
        for call, outcome in zip(reply.tool_calls, outcomes, strict=False):
            self._record(
                task,
                "tool",
                call.name,
                input=clip_json(call.input, TOOL_INPUT_CHARS),
                is_error=outcome.is_error,
                result=outcome.content[:TOOL_RESULT_CHARS],
            )

    def _toolset(self, role: str, config: RoleModel, reviews: list[bool]) -> Toolset:
        tools = [
            replace(tool, handler=_watching(tool.handler, reviews))
            if tool.name == REPORT_TOOL
            else tool
            for tool in self.tools.get(role, ())
        ]
        return build_toolset(role, tools, config.tools)

    def _end(
        self,
        task: ResearchTask,
        state: TaskState,
        reason: str,
        said: str = "",
        *,
        code: str,
        params: Mapping[str, object] | None = None,
    ) -> None:
        """Move the task out of in progress, say so in the conversation (the English reason, and
        the code and params the console shows it by) and, for a task the orchestrator delegated,
        hand the next step back to it."""
        if not self._move(task, state, reason):
            return
        detail = checked("chat_end", code, params or {})
        self._record(task, "status", state.value, reason=reason, code=code, params=detail)
        if task.owner_role == LEAD or not self._delegated_by_lead(task):
            return
        outcome = (said or reason)[:OUTCOME_CHARS]
        try:
            created = self.tasks.create(follow_up(task, state, outcome))
        except Denied:
            log.exception("no follow-up for task %s", task.id)
            return
        self._record(task, "status", "follow_up", task_id=created.id)

    def _delegated_by_lead(self, task: ResearchTask) -> bool:
        if task.parent_task_id is None:
            return False
        try:
            return self.tasks.get(task.parent_task_id).owner_role == LEAD
        except Denied:
            return False

    def _move(self, task: ResearchTask, state: TaskState, reason: str) -> bool:
        """Move the task from in progress; a task someone else already moved stays where it is."""
        try:
            if self.tasks.get(task.id).state is not TaskState.IN_PROGRESS:
                return False
            event = f"dispatch:{task.trigger_event_id}:{state.value}"
            self.tasks.transition(task.id, state, event, reason)
        except Denied:
            log.exception("task %s could not move to %s", task.id, state.value)
            return False
        return True
