"""Workbench routes that start and steer a research round (architecture §5.2), under ``/wb``.

An operator creates a project, saves a research protocol and creates a round; sets the project's
model call budget; states a research goal, which becomes the first orchestrator task; reads a
stage's run sheet with its validation findings before approving it; chooses what follows a
stopped stage; and aborts a round. Every route here needs an operator session: a model role is
refused with ``model_role``, reads included.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Path
from pydantic import Field, StrictInt, StringConstraints

from growbridge.archive.ids import new_id
from growbridge.archive.models import Budget, ResearchProtocol, ResearchTask, non_finite_paths
from growbridge.ports import Actor, Denied
from growbridge.workbench.common import REQUEST_ID, Body, rejected
from growbridge.workflow.service import Choice, WorkflowService
from growbridge.workflow.tasks import TaskBoard

GOAL_ROLE = "orchestrator"  # the single entry point for a goal (architecture §4)
GOAL_TASK_BUDGET = Budget(max_calls=20, max_cost=5.0)  # as for tasks the orchestrator creates
MAX_ID_CHARS = 100
MAX_PROTOCOL_VERSION = 1_000_000
MAX_NAME_CHARS = 200
MAX_GOAL_CHARS = 2000
MAX_CONSTRAINTS = 20
MAX_CONSTRAINT_CHARS = 500
MAX_BUDGET_CALLS = 1_000_000
MAX_BUDGET_COST = 1_000_000.0

Ident = Annotated[str, Field(min_length=1, max_length=MAX_ID_CHARS)]
PathId = Annotated[str, Path(min_length=1, max_length=MAX_ID_CHARS)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Dependency = Callable[..., Awaitable[Actor]]  # one of the workbench's operator dependencies


class ProjectBudget(Protocol):
    """What these routes need of the model call budget (``agents/budget.py``)."""

    def set(self, project_id: str, budget: Budget) -> None: ...

    def remaining(self, project_id: str) -> tuple[int, float]: ...


# --- request bodies ----------------------------------------------------------------------------


class ProjectIn(Body):
    name: str = Field(min_length=1, max_length=MAX_NAME_CHARS)


class ProtocolIn(Body):
    protocol: ResearchProtocol


class RoundIn(Body):
    project_id: Ident
    protocol_id: Ident


class BudgetIn(Body):
    """Zero is allowed: it stops further model calls of the project."""

    max_calls: StrictInt = Field(ge=0, le=MAX_BUDGET_CALLS)
    max_cost: float = Field(ge=0, le=MAX_BUDGET_COST)


class GoalIn(Body):
    project_id: Ident
    goal: Annotated[Text, Field(max_length=MAX_GOAL_CHARS)]
    round_id: Ident | None = None
    constraints: tuple[Annotated[Text, Field(max_length=MAX_CONSTRAINT_CHARS)], ...] = Field(
        default=(), max_length=MAX_CONSTRAINTS
    )
    request_id: str | None = Field(default=None, pattern=REQUEST_ID)


class ChoiceIn(Body):
    choice: Choice


# --- answers -----------------------------------------------------------------------------------


def round_json(workflow: WorkflowService, round_id: str) -> dict:
    store = workflow.store
    rnd = store.round(round_id)
    stages = store.stages_of_round(round_id)
    return {
        "round_id": rnd.id,
        **rnd.model_dump(mode="json", exclude={"id"}),
        "stage_total": store.stage_total(rnd),
        "stages": [{"stage_id": row.stage_id, "state": row.state.value} for row in stages],
    }


def review_json(workflow: WorkflowService, stage_id: str) -> dict:
    """The run sheet as it would be approved now, checked by the validator ``approve`` uses.
    The digest is the one an approval records. Reading changes nothing."""
    stage = workflow.stage(stage_id)
    sheet = stage.run_sheet
    findings = tuple(workflow.validate(sheet)) if workflow.validate else ()
    return {
        "stage_id": stage.stage_id,
        "state": stage.state.value,
        "run_sheet_version": sheet.version,
        "run_sheet_digest": sheet.digest(),
        "run_sheet": sheet.model_dump(mode="json"),
        "findings": [item.model_dump(mode="json") for item in findings],
        "blocking": any(item.blocking for item in findings),
    }


def checked_protocol(protocol: ResearchProtocol) -> ResearchProtocol:
    """Refuse what a saved, never-overwritten version must not contain and the shared model
    leaves open: an id too long for a key, a version out of range, a NaN or an infinity. (The
    body's ``allow_inf_nan`` does not reach nested models.)"""
    if not all(1 <= len(key) <= MAX_ID_CHARS for key in (protocol.id, protocol.project_id)):
        raise rejected(f"protocol and project ids have 1 to {MAX_ID_CHARS} characters")
    if not 1 <= protocol.version <= MAX_PROTOCOL_VERSION:
        raise rejected(f"the protocol version is between 1 and {MAX_PROTOCOL_VERSION}")
    spoiled = non_finite_paths(protocol.model_dump())
    if spoiled:
        raise rejected(f"protocol numbers must be finite; not at {', '.join(spoiled)}")
    return protocol


def same_goal(stored: ResearchTask, asked: ResearchTask) -> bool:
    """Whether a repeated request asks for exactly what the stored task already is."""
    fields = {"question", "constraints", "input_refs", "owner_role"}
    return stored.model_dump(include=fields) == asked.model_dump(include=fields)


def goal_task(body: GoalIn, actor: Actor, workflow: WorkflowService) -> ResearchTask:
    """The orchestrator task of a goal. Its trigger names the project, the operator and the
    request, so a repeated request finds the task it already made. Without a request id every
    request makes a new task."""
    refs: tuple[str, ...] = ()
    if body.round_id is not None:
        if workflow.store.round(body.round_id).project_id != body.project_id:
            raise Denied("state", f"round {body.round_id} is not in project {body.project_id}")
        refs = (f"round:{body.round_id}",)
    key = body.request_id or new_id("goal")
    return ResearchTask(
        id=new_id("task"),
        project_id=body.project_id,
        question=body.goal,
        owner_role=GOAL_ROLE,
        budget=GOAL_TASK_BUDGET,
        trigger_event_id=f"goal:{body.project_id}:{actor.id}:{key}",
        correlation_id=new_id("goal"),
        constraints=body.constraints,
        input_refs=refs,
    )


# --- routes ------------------------------------------------------------------------------------


def _design_routes(router: APIRouter, operator: Dependency, workflow: WorkflowService) -> None:
    Operator = Annotated[Actor, Depends(operator)]  # noqa: N806

    @router.post("/projects")
    async def create_project(body: ProjectIn, actor: Operator):
        return {"project_id": workflow.create_project(body.name, actor)}

    @router.post("/protocols")
    async def save_protocol(body: ProtocolIn, actor: Operator):
        saved = workflow.save_protocol(checked_protocol(body.protocol), actor)
        return {"protocol_id": saved.id, "version": saved.version, "digest": saved.digest()}

    @router.post("/rounds")
    async def create_round(body: RoundIn, actor: Operator):
        round_id = workflow.create_round(body.project_id, body.protocol_id, actor)
        return {"round_id": round_id, "state": workflow.round_state(round_id).value}


def _steering_routes(router: APIRouter, operator: Dependency, workflow: WorkflowService) -> None:
    Operator = Annotated[Actor, Depends(operator)]  # noqa: N806

    @router.get("/rounds/{round_id}")
    async def read_round(round_id: PathId, actor: Operator):
        return round_json(workflow, round_id)

    @router.get("/stages/{stage_id}/run-sheet")
    async def read_run_sheet(stage_id: PathId, actor: Operator):
        return review_json(workflow, stage_id)

    @router.post("/rounds/{round_id}/choice")
    async def choose_after_stop(round_id: PathId, body: ChoiceIn, actor: Operator):
        state = await workflow.choose_after_stop(round_id, body.choice, actor)
        return {"round_id": round_id, "state": state.value}

    @router.post("/rounds/{round_id}/abort")
    async def abort_round(round_id: PathId, actor: Operator):
        state = await workflow.abort_round(round_id, actor)
        return {"round_id": round_id, "state": state.value}


def _model_routes(
    router: APIRouter,
    operator: Dependency,
    fresh: Dependency,
    workflow: WorkflowService,
    tasks: TaskBoard,
    budget: ProjectBudget,
) -> None:
    """What lets model roles work on a project: its call budget and a goal for the orchestrator."""
    Operator = Annotated[Actor, Depends(operator)]  # noqa: N806
    Fresh = Annotated[Actor, Depends(fresh)]  # noqa: N806

    def require_project(project_id: str) -> None:
        if not workflow.store.has_project(project_id):
            raise Denied("state", f"unknown project {project_id}")

    def require_budget_left(project_id: str) -> None:
        """Before a task is made that could never call a model."""
        calls, cost = budget.remaining(project_id)  # refused with ``budget`` when none was set
        if calls <= 0 or cost <= 0:
            raise Denied("budget", f"nothing is left of the call budget of project {project_id}")

    @router.post("/projects/{project_id}/budget")
    async def set_budget(project_id: PathId, body: BudgetIn, actor: Fresh):
        require_project(project_id)
        budget.set(project_id, Budget(max_calls=body.max_calls, max_cost=body.max_cost))
        calls, cost = budget.remaining(project_id)
        return {
            "project_id": project_id,
            "max_calls": body.max_calls,
            "max_cost": body.max_cost,
            "remaining_calls": calls,
            "remaining_cost": cost,
        }

    @router.post("/goals")
    async def submit_goal(body: GoalIn, actor: Operator):
        require_project(body.project_id)
        require_budget_left(body.project_id)
        task = goal_task(body, actor, workflow)
        stored = tasks.create(task)  # one task per trigger: a repeat returns the first
        reused = stored.id != task.id
        if reused and not same_goal(stored, task):
            raise Denied("state", "this request id was already used for another goal")
        return {"task_id": stored.id, "state": stored.state.value, "reused": reused}


def add_round_routes(
    router: APIRouter,
    operator: Dependency,
    fresh: Dependency,
    workflow: WorkflowService,
    tasks: TaskBoard | None = None,
    budget: ProjectBudget | None = None,
) -> None:
    """Mount the routes on ``router``. ``operator`` and ``fresh`` are the workbench's operator
    dependencies (session, entry and origin checks; ``fresh`` also asks for a recent
    re-authentication). The budget and goal routes exist only when ``tasks`` and ``budget`` are
    given."""
    _design_routes(router, operator, workflow)
    _steering_routes(router, operator, workflow)
    if tasks is not None and budget is not None:
        _model_routes(router, operator, fresh, workflow, tasks, budget)
