"""Greenhouse lock routes of the workbench (multi-user), under ``/wb``.

An operator sees every greenhouse as free, theirs or taken (by whom only an administrator sees),
locks a selection all at once (recent re-authentication), and releases their own. Releasing hands
the greenhouse's care back first; see ``workflow/locks.py``.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import Field

from growbridge.ports import Actor
from growbridge.workbench.common import Body
from growbridge.workbench.rounds import PathId
from growbridge.workflow.access import Access
from growbridge.workflow.locks import GreenhouseLocks

Dependency = Callable[..., Awaitable[Actor]]
MAX_SELECTION = 64


class LockIn(Body):
    greenhouse_ids: list[str] = Field(min_length=1, max_length=MAX_SELECTION)


class ReleaseIn(Body):
    plants_removed: bool = False  # the holder confirms the chamber is empty


def greenhouse_rows(locks: GreenhouseLocks, access: Access, actor: Actor) -> list[dict]:
    rows = []
    for row in locks.overview():
        holder = row["holder"]
        state = "free" if holder is None else ("mine" if holder == actor.id else "taken")
        shown = {"id": row["id"], "name": row["name"], "state": state}
        # when a colleague took their greenhouse is theirs: the holder and administrators see it
        sees_when = state == "mine" or access.is_admin(actor)
        shown["locked_at"] = row["locked_at"] if sees_when else None
        if access.is_admin(actor):
            shown["holder"] = holder
        rows.append(shown)
    return rows


def add_greenhouse_routes(
    router: APIRouter,
    operator: Dependency,
    fresh: Dependency,
    locks: GreenhouseLocks,
    access: Access,
) -> None:
    Operator = Annotated[Actor, Depends(operator)]  # noqa: N806
    Fresh = Annotated[Actor, Depends(fresh)]  # noqa: N806

    @router.get("/greenhouses")
    async def greenhouses(actor: Operator):
        return {"greenhouses": greenhouse_rows(locks, access, actor)}

    @router.post("/greenhouses/lock")
    async def lock(body: LockIn, actor: Fresh):
        return {"locked": list(locks.lock(actor.id, body.greenhouse_ids))}

    @router.post("/greenhouses/{greenhouse_id}/release")
    async def release(greenhouse_id: PathId, actor: Operator, body: ReleaseIn | None = None):
        confirmed = body is not None and body.plants_removed
        await locks.release(greenhouse_id, actor.id, plants_removed=confirmed)
        return {"released": greenhouse_id}
