"""The pump watchdog's decisions against a fake control service."""

from growbridge.executor.watchdog import PumpWatchdog
from growbridge.ports import Denied, PumpReading
from growbridge.sim.clock import FakeClock


class FakeControl:
    def __init__(self):
        self.connected_now = True
        self.interlocked_now = False
        self.irrigating_now = False
        self.reading = PumpReading(on=None, at=0.0, mono=0.0)
        self.cycle_end: float | None = None
        self.result: bool | Exception = True
        self.off_calls: list[str] = []
        self.off_id: str | None = None
        self.interlock_after = False

    def connected(self):
        return self.connected_now

    def interlocked(self):
        return self.interlocked_now

    def irrigating(self):
        return self.irrigating_now

    def pump_reading(self):
        return self.reading

    def last_cycle_end(self):
        return self.cycle_end

    async def pump_off(self, trigger="interlock"):
        self.off_calls.append(trigger)
        if isinstance(self.result, Exception):
            raise self.result
        self.off_id = "pumpoff-1"
        self.interlocked_now = self.interlock_after
        return self.result

    def last_pump_off_id(self):
        return self.off_id


class FakeStages:
    def __init__(self):
        self.interventions: list[tuple[str, str, dict]] = []

    def record_intervention(self, stage_id, kind, detail):
        self.interventions.append((stage_id, kind, detail))


class FakeStage:
    stage_id = "stage-1"


def make():
    control, stages, clock = FakeControl(), FakeStages(), FakeClock(now=1000.0)
    clock.mono = 10.0  # the same monotonic scale as the statuses below
    dog = PumpWatchdog(control, stages, clock)
    alerts: list[tuple[str, str, str]] = []
    resolved: list[tuple[str, str]] = []
    texts: list[str] = []
    coded: list[tuple[str, str, str | None, dict | None]] = []

    def alert(kind, key, message, severity, *, code=None, params=None):
        alerts.append((kind, key, severity))
        texts.append(message)
        coded.append((kind, key, code, params))
        return True  # written

    def resolve(kind, key):
        resolved.append((kind, key))
        return True

    dog.alert = alert
    dog.resolve = resolve
    dog.coded = coded  # type: ignore[attr-defined]
    return control, stages, clock, dog, alerts, resolved, texts


def failing_first(hook, kind):
    """``hook``, except that its first call for ``kind`` reports a failed write."""
    failed: list[str] = []

    def wrapped(*args, **kwargs):
        if args[0] == kind and not failed:
            failed.append(kind)
            return False  # what the runtime's hook reports after swallowing a write error
        return hook(*args, **kwargs)

    return wrapped


def on(mono, at=100.0):
    return PumpReading(on=True, at=at, mono=mono)


async def test_switches_off_a_pump_found_on():
    control, stages, _, dog, alerts, _, _ = make()
    control.reading = on(10.0)
    await dog.step(FakeStage())
    assert control.off_calls == ["watchdog"]
    assert alerts == [("pump_unexpected", "pump", "critical")]
    [(stage_id, kind, detail)] = stages.interventions
    assert (stage_id, kind) == ("stage-1", "unexpected_watering")
    assert detail["status_at"] == 100.0
    assert detail["request_id"] == "pumpoff-1"
    assert detail["off_confirmed"] is True


async def test_quiet_while_irrigating():
    control, _, _, dog, alerts, _, _ = make()
    control.reading = on(10.0)
    control.irrigating_now = True
    await dog.step(FakeStage())
    assert control.off_calls == [] and alerts == []


async def test_quiet_on_a_status_from_before_the_cycle_ended():
    control, _, _, dog, alerts, _, _ = make()
    control.reading = on(10.0)
    control.cycle_end = 10.0
    await dog.step(FakeStage())
    assert control.off_calls == [] and alerts == []


async def test_quiet_before_the_first_status():
    control, _, _, dog, alerts, _, _ = make()
    control.reading = PumpReading(on=True, at=0.0, mono=0.0)
    await dog.step(FakeStage())
    assert control.off_calls == [] and alerts == []


