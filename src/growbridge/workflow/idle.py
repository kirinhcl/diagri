"""The idle write right of a greenhouse (design 2026-11-24, 5.3).

Before the device's first stage, and once a release ended its last one, the workflow holds one
care-kind write right that may write only the configured idle levels; the
executor aligns the device to them. A stage start hands the right back together with the care
rights, so no idle write lands after it; while a start awaits those hand-overs no idle right is
granted or used (a tick may run in between). The right is not stored: a restart revokes every
right anyway, and ``restore`` grants a fresh one on the next tick. An aborted or delivered round
without a release is not idle: the holder's plants may still be inside.
"""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager

from growbridge.archive.models import RightKind, RuleAction
from growbridge.ports import ControlPort, IdleRuntime, RightScope
from growbridge.workflow.store import WorkflowStore


class IdleCare:
    def __init__(
        self,
        store: WorkflowStore,
        control: ControlPort,
        device_id: str,
        levels: tuple[RuleAction, ...],
    ):
        self.store = store
        self.control = control
        self.device_id = device_id
        self.levels = levels
        self._right: int | None = None
        self._starts = 0  # stage starts handing rights back, or device tests, right now

    @property
    def right(self) -> int | None:
        """The number of the idle right last granted, valid or not."""
        return self._right

    def restore(self) -> None:
        """Grant the idle right when it is due and the held one is missing or void."""
        if not self._due() or self._valid():
            return
        if not self.control.transport_stopped() or self.control.interlocked():
            return  # the same gate as restoring care: old writes must be confirmed gone
        scope = RightScope(device_id=self.device_id, levels=self.levels)
        self._right = self.control.grant(RightKind.CARE, scope)

    def runtime(self) -> IdleRuntime | None:
        """What the executor may write now, or None."""
        if not self._due() or not self._valid():
            return None
        assert self._right is not None
        return IdleRuntime(right=self._right, levels=self.levels)

    @contextmanager
    def held_back(self) -> Iterator[None]:
        """Around a stage start: no idle right is granted or used until it is over."""
        self._starts += 1
        try:
            yield
        finally:
            self._starts -= 1

    @asynccontextmanager
    async def paused(self) -> AsyncIterator[None]:
        """Around a device test: the idle right is handed back and none is granted or used until
        it is over; ``restore`` grants a fresh one on the next tick."""
        self._starts += 1
        try:
            if self._valid():
                assert self._right is not None
                await self.control.handover(self._right, "device test")
            yield
        finally:
            self._starts -= 1

    def _due(self) -> bool:
        if self._starts or not self.levels:
            return False
        last = self.store.last_started_on(self.device_id)
        return last is None or last.care_released

    def _valid(self) -> bool:
        right = None if self._right is None else self.control.right(self._right)
        if right is None or right.revoked_at is not None:
            return False
        return right.recovery_number == self.control.recovery_number()
