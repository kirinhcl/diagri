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
from growbridge.ports import ControlPort, Denied, StagePort, StageRuntime

UNREADABLE = "pump_unreadable"
UNEXPECTED = "pump_unexpected"
KEY = "pump"
FAILURE = "pump_watchdog"
INTERVENTION = "unexpected_watering"

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
        self.alert: Callable[[str, str, str, Severity], None] | None = None
        self.resolve: Callable[[str, str], None] | None = None
        self._acted: float | None = None  # monotonic time of its own last switch-off
        # latched alerts: raised on entering a state, resolved on leaving it; unknown until seen
        self._latched: dict[tuple[str, str], bool] = {}

    async def step(self, stage: StageRuntime | None) -> None:
        await self._decide(stage)
        self._leave(FAILURE, "step")  # reached only when the step completed without raising

    async def _decide(self, stage: StageRuntime | None) -> None:
        control = self.control
        if not control.connected() or control.interlocked():
            return
        reading = control.pump_reading()
        if reading.mono <= 0:
            return  # no status received yet
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

    def _raise(self, kind: str, message: str, severity: Severity, key: str = KEY) -> None:
        if self.alert is not None:
            self.alert(kind, key, message, severity)

    def step_failed(self, error: Exception) -> None:
        """The engine's report that ``step`` itself raised."""
        self._enter(
            FAILURE,
            "step",
            f"The pump watchdog failed: {type(error).__name__}: {error}",
            "critical",
        )

    def _enter(self, kind: str, key: str, message: str, severity: Severity) -> None:
        if self._latched.get((kind, key)) is True:
            return
        self._latched[(kind, key)] = True
        self._raise(kind, message, severity, key=key)

    def _leave(self, kind: str, key: str) -> None:
        if self._latched.get((kind, key)) is False:
            return
        self._latched[(kind, key)] = False
        self._close(kind, key)

    def _close(self, kind: str, key: str = KEY) -> None:
        if self.resolve is not None:
            self.resolve(kind, key)
