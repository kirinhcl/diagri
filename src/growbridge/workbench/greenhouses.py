"""Greenhouse lock routes of the workbench (multi-user), under ``/wb``.

An operator sees every greenhouse as free, theirs or taken (by whom only an administrator sees),
locks a selection all at once (recent re-authentication), and releases their own. Releasing hands
the greenhouse's care back first; see ``workflow/locks.py``.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import Field, StringConstraints

from growbridge.archive.models import Channel
from growbridge.ports import Actor
from growbridge.workbench.common import Body
from growbridge.workbench.rounds import PathId
from growbridge.workflow import device_test_denials
from growbridge.workflow.access import Access
from growbridge.workflow.device_test import DeviceTestRecord, DeviceTests
from growbridge.workflow.locks import GreenhouseLocks

Dependency = Callable[..., Awaitable[Actor]]
MAX_SELECTION = 64


class LockIn(Body):
    greenhouse_ids: list[str] = Field(min_length=1, max_length=MAX_SELECTION)


class ReleaseIn(Body):
    plants_removed: bool = False  # the holder confirms the chamber is empty


class SettleIn(Body):
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


HISTORY_FIELDS = {"test_id", "channel", "operator", "state", "result", "started_at", "ended_at"}


def test_fields(tests: DeviceTests | None, row: dict, actor: Actor) -> dict[str, Any]:
    """What the page needs to show a greenhouse's device test section (holder only)."""
    if tests is None or row["holder"] != actor.id:
        return {"testable": False, "test_running": None, "test_unsettled": None}
    running, unsettled = tests.running(row["device_id"]), tests.unsettled(row["device_id"])
    shown = None
    if unsettled is not None:
        shown = {"test_id": unsettled.test_id, "channel": unsettled.channel.value}
        shown["state"] = unsettled.state
    return {
        "testable": tests.testable(row, actor),
        "test_running": None if running is None else running.channel.value,
        "test_unsettled": shown,
    }


def history_row(record: DeviceTestRecord) -> dict[str, Any]:
    return record.model_dump(mode="json", include=HISTORY_FIELDS | {"note"})


def greenhouse_rows(
    locks: GreenhouseLocks, access: Access, actor: Actor, tests: DeviceTests | None = None
) -> list[dict]:
    rows = []
    for row in locks.overview():
        holder = row["holder"]
        state = "free" if holder is None else ("mine" if holder == actor.id else "taken")
        shown = {"id": row["id"], "name": row["name"], "state": state}
        # only this greenhouse's device is driven here: the others can be held but not run
        shown["controlled"] = row["device_id"] == access.local_device
        # when a colleague took their greenhouse is theirs: the holder and administrators see it
        sees_when = state == "mine" or access.is_admin(actor)
        shown["locked_at"] = row["locked_at"] if sees_when else None
        if access.is_admin(actor):
            shown["holder"] = holder
        rows.append(shown | test_fields(tests, row, actor))
    return rows


def add_greenhouse_routes(
    router: APIRouter,
    operator: Dependency,
    fresh: Dependency,
    locks: GreenhouseLocks,
    access: Access,
    tests: DeviceTests | None = None,
) -> None:
    Operator = Annotated[Actor, Depends(operator)]  # noqa: N806
    Fresh = Annotated[Actor, Depends(fresh)]  # noqa: N806

    @router.get("/greenhouses")
    async def greenhouses(actor: Operator):
        return {"greenhouses": greenhouse_rows(locks, access, actor, tests)}

    @router.post("/greenhouses/lock")
    async def lock(body: LockIn, actor: Fresh):
        return {"locked": list(locks.lock(actor.id, body.greenhouse_ids))}

    @router.post("/greenhouses/{greenhouse_id}/release")
    async def release(greenhouse_id: PathId, actor: Operator, body: ReleaseIn | None = None):
        confirmed = body is not None and body.plants_removed
        await locks.release(greenhouse_id, actor.id, plants_removed=confirmed)
        return {"released": greenhouse_id}

    if tests is not None:
        add_device_test_routes(router, Operator, locks, access, tests)


def add_device_test_routes(
    router: APIRouter, operator: Any, locks: GreenhouseLocks, access: Access, tests: DeviceTests
) -> None:
    Operator = operator  # noqa: N806

    @router.post("/greenhouses/{greenhouse_id}/test/{channel}")
    async def test_device(greenhouse_id: PathId, channel: Channel, actor: Operator):
        # shielded: a browser that goes away mid-test does not stop the restore
        return await asyncio.shield(tests.run(greenhouse_id, channel, actor))

    @router.post("/greenhouses/{greenhouse_id}/tests/{test_id}/retry")
    async def retry_test(greenhouse_id: PathId, test_id: PathId, actor: Operator):
        return await asyncio.shield(tests.retry(greenhouse_id, test_id, actor))

    @router.post("/greenhouses/{greenhouse_id}/tests/{test_id}/settle")
    async def settle_test(greenhouse_id: PathId, test_id: PathId, body: SettleIn, actor: Operator):
        tests.settle(greenhouse_id, test_id, actor, body.note)
        return {"settled": test_id}

    @router.get("/greenhouses/{greenhouse_id}/tests")
    async def test_history(greenhouse_id: PathId, actor: Operator):
        house = locks.greenhouse(greenhouse_id)
        if not access.is_admin(actor) and locks.holder_of_device(house.device_id) != actor.id:
            raise device_test_denials.not_held(greenhouse_id)
        return {"tests": [history_row(record) for record in tests.history(greenhouse_id)]}
