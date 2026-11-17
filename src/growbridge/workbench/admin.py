"""Administrator routes of the workbench (multi-user), under ``/wb/admin``.

Accounts (add, disable, reset a secret: the name travels in the body, since a name may hold a
slash), the greenhouse locks with their history, a forced release with a reason, and handing a
project to another operator. A project changes hands only when nobody can act on it any more (no
owner, or a disabled one) and no stage of it is unfinished, so no command is in flight and no
write right is bound to the old owner. Every write needs a recent re-authentication.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from growbridge.ports import Actor, Denied
from growbridge.workbench.auth import (
    MAX_SECRET_LENGTH,
    MIN_SECRET_LENGTH,
    NAME_LIMIT,
    ROLES,
    Operators,
)
from growbridge.workbench.common import Body, rejected
from growbridge.workbench.greenhouses import greenhouse_rows
from growbridge.workbench.rounds import PathId
from growbridge.workflow import denials
from growbridge.workflow.access import Access
from growbridge.workflow.locks import GreenhouseLocks
from growbridge.workflow.store import WorkflowStore

Dependency = Callable[..., Awaitable[Actor]]
Name = Annotated[str, Field(min_length=1, max_length=64)]
Secret = Annotated[str, Field(min_length=1, max_length=256)]
Note = Annotated[str, Field(min_length=1, max_length=500)]


class OperatorIn(Body):
    name: Name
    secret: Secret
    role: Literal["user", "admin"] = "user"


class NameIn(Body):
    name: Name


class SecretIn(Body):
    name: Name
    secret: Secret


class NoteIn(Body):
    note: Note


class OwnerIn(Body):
    owner: Name
    note: Note


def _accounts(operators: Operators, store: WorkflowStore) -> list[dict]:
    return [
        {**row, "unfinished_stages": store.unfinished_stages_of_owner(row["name"])}
        for row in operators.listing()
    ]


def _transferable(operators: Operators, store: WorkflowStore, project_id: str, owner: str):
    """The transfer conditions; run again inside the transaction that changes the owner."""

    def check() -> None:
        if not store.has_project(project_id):
            raise denials.unknown("project", project_id)
        current = store.project_owner(project_id)
        if current is not None and operators.active(current):
            raise Denied(
                "state",
                "the owner can still act: disable the account first",
                reason="owner_still_active",
                params={"project_id": project_id, "owner": current},
            )
        if store.project_unfinished(project_id):
            raise Denied(
                "state",
                "stop the project's unfinished stages first",
                reason="project_has_unfinished_stages",
                params={"project_id": project_id},
            )
        if not operators.active(owner):
            raise Denied(
                "state",
                f"{owner} is not an active operator",
                reason="operator_not_active",
                params={"name": owner},
            )

    return check


def _account_refused(error: ValueError, name: str) -> HTTPException:
    """The refusal for an account change ``Operators`` turned down, by the case it names."""
    message, case = str(error), getattr(error, "case", None)
    if case == "name_length":
        return rejected(message, reason="operator_name_length", params={"max_length": NAME_LIMIT})
    if case == "secret_length":
        bounds = {"min_length": MIN_SECRET_LENGTH, "max_length": MAX_SECRET_LENGTH}
        return rejected(message, reason="secret_length", params=bounds)
    if case == "role":
        choices = {"field": "role", "choices": list(ROLES)}
        return rejected(message, reason="param_not_in_choices", params=choices)
    if case == "name_taken":
        return rejected(message, reason="operator_exists", params={"name": name})
    if case == "unknown_operator":
        return rejected(message, reason="operator_unknown", params={"name": name})
    if case == "own_account":
        return rejected(message, reason="own_account")
    if case == "last_admin":
        return rejected(message, reason="last_admin")
    return rejected(message, reason="account_change_refused", params={"detail": message})


def _accounts_routes(router, fresh, operators, store, admin) -> None:
    Admin = Annotated[Actor, Depends(admin)]  # noqa: N806
    Fresh = Annotated[Actor, Depends(fresh)]  # noqa: N806

    @router.get("/admin/operators")
    async def accounts(actor: Admin):
        return {"operators": _accounts(operators, store)}

    @router.post("/admin/operators")
    async def add(body: OperatorIn, actor: Fresh, _admin: Admin):
        try:
            operators.add(body.name, body.secret, body.role)
        except ValueError as error:
            raise _account_refused(error, body.name.strip()) from error
        return {"name": body.name.strip(), "role": body.role}

    @router.post("/admin/operators/disable")
    async def disable(body: NameIn, actor: Fresh, _admin: Admin):
        try:
            operators.disable(body.name, by=actor.id)
        except ValueError as error:
            raise _account_refused(error, body.name) from error
        return {"disabled": body.name}

    @router.post("/admin/operators/secret")
    async def secret(body: SecretIn, actor: Fresh, _admin: Admin):
        try:
            operators.reset_secret(body.name, body.secret)
        except ValueError as error:
            raise _account_refused(error, body.name) from error
        return {"reset": body.name}


def _lock_routes(router, fresh, operators, locks, store, access, admin) -> None:
    Admin = Annotated[Actor, Depends(admin)]  # noqa: N806
    Fresh = Annotated[Actor, Depends(fresh)]  # noqa: N806

    @router.get("/admin/locks")
    async def all_locks(actor: Admin):
        return {"locks": greenhouse_rows(locks, access, actor), "events": locks.events()}

    @router.post("/admin/greenhouses/{greenhouse_id}/release")
    async def force_release(greenhouse_id: PathId, body: NoteIn, actor: Fresh, _admin: Admin):
        await locks.release(greenhouse_id, actor.id, force=True, note=body.note)
        return {"released": greenhouse_id}

    @router.post("/admin/projects/{project_id}/owner")
    async def transfer(project_id: PathId, body: OwnerIn, actor: Fresh, _admin: Admin):
        eligible = _transferable(operators, store, project_id, body.owner)
        now = locks.clock.now()
        store.set_project_owner(project_id, body.owner, actor.id, body.note, now, eligible)
        return {"project_id": project_id, "owner": body.owner}


def add_admin_routes(
    router: APIRouter,
    operator: Dependency,
    fresh: Dependency,
    operators: Operators,
    locks: GreenhouseLocks,
    store: WorkflowStore,
    access: Access,
) -> None:
    async def admin(actor: Annotated[Actor, Depends(operator)]) -> Actor:
        access.require_admin(actor)
        return actor

    _accounts_routes(router, fresh, operators, store, admin)
    _lock_routes(router, fresh, operators, locks, store, access, admin)
