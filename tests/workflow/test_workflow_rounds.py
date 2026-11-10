import pytest

from growbridge.archive.models import RightKind
from growbridge.ports import Denied
from growbridge.ports import StageEventKind as Kind

TWO = ("vegetative", "flowering")


async def end_stage(world, stage_id="stage-1"):
    await world.report(Kind.END_CONDITION_MET, stage_id)
    await world.report(Kind.END_ACTIONS, stage_id, detail={"confirmed": True})


async def stopped_round(world, stages=TWO):
    await world.design(stages)
    await world.running()
    await world.svc.stop_stage("stage-1", world.op)


async def to_verification(world):
    await world.running()
    await end_stage(world)


async def choose(world, choice, actor=None):
    return await world.svc.choose_after_stop(world.round_id, choice, actor or world.op)


def handed(world) -> list[int]:
    return [number for number, _ in world.control.handovers]


# --- stage end -> round ------------------------------------------------------------------------


async def test_round_stage_running_to_stage_review_while_protocol_has_more_stages(world):
    await world.design(TWO)
    await world.running()
    await end_stage(world)
    assert world.state() == "ended"
    assert world.round_state() == "stage_review"


async def test_round_ended_stage_keeps_the_care_right_while_the_next_stage_waits(world):
    await world.design(TWO)
    await world.running()
    care = world.svc.stage("stage-1").care_right
    await end_stage(world)
    active = world.svc.active_stage()
    assert active.stage_id == "stage-1" and active.state.value == "ended"
    assert active.care_right == care and care in world.control.live(RightKind.CARE)
    await world.pending("stage-2")
    assert world.svc.active_stage().stage_id == "stage-1"


async def test_round_starting_the_next_stage_hands_over_the_old_care_right(world):
    await world.design(TWO)
    await world.running()
    old_care = world.svc.stage("stage-1").care_right
    await end_stage(world)
    await world.running("stage-2")
    assert old_care in handed(world)
    assert world.svc.stage("stage-1").care_right is None
    assert world.svc.stage("stage-2").care_right in world.control.live(RightKind.CARE)
    assert world.svc.active_stage().stage_id == "stage-2"
    assert world.round_state() == "stage_running"


async def test_round_stage_running_to_data_verification_after_the_last_stage(world):
    await world.running()
    await end_stage(world)
    assert world.round_state() == "data_verification"


async def test_round_last_stage_of_two_ends_in_data_verification(world):
    await world.design(TWO)
    await world.running()
    await end_stage(world)
    await world.running("stage-2")
    await end_stage(world, "stage-2")
    assert world.round_state() == "data_verification"


async def test_round_another_round_cannot_start_while_a_stage_on_the_device_needs_checking(world):
    await world.running()
    await world.report(Kind.TRANSPORT_UNCONFIRMED)
    other = world.svc.create_round(world.project_id, "protocol-1", world.op)
    world.svc.submit_run_sheet(other, world.sheet("stage-9"), world.op)
    world.svc.approve("stage-9", world.op)
    with pytest.raises(Denied) as caught:
        await world.svc.start_stage("stage-9", world.op)
    assert caught.value.code == "state"


# --- stopped stage: the operator chooses -------------------------------------------------------


async def test_round_stop_waits_for_the_operator_choice(world):
    await stopped_round(world)
    assert world.round_state() == "stage_running"
    assert world.state() == "stopped"


@pytest.mark.parametrize("choice", ["redo", "next"])
async def test_round_stage_stopped_redo_or_next_goes_back_to_stage_review(world, choice):
    await stopped_round(world)
    state = await choose(world, choice, world.op)
    assert state.value == "stage_review"


async def test_round_redo_accepts_a_new_run_sheet_for_a_new_stage_id(world):
    await stopped_round(world)
    await choose(world, "redo", world.op)
    await world.pending("stage-1b")
    assert world.svc.stage("stage-1b").state.value == "pending_review"
    assert world.round_state() == "stage_review"


async def test_round_submit_is_denied_while_a_choice_is_open(world):
    await stopped_round(world)
    with pytest.raises(Denied) as caught:
        world.svc.submit_run_sheet(world.round_id, world.sheet("stage-2"), world.op)
    assert caught.value.code == "state"


async def test_round_next_counts_the_stopped_stage_as_done(world):
    await stopped_round(world)
    await choose(world, "next", world.op)
    await world.running("stage-2")
    await end_stage(world, "stage-2")
    assert world.round_state() == "data_verification"


async def test_round_redo_does_not_count_the_stopped_stage_as_done(world):
    await stopped_round(world)
    await choose(world, "redo", world.op)
    await world.running("stage-1b")
    await end_stage(world, "stage-1b")
    assert world.round_state() == "stage_review"


async def test_round_stage_stopped_verify_goes_to_data_verification(world):
    await stopped_round(world)
    state = await choose(world, "verify", world.op)
    assert state.value == "data_verification"


async def test_round_stage_stopped_abort_goes_to_aborted(world):
    await stopped_round(world)
    assert (await choose(world, "abort", world.op)).value == "aborted"


async def test_round_next_is_denied_when_no_stage_is_left(world):
    await stopped_round(world, ("vegetative",))
    with pytest.raises(Denied) as caught:
        await choose(world, "next", world.op)
    assert caught.value.code == "state"
    assert world.round_state() == "stage_running"


async def test_round_choice_needs_a_stopped_stage(world):
    await world.running()
    with pytest.raises(Denied) as caught:
        await choose(world, "redo", world.op)
    assert caught.value.code == "state"


async def test_round_choice_can_only_be_made_once(world):
    await stopped_round(world)
    await choose(world, "redo", world.op)
    with pytest.raises(Denied):
        await choose(world, "verify", world.op)


