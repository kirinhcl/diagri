import pytest
from conftest import DAY_START

from growbridge.archive.models import (
    Channel,
    Condition,
    FeedbackRule,
    FrozenCheck,
    ProtectionRule,
    RuleAction,
)
from growbridge.archive.store import Archive
from growbridge.observer.alerts import AlertBook
from growbridge.observer.frozen_watch import CHECK_SECONDS, FrozenWatch
from growbridge.observer.outbox import Outbox
from growbridge.observer.service import Observer
from growbridge.ports import StageEventKind, StageRuntime
from growbridge.sim.fixtures import make_run_sheet, make_safety
from growbridge.workflow.states import StageState

MIN = 60.0


def feedback(sensor: str) -> FeedbackRule:
    return FeedbackRule(
        id=f"fb-{sensor}",
        sensor=sensor,
        position="canopy",
        unit="C",
        validity_seconds=30,
        trigger=Condition(op=">", value=30),
        recover=Condition(op="<", value=28),
        duration_seconds=30,
        action=RuleAction(channel=Channel.EXHAUST, level=80),
        release=RuleAction(channel=Channel.EXHAUST, level=30),
    )


def protection_rule(sensor: str) -> ProtectionRule:
    return ProtectionRule(
        id=f"prot-{sensor}",
        sensor=sensor,
        unit="%",
        validity_seconds=20,
        trigger=Condition(op=">", value=90),
        duration_seconds=30,
        action=RuleAction(channel=Channel.LIGHT, level=0),
    )


class FakeStages:
    def __init__(self):
        self.stage_id = "st1"
        self.state = StageState.RUNNING
        self.sensors: tuple[str, ...] = ()
        self.events = []

    def active_stage(self):
        rules = tuple(feedback(s) for s in self.sensors)
        return StageRuntime(
            stage_id=self.stage_id,
            experiment_id="e1",
            project_id="p1",
            state=self.state,
            run_sheet=make_run_sheet(feedback_rules=rules),
        )

    async def report(self, event):
        self.events.append(event)


class CountingArchive(Archive):
    reads = 0

    def sensor_points(self, since):
        self.reads += 1
        return super().sensor_points(since)


class Rig:
    def __init__(self, db, clock, tmp_path, make_sample):
        self.archive = CountingArchive(db, tmp_path / "archive", clock)
        self.db, self.clock, self.make_sample = db, clock, make_sample
        self.book = AlertBook(db, clock)
        self.stages = FakeStages()
        self.config = make_safety(rules=())
        self.watch = self.new_watch()
        clock.wall = DAY_START
        self.end = 0.0

    def new_watch(self):
        return FrozenWatch(self.archive, self.book, self.stages, lambda: self.config, self.clock)

    def feed(self, minutes, **sensors):
        """One sample a minute; a callable value is called with the sample index."""
        for i in range(int(minutes)):
            data = {k: (v(i) if callable(v) else v) for k, v in sensors.items()}
            self.archive.append_sample(self.make_sample(self.end, {"sensor": data}))
            self.end += MIN
        self.clock.wall = DAY_START + self.end
        self.clock.mono += minutes * MIN

    async def check(self):
        self.clock.mono += CHECK_SECONDS
        await self.watch.tick()

    def open_for(self, sensor):
        return [p for p in self.archive.open_frozen_periods() if p.sensor == sensor]

    def alerts(self, key="temp"):
        return [a for a in self.book.open() if (a.kind, a.key) == ("frozen_reading", key)]


@pytest.fixture
def rig(db, clock, tmp_path, make_sample):
    return Rig(db, clock, tmp_path, make_sample)


def moving(i):
    return 40.0 + (i % 7)


async def test_temp_flat_for_two_hours_opens_a_period_and_warns(rig):
    rig.feed(121, temp=24.0, humi=moving, co2=moving)
    await rig.check()
    assert [p.value for p in rig.open_for("temp")] == [24.0]
    assert [a.severity for a in rig.alerts()] == ["warning"]
    assert rig.open_for("humi") == [] and rig.open_for("co2") == []


async def test_a_change_closes_the_period_and_the_alert(rig):
    rig.feed(121, temp=24.0)
    await rig.check()
    rig.feed(3, temp=24.5)
    await rig.check()
    assert rig.open_for("temp") == []
    assert rig.alerts() == []
    closed = rig.archive.frozen_periods(DAY_START - 1, DAY_START + 10 * 3600)
    assert len(closed) == 1
    assert closed[0]["close_reason"] == "value_changed"


async def test_ppfd_vpd_and_unlisted_sensors_are_not_checked(rig):
    rig.feed(300, ppfd=100.0, vpd=1.2, other=5.0)
    await rig.check()
    assert rig.archive.open_frozen_periods() == ()


