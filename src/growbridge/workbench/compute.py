"""Workbench routes for the compute service (architecture §9.4), under ``/wb``.

FirecREST reports no project balance, so an operator reads it from MyCSC and enters it here; the
entry is appended with the operator's name and the time, both taken from the server. Setting a
task's compute budget is the other thing only a person decides, and so is settling an attempt
that nobody can recover. These three writes need a recent re-authentication; reading the
overview does not. Operators only: a model role is refused with ``model_role``. The routes are
not mounted without a compute service.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import Field, StringConstraints

from growbridge.compute.service import ComputeService
from growbridge.ports import Actor, Denied
from growbridge.workbench.common import Body
from growbridge.workbench.rounds import PathId
from growbridge.workbench.scope import admin_only, project_write, visible_task
from growbridge.workflow.access import Access
from growbridge.workflow.tasks import TaskBoard

MAX_NOTE_CHARS = 500
Dependency = Callable[..., Awaitable[Actor]]
Amount = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]  # no bool, no string


class BalanceIn(Body):
    cpu_hours: Amount
    note: str = Field(default="", max_length=MAX_NOTE_CHARS)


class SettleIn(Body):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class BudgetIn(Body):
    cpu_hours: Amount
    storage_gb: Amount


def add_compute_routes(
    router: APIRouter,
    operator: Dependency,
    fresh: Dependency,
    compute: ComputeService,
    tasks: TaskBoard,
    access: Access | None = None,
) -> None:
    """Mount the routes on ``router``; ``operator`` and ``fresh`` are the workbench's operator
    dependencies (``fresh`` also asks for a recent re-authentication)."""
    Operator = Annotated[Actor, Depends(operator)]  # noqa: N806
    Fresh = Annotated[Actor, Depends(fresh)]  # noqa: N806

    @router.post("/compute/balance")
    async def record_balance(body: BalanceIn, actor: Fresh):
        admin_only(access, actor)
        compute.record_balance(body.cpu_hours, actor.id, body.note)
        return compute.overview()["balance"]

    @router.post("/compute/tasks/{task_id}/budget")
    async def set_budget(task_id: PathId, body: BudgetIn, actor: Fresh):
        unknown = Denied("scope", f"unknown task {task_id}")
        try:
            task = tasks.get(task_id)
        except Denied:
            raise unknown from None
        project_write(access, actor, task.project_id, lambda: unknown)
        compute.set_task_budget(task_id, body.cpu_hours, body.storage_gb)
        (row,) = [t for t in compute.overview()["tasks"] if t["task_id"] == task_id]
        return row

    @router.post("/compute/attempts/{attempt_id}/settle")
    async def settle(attempt_id: PathId, body: SettleIn, actor: Fresh):
        """End an attempt nobody can recover, charged as unknown (see ``settle_attempt``)."""
        admin_only(access, actor)
        attempt = await compute.settle_attempt(attempt_id, actor.id, body.reason)
        return {
            "attempt_id": attempt.id,
            "phase": attempt.phase,
            "task_state": attempt.task_state.value,
            "used_cpu": attempt.used_cpu,
            "used_storage": attempt.used_storage,
            "settled_by": attempt.settled_by,
            "settle_reason": attempt.settle_reason,
            "error": attempt.error,
        }

    @router.get("/compute")
    async def overview(actor: Operator):
        found = compute.overview()
        if access is None or access.is_admin(actor):
            return found
        mine = lambda row: visible_task(access, actor, tasks, row["task_id"])  # noqa: E731
        lists = {
            name: [row for row in found[name] if mine(row)] for name in ("tasks", "jobs", "stuck")
        }
        return {**found, **lists, "balance": None, "service": None}  # no project-wide figures