@pytest.mark.parametrize("kind", ["model", "observer", "workflow"])
async def test_round_choice_is_for_operators_only(world, kind):
    await stopped_round(world)
    with pytest.raises(Denied):
        await choose(world, "abort", world.actor(kind))
    assert world.round_state() == "stage_running"


async def test_round_stopping_a_stage_before_it_ran_also_asks_for_a_choice(world):
    await world.design(TWO)
    await world.pending()
    await world.svc.stop_stage("stage-1", world.op)
    assert world.round_state() == "stage_review"
    assert (await choose(world, "redo", world.op)).value == "stage_review"


async def test_round_revoking_approval_of_a_pending_stage_asks_for_a_choice(world):
    await world.design(TWO)
    await world.approved()
    world.svc.revoke_approval("stage-1", world.op)
    state = await choose(world, "verify", world.op)
    assert state.value == "data_verification"


async def test_round_stage_stopped_by_wait_expiry_also_asks_for_a_choice(world):
    await world.design(TWO)
    await world.running(on_expiry="stop")
    await world.svc.pause_stage("stage-1", world.op, "x")
    await world.report(Kind.MAX_WAIT_EXPIRED)
    assert (await choose(world, "abort", world.op)).value == "aborted"


# --- data verification, analysis, delivery -----------------------------------------------------


async def test_round_data_verification_to_analysis_when_the_snapshot_is_frozen(world):
    await to_verification(world)
    state = world.svc.mark_snapshot_frozen(world.round_id, "snap-1", "ev-snap")
    assert state.value == "analysis"


async def test_round_snapshot_event_advances_only_once(world):
    await to_verification(world)
    world.svc.mark_snapshot_frozen(world.round_id, "snap-1", "ev-snap")
    world.svc.mark_report_published(world.round_id, "art-1", "ev-rep")
    again = world.svc.mark_snapshot_frozen(world.round_id, "snap-1", "ev-snap")
    assert again.value == "delivered"


async def test_round_snapshot_event_in_the_wrong_state_is_dropped(world):
    await world.running()
    state = world.svc.mark_snapshot_frozen(world.round_id, "snap-1", "ev-snap")
    assert state.value == "stage_running"


async def test_round_analysis_to_delivered_when_the_report_is_published(world):
    await to_verification(world)
    world.svc.mark_snapshot_frozen(world.round_id, "snap-1", "ev-snap")
    state = world.svc.mark_report_published(world.round_id, "art-1", "ev-rep")
    assert state.value == "delivered"


async def test_round_report_before_analysis_is_dropped(world):
    await to_verification(world)
    state = world.svc.mark_report_published(world.round_id, "art-1", "ev-rep")
    assert state.value == "data_verification"


async def test_round_delivered_round_cannot_be_aborted(world):
    await to_verification(world)
    world.svc.mark_snapshot_frozen(world.round_id, "snap-1", "ev-snap")
    world.svc.mark_report_published(world.round_id, "art-1", "ev-rep")
    with pytest.raises(Denied) as caught:
        await world.svc.abort_round(world.round_id, world.op)
    assert caught.value.code == "state"


# --- abort -------------------------------------------------------------------------------------


async def test_round_abort_while_designing(world):
    await world.design()
    assert (await world.svc.abort_round(world.round_id, world.op)).value == "aborted"


async def test_round_abort_while_a_stage_waits_for_review(world):
    await world.approved()
    assert (await world.svc.abort_round(world.round_id, world.op)).value == "aborted"
    assert world.state() == "stopped"


async def test_round_abort_while_running_hands_over_every_right_and_stops_the_stage(world):
    await world.running()
    stage = world.svc.stage("stage-1")
    state = await world.svc.abort_round(world.round_id, world.op)
    assert state.value == "aborted"
    assert world.state() == "stopped"
    assert {stage.right_number, stage.care_right} <= set(handed(world))
    assert world.control.live(RightKind.STAGE) == [] and world.control.live(RightKind.CARE) == []
    assert world.svc.active_stage() is None


async def test_round_abort_while_manual_hands_over_the_manual_right(world):
    await world.running()
    await world.svc.takeover("stage-1", world.op)
    manual = world.svc.stage("stage-1").manual_right
    await world.svc.abort_round(world.round_id, world.op)
    assert manual in handed(world)


async def test_round_abort_after_the_last_stage_ended(world):
    await to_verification(world)
    state = await world.svc.abort_round(world.round_id, world.op)
    assert state.value == "aborted"
    assert world.control.live(RightKind.CARE) == []


async def test_round_abort_in_analysis(world):
    await to_verification(world)
    world.svc.mark_snapshot_frozen(world.round_id, "snap-1", "ev-snap")
    assert (await world.svc.abort_round(world.round_id, world.op)).value == "aborted"


async def test_round_abort_twice_is_denied(world):
    await world.design()
    await world.svc.abort_round(world.round_id, world.op)
    with pytest.raises(Denied) as caught:
        await world.svc.abort_round(world.round_id, world.op)
    assert caught.value.code == "state"


@pytest.mark.parametrize("kind", ["model", "observer", "workflow"])
async def test_round_abort_is_for_operators_only(world, kind):
    await world.design()
    with pytest.raises(Denied):
        await world.svc.abort_round(world.round_id, world.actor(kind))
    assert world.round_state() == "designing"


async def test_round_nothing_can_be_submitted_after_abort(world):
    await world.design()
    await world.svc.abort_round(world.round_id, world.op)
    with pytest.raises(Denied) as caught:
        world.svc.submit_run_sheet(world.round_id, world.sheet(), world.op)
    assert caught.value.code == "state"
