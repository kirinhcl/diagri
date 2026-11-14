"""FakeControl keeps up with the methods ControlPort gained for the pump watchdog."""

from growbridge.sim.control import FakeControl


async def test_fake_control_answers_the_pump_watchdog_methods():
    control = FakeControl()
    assert control.irrigating() is False
    assert control.pump_reading().mono == 0.0
    assert control.last_cycle_end() is None
    assert control.last_pump_off_id() is None

    assert await control.pump_off(trigger="watchdog") is True

    assert control.last_pump_off_id() == "pumpoff-watchdog"
    assert await control.pump_off() is True
