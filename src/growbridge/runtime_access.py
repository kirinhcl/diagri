"""Assembly of the multi-user rules (design 2026-11-16): greenhouse locks and access checks.

Kept out of ``runtime.py`` (which stays within 800 lines). With ``multi_user`` off nothing is built
and the workflow and the workbench behave exactly as before.
"""

from collections.abc import Awaitable, Callable
from typing import Any, NamedTuple

from growbridge.archive.clock import Clock
from growbridge.archive.db import Database
from growbridge.config import Settings
from growbridge.ports import ControlPort
from growbridge.workflow.access import Access
from growbridge.workflow.device_test import DeviceTests
from growbridge.workflow.locks import GreenhouseLocks
from growbridge.workflow.service import WorkflowService


class AccessParts(NamedTuple):
    locks: GreenhouseLocks
    access: Access
    tests: DeviceTests  # device tests before a round (design 2026-11-27)


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
    tests = DeviceTests(
        db,
        clock,
        control,
        locks,
        access,
        workflow.store,
        workflow.idle_care,
        max_pump_seconds=settings.max_pump_seconds,
    )
    locks.tests = workflow.device_tests = tests
    return AccessParts(locks, access, tests)


def device_test_step(parts: AccessParts | None) -> Callable[[], Awaitable[None]]:
    """The runtime tick's step: a test a restart cut off is restored once the link allows."""

    async def step() -> None:
        if parts is not None:
            await parts.tests.resume()

    return step


def wire_device_tests(parts: AccessParts | None, executor: Any, runtime: Any) -> None:
    """Once the executor and the runtime exist: protected channels, alerts and their resolve."""
    if parts is None:
        return
    parts.tests.protected = executor.protected_channels
    parts.tests.alert = runtime.alert
    parts.tests.resolve = runtime.resolve_alert


def workbench_access(parts: AccessParts | None) -> dict[str, Any]:
    """The keyword arguments ``create_workbench`` takes for the multi-user rules."""
    if parts is None:
        return {}
    return {"access": parts.access, "locks": parts.locks, "tests": parts.tests}
