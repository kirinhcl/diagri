"""The watchdog's alerts through the real runtime: raised, notified, closed and raised anew."""

from e2e_support import RecordingChannel

from growbridge.archive.models import Channel

KIND = "pump_unexpected"


def pump_alerts(runtime):
    return [a for a in runtime.book.open() if a.kind == KIND]


def panel_on(world):
    world.sim.external_change("outlet", "O4", mOnOff=1)


async def test_panel_pump_on_raises_one_critical_alert_and_one_notification(world):
    channel = RecordingChannel()
    runtime = await world.boot(channels={"rec": channel})
    panel_on(world)
    await world.beat(runtime, 5)

    [alert] = pump_alerts(runtime)
    assert alert.severity == "critical" and alert.key == "pump"
    assert runtime.outbox.status(alert.event_id, "rec") is not None
    assert (await runtime.control.read_state()).levels[Channel.PUMP] == 0


async def test_an_off_status_closes_the_alert_and_a_later_pump_on_is_a_new_event(world):
    runtime = await world.boot(channels={"rec": RecordingChannel()})
    panel_on(world)
    await world.beat(runtime, 5)
    [first] = pump_alerts(runtime)

    await world.beat(runtime, 5)  # the status now reads off (the watchdog switched it off)
    assert pump_alerts(runtime) == []
    assert runtime.book.get(first.event_id).resolved_at is not None

    panel_on(world)
    await world.beat(runtime, 5)
    [second] = pump_alerts(runtime)
    assert second.event_id != first.event_id
    assert runtime.outbox.status(second.event_id, "rec") is not None
