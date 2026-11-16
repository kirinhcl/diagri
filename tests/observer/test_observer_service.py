import pytest

from growbridge.archive.models import Condition
from growbridge.observer.alerts import AlertBook, AlertRule
from growbridge.observer.outbox import Outbox
from growbridge.observer.service import Observer
from growbridge.ports import Reading, StageEventKind, StageRuntime
from growbridge.sim.fixtures import make_run_sheet
from growbridge.workflow.states import StageState

HOT = AlertRule(
    name="too_hot",
    sensor="temperature",
    condition=Condition(op=">", value=30.0),
    duration_seconds=60.0,
    severity="critical",
    pause_stage=True,
)
WARM = HOT.model_copy(update={"name": "warm", "pause_stage": False})


class FakeStages:
    def __init__(self, active=True):
        self.active = active
        self.events = []

    def active_stage(self):
        if not self.active:
            return None
        return StageRuntime(
            stage_id="st1",
            experiment_id="e1",
            project_id="p1",
            state=StageState.RUNNING,
            run_sheet=make_run_sheet(),
        )

    async def report(self, event):
        self.events.append(event)


class Rig:
    """The observer with a settable list of readings."""

    def __init__(self, db, clock, rules=(HOT,), active=True):
        self.readings: list[Reading] = []
        self.stages = FakeStages(active)
        self.book = AlertBook(db, clock)
        self.outbox = Outbox(db, clock, base_seconds=10, cap_seconds=40)
        self.clock = clock
        self.observer = Observer(
            self.stages,
            lambda: tuple(self.readings),
            self.book,
            self.outbox,
            rules,
            clock,
            notify_channels=("telegram", "email"),
        )

    def hot(self, value=35.0):
        self.readings = [
            Reading(
                sensor="temperature",
                value=value,
                unit="C",
                at=self.clock.now(),
                mono=self.clock.monotonic(),
            )
        ]

    def kinds(self):
        return sorted((a.kind, a.key) for a in self.book.open())


@pytest.fixture
def rig(db, clock):
    return Rig(db, clock)


async def test_observer_stale_data_marks_gap_and_stops_threshold_alerts(rig, clock):
    rig.hot()
    await rig.observer.tick()
    clock.advance(200)  # the reading from t0 is now stale and nothing newer arrived

    await rig.observer.tick()

    assert rig.kinds() == [("data_gap", "temperature")]
    assert rig.stages.events == []

    clock.advance(1000)
    await rig.observer.tick()  # still stale: no threshold alert can appear from old readings
    assert ("threshold", "too_hot") not in rig.kinds()


async def test_a_data_gap_breaks_the_continuity_of_a_threshold_rule(rig, clock):
    rig.hot()
    await rig.observer.tick()  # hot since t0
    clock.advance(200)
    await rig.observer.tick()  # gap: the hot time so far no longer counts
    clock.advance(10)
    rig.hot()
    await rig.observer.tick()  # fresh again, but only 0 s of continuous heat

    assert ("threshold", "too_hot") not in rig.kinds()
    assert ("data_gap", "temperature") not in rig.kinds()  # recovered data resolves the gap

    clock.advance(60)
    rig.hot()
    await rig.observer.tick()

    assert ("threshold", "too_hot") in rig.kinds()


async def test_firing_rule_raises_one_alert_queues_notifications_and_pauses_the_stage(rig, clock):
    rig.hot()
    await rig.observer.tick()
    clock.advance(60)
    rig.hot()
    await rig.observer.tick()
    clock.advance(10)
    rig.hot()
    await rig.observer.tick()

    alert = rig.book.open()[0]
    assert (alert.kind, alert.key, alert.severity) == ("threshold", "too_hot", "critical")
    assert rig.outbox.status(alert.event_id, "telegram") == "pending"
    assert rig.outbox.status(alert.event_id, "email") == "pending"
    assert len(rig.stages.events) == 1
    event = rig.stages.events[0]
    assert event.kind is StageEventKind.ALERT_PAUSE
    assert event.stage_id == "st1"
    assert alert.event_id in event.event_id


async def test_rule_without_pause_stage_only_alerts(db, clock):
    rig = Rig(db, clock, rules=(WARM,))
    rig.hot()
    await rig.observer.tick()
    clock.advance(60)
    rig.hot()
    await rig.observer.tick()

    assert rig.kinds() == [("threshold", "warm")]
    assert rig.stages.events == []


async def test_pause_is_skipped_when_no_stage_governs_the_device(db, clock):
    rig = Rig(db, clock, active=False)
    rig.hot()
    await rig.observer.tick()
    clock.advance(60)
    rig.hot()
    await rig.observer.tick()

    assert rig.kinds() == [("threshold", "too_hot")]
    assert rig.stages.events == []


async def test_recovery_resolves_the_threshold_alert(rig, clock):
    rig.hot()
    await rig.observer.tick()
    clock.advance(60)
    rig.hot()
    await rig.observer.tick()
    clock.advance(10)
    rig.hot(25.0)
    await rig.observer.tick()

    assert rig.book.open() == ()


async def test_repeated_data_gap_ticks_merge_into_one_alert_and_one_notification(rig, clock):
    for _ in range(3):
        await rig.observer.tick()
        clock.advance(5)

    (alert,) = rig.book.open()
    assert (alert.kind, alert.count) == ("data_gap", 3)
    assert rig.outbox.status(alert.event_id, "telegram") == "pending"
    assert rig.outbox.queue_notification(alert.event_id, "telegram", "dup") is False


