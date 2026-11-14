"""Unexpected-pump watchdog: a pump found on while DiAGRI is not irrigating is switched off.

Nobody switches the pump on by hand during an experiment and the pump is never left to the AC5
timer, so any pump-on that DiAGRI did not start is unexpected. The watchdog only reads the pump
read-back and acts through the dedicated ``pump_off`` path; it has no way to switch the pump on.
"""

from collections.abc import Callable
from typing import Any

from growbridge.archive.clock import Clock
from growbridge.observer.alerts import Severity
from growbridge.ports import ControlPort, Denied, StagePort, StageRuntime

UNREADABLE = "pump_unreadable"
UNEXPECTED = "pump_unexpected"
KEY = "pump"
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


class PumpWatchdog:
    def __init__(self, control: ControlPort, stages: StagePort, clock: Clock):
        self.control = control
        self.stages = stages
        self.clock = clock
        self.alert: Callable[[str, str, str, Severity], None] | None = None
        self.resolve: Callable[[str, str], None] | None = None
        self._acted: float | None = None  # monotonic time of its own last switch-off

    async def step(self, stage: StageRuntime | None) -> None:
        control = self.control
        if not control.connected() or control.interlocked():
            return
        reading = control.pump_reading()
        if reading.mono <= 0:
            return  # no status received yet
        if reading.on is None:
            self._raise(UNREADABLE, UNREADABLE_TEXT, "warning")
            return
        self._close(UNREADABLE)
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
        try:
            confirmed = await self.control.pump_off(trigger="watchdog")
        except Denied:
            confirmed = False
        self._raise(UNEXPECTED, OFF_TEXT if confirmed else UNCONFIRMED_TEXT, "critical")
        if stage is None:
            return
        detail: dict[str, Any] = {
            "status_at": status_at,
            "off_confirmed": confirmed,
            "off_confirmed_at": self.clock.now() if confirmed else None,
            "request_id": self.control.last_pump_off_id(),
        }
        self.stages.record_intervention(stage.stage_id, INTERVENTION, detail)

    def _raise(self, kind: str, message: str, severity: Severity) -> None:
        if self.alert is not None:
            self.alert(kind, KEY, message, severity)

    def _close(self, kind: str) -> None:
        if self.resolve is not None:
            self.resolve(kind, KEY)