async def test_a_gap_before_opening_restarts_the_count(rig):
    rig.feed(70, temp=24.0)
    rig.end += 601
    rig.feed(70, temp=24.0)
    await rig.check()
    assert rig.open_for("temp") == []


async def test_a_gap_after_opening_keeps_the_same_period(rig):
    rig.feed(121, temp=24.0)
    await rig.check()
    (period,) = rig.open_for("temp")
    rig.end += 900
    rig.feed(5, temp=24.0)
    await rig.check()
    assert [p.period_id for p in rig.open_for("temp")] == [period.period_id]
    assert [a.count for a in rig.alerts()] == [1]


async def test_a_new_watch_finds_open_periods_after_a_restart(rig):
    rig.feed(121, temp=24.0)
    await rig.check()
    (period,) = rig.open_for("temp")
    rig.watch = rig.new_watch()
    await rig.check()
    assert [p.period_id for p in rig.open_for("temp")] == [period.period_id]
    rig.feed(2, temp=25.0)
    await rig.check()
    assert rig.open_for("temp") == []


async def test_checks_at_most_every_five_minutes(rig):
    rig.feed(10, temp=moving)
    assert await rig.watch.tick() is True
    assert rig.archive.reads == 1
    rig.clock.mono += CHECK_SECONDS - 1
    assert await rig.watch.tick() is False
    assert rig.archive.reads == 1
    rig.clock.mono += 1
    assert await rig.watch.tick() is True
    assert rig.archive.reads == 2


async def frozen_running(rig, *sensors):
    rig.stages.sensors = sensors
    rig.feed(121, temp=24.0)
    await rig.check()
    (period,) = rig.open_for("temp")
    return period


async def test_pauses_once_when_a_feedback_rule_uses_the_sensor(rig):
    period = await frozen_running(rig, "temp")
    (event,) = rig.stages.events
    assert event.kind is StageEventKind.ALERT_PAUSE
    assert event.event_id == f"frozen_pause:{period.period_id}:st1"
    assert event.detail["rule"] == "frozen:temp"
    assert event.detail["alert"] == rig.alerts()[0].event_id
    assert [a.severity for a in rig.alerts()] == ["warning"]
    await rig.check()
    assert len(rig.stages.events) == 1


async def test_two_periods_opened_together_send_one_pause_per_check(rig):
    rig.stages.sensors = ("temp", "humi")
    report = rig.stages.report

    async def pausing_report(event):
        await report(event)
        rig.stages.state = StageState.PAUSED  # what the workflow does with an alert pause

    rig.stages.report = pausing_report
    rig.feed(121, temp=24.0, humi=55.0)
    await rig.check()
    assert len(rig.stages.events) == 1
    first = rig.stages.events[0].detail["rule"]

    await rig.check()  # still paused: nothing more is sent, no id is spent
    assert len(rig.stages.events) == 1

    rig.stages.state = StageState.RUNNING  # the operator resumed
    await rig.check()
    assert len(rig.stages.events) == 2
    assert {e.detail["rule"] for e in rig.stages.events} == {"frozen:temp", "frozen:humi"}
    assert rig.stages.events[1].detail["rule"] != first


async def test_an_ignored_pause_event_lets_the_same_check_report_the_next_period(rig):
    rig.stages.sensors = ("temp", "humi")  # the fake keeps the stage RUNNING: the event was a no-op
    rig.feed(121, temp=24.0, humi=55.0)
    await rig.check()
    assert {e.detail["rule"] for e in rig.stages.events} == {"frozen:temp", "frozen:humi"}


async def test_the_period_a_protection_rule_uses_is_reported_first(rig):
    rig.config = make_safety(rules=(protection_rule("humi"),))
    rig.stages.sensors = ("temp",)  # temp is feedback-only; humi is used by protection
    rig.feed(121, temp=24.0, humi=55.0)
    await rig.check()
    assert [e.detail["rule"] for e in rig.stages.events] == ["frozen:humi", "frozen:temp"]


async def test_a_new_stage_is_paused_for_a_period_already_open(rig):
    period = await frozen_running(rig, "temp")
    rig.stages.stage_id = "st2"
    await rig.check()
    assert rig.stages.events[-1].event_id == f"frozen_pause:{period.period_id}:st2"


async def test_a_stage_that_is_not_running_is_not_paused(rig):
    rig.stages.state = StageState.PAUSED
    await frozen_running(rig, "temp")
    assert rig.stages.events == []


async def test_no_rule_no_pause(rig):
    await frozen_running(rig, "humi")
    assert rig.stages.events == []
    assert len(rig.alerts()) == 1


async def test_a_vpd_rule_counts_as_using_temp(rig):
    await frozen_running(rig, "vpd")
    assert len(rig.stages.events) == 1


