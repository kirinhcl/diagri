"""Finds sensors whose reading has stopped changing, records the period, and alerts.

Reads stored samples (never changes them). A running stage is paused only when one of its own
rules, or a protection rule, depends on the frozen sensor.
"""

import logging
from collections.abc import Callable, Sequence

from growbridge.archive.clock import Clock
from growbridge.archive.models import FrozenCheck, FrozenPeriod, SafetyConfig
from growbridge.archive.store import Archive
from growbridge.observer.alerts import AlertBook
from growbridge.observer.frozen import first_change, flat_tail, sensors_used
from growbridge.ports import StageEvent, StageEventKind, StagePort
from growbridge.workflow.states import StageState

CHECK_SECONDS = 300.0
KIND = "frozen_reading"
log = logging.getLogger(__name__)

Series = Sequence[tuple[float, object]]


def _series(points: Sequence[tuple[float, dict]], sensor: str) -> list[tuple[float, object]]:
    return [(at, sensors.get(sensor)) for at, sensors in points]


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

    async def tick(self) -> None:
        mono = self.clock.monotonic()
        if self._checked_at is not None and mono - self._checked_at < CHECK_SECONDS:
            return
        self._checked_at = mono
        config = self.safety()
        settings = config.frozen if config is not None else FrozenCheck()
        protection = frozenset(rule.sensor for rule in config.rules) if config else frozenset()
        self._update_periods(settings, protection)
        await self._pause_stage(protection)

    def _update_periods(self, settings: FrozenCheck, protection: frozenset[str]) -> None:
        periods = self.archive.open_frozen_periods()
        points: Sequence[tuple[float, dict]] = ()
        if settings.minutes:
            window = max(settings.minutes.values()) * 60 + settings.max_gap_seconds
            points = self.archive.sensor_points(self.clock.now() - window)
        critical = sensors_used(protection)
        for period in periods:
            if period.sensor not in settings.minutes:
                self._close(period, _series(points, period.sensor))
            else:
                self._follow(period, _series(points, period.sensor), critical)
        have_open = {p.sensor for p in periods}
        for name, minutes in settings.minutes.items():
            if name not in have_open:
                self._maybe_open(name, minutes, _series(points, name), settings, critical)

    def _close(self, period: FrozenPeriod, series: Series) -> None:
        self.archive.close_frozen(period.period_id, period.sensor, _last_same(series, period))
        self.book.resolve(KIND, period.sensor)

    def _follow(self, period: FrozenPeriod, series: Series, critical: frozenset[str]) -> None:
        after = [point for point in series if point[0] > period.first_at]
        if first_change(after, period.value) is not None:
            self._close(period, series)
        elif self._alert_id(period.sensor) is None:  # the alert was lost; keep it visible
            self._raise(period.sensor, period.value, critical)

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

    def _alert_id(self, name: str) -> str | None:
        for alert in self.book.open():
            if alert.kind == KIND and alert.key == name:
                return alert.event_id
        return None

    async def _pause_stage(self, protection: frozenset[str]) -> None:
        stage = self.stages.active_stage()
        if stage is None or stage.state is not StageState.RUNNING:
            return
        rules = {rule.sensor for rule in stage.run_sheet.feedback_rules}
        used = sensors_used(protection | rules)
        for period in self.archive.open_frozen_periods():
            event_id = f"frozen_pause:{period.period_id}:{stage.stage_id}"
            if period.sensor not in used or event_id in self._reported:
                continue
            detail: dict[str, object] = {"rule": f"frozen:{period.sensor}"}
            alert_id = self._alert_id(period.sensor)
            if alert_id is not None:
                detail["alert"] = alert_id
            detail["period"] = period.period_id
            event = StageEvent(
                event_id=event_id,
                kind=StageEventKind.ALERT_PAUSE,
                stage_id=stage.stage_id,
                at=self.clock.now(),
                detail=detail,
            )
            await self.stages.report(event)
            self._reported.add(event_id)
