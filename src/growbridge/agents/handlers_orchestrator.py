"""Orchestrator tool handlers (architecture doc §5.2): read state, create or delegate tasks, file
drafts for review. Nothing here controls a stage or the device."""

from __future__ import annotations

from typing import Literal

from growbridge.agents.handlers_common import (
    MAX_ITEMS,
    Deps,
    ToolInput,
    bound_task,
    clip,
    require_bound,
    require_project,
    require_round_project,
    require_stage_project,
)
from growbridge.agents.tools import Tool
from growbridge.archive.ids import file_digest, new_id
from growbridge.archive.models import Budget, ResearchTask
from growbridge.ports import Denied

ROLE = "orchestrator"
HISTORY_TAIL = 10
MAX_ARTIFACT_BYTES = 64_000
DEFAULT_TASK_BUDGET = Budget(max_calls=20, max_cost=5.0)
ModelRole = Literal["planner", "researcher"]


class ProjectStateInput(ToolInput):
    project_id: str
    round_id: str | None = None


class RunStatusInput(ToolInput):
    stage_id: str


class CreateTaskInput(ToolInput):
    project_id: str
    owner_role: ModelRole
    question: str
    trigger_event_id: str
    correlation_id: str
    constraints: tuple[str, ...] = ()
    input_refs: tuple[str, ...] = ()
    expected_artifacts: tuple[str, ...] = ()
    budget: Budget = DEFAULT_TASK_BUDGET


class DelegateInput(ToolInput):
    """A full handoff (``roles.Handoff``) plus the project and the receiving role."""

    project_id: str
    to_role: ModelRole
    goal: str
    budget: Budget
    trigger_event_id: str
    correlation_id: str
    constraints: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    expected_artifacts: tuple[str, ...] = ()
    parent_task_id: str | None = None


class TaskStatusInput(ToolInput):
    task_id: str


class ArtifactInput(ToolInput):
    artifact_id: str


def _task_summary(task: ResearchTask) -> dict:
    return {
        "id": task.id,
        "owner_role": task.owner_role,
        "state": task.state.value,
        "question": clip(task.question, 200),
    }


_SAME_TASK_FIELDS = {"owner_role", "question", "constraints", "input_refs", "parent_task_id"}
# Model roles run one task at a time: a task made here starts only after this run ends, so a
# model that waits for it (polling its status) waits for nothing.
STARTS_LATER = (
    "This task starts after your run ends; it cannot progress while you wait. Do not poll it or "
    "do its work. End your turn now with a short reply to the user; "
)
REPORTED_BACK = "when the task ends you get a follow-up task that tells you how it went."
NOT_REPORTED = (
    "it is a top-level task, so you are not told when it ends (the operator is alerted when it "
    "needs attention)."
)
TASK_REF = "task:"


def _stored(deps: Deps, task: ResearchTask) -> dict:
    """One task per trigger event: a repeat of the same request returns the first task. A trigger
    that already belongs to a different task is refused, so a model that copied an id (its own
    task's, say) learns that nothing was created instead of being handed someone else's task."""
    stored = deps.tasks.create(task)
    reused = stored.id != task.id
    if reused and stored.model_dump(include=_SAME_TASK_FIELDS) != task.model_dump(
        include=_SAME_TASK_FIELDS
    ):
        raise Denied(
            "state",
            f"trigger_event_id {task.trigger_event_id!r} already belongs to task {stored.id} "
            f"(owner {stored.owner_role}); nothing was created. Use a new trigger_event_id.",
            reason="request_id_reused_for_other_goal",
            params={"task_id": stored.id, "request_id": task.trigger_event_id},
        )
    return {
        "task_id": stored.id,
        "state": stored.state.value,
        "reused": reused,
        "next": STARTS_LATER + (NOT_REPORTED if stored.parent_task_id is None else REPORTED_BACK),
    }