async def test_alert_raised_without_its_notification_is_queued_once_on_the_next_tick(
    rig, clock, db
):
    # a crash between raise_alert and queue_notification leaves exactly this state
    alert = rig.book.raise_alert("data_gap", "temperature", "warning", "no data")
    assert rig.outbox.status(alert.event_id, "telegram") is None

    await rig.observer.tick()
    await rig.observer.tick()

    assert rig.outbox.status(alert.event_id, "telegram") == "pending"
    assert rig.outbox.status(alert.event_id, "email") == "pending"
    rows = db.query("SELECT * FROM observer_outbox WHERE event_id = ?", (alert.event_id,))
    assert len(rows) == 2


class FakeFrozen:
    """Each tick takes the next outcome: True or False is returned, an exception is raised."""

    def __init__(self, *outcomes):
        self.calls = 0
        self.outcomes = list(outcomes) or [True]

    async def tick(self):
        self.calls += 1
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


async def test_observer_tick_runs_the_frozen_watch(rig):
    await rig.observer.tick()  # no watch: unchanged behaviour
    frozen = FakeFrozen()
    rig.observer.frozen = frozen
    await rig.observer.tick()
    assert frozen.calls == 1


async def test_a_failing_frozen_watch_does_not_stop_the_tick(rig, clock):
    rig.observer.frozen = FakeFrozen(RuntimeError("boom"))
    rig.hot()
    await rig.observer.tick()
    clock.advance(60)
    rig.hot()
    await rig.observer.tick()
    clock.advance(10)
    rig.hot()
    await rig.observer.tick()
    open_alerts = {(a.kind, a.key): a for a in rig.book.open()}
    watch = open_alerts[("frozen_watch", "check")]
    assert watch.severity == "critical"
    assert ("threshold", "too_hot") in open_alerts
    assert rig.outbox.status(watch.event_id, "telegram") == "pending"
    assert len(rig.stages.events) == 1


async def test_the_frozen_check_alert_resolves_only_after_a_completed_check(rig):
    rig.observer.frozen = FakeFrozen(RuntimeError("boom"), False, True)
    await rig.observer.tick()
    assert ("frozen_watch", "check") in {(a.kind, a.key) for a in rig.book.open()}
    await rig.observer.tick()  # gated: no check ran, so the alert stays
    assert ("frozen_watch", "check") in {(a.kind, a.key) for a in rig.book.open()}
    await rig.observer.tick()  # a check completed
    assert ("frozen_watch", "check") not in {(a.kind, a.key) for a in rig.book.open()}


async def test_a_failing_stage_check_raises_one_critical_alert_and_the_rules_still_run(rig, clock):
    rig.observer.stage_checks = FakeFrozen(RuntimeError("boom"))
    rig.hot()
    await rig.observer.tick()
    clock.advance(60)
    rig.hot()
    await rig.observer.tick()
    clock.advance(10)
    rig.hot()
    await rig.observer.tick()
    open_alerts = {(a.kind, a.key): a for a in rig.book.open()}
    check = open_alerts[("stage_checks", "check")]
    assert check.severity == "critical"
    assert check.message == "The stage checks are failing"
    assert ("threshold", "too_hot") in open_alerts
    assert [a.key for a in rig.book.open() if a.kind == "stage_checks"] == ["check"]


async def test_the_stage_check_alert_resolves_after_a_completed_check(rig):
    rig.observer.stage_checks = FakeFrozen(RuntimeError("boom"), False, True)
    await rig.observer.tick()
    assert ("stage_checks", "check") in {(a.kind, a.key) for a in rig.book.open()}
    await rig.observer.tick()  # nothing completed: the alert stays
    assert ("stage_checks", "check") in {(a.kind, a.key) for a in rig.book.open()}
    await rig.observer.tick()
    assert ("stage_checks", "check") not in {(a.kind, a.key) for a in rig.book.open()}


async def test_data_gap_alert_carries_the_sensor(rig, clock):
    rig.hot()
    await rig.observer.tick()
    clock.advance(200)
    await rig.observer.tick()
    alert = {(a.kind, a.key): a for a in rig.book.open()}[("data_gap", "temperature")]
    assert alert.code == "data_gap"
    assert alert.params == {"sensor": "temperature"}


async def test_threshold_alert_carries_sensor_operator_value_and_seconds(rig, clock):
    rig.hot()
    await rig.observer.tick()
    clock.advance(60)
    rig.hot()
    await rig.observer.tick()
    alert = {(a.kind, a.key): a for a in rig.book.open()}[("threshold", "too_hot")]
    assert alert.code == "threshold"
    assert alert.params == {
        "sensor": "temperature",
        "op": ">",
        "value": 30.0,
        "duration_seconds": 60.0,
        "rule": "too_hot",
    }
    assert alert.message == "temperature > 30.0 for 60 s (too_hot)"


async def test_frozen_watch_alert_carries_no_params_and_keeps_the_error_out_of_them(rig):
    rig.observer.frozen = FakeFrozen(RuntimeError("secret detail"))
    await rig.observer.tick()
    alert = {(a.kind, a.key): a for a in rig.book.open()}[("frozen_watch", "check")]
    assert (alert.code, alert.params) == ("frozen_watch", {})
    assert alert.message == "The frozen-reading check is failing"


async def test_stage_checks_alert_carries_no_params(rig):
    rig.observer.stage_checks = FakeFrozen(RuntimeError("secret detail"))
    await rig.observer.tick()
    alert = {(a.kind, a.key): a for a in rig.book.open()}[("stage_checks", "check")]
    assert (alert.code, alert.params) == ("stage_checks", {})
    assert alert.message == "The stage checks are failing"
