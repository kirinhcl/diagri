"""Workbench routes for holdout registration (architecture §9.2), under ``/wb``.

An operator registers a holdout before any of its outcome data exists: if an outcome metric of a
held-out batch is already recorded in the project, the data may have been seen and the
registration is refused (``state``). The holdout id and the registrant come from the server (an
id in the body, or a name, is dropped). Registering needs a recent re-authentication; listing
does not. Operators only: a model role is refused with ``model_role``.

Registering a model for a holdout and scoring it have no route: nothing yet scores a prediction
without exposing the held-out outcomes to the model.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import Field

from growbridge.archive.ids import new_id
from growbridge.ports import Actor, Denied
from growbridge.research.holdout import Holdout, HoldoutRegistry
from growbridge.workbench.common import Body
from growbridge.workbench.rounds import Ident
from growbridge.workbench.scope import project_read, project_write
from growbridge.workflow.access import Access
from growbridge.workflow.service import WorkflowService

MAX_NAMES = 50
Dependency = Callable[..., Awaitable[Actor]]
Names = Annotated[tuple[Ident, ...], Field(min_length=1, max_length=MAX_NAMES)]


class HoldoutIn(Body):
    project_id: Ident
    batch_ids: Names
    development_batch_ids: Names
    outcome_fields: Names


def holdout_json(item: Holdout, holdout: HoldoutRegistry | None = None) -> dict:
    """The registration, with its read log when a registry is given."""
    body = item.model_dump(mode="json")
    if holdout is not None:
        reads = holdout.reads(item.holdout_id)
        body["reads"] = [read.model_dump(mode="json", exclude={"holdout_id"}) for read in reads]
    return body


def add_holdout_routes(
    router: APIRouter,
    operator: Dependency,
    fresh: Dependency,
    workflow: WorkflowService,
    holdout: HoldoutRegistry,
    access: Access | None = None,
) -> None:
    """Mount the routes on ``router``; ``operator`` and ``fresh`` are the workbench's operator
    dependencies (``fresh`` also asks for a recent re-authentication)."""
    Operator = Annotated[Actor, Depends(operator)]  # noqa: N806
    Fresh = Annotated[Actor, Depends(fresh)]  # noqa: N806

    def require_project(project_id: str, actor: Actor, write: bool = True) -> None:
        unknown = Denied(  # another's project answers as one that does not exist
            "scope",
            f"unknown project {project_id}",
            reason="not_this_project",
            params={"project_id": project_id},
        )
        if not workflow.store.has_project(project_id):
            raise unknown
        check = project_write if write else project_read
        check(access, actor, project_id, lambda: unknown)

    @router.post("/holdouts")
    async def register_holdout(body: HoldoutIn, actor: Fresh):
        require_project(body.project_id, actor)
        holdout_id = new_id("holdout")
        args = (body.project_id, holdout_id, body.batch_ids, body.outcome_fields)
        holdout.register(*args, body.development_batch_ids, registered_by=actor.id)
        (made,) = [h for h in holdout.holdouts(body.project_id) if h.holdout_id == holdout_id]
        return holdout_json(made)

    @router.get("/holdouts")
    async def list_holdouts(
        project_id: Annotated[str, Query(min_length=1, max_length=100)], actor: Operator
    ):
        require_project(project_id, actor, write=False)
        return {"holdouts": [holdout_json(item, holdout) for item in holdout.holdouts(project_id)]}