async def test_quiet_when_disconnected():
    control, _, _, dog, alerts, _, _ = make()
    control.reading = on(10.0)
    control.connected_now = False
    await dog.step(FakeStage())
    assert control.off_calls == [] and alerts == []


async def test_quiet_when_interlocked():
    control, _, _, dog, alerts, _, _ = make()
    control.reading = on(10.0)
    control.interlocked_now = True
    await dog.step(FakeStage())
    assert control.off_calls == [] and alerts == []


async def test_waits_for_a_status_after_its_own_switch_off():
    control, _, _, dog, _, _, _ = make()
    control.reading = on(10.0)
    await dog.step(FakeStage())
    await dog.step(FakeStage())
    assert control.off_calls == ["watchdog"]
    control.reading = on(20.0)
    await dog.step(FakeStage())
    assert control.off_calls == ["watchdog", "watchdog"]


async def test_off_status_closes_the_alert():
    control, _, _, dog, _, resolved, _ = make()
    control.reading = on(10.0)
    await dog.step(FakeStage())
    control.reading = PumpReading(on=False, at=110.0, mono=20.0)
    await dog.step(FakeStage())
    assert ("pump_unexpected", "pump") in resolved


async def test_unreadable_outlet_warns_and_does_not_switch():
    control, _, _, dog, alerts, resolved, _ = make()
    control.reading = PumpReading(on=None, at=50.0, mono=5.0)
    await dog.step(FakeStage())
    assert alerts == [("pump_unreadable", "pump", "warning")]
    assert control.off_calls == []
    control.reading = PumpReading(on=False, at=60.0, mono=6.0)
    await dog.step(FakeStage())
    assert ("pump_unreadable", "pump") in resolved


async def test_no_intervention_without_a_stage():
    control, stages, _, dog, alerts, _, _ = make()
    control.reading = on(10.0)
    await dog.step(None)
    assert control.off_calls == ["watchdog"]
    assert alerts == [("pump_unexpected", "pump", "critical")]
    assert stages.interventions == []


async def test_unconfirmed_switch_off_is_reported():
    control, stages, _, dog, alerts, _, texts = make()
    control.reading = on(10.0)
    control.result = False
    control.interlock_after = True
    await dog.step(FakeStage())
    assert alerts == [("pump_unexpected", "pump", "critical")]
    assert "unconfirmed" in texts[0] and "interlock is set" in texts[0]
    detail = stages.interventions[0][2]
    assert detail["off_confirmed"] is False and detail["off_confirmed_at"] is None


async def test_a_denied_switch_off_counts_as_unconfirmed():
    control, stages, _, dog, _, _, texts = make()
    control.reading = on(10.0)
    control.result = Denied("interlock", "no")
    control.off_id = "pumpoff-old"  # an unrelated earlier pump-off
    await dog.step(FakeStage())
    assert "unconfirmed" in texts[0] and "no interlock is set" in texts[0]
    detail = stages.interventions[0][2]
    assert detail["off_confirmed"] is False
    assert detail["request_id"] is None


async def test_runs_without_alert_hooks():
    control, _, _, dog, _, _, _ = make()
    dog.alert = None
    dog.resolve = None
    control.reading = on(10.0)
    await dog.step(None)
    assert control.off_calls == ["watchdog"]


async def test_a_failing_intervention_write_never_undoes_the_switch_off():
    control, stages, _, dog, alerts, _, _ = make()

    def broken(*_):
        raise RuntimeError("disk full")

    stages.record_intervention = broken
    control.reading = on(10.0)
    await dog.step(FakeStage())
    assert control.off_calls == ["watchdog"]
    assert ("pump_watchdog", "intervention", "critical") in alerts
    assert ("pump_unexpected", "pump", "critical") in alerts


