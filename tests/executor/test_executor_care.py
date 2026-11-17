"""Care rules, clock trust and stage end (spec 7.7)."""

from executor_helpers import DAY, STAGE

from growbridge.archive.models import ActionState, CareRule, Channel, TimedAction
from growbridge.ports import StageEventKind


async def pause(rig):
    await rig.svc.pause_stage(STAGE, rig.op, "test")
    assert rig.state() == "paused"


def morning_and_evening_light() -> tuple[CareRule, ...]:
    """Two care rules on the light whose steps have the same ids, ``on`` and ``off``."""
    light = Channel.LIGHT

    def steps(on: str, off: str) -> tuple[TimedAction, ...]:
        return (
            TimedAction(id="on", channel=light, at=on, level=60),
            TimedAction(id="off", channel=light, at=off, level=0),
        )

    return (
        CareRule(id="care-morning", channel=light, schedule=steps("06:00", "06:05")),
        CareRule(id="care-evening", channel=light, schedule=steps("06:10", "22:00")),
    )


async def test_executor_care_write_names_its_care_rule_and_step(rig):
    await rig.at("06:01")
    await rig.start()
    await pause(rig)

    (request_id,) = (await rig.tick()).writes

    assert rig.control.receipt(request_id).trigger == "care:care-light/care-on"
    assert request_id.endswith(f":care:care-light/care-on:light:60:{DAY}.g0")


async def test_executor_care_step_of_another_care_rule_is_not_filed_as_a_retry(rig):
    await rig.at("05:59")
    await rig.start(care_rules=morning_and_evening_light())
    await pause(rig)
    await rig.tick()  # light off, as the evening rule's 22:00 step of the day before says
    rig.sim.ignore_writes = True  # the morning light does not take
    await rig.at("06:01")
    (morning,) = (await rig.tick()).writes
    assert rig.control.receipt(morning).state is ActionState.FAILED
    rig.sim.ignore_writes = False

    await rig.at("06:11")
    (evening,) = (await rig.tick()).writes

    record = rig.control.receipt(evening)
    assert record.supersedes is None  # the evening step is not a retry of the morning one
    assert record.trigger == "care:care-evening/on"


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
