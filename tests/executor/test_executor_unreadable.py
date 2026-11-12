"""An unreadable device state is never read as "matches" (fail closed)."""

from growbridge.ports import StageEventKind

KIND = StageEventKind
STEP = 30  # seconds between ticks; the run sheet allows 120 s without data


def unreadable(rig, on=True):
    """The state query fails while the link and the sensor telemetry stay fine."""
    device = rig.control.device

    async def failing(at):
        raise ConnectionError("state query failed")

    if on:
        device.read_state = failing
    else:
        del device.read_state  # back to the real method on the class


async def test_executor_unreadable_state_for_longer_than_the_gap_limit_pauses_the_stage(rig):
    await rig.start()
    await rig.tick()
    unreadable(rig)

    for step in range(8):
        await rig.pass_time(STEP)
        report = await rig.tick()
        if KIND.READINGS_STALE in report.reported:
            assert step * STEP > 120  # not before the run sheet's gap limit
            assert report.writes == ()
            break
        assert rig.state() == "running"
    else:
        raise AssertionError("an unreadable state was never reported")

    assert rig.state() == "paused"


async def test_executor_transient_unreadable_state_does_not_pause_the_stage(rig):
    await rig.start()
    await rig.tick()

    for _ in range(2):  # two separate failures of 90 s each: more than 120 s in total
        unreadable(rig)
        for _ in range(3):
            await rig.pass_time(STEP)
            assert (await rig.tick()).reported == ()
        unreadable(rig, on=False)
        await rig.pass_time(STEP)
        assert (await rig.tick()).reported == ()

    assert rig.state() == "running"


async def test_executor_unreadable_state_after_an_outage_counts_as_a_difference(rig):
    await rig.start()
    await rig.tick()
    rig.sim.connected = False
    await rig.tick()
    rig.clock.advance(30)  # short outage, nothing due: only the state check can matter
    rig.sim.connected = True
    await rig.refresh()
    unreadable(rig)

    report = await rig.tick()

    assert KIND.DISCONNECT_AFFECTS in report.reported
    assert rig.state() == "paused"


async def overheat(rig):
    rig.sim.set_sensor("temp", 40)
    await rig.pass_time(1)
    await rig.tick()
    await rig.pass_time(31)
    await rig.tick()


async def test_executor_protection_is_resent_when_its_level_cannot_be_read_back(rig):
    from growbridge.executor.engine import PROTECTION_RESEND_SECONDS

    await rig.start()
    await rig.tick()
    await overheat(rig)
    sent = len(rig.writes())
    unreadable(rig)

    await rig.pass_time(1)
    await rig.tick()
    assert len(rig.writes()) == sent + 1  # re-asserted once
    for _ in range(20):  # a 1 Hz tick must not write a record per tick
        await rig.pass_time(1)
        await rig.tick()
    assert len(rig.writes()) == sent + 1

    await rig.pass_time(PROTECTION_RESEND_SECONDS)
    await rig.tick()
    assert len(rig.writes()) == sent + 2
