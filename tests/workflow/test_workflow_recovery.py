import pytest

from growbridge.archive.models import ActionRecord, ActionState, Channel, RightKind
from growbridge.ports import Denied, Difference
from growbridge.ports import StageEventKind as Kind
from growbridge.sim.fixtures import make_safety
from growbridge.workflow.service import WorkflowService

STAGE, CARE, MANUAL = RightKind.STAGE, RightKind.CARE, RightKind.MANUAL


def unknown_action(world) -> ActionRecord:
    return ActionRecord(
        request_id="r-1",
        state=ActionState.UNKNOWN,
        channel=Channel.LIGHT,
        planned_level=60,
        right_number=1,
        right_kind=STAGE,
        trigger="light-on",
        created_at=world.clock.now(),
    )


def lost_difference() -> Difference:
    return Difference(channel=Channel.LIGHT, field="level", expected=60, actual=0)


async def reach(world, start: str) -> None:
    """Run a stage and bring it to ``running``, ``paused``, ``manual`` or ``pending_review``."""
    if start == "pending_review":
        await world.approved()
        return
    await world.running()
    if start == "paused":
        await world.svc.pause_stage("stage-1", world.op, "x")
    if start == "manual":
        await world.svc.takeover("stage-1", world.op)


async def restarted(world, start: str = "running") -> None:
    await reach(world, start)
    await world.svc.on_restart()


# --- entering recovery_check -------------------------------------------------------------------


@pytest.mark.parametrize("start", ["running", "paused", "manual"])
async def test_stage_restart_moves_a_live_stage_to_recovery_check_and_drops_rights(world, start):
    world.control.stopped = False  # care is only restored once old writes are confirmed gone
    await restarted(world, start)
    runtime = world.svc.stage("stage-1")
    assert runtime.state.value == "recovery_check"
    assert runtime.prior_state.value == start
    assert runtime.right_number is None
    assert runtime.care_right is None and runtime.manual_right is None


async def test_stage_restart_moves_a_pending_stage_to_recovery_check(world):
    await restarted(world, "pending_review")
    runtime = world.svc.stage("stage-1")
    assert runtime.state.value == "recovery_check"
    assert runtime.prior_state.value == "pending_review"
    assert world.svc.approvals("stage-1")[0].voided_at is None


async def test_stage_restart_leaves_finished_stages_alone(world):
    await world.running()
    await world.svc.stop_stage("stage-1", world.op)
    await world.svc.on_restart()
    assert world.state() == "stopped"


async def test_stage_restart_twice_keeps_the_original_prior_state(world):
    await restarted(world, "paused")
    await world.svc.on_restart()
    runtime = world.svc.stage("stage-1")
    assert runtime.state.value == "recovery_check" and runtime.prior_state.value == "paused"


async def test_stage_recovery_number_bump_voids_the_approval_and_enters_recovery_check(world):
    await world.running()
    world.control.stopped = False
    world.control.bump_recovery("restored from backup")
    await world.svc.on_recovery_bump()
    runtime = world.svc.stage("stage-1")
    assert runtime.state.value == "recovery_check"
    assert runtime.prior_state.value == "running"
    assert runtime.right_number is None and runtime.care_right is None
    assert all(approval.voided_at is not None for approval in world.svc.approvals("stage-1"))


async def test_stage_restart_state_is_stored_for_the_next_process(world, db, clock, control):
    await world.running()
    await world.svc.on_restart()
    again = WorkflowService(db, clock, control)
    assert again.stage("stage-1").state.value == "recovery_check"
    assert again.active_stage().stage_id == "stage-1"


# --- leaving recovery_check: transport confirmed -----------------------------------------------


async def test_stage_recovery_check_to_paused_when_transport_readback_and_actions_are_clean(world):
    await restarted(world, "running")
    runtime = await world.svc.try_exit_recovery("stage-1")
    assert runtime.state.value == "paused"
    assert runtime.prior_state is None
    assert runtime.right_number is None
    assert runtime.care_right in world.control.live(CARE)
    assert world.control.expected_seen[-1] == world.sheet().expected_levels(world.clock.now())


async def test_stage_recovery_check_from_paused_goes_back_to_paused(world):
    await restarted(world, "paused")
    assert (await world.svc.try_exit_recovery("stage-1")).state.value == "paused"


@pytest.mark.parametrize("breakage", ["not_stopped", "interlock", "unsettled", "differences"])
async def test_stage_recovery_check_stays_while_a_condition_fails(world, control, breakage):
    await restarted(world, "running")
    if breakage == "not_stopped":
        control.stopped = False
    if breakage == "interlock":
        control.interlock = True
    if breakage == "unsettled":
        control.unsettled = (unknown_action(world),)
    if breakage == "differences":
        control.diffs = (lost_difference(),)
    runtime = await world.svc.try_exit_recovery("stage-1")
    assert runtime.state.value == "recovery_check"


async def test_stage_recovery_check_exit_when_the_conditions_become_true(world, control):
    await restarted(world, "running")
    control.stopped = False
    await world.svc.try_exit_recovery("stage-1")
    control.stopped = True
    assert (await world.svc.try_exit_recovery("stage-1")).state.value == "paused"


async def test_stage_exit_of_a_stage_that_is_not_in_recovery_is_a_no_op(world):
    await world.running()
    runtime = await world.svc.try_exit_recovery("stage-1")
    assert runtime.state.value == "running"


# --- leaving recovery_check: on-site check -----------------------------------------------------


