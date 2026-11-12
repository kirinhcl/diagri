"""A wall-clock step pauses the running stage once; the operator's resume clears the suspicion."""

from executor_helpers import STAGE

from growbridge.ports import StageEventKind

ANOMALY = StageEventKind.CLOCK_ANOMALY
STEP_SECONDS = 30  # more than the 5 s the wall clock may differ from the monotonic clock


async def paused_by_a_clock_step(rig) -> None:
    await rig.start()
    await rig.tick()
    rig.clock.jump(STEP_SECONDS)  # the host still says it is synchronised
    await rig.refresh()
    report = await rig.tick()
    assert ANOMALY in report.reported
    assert rig.state() == "paused"


async def test_executor_stage_resumed_after_a_clock_step_keeps_running(rig):
    await paused_by_a_clock_step(rig)
    await rig.pass_time(60)  # the operator checks the host clock
    await rig.tick()

    await rig.svc.resume_stage(STAGE, rig.op)
    await rig.pass_time(1)
    report = await rig.tick()

    assert ANOMALY not in report.reported
    assert rig.state() == "running"


async def test_executor_clock_step_while_the_stage_is_paused_is_reported_once_on_resume(rig):
    await rig.start()
    await rig.tick()
    await rig.svc.pause_stage(STAGE, rig.op, "operator pause")
    await rig.tick()
    rig.clock.jump(STEP_SECONDS)
    await rig.refresh()
    await rig.tick()  # nothing is running: nobody is told yet

    await rig.svc.resume_stage(STAGE, rig.op)
    await rig.pass_time(1)
    assert ANOMALY in (await rig.tick()).reported  # the operator is told once

    await rig.svc.resume_stage(STAGE, rig.op)
    await rig.pass_time(1)
    report = await rig.tick()

    assert ANOMALY not in report.reported
    assert rig.state() == "running"


async def test_executor_clock_step_since_the_last_tick_is_still_noticed_after_resume(rig):
    await paused_by_a_clock_step(rig)
    await rig.pass_time(60)
    await rig.tick()

    await rig.svc.resume_stage(STAGE, rig.op)
    rig.clock.jump(STEP_SECONDS)  # a second step, after the operator looked
    await rig.refresh()
    report = await rig.tick()

    assert ANOMALY in report.reported
    assert rig.state() == "paused"


async def test_executor_resume_does_not_clear_an_unsynchronised_clock(rig):
    await rig.start()
    await rig.tick()
    rig.clock.synced = False
    assert ANOMALY in (await rig.tick()).reported

    await rig.svc.resume_stage(STAGE, rig.op)
    await rig.pass_time(1)
    report = await rig.tick()

    assert ANOMALY in report.reported
    assert rig.state() == "paused"


TWO_STAGES = ("vegetative", "flowering")


async def test_executor_another_stage_starting_does_not_clear_the_clock_suspicion(rig):
    await rig.start(stages=TWO_STAGES)
    await rig.tick()
    rig.clock.jump(STEP_SECONDS)
    await rig.refresh()
    assert ANOMALY in (await rig.tick()).reported  # stage-1 is paused by the step
    await rig.start_next_stage("stage-2", experiment_id="experiment-stage-1")

    await rig.pass_time(1)
    report = await rig.tick()

    assert ANOMALY in report.reported  # nobody has acknowledged the clock for this stage
    assert rig.state("stage-2") == "paused"


async def test_executor_resuming_the_stage_that_the_step_paused_clears_the_suspicion(rig):
    await rig.start(stages=TWO_STAGES)
    await rig.tick()
    rig.clock.jump(STEP_SECONDS)
    await rig.refresh()
    await rig.tick()
    await rig.start_next_stage("stage-2", experiment_id="experiment-stage-1")
    await rig.pass_time(1)
    await rig.tick()  # stage-2 is paused too, and is itself told about the clock

    await rig.svc.resume_stage("stage-2", rig.op)
    await rig.pass_time(1)
    report = await rig.tick()

    assert ANOMALY not in report.reported
    assert rig.state("stage-2") == "running"
    rig.clock.jump(STEP_SECONDS)  # a new step after the acknowledgement is caught again
    await rig.refresh()
    assert ANOMALY in (await rig.tick()).reported
    assert rig.state("stage-2") == "paused"
