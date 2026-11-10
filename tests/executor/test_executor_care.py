"""Care rules, clock trust and stage end (spec 7.7)."""

from executor_helpers import STAGE

from growbridge.archive.models import Channel
from growbridge.ports import StageEventKind


async def pause(rig):
    await rig.svc.pause_stage(STAGE, rig.op, "test")
    assert rig.state() == "paused"


async def test_executor_care_keeps_the_light_on_schedule_while_paused(rig):
    await rig.at("05:59")
    await rig.start()
    await pause(rig)
    await rig.tick()
    assert (await rig.levels())[Channel.LIGHT] == 0

    await rig.at("06:01")
    await rig.pass_time(0)
    await rig.tick()

    assert (await rig.levels())[Channel.LIGHT] == 60


async def test_executor_care_does_not_run_the_experiment_timed_actions(rig):
    await rig.start()
    await pause(rig)

    await rig.tick()

    assert {key for key, _ in rig.written()} == {"light"}  # care only: no exhaust base action


async def test_executor_care_pauses_during_manual_takeover(rig):
    await rig.at("05:59")
    await rig.start()
    await rig.svc.takeover(STAGE, rig.op)
    assert rig.state() == "manual"

    await rig.tick()

    assert rig.writes() == []


async def test_executor_care_follows_the_monotonic_clock_when_the_wall_clock_is_untrusted(rig):
    await rig.at("05:59")
    await rig.start()
    await pause(rig)
    await rig.tick()  # trusted tick: 05:59, light off
    assert (await rig.levels())[Channel.LIGHT] == 0

    rig.clock.synced = False
    rig.clock.jump(5 * 3600)  # the wall clock says 10:59
    await rig.refresh()
    await rig.tick()
    assert (await rig.levels())[Channel.LIGHT] == 0  # monotonic time says it is still 05:59

    await rig.pass_time(120)  # 06:01 by the monotonic clock
    await rig.tick()
    assert (await rig.levels())[Channel.LIGHT] == 60


async def test_executor_care_treats_a_synced_clock_that_jumps_as_untrusted(rig):
    await rig.at("05:59")
    await rig.start()
    await pause(rig)
    await rig.tick()

    rig.clock.jump(5 * 3600)  # a step that the host did not flag as unsynchronised
    await rig.refresh()
    await rig.tick()

    assert (await rig.levels())[Channel.LIGHT] == 0


async def test_executor_care_without_any_trusted_time_writes_nothing(make_rig):
    rig = await make_rig()
    rig.clock.synced = False
    await rig.start()
    await pause(rig)

    await rig.tick()

    assert rig.writes() == []


async def test_executor_running_stage_with_an_untrusted_clock_is_reported(rig):
    await rig.start()
    await rig.tick()
    rig.clock.synced = False

    report = await rig.tick()

    assert StageEventKind.CLOCK_ANOMALY in report.reported
    assert rig.state() == "paused"


async def test_executor_end_condition_runs_end_actions_and_ends_the_stage(rig):
    await rig.start(duration_seconds=3600)
    await rig.tick()
    assert (await rig.levels())[Channel.LIGHT] == 60

    await rig.pass_time(3601)
    report = await rig.tick()

    assert StageEventKind.END_CONDITION_MET in report.reported
    assert StageEventKind.END_ACTIONS in report.reported
    assert rig.state() == "ended"
    assert (await rig.levels())[Channel.LIGHT] == 0  # the approved end action


async def test_executor_care_continues_after_the_stage_has_ended(rig):
    await rig.start(duration_seconds=3600)
    await rig.tick()
    await rig.pass_time(3601)
    await rig.tick()
    assert rig.state() == "ended"

    await rig.at("06:30", "2027-01-16")
    await rig.tick()

    assert (await rig.levels())[Channel.LIGHT] == 60  # the care rule, not the experiment
    assert {key for key, _ in rig.written()} <= {"light", "blower"}


async def test_executor_end_actions_unconfirmed_hold_the_stage_for_checking(rig):
    await rig.start(duration_seconds=3600)
    await rig.tick()
    await rig.pass_time(3601)
    rig.sim.ignore_writes = True  # the device acknowledges but does not change

    report = await rig.tick()

    assert StageEventKind.END_ACTIONS in report.reported
    assert rig.state() == "recovery_check"
