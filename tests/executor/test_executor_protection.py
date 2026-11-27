"""Protection rules act in every stage state while the link is up (spec 7.5, 7.8)."""

import pytest

from growbridge.archive.models import Channel, Condition, RuleAction
from growbridge.sim.fixtures import humidity_rule


def humid_light(**overrides):
    """A feedback rule on humidity that drives the light, the channel the overheat
    protection holds. It is on another sensor, so planning does not block it (spec non-goal)."""
    fields = {
        "id": "humid-light",
        "trigger": Condition(op=">", value=70),
        "recover": Condition(op="<", value=60),
        "duration_seconds": 10,
        "action": RuleAction(channel=Channel.LIGHT, level=80),
        "release": RuleAction(channel=Channel.LIGHT, level=50),
        "min_switch_seconds": 0,
    }
    return humidity_rule(**{**fields, **overrides})


async def light(rig) -> int:
    return (await rig.levels())[Channel.LIGHT]


def ended_detail(rig) -> dict:
    """What the stage history kept of the end event (confirmed, held)."""
    row = [row for row in rig.svc.history("stage-1") if row["event"] == "end_actions"][-1]
    return {key: row["detail"].get(key) for key in ("confirmed", "held")}


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


# --- protection beats feedback rules and end actions (spec 7.4) ---------------------------------


async def test_executor_protection_holds_the_light_against_a_feedback_rule(rig):
    await rig.start(feedback_rules=(humid_light(),))
    await rig.tick()
    rig.sim.set_sensor("humi", 80)
    await overheat(rig)  # the rule's 10 s have passed when protection trips
    levels = [await light(rig)]

    for _ in range(6):
        await rig.pass_time(10)
        report = await rig.tick()
        levels.append(await light(rig))

    assert levels == [0] * 7
    assert all(level != 80 for _, level in rig.written())
    assert any("held by protection overheat-light-off" in reason for reason in report.denied)


async def test_executor_feedback_rule_acts_once_protection_releases(rig):
    await rig.start(feedback_rules=(humid_light(),))
    await rig.tick()
    rig.sim.set_sensor("humi", 80)
    await overheat(rig)
    # Held for 90 s more. The rule last saw its reading move it 121 s before the third
    # tick: if holding froze its state, that tick would read as a gap over the sheet's 120 s,
    # restart the timer, and the rule would wait another 10 s after protection releases.
    for _ in range(3):
        await rig.pass_time(30)
        await rig.tick()

    rig.sim.set_sensor("temp", 25)
    await rig.pass_time(1)
    await rig.tick()

    assert await light(rig) == 80


async def test_executor_feedback_release_is_held_while_protection_holds(rig):
    await rig.start(feedback_rules=(humid_light(),))
    await rig.tick()
    rig.sim.set_sensor("humi", 80)
    for seconds in (1, 11):
        await rig.pass_time(seconds)
        await rig.tick()
    assert await light(rig) == 80
    await overheat(rig)

    rig.sim.set_sensor("humi", 50)  # below the rule's recovery: it wants to release to 50
    for _ in range(4):
        await rig.pass_time(10)
        await rig.tick()
        assert await light(rig) == 0
    assert all(level != 50 for _, level in rig.written())

    rig.sim.set_sensor("temp", 25)
    await rig.pass_time(1)
    await rig.tick()
    assert await light(rig) == 50


async def test_executor_end_action_on_a_protected_channel_is_skipped(rig):
    end = (
        RuleAction(channel=Channel.LIGHT, level=100),
        RuleAction(channel=Channel.EXHAUST, level=10),
    )
    await rig.start(end_actions=end, duration_seconds=60)
    await rig.tick()
    await overheat(rig)

    await rig.pass_time(30)  # past the 60 s duration while protection holds the light
    await rig.tick()

    assert rig.state() == "ended"
    assert await light(rig) == 0
    assert (await rig.levels())[Channel.EXHAUST] == 10
    assert ended_detail(rig) == {"confirmed": True, "held": ["light"]}


async def test_executor_stage_ends_on_time_when_every_end_action_is_held(rig):
    end = (RuleAction(channel=Channel.LIGHT, level=100),)
    await rig.start(end_actions=end, duration_seconds=60)
    await rig.tick()
    await overheat(rig)

    await rig.pass_time(30)
    await rig.tick()

    assert rig.state() == "ended"
    assert await light(rig) == 0
    assert ended_detail(rig) == {"confirmed": True, "held": ["light"]}


async def test_protected_channels_lists_active_protection(rig):
    await rig.start()
    await rig.tick()
    assert rig.engine.protected_channels() == frozenset()

    await overheat(rig)

    assert rig.engine.protected_channels() == frozenset({Channel.LIGHT})
