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


async def test_writing_fake_control_writes_snapshots_and_restores():
    from growbridge.archive.models import ActionState, Channel, RightKind
    from growbridge.ports import ActionRequest, RightScope
    from growbridge.sim.control import WritingFakeControl

    control = WritingFakeControl()
    control.levels[Channel.LIGHT] = 20
    scope = RightScope(device_id="SIMULATED", channels=(Channel.LIGHT,))
    number = control.grant(RightKind.TEST, scope, operator="alice")
    snapshot = await control.snapshot(Channel.LIGHT)

    def request(level, rid):
        return ActionRequest(
            request_id=rid, right_number=number, channel=Channel.LIGHT, level=level, trigger="t"
        )

    on = await control.submit(request(100, "on"))
    assert on.state is ActionState.CONFIRMED and control.levels[Channel.LIGHT] == 100
    back = await control.restore(request(20, "back"), snapshot)
    assert back.state is ActionState.CONFIRMED and control.levels[Channel.LIGHT] == 20
    control.fail_restore = True
    assert (await control.restore(request(20, "again"), snapshot)).state is ActionState.FAILED
