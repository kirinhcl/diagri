"""Protection rules act in every stage state while the link is up (spec 7.5, 7.8)."""

import pytest

from growbridge.archive.models import Channel


async def overheat(rig):
    """Above 35 C for more than the rule's 30 s."""
    rig.sim.set_sensor("temp", 40)
    await rig.pass_time(1)
    await rig.tick()
    await rig.pass_time(31)
    await rig.tick()


async def put_stage_in(rig, situation):
    if situation == "paused":
        await rig.svc.pause_stage("stage-1", rig.op, "test")
    elif situation == "takeover":
        await rig.svc.takeover("stage-1", rig.op)
    else:
        await rig.interlock()


@pytest.mark.parametrize("situation", ["running", "paused", "takeover", "interlock"])
async def test_executor_protection_switches_the_light_off(rig, situation):
    await rig.start()
    await rig.tick()
    assert (await rig.levels())[Channel.LIGHT] == 60
    if situation != "running":
        await put_stage_in(rig, situation)

    await overheat(rig)

    assert (await rig.levels())[Channel.LIGHT] == 0


async def test_executor_protection_beats_the_timed_schedule_while_it_holds(rig):
    await rig.start()
    await rig.tick()
    await overheat(rig)

    for _ in range(3):
        await rig.pass_time(31)
        await rig.tick()

    assert (await rig.levels())[Channel.LIGHT] == 0


async def test_executor_returns_to_the_schedule_once_protection_clears(rig):
    await rig.start()
    await rig.tick()
    await overheat(rig)

    rig.sim.set_sensor("temp", 25)
    await rig.pass_time(31)
    await rig.tick()  # the trigger no longer holds
    await rig.pass_time(1)
    await rig.tick()

    assert (await rig.levels())[Channel.LIGHT] == 60


async def test_executor_protection_reasserts_when_the_light_is_switched_back_on(rig):
    await rig.start()
    await rig.tick()
    await overheat(rig)
    rig.sim.external_change("device", "light", mOnOff=1, mLevel=60)

    await rig.pass_time(1)
    await rig.tick()

    assert (await rig.levels())[Channel.LIGHT] == 0


async def test_executor_protection_ignores_a_reading_that_is_too_old(rig):
    await rig.start()
    await rig.tick()
    rig.sim.set_sensor("temp", 40)
    await rig.pass_time(1)
    await rig.tick()
    rig.clock.advance(31)  # no new telemetry: the reading is older than its validity

    await rig.tick()

    assert (await rig.levels())[Channel.LIGHT] == 60


async def test_executor_protection_still_dims_the_light_with_an_unconfirmed_transport(rig):
    await rig.start()
    await rig.tick()
    rig.sim.halt_confirmed = False
    await rig.control.confirm_transport_stopped()
    await rig.tick()
    assert rig.state() == "recovery_check"

    await overheat(rig)

    assert (await rig.levels())[Channel.LIGHT] == 0