async def test_many_unreadable_ticks_raise_one_alert_and_the_good_status_resolves_it():
    control, _, _, dog, alerts, resolved, _ = make()
    for mono in (5.0, 6.0, 7.0, 8.0):
        control.reading = PumpReading(on=None, at=50.0, mono=mono)
        await dog.step(FakeStage())
    assert alerts == [("pump_unreadable", "pump", "warning")]
    control.reading = PumpReading(on=False, at=60.0, mono=9.0)
    await dog.step(FakeStage())
    await dog.step(FakeStage())
    assert resolved.count(("pump_unreadable", "pump")) == 1


async def test_a_failing_step_alerts_once_and_a_good_step_resolves_it():
    control, _, _, dog, alerts, resolved, _ = make()
    dog.step_failed(RuntimeError("boom"))
    dog.step_failed(RuntimeError("boom"))
    assert alerts == [("pump_watchdog", "step", "critical")]
    control.reading = PumpReading(on=False, at=60.0, mono=9.0)
    await dog.step(FakeStage())
    assert ("pump_watchdog", "step") in resolved


async def test_the_intervention_alert_is_raised_once_and_resolved_by_a_later_success():
    control, stages, _, dog, alerts, resolved, _ = make()
    good = stages.record_intervention

    def broken(*_):
        raise RuntimeError("disk full")

    stages.record_intervention = broken
    control.reading = on(10.0)
    await dog.step(FakeStage())
    control.reading = on(30.0)
    await dog.step(FakeStage())
    assert alerts.count(("pump_watchdog", "intervention", "critical")) == 1
    stages.record_intervention = good
    control.reading = on(50.0)
    await dog.step(FakeStage())
    assert ("pump_watchdog", "intervention") in resolved


async def test_a_persisting_unreadable_outlet_is_raised_again_only_every_300_seconds():
    control, _, clock, dog, alerts, _, _ = make()
    control.reading = PumpReading(on=None, at=50.0, mono=5.0)
    await dog.step(FakeStage())
    clock.mono += 299.0
    await dog.step(FakeStage())
    assert len(alerts) == 1
    clock.mono += 1.0
    await dog.step(FakeStage())
    assert len(alerts) == 2
    await dog.step(FakeStage())
    assert len(alerts) == 2


async def test_a_step_failure_is_resolved_only_by_a_step_that_read_the_pump():
    control, _, _, dog, _, resolved, _ = make()
    dog.step_failed(RuntimeError("boom"))
    control.connected_now = False
    await dog.step(FakeStage())
    control.connected_now, control.interlocked_now = True, True
    await dog.step(FakeStage())
    control.interlocked_now = False
    await dog.step(FakeStage())  # no status received yet
    assert ("pump_watchdog", "step") not in resolved
    control.reading = PumpReading(on=False, at=60.0, mono=9.0)
    await dog.step(FakeStage())
    assert ("pump_watchdog", "step") in resolved


async def test_a_message_that_changes_every_tick_is_not_stored_again_while_its_code_is_the_same():
    _, _, clock, dog, alerts, _, _ = make()
    dog.step_failed(RuntimeError("one"))
    clock.mono += 59.0
    dog.step_failed(RuntimeError("two"))
    clock.mono += 1.0
    dog.step_failed(RuntimeError("three"))
    assert len(alerts) == 1
    clock.mono += 240.0
    dog.step_failed(RuntimeError("four"))
    assert len(alerts) == 2


async def test_a_long_failure_message_is_truncated():
    _, _, _, dog, _, _, texts = make()
    dog.step_failed(RuntimeError("x" * 1000))
    assert len(texts[0]) == 200 and texts[0].startswith("The pump watchdog failed: RuntimeError")


async def test_a_latched_alert_whose_write_failed_is_tried_again_on_the_next_step():
    control, _, _, dog, alerts, _, _ = make()
    dog.alert = failing_first(dog.alert, "pump_unreadable")
    control.reading = PumpReading(on=None, at=50.0, mono=5.0)
    await dog.step(FakeStage())
    assert alerts == []

    await dog.step(FakeStage())  # the clock has not moved: far less than 300 s later

    assert alerts == [("pump_unreadable", "pump", "warning")]
    await dog.step(FakeStage())
    assert len(alerts) == 1  # latched once written