def build_orchestrator_tools(deps: Deps) -> list[Tool]:
    def project_state(data: ProjectStateInput) -> dict:
        require_project(deps, data.project_id)
        if data.round_id is not None:
            require_round_project(deps, data.round_id)
        tasks = deps.tasks.list(data.project_id)
        out: dict = {"tasks": [_task_summary(t) for t in tasks[-MAX_ITEMS:]]}
        out["active_stage"] = getattr(deps.workflow.active_stage(), "stage_id", None)
        if data.round_id is not None:
            out["round_state"] = deps.workflow.round_state(data.round_id).value
            out["stages"] = [
                {"stage_id": s.stage_id, "state": s.state.value}
                for s in deps.workflow.store.stages_of_round(data.round_id)
            ]
        return out

    def run_status(data: RunStatusInput) -> dict:
        require_stage_project(deps, data.stage_id)
        stage = deps.workflow.stage(data.stage_id)
        return {
            "stage_id": stage.stage_id,
            "state": stage.state.value,
            "experiment_id": stage.experiment_id,
            "started_at": stage.started_at,
            "paused_at": stage.paused_at,
            "end_pending": stage.end_pending,
            "history": list(deps.workflow.history(data.stage_id))[-HISTORY_TAIL:],
        }

    def create_task(data: CreateTaskInput) -> dict:
        running = require_project(deps, data.project_id)
        task = ResearchTask(
            id=new_id("task"),
            project_id=data.project_id,
            question=data.question,
            owner_role=data.owner_role,
            budget=data.budget,
            trigger_event_id=data.trigger_event_id,
            correlation_id=data.correlation_id,
            constraints=data.constraints,
            input_refs=data.input_refs,
            expected_artifacts=data.expected_artifacts,
            language=running.language,
        )
        return _stored(deps, task)

    def delegate(data: DelegateInput) -> dict:
        running = require_project(deps, data.project_id)
        if data.parent_task_id is not None:
            require_bound(deps, data.parent_task_id)
        task = ResearchTask(
            id=new_id("task"),
            project_id=data.project_id,
            question=data.goal,
            owner_role=data.to_role,
            budget=data.budget,
            trigger_event_id=data.trigger_event_id,
            correlation_id=data.correlation_id,
            constraints=data.constraints,
            input_refs=data.evidence_refs,
            expected_artifacts=data.expected_artifacts,
            # a handoff always hangs under the running task, named or not: only then does the
            # dispatcher hand its end back as the follow-up the tool result promises
            parent_task_id=running.id,
            language=running.language,
        )
        return _stored(deps, task)

    def task_status(data: TaskStatusInput) -> dict:
        task = _visible_task(deps, data.task_id)
        artifacts = deps.archive.artifacts(task.id)
        return {
            **_task_summary(task),
            "artifacts": [{"id": a.id, "kind": a.kind, "label": a.label} for a in artifacts],
        }

    def read_artifact(data: ArtifactInput) -> dict:
        return _read(deps, data.artifact_id)

    return [
        Tool(
            "get_project_state",
            "Read tasks, round and stage states of a project.",
            ProjectStateInput,
            project_state,
        ),
        Tool(
            "get_run_status",
            "Read the state and recent history of one stage.",
            RunStatusInput,
            run_status,
        ),
        Tool(
            "create_research_task",
            "Create a top-level task, not tied to yours: you are not told when it ends, so "
            "prefer delegate_task. The planner designs experiments and run sheets; the "
            "researcher analyses frozen data and writes reports. trigger_event_id must be a new "
            "id for this task, never the id of your own task.",
            CreateTaskInput,
            create_task,
            writes=True,
        ),
        Tool(
            "delegate_task",
            "Delegate a task under your own (parent_task_id, your task's id if given) with a full "
            "handoff; when it ends you get a follow-up task. The planner designs experiments and "
            "run sheets; the researcher analyses frozen data and writes reports. trigger_event_id "
            "must be a new id for this task, never the id of your own task.",
            DelegateInput,
            delegate,
            writes=True,
        ),
        Tool(
            "get_task_status", "Read a task's state and artifact ids.", TaskStatusInput, task_status
        ),
        Tool(
            "read_artifact",
            "Read a registered text artifact (checked against its digest).",
            ArtifactInput,
            read_artifact,
        ),
    ]


def _visible_task(deps: Deps, task_id: str) -> ResearchTask:
    """The running task, the tasks delegated below it and a task it names as an input (a
    follow-up names the task it follows); nothing else, in any project."""
    bound = bound_task(deps)
    try:
        cursor = deps.tasks.get(task_id)
    except Denied:
        raise Denied(
            "scope", "that task is not available to this run", reason="not_this_run", params={}
        ) from None
    if f"{TASK_REF}{task_id}" in bound.input_refs and cursor.project_id == bound.project_id:
        return cursor
    while cursor.project_id == bound.project_id:
        if cursor.id == bound.id:
            return deps.tasks.get(task_id)
        if cursor.parent_task_id is None:
            break
        cursor = deps.tasks.get(cursor.parent_task_id)
    raise Denied(
        "scope", "that task is not available to this run", reason="not_this_run", params={}
    )


def _own_artifact(deps: Deps, artifact_id: str):
    """An artifact of a task of the run's project; unknown ids look the same."""
    artifact = deps.archive.artifact(artifact_id)
    owner = None
    if artifact is not None:
        try:
            owner = deps.tasks.get(artifact.task_id)
        except Denied:
            owner = None
    if artifact is None or owner is None or owner.project_id != bound_task(deps).project_id:
        raise Denied(
            "scope",
            f"artifact {artifact_id} is not available to this run",
            reason="not_this_run",
            params={},
        )
    return artifact


def _read(deps: Deps, artifact_id: str) -> dict:
    artifact = _own_artifact(deps, artifact_id)
    path = deps.archive.root.joinpath(artifact.path).resolve()
    roots = (deps.work_root.resolve(), deps.archive.root.resolve())
    if not any(path.is_relative_to(root) for root in roots) or not path.is_file():
        raise Denied(
            "scope",
            f"artifact {artifact_id} is outside the project data",
            reason="not_this_run",
            params={},
        )
    if file_digest(path) != artifact.sha256:
        raise Denied(
            "state",
            f"artifact {artifact_id} no longer matches its recorded digest",
            reason="artifact_digest_mismatch",
            params={"round_id": None, "artifact_id": artifact_id},
        )
    with path.open("rb") as handle:
        raw = handle.read(MAX_ARTIFACT_BYTES + 1)
    text = raw[:MAX_ARTIFACT_BYTES].decode(errors="replace")
    return {
        "artifact_id": artifact_id,
        "kind": artifact.kind,
        "label": artifact.label,
        "truncated": len(raw) > MAX_ARTIFACT_BYTES,
        "text": text,
    }