async def test_critical_when_a_protection_rule_uses_the_sensor(rig):
    rig.config = make_safety()
    await frozen_running(rig)
    assert [a.severity for a in rig.alerts()] == ["critical"]
    assert len(rig.stages.events) == 1


async def test_defaults_apply_without_a_safety_config(rig):
    rig.config = None
    await frozen_running(rig)
    assert len(rig.open_for("temp")) == 1


async def test_removing_a_sensor_from_the_thresholds_closes_its_period(rig):
    await frozen_running(rig)
    rig.config = make_safety(rules=(), frozen=FrozenCheck(minutes={"humi": 60.0}))
    await rig.check()
    assert rig.open_for("temp") == []
    assert rig.alerts() == []
    (closed,) = rig.archive.frozen_periods(DAY_START - 1, DAY_START + 10 * 3600)
    assert closed["close_reason"] == "no_longer_listed"


async def test_an_empty_threshold_list_checks_nothing_and_closes_everything(rig):
    await frozen_running(rig)
    rig.config = make_safety(rules=(), frozen=FrozenCheck(minutes={}))
    reads = rig.archive.reads
    await rig.check()
    assert rig.archive.reads == reads
    assert rig.archive.open_frozen_periods() == ()
    assert rig.alerts() == []
    (closed,) = rig.archive.frozen_periods(DAY_START - 1, DAY_START + 10 * 3600)
    assert closed["close_reason"] == "nothing_checked"


async def test_closing_uses_the_last_same_value_point(rig):
    await frozen_running(rig)
    rig.feed(1, temp=24.0)
    last_same = DAY_START + (rig.end - MIN)
    rig.feed(1, temp=30.0)
    await rig.check()
    (closed,) = rig.archive.frozen_periods(DAY_START - 1, DAY_START + 10 * 3600)
    assert closed["last_at"] == last_same


async def test_samples_without_sensor_blocks_do_not_break_the_check(rig):
    for i in range(130):
        rig.archive.append_sample(rig.make_sample(i * MIN, {}))
    rig.end = 130 * MIN
    rig.clock.wall = DAY_START + rig.end
    await rig.check()
    assert rig.archive.open_frozen_periods() == ()


async def test_raw_samples_are_unchanged(rig):
    rig.feed(121, temp=24.0)
    before = rig.db.query("SELECT id, body FROM samples ORDER BY id")
    await rig.check()
    rig.feed(2, temp=25.0)
    await rig.check()
    after = rig.db.query("SELECT id, body FROM samples ORDER BY id")
    kept = {r["id"]: r["body"] for r in after}
    assert all(kept[r["id"]] == r["body"] for r in before)
    assert len(after) == len(before) + 2


async def test_critical_when_a_vpd_protection_rule_depends_on_the_frozen_temp(rig):
    base = make_safety()
    rule = base.rules[0].model_copy(update={"sensor": "vpd"})
    rig.config = base.model_copy(update={"rules": (rule,)})
    await frozen_running(rig)
    assert [a.severity for a in rig.alerts()] == ["critical"]


async def test_an_earlier_different_value_does_not_close_the_period(rig):
    rig.feed(30, temp=moving)
    rig.feed(121, temp=24.0)
    await rig.check()
    (period,) = rig.open_for("temp")
    rig.feed(1, temp=24.0)
    await rig.check()
    assert [p.period_id for p in rig.open_for("temp")] == [period.period_id]
    assert [a.count for a in rig.alerts()] == [1]


async def test_a_window_without_new_samples_keeps_the_period_open(rig):
    await frozen_running(rig)
    (period,) = rig.open_for("temp")
    rig.clock.wall += 6 * 3600  # past the scan window, with no new samples
    await rig.check()
    assert [p.period_id for p in rig.open_for("temp")] == [period.period_id]
    assert [a.count for a in rig.alerts()] == [1]


async def test_no_config_closes_nothing(rig):
    rig.config = make_safety(rules=(), frozen=FrozenCheck(minutes={"ppfd": 30.0}))
    rig.feed(40, ppfd=10.0)
    await rig.check()
    assert len(rig.open_for("ppfd")) == 1
    rig.config = None  # the default list has no ppfd, but a missing config closes nothing
    await rig.check()
    assert len(rig.open_for("ppfd")) == 1
    assert len(rig.alerts("ppfd")) == 1


async def test_a_new_protection_rule_raises_the_open_alert_to_critical(rig):
    await frozen_running(rig)
    assert [a.severity for a in rig.alerts()] == ["warning"]
    rig.config = make_safety()  # protection rule on temp approved
    await rig.check()
    assert [a.severity for a in rig.alerts()] == ["critical"]
    count = rig.alerts()[0].count
    await rig.check()
    assert rig.alerts()[0].count == count  # unchanged severity: no re-raise