async def test_stage_recovery_check_to_paused_by_an_onsite_check_even_with_failures(world, control):
    await restarted(world, "running")
    control.stopped = False
    control.diffs = (lost_difference(),)
    runtime = await world.svc.record_onsite_check("stage-1", world.op, "checked the tent")
    assert runtime.state.value == "paused"
    assert ("onsite_check", "op-1", "checked the tent") in control.log
    notes = [row for row in world.svc.history("stage-1") if row["event"] == "onsite_check"]
    assert notes[0]["detail"]["note"] == "checked the tent"


async def test_stage_onsite_check_needs_an_operator_and_a_stage_in_recovery(world):
    await restarted(world, "running")
    with pytest.raises(Denied) as caught:
        await world.svc.record_onsite_check("stage-1", world.actor("model"), "x")
    assert caught.value.code == "model_role"
    await world.svc.try_exit_recovery("stage-1")
    await world.svc.resume_stage("stage-1", world.op)
    with pytest.raises(Denied) as caught:
        await world.svc.record_onsite_check("stage-1", world.op, "x")
    assert caught.value.code == "state"


async def test_stage_onsite_check_does_not_carry_over_to_a_later_recovery(world, control):
    await restarted(world, "running")
    await world.svc.record_onsite_check("stage-1", world.op, "first")
    await world.svc.on_restart()
    control.stopped = False
    runtime = await world.svc.try_exit_recovery("stage-1")
    assert runtime.state.value == "recovery_check"


# --- destinations ------------------------------------------------------------------------------


async def test_stage_recovery_check_from_manual_issues_a_new_manual_right_and_stays_manual(world):
    await restarted(world, "manual")
    runtime = await world.svc.try_exit_recovery("stage-1")
    assert runtime.state.value == "manual"
    assert runtime.manual_right in world.control.live(MANUAL)
    assert world.control.rights[runtime.manual_right].operator == "op-1"
    assert runtime.right_number is None and runtime.care_right is None


async def test_stage_recovery_check_from_pending_review_goes_back_to_pending_review(world):
    await restarted(world, "pending_review")
    runtime = await world.svc.try_exit_recovery("stage-1")
    assert runtime.state.value == "pending_review"
    assert world.svc.approvals("stage-1")[0].voided_at is None
    started = await world.svc.start_stage("stage-1", world.op)
    assert started.state.value == "running"


@pytest.mark.parametrize("start", ["running", "paused", "manual", "pending_review"])
async def test_stage_recovery_with_a_new_recovery_number_always_returns_to_pending_review(
    world, start
):
    await reach(world, start)
    world.control.bump_recovery("restore")
    await world.svc.on_recovery_bump()
    runtime = await world.svc.try_exit_recovery("stage-1")
    assert runtime.state.value == "pending_review"
    assert runtime.right_number is None and runtime.manual_right is None
    assert all(a.voided_at is not None for a in world.svc.approvals("stage-1"))
    assert world.round_state() == "stage_review"
    with pytest.raises(Denied) as caught:
        await world.svc.start_stage("stage-1", world.op)
    assert caught.value.code == "approval_invalid"


async def test_stage_recovery_with_a_new_number_needs_the_safety_config_confirmed_first(world):
    await world.running()
    world.control.bump_recovery("restore")
    await world.svc.on_recovery_bump()
    world.control.safety_config = None
    runtime = await world.svc.try_exit_recovery("stage-1")
    assert runtime.state.value == "recovery_check"
    world.control.safety_config = make_safety(approved_by="op-1", approved_at=1.0)
    assert (await world.svc.try_exit_recovery("stage-1")).state.value == "pending_review"


async def test_stage_reapproval_after_a_recovery_number_change_can_start_again(world):
    await world.running()
    world.control.bump_recovery("restore")
    await world.svc.on_recovery_bump()
    await world.svc.try_exit_recovery("stage-1")
    approval = world.svc.approve("stage-1", world.op)
    assert approval.recovery_number == world.control.recovery_number()
    runtime = await world.svc.start_stage("stage-1", world.op)
    assert runtime.state.value == "running"
    assert world.round_state() == "stage_running"


async def test_stage_end_pending_survives_recovery(world):
    await world.running()
    await world.report(Kind.END_CONDITION_MET)
    await world.svc.on_restart()
    runtime = await world.svc.try_exit_recovery("stage-1")
    assert runtime.state.value == "paused" and runtime.end_pending is True


# --- care right after a restart ----------------------------------------------------------------


async def end_first_of_two(world) -> None:
    await world.design(("a", "b"))
    await world.running()
    await world.report(Kind.END_CONDITION_MET)
    await world.report(Kind.END_ACTIONS, detail={"confirmed": True})


async def test_stage_restart_restores_the_care_right_of_an_ended_stage_once_transport_stopped(
    world, control
):
    await end_first_of_two(world)
    old_care = world.svc.stage("stage-1").care_right
    control.stopped = False
    control.revoked.add(old_care)
    await world.svc.on_restart()
    assert world.svc.stage("stage-1").care_right is None
    control.stopped = True
    await world.svc.restore_care()
    new_care = world.svc.stage("stage-1").care_right
    assert new_care is not None and new_care != old_care
    assert new_care in control.live(CARE)


async def test_stage_restore_care_does_nothing_while_transport_is_unconfirmed(world, control):
    await end_first_of_two(world)
    control.stopped = False
    await world.svc.on_restart()
    await world.svc.restore_care()
    assert world.svc.stage("stage-1").care_right is None
