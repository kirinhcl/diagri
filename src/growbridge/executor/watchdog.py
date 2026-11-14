"""Unexpected-pump watchdog: a pump found on while DiAGRI is not irrigating is switched off.

Nobody switches the pump on by hand during an experiment and the pump is never left to the AC5
timer, so any pump-on that DiAGRI did not start is unexpected. The watchdog only reads the pump
read-back and acts through the dedicated ``pump_off`` path; it has no way to switch the pump on.
"""

import logging
from collections.abc import Callable
from typing import Any

from growbridge.archive.clock import Clock
from growbridge.observer.alerts import Severity
from growbridge.ports import ControlPort, Denied, PumpReading, StagePort, StageRuntime

UNREADABLE = "pump_unreadable"
UNEXPECTED = "pump_unexpected"
KEY = "pump"
FAILURE = "pump_watchdog"
INTERVENTION = "unexpected_watering"
REASSERT_SECONDS = 300.0  # a latched alert is stored again this often while it persists
MIN_UPDATE_SECONDS = 60.0  # a changed message is stored at most this often
MAX_MESSAGE = 200

UNREADABLE_TEXT = (
    "The pump outlet could not be read from the device status, so the pump watchdog cannot "
    "tell whether the pump is on."
)
OFF_TEXT = (
    "The pump was on while DiAGRI was not irrigating. It has been switched off and the pump "
    "outlet mode on the device was reset to manual."
)
UNCONFIRMED_TEXT = (
    "The pump was on while DiAGRI was not irrigating. The switch-off is unconfirmed; the "
    "interlock is set and keeps retrying."
)
FAILED_TEXT = (
    "The pump was on while DiAGRI was not irrigating. The switch-off failed (unconfirmed) and "
    "no interlock is set; the watchdog tries again on the next status."
)
RECORD_FAILED_TEXT = "The pump watchdog could not record the unexpected_watering intervention."

log = logging.getLogger(__name__)


class PumpWatchdog:
    def __init__(self, control: ControlPort, stages: StagePort, clock: Clock):
        self.control = control
        self.stages = stages
        self.clock = clock
        # hooks report whether the alert was stored; a latch is set only after a stored write
        self.alert: Callable[[str, str, str, Severity], bool] | None = None
        self.resolve: Callable[[str, str], bool] | None = None
        self._acted: float | None = None  # monotonic time of its own last switch-off
        # latched alerts: (message, monotonic time raised) while active, False once resolved;
        # absent until seen
        self._latched: dict[tuple[str, str], tuple[str, float] | bool] = {}

    async def step(self, stage: StageRuntime | None) -> None:
        if await self._decide(stage):
            self._leave(FAILURE, "step")  # a step that read the pump and did not raise

    async def _decide(self, stage: StageRuntime | None) -> bool:
        """True when the step got far enough to evaluate a pump reading."""
        control = self.control
        if not control.connected() or control.interlocked():
            return False
        reading = control.pump_reading()
        if reading.mono <= 0:
            return False  # no status received yet
        await self._evaluate(stage, reading)
        return True

    async def _evaluate(self, stage: StageRuntime | None, reading: PumpReading) -> None:
        control = self.control
        if reading.on is None:
            self._enter(UNREADABLE, KEY, UNREADABLE_TEXT, "warning")
            return
        self._leave(UNREADABLE, KEY)
        if control.irrigating():
            return
        end = control.last_cycle_end()
        if end is not None and reading.mono <= end:
            return  # a status from before the cycle's pump-off finished
        if self._acted is not None and reading.mono <= self._acted:
            return  # wait for a status newer than our own switch-off
        if reading.on is False:
            self._close(UNEXPECTED)
            return
        await self._switch_off(stage, reading.at)

    async def _switch_off(self, stage: StageRuntime | None, status_at: float) -> None:
        self._acted = self.clock.monotonic()
        before = self.control.last_pump_off_id()
        try:
            confirmed = await self.control.pump_off(trigger="watchdog")
        except Denied:
            confirmed = False
        if confirmed:
            text = OFF_TEXT
        else:
            text = UNCONFIRMED_TEXT if self.control.interlocked() else FAILED_TEXT
        self._raise(UNEXPECTED, text, "critical")
        if stage is None:
            return
        after = self.control.last_pump_off_id()
        detail: dict[str, Any] = {
            "status_at": status_at,
            "off_confirmed": confirmed,
            "off_confirmed_at": self.clock.now() if confirmed else None,
            "request_id": after if after != before else None,
        }
        try:
            self.stages.record_intervention(stage.stage_id, INTERVENTION, detail)
        except Exception:
            log.exception("could not record the unexpected_watering intervention")
            self._enter(FAILURE, "intervention", RECORD_FAILED_TEXT, "critical")
        else:
            self._leave(FAILURE, "intervention")

    def _raise(self, kind: str, message: str, severity: Severity, key: str = KEY) -> bool:
        """True when the hook stored the alert."""
        return self.alert is not None and bool(self.alert(kind, key, message, severity))

    def step_failed(self, error: Exception) -> None:
        """The engine's report that ``step`` itself raised."""
        self._enter(
            FAILURE,
            "step",
            f"The pump watchdog failed: {type(error).__name__}: {error}"[:MAX_MESSAGE],
            "critical",
        )

    def _enter(self, kind: str, key: str, message: str, severity: Severity) -> None:
        now = self.clock.monotonic()
        state = self._latched.get((kind, key))
        if isinstance(state, tuple):
            wait = REASSERT_SECONDS if state[0] == message else MIN_UPDATE_SECONDS
            if now - state[1] < wait:
                return
        if self._raise(kind, message, severity, key=key):  # a failed write is retried next time
            self._latched[(kind, key)] = (message, now)

    def _leave(self, kind: str, key: str) -> None:
        if self._latched.get((kind, key)) is False:
            return
        if self._close(kind, key):  # a failed resolve is retried next time
            self._latched[(kind, key)] = False

    def _close(self, kind: str, key: str = KEY) -> bool:
        """True when the hook resolved the alert (or found none open)."""
        return self.resolve is not None and bool(self.resolve(kind, key))