async def test_the_pause_is_reported_even_when_the_update_fails(rig):
    rig.stages.sensors = ("temp",)
    rig.feed(121, temp=24.0)
    rig.stages.state = StageState.PAUSED  # open the period without pausing
    await rig.check()
    rig.stages.state = StageState.RUNNING
    assert rig.stages.events == []

    def fail(since):
        raise RuntimeError("database is locked")

    rig.archive.sensor_points = fail
    with pytest.raises(RuntimeError):
        await rig.check()
    assert len(rig.stages.events) == 1


def unreadable_safety():
    raise RuntimeError("ledger is unreadable")


async def open_while_paused(rig, **sensors):
    """Open periods during a check that cannot pause: the stage is paused at that moment."""
    rig.stages.state = StageState.PAUSED
    rig.feed(121, **sensors)
    await rig.check()
    rig.stages.state = StageState.RUNNING
    assert rig.stages.events == []


async def test_the_pause_is_reported_even_when_reading_the_safety_config_fails(rig):
    rig.stages.sensors = ("temp",)
    await open_while_paused(rig, temp=24.0)
    rig.watch.safety = unreadable_safety

    with pytest.raises(RuntimeError):
        await rig.check()

    assert [e.detail["rule"] for e in rig.stages.events] == ["frozen:temp"]


async def test_a_failed_config_read_still_pauses_for_the_last_known_protection_sensors(rig):
    rig.config = make_safety(rules=(protection_rule("humi"),))
    await open_while_paused(rig, temp=moving, humi=55.0)  # no feedback rule: protection only
    rig.watch.safety = unreadable_safety

    with pytest.raises(RuntimeError):
        await rig.check()

    assert [e.detail["rule"] for e in rig.stages.events] == ["frozen:humi"]


def locked(kind, key):
    raise RuntimeError("alert store is locked")


async def closed_with_its_alert_left_behind(rig, **others):
    rig.feed(121, temp=24.0, **others)
    await rig.check()
    rig.feed(3, temp=24.5, **others)
    working = rig.book.resolve
    rig.book.resolve = locked
    with pytest.raises(RuntimeError):
        await rig.check()
    assert rig.open_for("temp") == [] and len(rig.alerts()) == 1
    return working


async def test_an_alert_left_by_a_failed_resolve_is_resolved_by_the_next_check(rig, caplog):
    rig.book.resolve = await closed_with_its_alert_left_behind(rig)

    await rig.check()

    assert rig.alerts() == []
    assert "no open period" in caplog.text  # the automatic resolution is on record


async def test_a_failing_alert_cleanup_never_stops_a_new_period_from_opening(rig):
    await closed_with_its_alert_left_behind(rig, humi=moving)
    rig.feed(61, temp=moving, humi=55.0)  # humi now flat for an hour

    with pytest.raises(RuntimeError):  # resolving the old temp alert still fails
        await rig.check()

    assert [p.value for p in rig.open_for("humi")] == [55.0]
    assert len(rig.alerts("humi")) == 1


async def handing_over(rig, before, after):
    """Each pause report is followed by another stage, using ``after``, taking over."""
    rig.stages.sensors = before
    report = rig.stages.report

    async def report_then_hand_over(event):
        await report(event)
        rig.stages.stage_id, rig.stages.sensors = "st2", after

    rig.stages.report = report_then_hand_over
    rig.feed(121, temp=24.0, humi=55.0)
    await rig.check()
    return [(e.stage_id, e.detail["rule"]) for e in rig.stages.events]


async def test_a_stage_taking_over_mid_check_is_paused_for_its_own_sensors(rig):
    events = await handing_over(rig, before=("temp",), after=("humi",))
    assert events == [("st1", "frozen:temp"), ("st2", "frozen:humi")]


async def test_a_stage_taking_over_mid_check_is_not_paused_for_the_old_stage_sensors(rig):
    events = await handing_over(rig, before=("temp", "humi"), after=())
    assert events == [("st1", "frozen:temp")]


async def test_a_real_watch_resolves_the_failure_alert_only_after_a_completed_check(rig):
    observer = Observer(
        rig.stages, lambda: (), rig.book, Outbox(rig.db, rig.clock, 10, 40), (), rig.clock
    )
    observer.frozen = rig.watch
    working = rig.archive.sensor_points
    calls = []

    def fail_once(since):
        calls.append(since)
        if len(calls) == 1:
            raise RuntimeError("database is locked")
        return working(since)

    rig.archive.sensor_points = fail_once

    def failure_open():
        return any((a.kind, a.key) == ("frozen_watch", "check") for a in rig.book.open())

    await observer.tick()
    assert failure_open()
    rig.clock.mono += CHECK_SECONDS - 1
    await observer.tick()  # gated: no check ran
    assert failure_open() and len(calls) == 1
    rig.clock.mono += 1
    await observer.tick()  # a check completed
    assert not failure_open() and len(calls) == 2
