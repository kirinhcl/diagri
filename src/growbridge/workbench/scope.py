"""Owner, lock and visibility checks shared by the workbench routes (multi-user).

Every function does nothing when ``access`` is None (multi-user off). ``hidden`` builds the very
answer the route gives for an id that does not exist, so another operator's object is
indistinguishable from a missing one.
"""

from __future__ import annotations

from growbridge.ports import Actor, Denied
from growbridge.workflow.access import Access, Hidden


def project_write(access: Access | None, actor: Actor, project_id: str, hidden: Hidden) -> None:
    if access is not None:
        access.require_project(actor, project_id, hidden)


def stage_write(
    access: Access | None,
    actor: Actor,
    stage_id: str,
    hidden: Hidden | None = None,
    emergency: bool = False,
) -> None:
    if access is None:
        return
    unknown = hidden or (lambda: Denied("state", f"unknown stage {stage_id}"))
    stage = access.store.find_stage(stage_id)
    if stage is None:
        raise unknown()
    access.require_stage(actor, stage, unknown, emergency)


def admin_only(access: Access | None, actor: Actor) -> None:
    if access is not None:
        access.require_admin(actor)


def project_read(access: Access | None, actor: Actor, project_id: str, hidden: Hidden) -> None:
    if access is not None and not access.sees_project(actor, project_id):
        raise hidden()


def stage_read(access: Access | None, actor: Actor, stage_id: str, hidden: Hidden) -> None:
    if access is not None and not access.sees_stage(actor, stage_id):
        raise hidden()
