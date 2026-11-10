import pytest

from growbridge.archive.models import ActionRecord, ActionState, Channel, RightKind
from growbridge.ports import Denied, Difference
from growbridge.ports import StageEventKind as Kind

CARE = RightKind.CARE


def unknown_action(world) -> ActionRecord:
    return ActionRecord(
        request_id="r-1",
        state=ActionState.UNKNOWN,
        channel=Channel.LIGHT,
        planned_level=60,
        right_number=1,
        right_kind=RightKind.STAGE,
        trigger="light-on",
        created_at=world.clock.now(),
    )


def reconciled(control) -> int:
    return len([entry for entry in control.log if entry[0] == "reconcile"])


# --- unknown results no longer deadlock the stage ----------------------------------------------


async def test_stage_result_unknown_pause_can_be_resumed_after_reconciliation(world, control):
    await world.running()
    control.unsettled = (unknown_action(world),)
    await world.report(Kind.RESULT_UNKNOWN)
    assert world.state() == "paused"
    control.reconcile_leaves = ()
    runtime = await world.svc.resume_stage("stage-1", world.op)
    assert runtime.state.value == "running"
    assert reconciled(control) >= 1


async def test_stage_resume_is_still_denied_when_reconciliation_leaves_actions(world, control):
    await world.running()
    await world.svc.pause_stage("stage-1", world.op, "x")
    control.unsettled = (unknown_action(world),)
    with pytest.raises(Denied) as caught:
        await world.svc.resume_stage("stage-1", world.op)
    assert caught.value.code == "state"
    assert reconciled(control) == 1


async def test_stage_takeover_reconciles_before_opening_manual_writes(world, control):
    await world.running()
    await world.svc.takeover("stage-1", world.op)
    assert reconciled(control) == 1


async def test_stage_recovery_exit_reconciles_unknown_actions(world, control):
    await world.running()
    await world.svc.on_restart()
    control.unsettled = (unknown_action(world),)
    control.reconcile_leaves = ()
    runtime = await world.svc.try_exit_recovery("stage-1")
    assert runtime.state.value == "paused"


async def test_stage_recovery_exit_waits_while_reconciliation_leaves_actions(world, control):
    await world.running()
    await world.svc.on_restart()
    control.unsettled = (unknown_action(world),)
    runtime = await world.svc.try_exit_recovery("stage-1")
    assert runtime.state.value == "recovery_check"


# --- on-site check from paused and manual ------------------------------------------------------


async def test_stage_onsite_check_while_paused_settles_and_stays_paused(world, control):
    await world.running()
    await world.svc.pause_stage("stage-1", world.op, "x")
    control.unsettled = (unknown_action(world),)
    runtime = await world.svc.record_onsite_check("stage-1", world.op, "looked at the tent")
    assert runtime.state.value == "paused"
    assert ("onsite_check", "op-1", "looked at the tent") in control.log
    assert (await world.svc.resume_stage("stage-1", world.op)).state.value == "running"


async def test_stage_onsite_check_while_manual_stays_manual(world, control):
    await world.running()
    await world.svc.takeover("stage-1", world.op)
    runtime = await world.svc.record_onsite_check("stage-1", world.op, "looked")
    assert runtime.state.value == "manual"
    notes = [row for row in world.svc.history("stage-1") if row["event"] == "onsite_check"]
    assert notes[0]["detail"]["note"] == "looked"


async def test_stage_onsite_check_is_denied_while_running(world):
    await world.running()
    with pytest.raises(Denied) as caught:
        await world.svc.record_onsite_check("stage-1", world.op, "x")
    assert caught.value.code == "state"


# --- stale events ------------------------------------------------------------------------------


async def test_stage_clock_anomaly_still_pauses_after_the_wall_clock_steps_back(world):
    await world.running()
    world.clock.jump(-3600)
    await world.report(Kind.CLOCK_ANOMALY)
    assert world.state() == "paused"


async def test_stage_event_with_the_current_right_number_applies(world):
    await world.running()
    current = world.svc.stage("stage-1").right_number
    await world.report(Kind.RULE_PAUSE, detail={"right_number": current})
    assert world.state() == "paused"


async def test_stage_event_with_another_right_number_is_dropped(world):
    await world.running()
    await world.report(Kind.RULE_PAUSE, detail={"right_number": 9999})
    assert world.state() == "running"


# --- care during recovery ----------------------------------------------------------------------


async def test_stage_care_is_restored_during_recovery_once_transport_is_stopped(world, control):
    await world.running()
    old = world.svc.stage("stage-1").care_right
    control.stopped = False
    await world.svc.on_restart()
    assert world.svc.stage("stage-1").care_right is None
    control.stopped = True
    await world.svc.restore_care()
    care = world.svc.stage("stage-1").care_right
    assert care is not None and care != old and care in control.live(CARE)
    await world.svc.restore_care()
    assert world.svc.stage("stage-1").care_right == care
    runtime = await world.svc.try_exit_recovery("stage-1")
    assert runtime.care_right == care
    assert len(control.granted(CARE)) == 2


async def test_stage_care_is_restored_when_recovery_is_polled(world, control):
    await world.running()
    control.stopped = False
    await world.svc.on_restart()
    control.stopped = True
    control.diffs = (Difference(channel=Channel.LIGHT, field="level", expected=60, actual=0),)
    runtime = await world.svc.try_exit_recovery("stage-1")
    assert runtime.state.value == "recovery_check" and runtime.care_right is not None


async def test_stage_care_is_not_restored_for_a_manual_stage(world, control):
    await world.running()
    await world.svc.takeover("stage-1", world.op)
    await world.svc.on_restart()
    assert world.svc.stage("stage-1").care_right is None
    assert len(control.granted(CARE)) == 1


async def test_stage_care_is_not_restored_after_a_recovery_number_change(world, control):
    await world.running()
    control.stopped = False
    control.bump_recovery("restore")
    await world.svc.on_recovery_bump()
    control.stopped = True
    await world.svc.restore_care()
    assert world.svc.stage("stage-1").care_right is None


# --- handback ----------------------------------------------------------------------------------


async def test_stage_failed_handback_readback_leaves_the_manual_right_alive(world, control):
    await world.running()
    manual = (await world.svc.takeover("stage-1", world.op)).manual_right
    control.differences_error = ConnectionError("device offline")
    with pytest.raises(ConnectionError):
        await world.svc.handback("stage-1", world.op, accept_as_intervention=False)
    runtime = world.svc.stage("stage-1")
    assert runtime.state.value == "manual" and runtime.manual_right == manual
    assert manual in control.live(RightKind.MANUAL)