async def test_a_step_failure_alert_whose_write_failed_is_tried_again_at_once():
    _, _, _, dog, alerts, _, _ = make()
    dog.alert = failing_first(dog.alert, "pump_watchdog")
    dog.step_failed(RuntimeError("boom"))
    dog.step_failed(RuntimeError("boom"))
    dog.step_failed(RuntimeError("boom"))
    assert alerts == [("pump_watchdog", "step", "critical")]


async def test_a_resolve_that_failed_is_tried_again_on_the_next_good_step():
    control, _, _, dog, _, resolved, _ = make()
    control.reading = PumpReading(on=None, at=50.0, mono=5.0)
    await dog.step(FakeStage())
    dog.resolve = failing_first(dog.resolve, "pump_unreadable")
    control.reading = PumpReading(on=False, at=60.0, mono=9.0)
    await dog.step(FakeStage())
    assert ("pump_unreadable", "pump") not in resolved

    await dog.step(FakeStage())

    assert resolved.count(("pump_unreadable", "pump")) == 1
    await dog.step(FakeStage())
    assert resolved.count(("pump_unreadable", "pump")) == 1


async def test_pump_unexpected_off_alert_carries_its_code():
    control, _, _, dog, _, _, _ = make()
    control.reading = on(10.0)
    await dog.step(FakeStage())
    assert dog.coded == [("pump_unexpected", "pump", "pump_unexpected_off", {})]


async def test_pump_unexpected_interlocked_alert_carries_its_code():
    control, _, _, dog, _, _, _ = make()
    control.reading = on(10.0)
    control.result = False
    control.interlock_after = True
    await dog.step(FakeStage())
    assert dog.coded == [("pump_unexpected", "pump", "pump_unexpected_interlocked", {})]


async def test_pump_unexpected_failed_alert_carries_its_code():
    control, _, _, dog, _, _, _ = make()
    control.reading = on(10.0)
    control.result = False
    await dog.step(FakeStage())
    assert dog.coded == [("pump_unexpected", "pump", "pump_unexpected_failed", {})]


async def test_pump_unreadable_alert_carries_its_code():
    control, _, _, dog, _, _, _ = make()
    control.reading = PumpReading(on=None, at=100.0, mono=10.0)
    await dog.step(FakeStage())
    assert dog.coded == [("pump_unreadable", "pump", "pump_unreadable", {})]


async def test_pump_watchdog_step_alert_carries_its_code_and_no_error_text():
    _, _, _, dog, _, _, _ = make()
    dog.step_failed(RuntimeError("secret detail"))
    assert dog.coded == [("pump_watchdog", "step", "pump_watchdog_step", {})]


async def test_pump_watchdog_record_alert_carries_its_code():
    control, stages, _, dog, _, _, _ = make()

    def broken(*_):
        raise RuntimeError("disk full")

    stages.record_intervention = broken
    control.reading = on(10.0)
    await dog.step(FakeStage())
    assert ("pump_watchdog", "intervention", "pump_watchdog_record", {}) in dog.coded


async def test_the_watchdog_restores_an_alert_only_when_its_code_or_params_change():
    _, _, clock, dog, alerts, _, _ = make()
    enter = dog._enter
    enter("pump_unexpected", "pump", "text one", "critical", "pump_unexpected_off")
    clock.mono += 59.0
    enter("pump_unexpected", "pump", "text two", "critical", "pump_unexpected_off")
    assert len(alerts) == 1  # the same shape inside a minute; the message is not compared
    clock.mono += 1.0
    enter("pump_unexpected", "pump", "text one", "critical", "pump_unexpected_interlocked")
    assert len(alerts) == 2  # a new code is stored at once
    enter(
        "pump_unexpected", "pump", "text one", "critical", "pump_unexpected_interlocked", {"n": 2}
    )
    assert len(alerts) == 3  # so are new params
    assert [c[2] for c in dog.coded] == [
        "pump_unexpected_off",
        "pump_unexpected_interlocked",
        "pump_unexpected_interlocked",
    ]
