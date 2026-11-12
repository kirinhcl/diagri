"""Clock trust and link outages for the executor (spec 7.7).

``ClockTrust`` decides whether wall time may drive calendar actions; when it may not, the last
trusted wall time plus elapsed monotonic time stands in for it. ``LinkWatch`` measures how long
the BLE link was down, and ``outage_reasons`` applies the four conditions that make an outage
affect the run.
"""

from growbridge.archive.clock import Clock
from growbridge.archive.models import Model, RunSheet

CLOCK_JUMP_SECONDS = 5.0  # wall time may differ this much from monotonic time between ticks


class ClockTrust:
    """Wall time is trusted while the host says it is synchronised and it has not stepped."""

    def __init__(self, clock: Clock):
        self._clock = clock
        self._anchor: tuple[float, float] | None = None  # (wall, monotonic) of the last trust
        self._last: tuple[float, float] | None = None
        self._was_synced = clock.synced
        self._suspect = False
        self.trusted = False

    def observe(self) -> bool:
        """Call once per tick, before using ``now``."""
        wall, mono, synced = self._clock.now(), self._clock.monotonic(), self._clock.synced
        if synced and not self._was_synced:
            self._suspect = False  # the host reports a fresh synchronisation
        self._was_synced = synced
        if synced and self._last is not None:
            drift = (wall - self._last[0]) - (mono - self._last[1])
            self._suspect = self._suspect or abs(drift) > CLOCK_JUMP_SECONDS
        self._last = (wall, mono)
        self.trusted = synced and not self._suspect
        if self.trusted:
            self._anchor = (wall, mono)
        return self.trusted

    def accept(self) -> None:
        """An operator has checked the host clock: forget the step seen earlier.

        The last observation is kept, so a step since the previous tick is still noticed, and
        the host's own ``synced`` flag is not overridden.
        """
        self._suspect = False

    def now(self) -> float | None:
        """Best known UTC time, or ``None`` when no trusted time has ever been seen."""
        if self.trusted:
            return self._clock.now()
        if self._anchor is None:
            return None
        return self._anchor[0] + (self._clock.monotonic() - self._anchor[1])


class Outage(Model):
    start_mono: float
    started_at: float | None  # trusted UTC time when the drop was noticed
    seconds: float


class LinkWatch:
    """Notices drops and reconnections; every outage is measured on the monotonic clock."""

    def __init__(self) -> None:
        self._down: tuple[float, float | None] | None = None

    def observe(self, connected: bool, mono: float, trusted_now: float | None) -> Outage | None:
        """Return the finished outage on the tick that sees the link come back."""
        if not connected:
            if self._down is None:
                self._down = (mono, trusted_now)
            return None
        if self._down is None:
            return None
        start, at = self._down
        self._down = None
        return Outage(start_mono=start, started_at=at, seconds=mono - start)


def outage_reasons(
    sheet: RunSheet, outage: Outage, now: float | None, unsettled: bool, differs: bool
) -> tuple[str, ...]:
    """Which of the §7.7 conditions hold; an empty tuple means the outage does not matter."""
    reasons = []
    if outage.started_at is not None and now is not None:
        if sheet.expected_levels(outage.started_at) != sheet.expected_levels(now):
            reasons.append("due_action")
    if differs:
        reasons.append("device_differs")
    if unsettled:
        reasons.append("unknown_result")
    if outage.seconds > sheet.sampling.max_gap_seconds:
        reasons.append("gap_too_long")
    return tuple(reasons)
