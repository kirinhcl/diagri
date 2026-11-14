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
        return self.result

    def last_pump_off_id(self):
        return "pumpoff-1"


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

    def alert(kind, key, message, severity):
        alerts.append((kind, key, severity))
        texts.append(message)

    dog.alert = alert
    dog.resolve = lambda kind, key: resolved.append((kind, key))
    return control, stages, clock, dog, alerts, resolved, texts


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
    await dog.step(FakeStage())
    assert alerts == [("pump_unexpected", "pump", "critical")]
    assert "unconfirmed" in texts[0]
    detail = stages.interventions[0][2]
    assert detail["off_confirmed"] is False and detail["off_confirmed_at"] is None


async def test_a_denied_switch_off_counts_as_unconfirmed():
    control, stages, _, dog, _, _, texts = make()
    control.reading = on(10.0)
    control.result = Denied("interlock", "no")
    await dog.step(FakeStage())
    assert "unconfirmed" in texts[0]
    assert stages.interventions[0][2]["off_confirmed"] is False


async def test_runs_without_alert_hooks():
    control, _, _, dog, _, _, _ = make()
    dog.alert = None
    dog.resolve = None
    control.reading = on(10.0)
    await dog.step(None)
    assert control.off_calls == ["watchdog"]
