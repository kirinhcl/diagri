"""Who may see and act on what when the workbench is multi-user (design 2026-11-16, §6, §7).

Only operator identities are checked: model, workflow and observer identities keep the scope they
always had (a model works for its bound task's project). An operator sees and acts on the
projects they own; an administrator sees everything but acts on another's stage only to pause or
stop it. Acting on a stage also needs the greenhouse lock of the stage's device. What a caller may
not see is answered exactly as if it did not exist (``hidden``).

The module-level ``guard_*`` functions are what ``WorkflowService`` calls: one line per entry
point, nothing at all when the service has no ``Access`` (multi-user off).
"""

from __future__ import annotations

from collections.abc import Callable

from growbridge.observer.alerts import Alert
from growbridge.ports import Actor, Denied
from growbridge.workflow.locks import GreenhouseLocks
from growbridge.workflow.store import StageRow, WorkflowStore

Hidden = Callable[[], Exception]


class Access:
    def __init__(self, store: WorkflowStore, locks: GreenhouseLocks, local_device: str):
        self.store = store
        self.locks = locks
        self.local_device = local_device

    @staticmethod
    def is_admin(actor: Actor) -> bool:
        return actor.kind == "operator" and actor.role == "admin"

    def owner_filter(self, actor: Actor) -> str | None:
        """The owner a listing keeps for this caller; None means every project."""
        return None if self.is_admin(actor) else actor.id

    # --- acting --------------------------------------------------------------------------------

    def require_project(self, actor: Actor, project_id: str, hidden: Hidden) -> None:
        if actor.kind != "operator" or self.store.project_owner(project_id) == actor.id:
            return
        if self.is_admin(actor) and self.store.has_project(project_id):
            raise Denied("not_owner", "administrators do not act on another operator's project")
        raise hidden()

    def require_stage(
        self, actor: Actor, stage: StageRow, hidden: Hidden, emergency: bool = False
    ) -> None:
        if actor.kind != "operator" or (emergency and self.is_admin(actor)):
            return
        self.require_project(actor, stage.project_id, hidden)
        if self.locks.holder_of_device(stage.device_id) != actor.id:
            raise Denied("not_lock_holder", "lock the stage's greenhouse first")

    def require_sheet_device(self, project_id: str, device_id: str) -> None:
        """Whoever drafts (an operator or a model), the project's owner holds the greenhouse."""
        owner = self.store.project_owner(project_id)
        if owner is None or self.locks.holder_of_device(device_id) != owner:
            raise Denied("not_lock_holder", "the project's owner does not hold this greenhouse")

    def require_admin(self, actor: Actor) -> None:
        if not self.is_admin(actor):
            raise Denied("admin_only", "only an administrator can do this")

    # --- seeing --------------------------------------------------------------------------------

    def sees_project(self, actor: Actor, project_id: str) -> bool:
        if actor.kind != "operator" or self.is_admin(actor):
            return True
        return self.store.project_owner(project_id) == actor.id

    def sees_stage(self, actor: Actor, stage_id: str) -> bool:
        stage = self.store.find_stage(stage_id)
        return stage is not None and self.sees_project(actor, stage.project_id)

    def sees_device(self, actor: Actor, device_id: str) -> bool:
        if actor.kind != "operator" or self.is_admin(actor):
            return True
        return self.locks.holder_of_device(device_id) == actor.id

    def sees_alert(self, actor: Actor, alert: Alert) -> bool:
        if self.is_admin(actor):
            return True
        if alert.scope is None:
            return False  # the system's own alerts, and those stored before scopes
        kind, ident = alert.scope
        checks = {
            "stage": self.sees_stage,
            "project": self.sees_project,
            "device": self.sees_device,
        }
        check = checks.get(kind)
        return check is not None and check(actor, ident)


# --- what WorkflowService calls ----------------------------------------------------------------


def guard_project(access: Access | None, actor: Actor, project_id: str, hidden: Hidden) -> None:
    if access is not None:
        access.require_project(actor, project_id, hidden)


def guard_stage(
    access: Access | None, actor: Actor, stage: StageRow, emergency: bool = False
) -> None:
    if access is not None:
        hidden = lambda: Denied("state", f"unknown stage {stage.stage_id}")  # noqa: E731
        access.require_stage(actor, stage, hidden, emergency)


def guard_round(access: Access | None, actor: Actor, store: WorkflowStore, round_id: str) -> None:
    if access is not None:
        project_id = store.round(round_id).project_id
        hidden = lambda: Denied("state", f"unknown round {round_id}")  # noqa: E731
        access.require_project(actor, project_id, hidden)


def guard_sheet(access: Access | None, project_id: str, device_id: str) -> None:
    if access is not None:
        access.require_sheet_device(project_id, device_id)
