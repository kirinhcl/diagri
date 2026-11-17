"""Assembly of the multi-user rules (design 2026-11-16): greenhouse locks and access checks.

Kept out of ``runtime.py`` (which stays within 800 lines). With ``multi_user`` off nothing is built
and the workflow and the workbench behave exactly as before.
"""

from typing import Any, NamedTuple

from growbridge.archive.clock import Clock
from growbridge.archive.db import Database
from growbridge.config import Settings
from growbridge.ports import ControlPort
from growbridge.workflow.access import Access
from growbridge.workflow.locks import GreenhouseLocks
from growbridge.workflow.service import WorkflowService


class AccessParts(NamedTuple):
    locks: GreenhouseLocks
    access: Access


def build_access(
    settings: Settings, db: Database, clock: Clock, workflow: WorkflowService, control: ControlPort
) -> AccessParts | None:
    """Locks and rules in the workflow database, handed to the workflow; None when off."""
    if not (settings.auto_research and settings.multi_user):
        return None
    registry = settings.greenhouse_registry()
    locks = GreenhouseLocks(db, clock, registry, workflow.store, control)
    access = Access(workflow.store, locks, settings.device)
    workflow.access = access
    return AccessParts(locks, access)


def workbench_access(parts: AccessParts | None) -> dict[str, Any]:
    """The keyword arguments ``create_workbench`` takes for the multi-user rules."""
    return {} if parts is None else {"access": parts.access, "locks": parts.locks}
