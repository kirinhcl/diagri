"""Timed actions, feedback rules, channel ownership and the pump (spec 7.2, 7.4)."""

from growbridge.archive.models import (
    Channel,
    ChannelPlan,
    Condition,
    Ownership,
    ProtectionRule,
    RuleAction,
    TimedAction,
)
from growbridge.sim.fixtures import humidity_rule, make_run_sheet, make_safety


async def test_executor_aligns_light_when_the_action_comes_due(rig):
    await rig.at("05:59")
    await rig.start()
    await rig.tick()
    assert (await rig.levels())[Channel.LIGHT] == 0

    await rig.at("06:01")
    await rig.pass_time(0)
    await rig.tick()

    assert (await rig.levels())[Channel.LIGHT] == 60


async def test_executor_missed_timer_aligns_to_the_schedule_at_the_current_time(rig):
    await rig.at("21:00")
    await rig.start()
    await rig.tick()
    assert (await rig.levels())[Channel.LIGHT] == 60

    await rig.at("23:30")  # 22:00 passed while nothing ticked
    await rig.pass_time(0)
    await rig.tick()

    assert (await rig.levels())[Channel.LIGHT] == 0
    assert rig.written().count(("light", 0)) == 1  # one catch-up write, no replay of history


async def test_executor_repeated_tick_does_not_write_twice(rig):
    await rig.start()
    first = await rig.tick()
    count = len(rig.writes())
    assert count >= 1 and first.writes

    for _ in range(3):
        again = await rig.tick()
        assert again.writes == ()

    assert len(rig.writes()) == count


async def test_executor_never_writes_a_device_managed_channel(rig):
    channels = (
        ChannelPlan(channel=Channel.LIGHT, ownership=Ownership.DEVICE),
        ChannelPlan(channel=Channel.EXHAUST, ownership=Ownership.HOST, retained_level=30),
    )
    timed = (
        TimedAction(id="light-on", channel=Channel.LIGHT, at="06:00", level=60),
        TimedAction(id="exhaust-base", channel=Channel.EXHAUST, at="00:00", level=30),
    )
    before = await rig.levels()
    exhaust_only = make_safety(
        rules=(
            ProtectionRule(
                id="overheat-exhaust-up",
                sensor="temp",
                unit="C",
                validity_seconds=20,
                trigger=Condition(op=">", value=35),
                duration_seconds=30,
                action=RuleAction(channel=Channel.EXHAUST, level=100),
            ),
        )
    )
    await rig.start(safety=exhaust_only, channels=channels, timed_actions=timed)

    await rig.tick()

    keys = {key for key, _ in rig.written()}
    assert keys == {"blower"}  # exhaust only; the light module and its timer stay untouched
    assert (await rig.levels())[Channel.LIGHT] == before[Channel.LIGHT]


async def test_executor_humidity_feedback_moves_only_the_exhaust(rig):
    await rig.start(feedback_rules=(humidity_rule(),))
    await rig.tick()
    light_before = (await rig.levels())[Channel.LIGHT]
    rig.sim.set_sensor("humi", 80)

    await rig.pass_time(1)
    await rig.tick()  # the condition starts timing
    await rig.pass_time(30)
    await rig.tick()
    assert (await rig.levels())[Channel.EXHAUST] == 30  # not long enough yet
    await rig.pass_time(31)
    await rig.tick()

    levels = await rig.levels()
    assert levels[Channel.EXHAUST] == 80
    assert levels[Channel.LIGHT] == light_before

    await rig.pass_time(5)
    await rig.tick()  # the timed exhaust base must not undo the feedback
    assert (await rig.levels())[Channel.EXHAUST] == 80


async def test_executor_humidity_feedback_releases_after_recovery(rig):
    await rig.start(feedback_rules=(humidity_rule(min_switch_seconds=0),))
    await rig.tick()
    rig.sim.set_sensor("humi", 80)
    for _ in range(3):
        await rig.pass_time(31)
        await rig.tick()
    assert (await rig.levels())[Channel.EXHAUST] == 80

    rig.sim.set_sensor("humi", 50)
    for _ in range(3):
        await rig.pass_time(31)
        await rig.tick()

    assert (await rig.levels())[Channel.EXHAUST] == 30


async def test_executor_has_no_way_to_start_the_pump(rig):
    from growbridge.executor import engine

    timed = (
        *make_run_sheet().timed_actions,
        TimedAction(id="pump-on", channel=Channel.PUMP, at="00:00", level=1),
    )
    await rig.start(timed_actions=timed)

    for _ in range(3):
        await rig.tick()
        await rig.pass_time(60)

    assert rig.sim.config["outlet"]["O4"]["mOnOff"] == 0
    assert not rig.sim.on_event.is_set()
    with open(engine.__file__) as source:
        assert "irrigate" not in source.read()


async def test_executor_does_nothing_without_an_active_stage(rig):
    report = await rig.tick()

    assert report.writes == () and report.reported == ()
    assert rig.writes() == []


async def test_executor_storage_guard_blocks_experiment_actions(make_rig):
    rig = await make_rig(allow=lambda kind: kind != "experiment_action")
    await rig.start()

    report = await rig.tick()

    assert rig.writes() == [] and report.writes == ()
    assert any("experiment_action" in item for item in report.denied)
