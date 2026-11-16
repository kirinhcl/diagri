"""The observer loop: local rules in, alerts, notifications and stage reports out (section 8.1).

The observer never writes to the device. A rule marked ``pause_stage`` only reports an
``ALERT_PAUSE`` event to the stage port; the workflow service decides what that means.
"""

import logging
from collections.abc import Callable, Sequence

from growbridge.archive.clock import Clock
from growbridge.archive.store import Archive
from growbridge.control.service import ControlService
from growbridge.observer.alerts import (
    Alert,
    AlertBook,
    AlertRule,
    RuleState,
    evaluate_alert_rules,
)
from growbridge.observer.frozen_watch import FrozenWatch
from growbridge.observer.outbox import Outbox
from growbridge.observer.stage_checks import StageChecks
from growbridge.ports import Reading, StageEvent, StageEventKind, StagePort

DEFAULT_CHANNELS = ("telegram",)
DEFAULT_ALERT_RULES: tuple[AlertRule, ...] = ()
log = logging.getLogger(__name__)


class Observer:
    def __init__(
        self,
        stages: StagePort,
        control_readings: Callable[[], Sequence[Reading]],
        book: AlertBook,
        outbox: Outbox,
        rules: Sequence[AlertRule],
        clock: Clock,
        notify_channels: Sequence[str] = DEFAULT_CHANNELS,
        frozen: FrozenWatch | None = None,
        stage_checks: StageChecks | None = None,
    ):
        self.stages = stages
        self.control_readings = control_readings
        self.book = book
        self.outbox = outbox
        self.rules = tuple(rules)
        self.clock = clock
        self.notify_channels = tuple(notify_channels)
        self.frozen = frozen
        self.stage_checks = stage_checks
        self.states: dict[str, RuleState] = {}

    def _queue_open_alerts(self) -> None:
        """Queue every open alert on every channel. The outbox is idempotent per event id and
        channel, so this also repairs an alert whose notification was lost to a crash."""
        for alert in self.book.open():
            text = f"[{alert.severity}] {alert.message}"
            for channel in self.notify_channels:
                self.outbox.queue_notification(alert.event_id, channel, text)

    async def _pause(self, rule: AlertRule, alert: Alert) -> None:
        stage = self.stages.active_stage()
        if stage is None:
            return
        await self.stages.report(
            StageEvent(
                event_id=f"alert_pause:{alert.event_id}",
                kind=StageEventKind.ALERT_PAUSE,
                stage_id=stage.stage_id,
                at=self.clock.now(),
                detail={"rule": rule.name, "alert": alert.event_id},
            )
        )

    def _track_gaps(self, gaps: Sequence[str]) -> None:
        for sensor in gaps:
            message = f"No usable {sensor} data; threshold alerts for it are suspended"
            self.book.raise_alert("data_gap", sensor, "warning", message)
        for sensor in {rule.sensor for rule in self.rules} - set(gaps):
            self.book.resolve("data_gap", sensor)

    async def tick(self) -> None:
        evaluation = evaluate_alert_rules(
            self.rules, self.control_readings(), self.states, self.clock.monotonic()
        )
        self.states = dict(evaluation.states)
        self._track_gaps(evaluation.data_gaps)
        for name in evaluation.cleared:
            self.book.resolve("threshold", name)
        for rule in evaluation.fired:
            message = (
                f"{rule.sensor} {rule.condition.op} {rule.condition.value} "
                f"for {rule.duration_seconds:g} s ({rule.name})"
            )
            alert = self.book.raise_alert("threshold", rule.name, rule.severity, message)
            if rule.pause_stage:
                await self._pause(rule, alert)
        await self._watch_frozen()
        await self._watch_stage()
        self._queue_open_alerts()

    async def _watch_frozen(self) -> None:
        if self.frozen is None:
            return
        try:
            checked = await self.frozen.tick()
        except Exception:
            log.exception("frozen-reading check failed")
            self.book.raise_alert(
                "frozen_watch", "check", "critical", "The frozen-reading check is failing"
            )
        else:
            if checked:  # only a completed check shows the failure is over
                self.book.resolve("frozen_watch", "check")

    async def _watch_stage(self) -> None:
        if self.stage_checks is None:
            return
        try:
            checked = await self.stage_checks.tick()
        except Exception:
            log.exception("stage checks failed")
            self.book.raise_alert(
                "stage_checks", "check", "critical", "The stage checks are failing"
            )
        else:
            if checked:  # only a completed check shows the failure is over
                self.book.resolve("stage_checks", "check")


def build_observer(
    flow: StagePort,
    control: ControlService,
    archive: Archive,
    book: AlertBook,
    outbox: Outbox,
    clock: Clock,
    notify: Sequence[str],
) -> Observer:
    """The observer with its frozen-reading watch and stage checks."""
    return Observer(
        flow,
        control.readings,
        book,
        outbox,
        DEFAULT_ALERT_RULES,
        clock,
        notify,
        frozen=FrozenWatch(archive, book, flow, control.safety, clock),
        stage_checks=StageChecks(archive, book, flow, clock),
    )
