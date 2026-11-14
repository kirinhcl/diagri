"""Finds sensors whose reading has stopped changing, records the period, and alerts.

Reads stored samples (never changes them). A running stage is paused only when one of its own
rules, or a protection rule, depends on the frozen sensor.
"""

import logging
from collections.abc import Callable, Sequence

from growbridge.archive.clock import Clock
from growbridge.archive.models import FrozenCheck, FrozenPeriod, SafetyConfig
from growbridge.archive.store import Archive
from growbridge.observer.alerts import Alert, AlertBook
from growbridge.observer.frozen import first_change, flat_tail, sensors_used
from growbridge.ports import StageEvent, StageEventKind, StagePort, StageRuntime
from growbridge.workflow.states import StageState

CHECK_SECONDS = 300.0
KIND = "frozen_reading"
log = logging.getLogger(__name__)

Series = Sequence[tuple[float, object]]


def _series(points: Sequence[tuple[float, dict]], sensor: str) -> list[tuple[float, object]]:
    return [(at, sensors.get(sensor)) for at, sensors in points]


def _protection_sensors(config: SafetyConfig | None) -> frozenset[str]:
    return frozenset(rule.sensor for rule in config.rules) if config else frozenset()


def _used_by(stage: StageRuntime, protection: frozenset[str]) -> frozenset[str]:
    """Sensors the stage depends on: those of its feedback rules and of the protection rules."""
    return sensors_used(protection | {rule.sensor for rule in stage.run_sheet.feedback_rules})


def _last_same(series: Series, period: FrozenPeriod) -> float:
    """Time of the last same-value valid point after the period opened and before any change."""
    after = [point for point in series if point[0] > period.first_at]
    change = first_change(after, period.value)
    last = period.first_at
    for at, value in after:
        if change is not None and at >= change:
            break
        if isinstance(value, int | float) and not isinstance(value, bool) and value == period.value:
            last = at
    return last


class FrozenWatch:
    def __init__(
        self,
        archive: Archive,
        book: AlertBook,
        stages: StagePort,
        safety: Callable[[], SafetyConfig | None],
        clock: Clock,
    ):
        self.archive = archive
        self.book = book
        self.stages = stages
        self.safety = safety
        self.clock = clock
        self._checked_at: float | None = None
        self._reported: set[str] = set()
        self._protection: frozenset[str] = frozenset()  # sensors of the last config read

    async def tick(self) -> bool:
        """True when a check ran to completion; False when skipped because one ran recently."""
        mono = self.clock.monotonic()
        if self._checked_at is not None and mono - self._checked_at < CHECK_SECONDS:
            return False
        self._checked_at = mono
        try:
            config = self.safety()
            self._protection = _protection_sensors(config)
            settings = config.frozen if config is not None else FrozenCheck()
            self._update_periods(settings, self._protection, may_close=config is not None)
        finally:  # periods already open still pause the stage if the config or update fails,
            await self._pause_stage(self._protection)  # using the last protection sensors read
        return True

    def _update_periods(
        self, settings: FrozenCheck, protection: frozenset[str], may_close: bool
    ) -> None:
        """Without a configuration the defaults open periods and follow changes, but nothing is
        closed because a sensor is missing from a list that is not there."""
        periods = self.archive.open_frozen_periods()
        self._resolve_stale_alerts({period.sensor for period in periods})
        points: Sequence[tuple[float, dict]] = ()
        if settings.minutes:
            window = max(settings.minutes.values()) * 60 + settings.max_gap_seconds
            points = self.archive.sensor_points(self.clock.now() - window)
        critical = sensors_used(protection)
        for period in periods:
            if period.sensor not in settings.minutes:
                if may_close:
                    reason = "no_longer_listed" if settings.minutes else "nothing_checked"
                    self._close(period, _series(points, period.sensor), reason)
            else:
                self._follow(period, _series(points, period.sensor), critical)
        have_open = {p.sensor for p in periods}
        for name, minutes in settings.minutes.items():
            if name not in have_open:
                self._maybe_open(name, minutes, _series(points, name), settings, critical)

    def _resolve_stale_alerts(self, open_sensors: set[str]) -> None:
        """Alerts and periods live in separate databases: a period can close while resolving its
        alert fails. Such an alert, with no open period behind it, is resolved here."""
        for alert in self.book.open():
            if alert.kind == KIND and alert.key not in open_sensors:
                self.book.resolve(KIND, alert.key)

    def _close(self, period: FrozenPeriod, series: Series, reason: str) -> None:
        last_at = _last_same(series, period)
        self.archive.close_frozen(period.period_id, period.sensor, last_at, reason)
        self.book.resolve(KIND, period.sensor)

    def _follow(self, period: FrozenPeriod, series: Series, critical: frozenset[str]) -> None:
        after = [point for point in series if point[0] > period.first_at]
        if first_change(after, period.value) is not None:
            self._close(period, series, "value_changed")
            return
        alert = self._open_alert(period.sensor)
        if alert is None or (period.sensor in critical and alert.severity != "critical"):
            self._raise(period.sensor, period.value, critical)  # lost, or now more serious

    def _maybe_open(
        self, name: str, minutes: float, series: Series, settings: FrozenCheck, critical: frozenset
    ) -> None:
        run = flat_tail(series, settings.max_gap_seconds)
        if run is None or run.last_at - run.first_at < minutes * 60:
            return
        self.archive.open_frozen(name, run.value, run.first_at)
        self._raise(name, run.value, critical)

    def _raise(self, name: str, value: float, critical: frozenset[str]) -> None:
        severity = "critical" if name in critical else "warning"
        message = f"{name} has reported exactly {value:g} without change (frozen reading)"
        self.book.raise_alert(KIND, name, severity, message)

    def _open_alert(self, name: str) -> Alert | None:
        for alert in self.book.open():
            if alert.kind == KIND and alert.key == name:
                return alert
        return None

    def _alert_id(self, name: str) -> str | None:
        alert = self._open_alert(name)
        return alert.event_id if alert else None

    async def _pause_stage(self, protection: frozenset[str]) -> None:
        """Report a pause for each open period the running stage depends on, protection-used
        sensors first. Once a report has paused the stage (or ended it) the rest wait for a
        later check: a second pause would be dropped and spend its event id."""
        stage = self.stages.active_stage()
        if stage is None or stage.state is not StageState.RUNNING:
            return
        critical = sensors_used(protection)
        used = _used_by(stage, protection)
        periods = sorted(
            self.archive.open_frozen_periods(), key=lambda p: (p.sensor not in critical, p.first_at)
        )
        for period in periods:
            event_id = f"frozen_pause:{period.period_id}:{stage.stage_id}"
            if period.sensor not in used or event_id in self._reported:
                continue
            await self.stages.report(self._pause_event(event_id, stage.stage_id, period))
            self._reported.add(event_id)
            stage = self.stages.active_stage()
            if stage is None or stage.state is not StageState.RUNNING:
                return
            used = _used_by(stage, protection)  # the stage may now be another one

    def _pause_event(self, event_id: str, stage_id: str, period: FrozenPeriod) -> StageEvent:
        detail: dict[str, object] = {"rule": f"frozen:{period.sensor}"}
        alert_id = self._alert_id(period.sensor)
        if alert_id is not None:
            detail["alert"] = alert_id
        detail["period"] = period.period_id
        return StageEvent(
            event_id=event_id,
            kind=StageEventKind.ALERT_PAUSE,
            stage_id=stage_id,
            at=self.clock.now(),
            detail=detail,
        )
