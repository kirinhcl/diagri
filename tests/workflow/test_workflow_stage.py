import asyncio

import pytest

from growbridge.archive.models import ActionRecord, ActionState, Channel, RightKind
from growbridge.ports import Denied, Difference
from growbridge.workflow.permissions import REAUTH_SECONDS

STAGE, CARE, MANUAL = RightKind.STAGE, RightKind.CARE, RightKind.MANUAL


def moves(world, stage_id="stage-1"):
    return [(row["from"], row["to"]) for row in world.svc.history(stage_id)]


def handed(world) -> list[int]:
    return [number for number, _ in world.control.handovers]


# --- approval ----------------------------------------------------------------------------------


async def test_approval_binds_sheet_project_experiment_stage_device_capability_and_recovery(world):
    await world.pending()
    approval = world.svc.approve("stage-1", world.op)
    sheet = world.sheet()
    assert approval.run_sheet_id == sheet.id
    assert approval.run_sheet_version == 1
    assert approval.run_sheet_digest == sheet.digest()
    assert approval.project_id == world.project_id
    assert approval.experiment_id == sheet.experiment_id
    assert approval.stage_id == "stage-1"
    assert approval.device_id == sheet.device_id
    assert approval.capability_version == world.control.capabilities().version
    assert approval.recovery_number == world.control.recovery_number()
    assert approval.operator == "op-1"
    assert approval.approved_at == world.clock.now()
    assert approval.voided_at is None
    assert world.svc.approvals("stage-1") == (approval,)


async def test_approval_only_for_a_stage_waiting_for_review(world):
    await world.running()
    with pytest.raises(Denied) as caught:
        world.svc.approve("stage-1", world.op)
    assert caught.value.code == "state"


async def test_approval_for_an_unknown_stage_is_denied(world):
    with pytest.raises(Denied) as caught:
        world.svc.approve("nope", world.op)
    assert caught.value.code == "state"


async def test_approval_a_second_approval_supersedes_the_first(world):
    await world.approved()
    world.clock.advance(5)
    second = world.svc.approve("stage-1", world.op)
    first, last = world.svc.approvals("stage-1")
    assert first.voided_at is not None
    assert last == second and last.voided_at is None


# --- start: pending -> running -----------------------------------------------------------------


async def test_stage_pending_to_running_with_new_stage_and_care_rights(world):
    await world.approved()
    runtime = await world.svc.start_stage("stage-1", world.op)
    assert runtime.state.value == "running"
    assert runtime.right_number == world.control.live(STAGE)[0]
    assert runtime.care_right == world.control.live(CARE)[0]
    assert runtime.manual_right is None
    assert runtime.started_at == world.clock.now()
    right = world.control.right(runtime.right_number)
    assert right.stage_id == "stage-1"
    assert right.run_sheet_digest == world.sheet().digest()
    assert set(right.channels) == set(world.sheet().host_channels())
    assert world.round_state() == "stage_running"


async def test_stage_care_right_is_limited_to_the_care_schedule(world):
    await world.running()
    (number,) = world.control.live(CARE)
    right = world.control.right(number)
    assert right.channels == (Channel.LIGHT,)
    assert {action.level for action in right.levels} == {0, 60}


async def test_stage_start_without_care_rules_grants_no_care_right(world):
    await world.approved(care_rules=())
    runtime = await world.svc.start_stage("stage-1", world.op)
    assert runtime.care_right is None
    assert world.control.granted(CARE) == []


async def test_stage_start_without_an_approval_is_denied(world):
    await world.pending()
    with pytest.raises(Denied) as caught:
        await world.svc.start_stage("stage-1", world.op)
    assert caught.value.code == "approval_invalid"
    assert world.control.grants == []


async def test_stage_start_twice_takes_effect_once(world):
    await world.approved()
    first = await world.svc.start_stage("stage-1", world.op)
    second = await world.svc.start_stage("stage-1", world.op)
    assert second == first
    assert len(world.control.granted(STAGE)) == 1
    assert len(world.control.granted(CARE)) == 1


async def test_stage_two_concurrent_starts_take_effect_once(world):
    await world.approved()
    await asyncio.gather(
        world.svc.start_stage("stage-1", world.op), world.svc.start_stage("stage-1", world.op)
    )
    assert len(world.control.granted(STAGE)) == 1


async def test_stage_start_after_a_capability_change_is_denied_and_voids_the_approval(world):
    await world.approved()
    world.control.capability_version = "caps-2"
    with pytest.raises(Denied) as caught:
        await world.svc.start_stage("stage-1", world.op)
    assert caught.value.code == "approval_invalid"
    assert world.state() == "pending_review"
    assert world.svc.approvals("stage-1")[0].voided_at is not None
    assert world.control.grants == []


async def test_stage_start_after_a_recovery_number_change_is_denied(world):
    await world.approved()
    world.control.bump_recovery("host changed")
    with pytest.raises(Denied) as caught:
        await world.svc.start_stage("stage-1", world.op)
    assert caught.value.code == "approval_invalid"
    assert world.svc.approvals("stage-1")[0].voided_at is not None


async def test_stage_start_with_an_old_version_approval_is_denied(world):
    await world.approved()
    world.svc.submit_run_sheet(world.round_id, world.sheet(version=2), world.op)
    with pytest.raises(Denied) as caught:
        await world.svc.start_stage("stage-1", world.op)
    assert caught.value.code == "approval_invalid"


async def test_stage_start_with_a_safety_conflict_is_denied(world):
    await world.approved()
    world.control.conflicts = ("overheat-light-off acts on light",)
    with pytest.raises(Denied) as caught:
        await world.svc.start_stage("stage-1", world.op)
    assert caught.value.code == "safety_conflict"
    assert world.state() == "pending_review"
    assert world.control.grants == []


async def test_stage_start_while_the_pump_interlock_is_on_is_denied(world):
    await world.approved()
    world.control.interlock = True
    with pytest.raises(Denied) as caught:
        await world.svc.start_stage("stage-1", world.op)
    assert caught.value.code == "interlock"


# --- pause and resume --------------------------------------------------------------------------


async def test_stage_operator_pause_hands_over_the_stage_right_and_keeps_care(world):
    await world.running()
    before = world.svc.stage("stage-1")
    runtime = await world.svc.pause_stage("stage-1", world.op, "leaf check")
    assert runtime.state.value == "paused"
    assert runtime.right_number is None
    assert runtime.care_right == before.care_right
    assert (before.right_number, "leaf check") in world.control.handovers
    assert before.care_right not in handed(world)
    assert runtime.paused_at == world.clock.now()


async def test_stage_pause_when_already_paused_does_nothing(world):
    await world.running()
    await world.svc.pause_stage("stage-1", world.op, "a")
    await world.svc.pause_stage("stage-1", world.op, "b")
    assert len(world.control.handovers) == 1


async def test_stage_pause_is_denied_for_a_stage_waiting_for_review(world):
    await world.pending()
    with pytest.raises(Denied) as caught:
        await world.svc.pause_stage("stage-1", world.op, "x")
    assert caught.value.code == "state"


async def test_stage_paused_to_running_when_readback_is_consistent(world):
    await world.running()
    old = world.svc.stage("stage-1")
    await world.svc.pause_stage("stage-1", world.op, "check")
    runtime = await world.svc.resume_stage("stage-1", world.op)
    assert runtime.state.value == "running"
    assert runtime.right_number is not None and runtime.right_number != old.right_number
    assert runtime.right_number in world.control.live(STAGE)
    assert world.control.expected_seen[-1] == world.sheet().expected_levels(world.clock.now())


async def test_stage_resume_with_differences_is_denied(world):
    await world.running()
    await world.svc.pause_stage("stage-1", world.op, "check")
    world.control.diffs = (Difference(channel=Channel.LIGHT, field="level", expected=60, actual=0),)
    with pytest.raises(Denied) as caught:
        await world.svc.resume_stage("stage-1", world.op)
    assert caught.value.code == "state"
    assert world.state() == "paused"


async def test_stage_resume_with_unsettled_actions_is_denied(world, control):
    await world.running()
    await world.svc.pause_stage("stage-1", world.op, "check")
    control.unsettled = (
        ActionRecord(
            request_id="r-1",
            state=ActionState.UNKNOWN,
            channel=Channel.LIGHT,
            planned_level=60,
            right_number=1,
            right_kind=STAGE,
            trigger="light-on",
            created_at=world.clock.now(),
        ),
    )
    with pytest.raises(Denied) as caught:
        await world.svc.resume_stage("stage-1", world.op)
    assert caught.value.code == "state"


async def test_stage_resume_with_a_changed_capability_is_denied(world):
    await world.running()
    await world.svc.pause_stage("stage-1", world.op, "check")
    world.control.capability_version = "caps-2"
    with pytest.raises(Denied) as caught:
        await world.svc.resume_stage("stage-1", world.op)
    assert caught.value.code == "approval_invalid"


async def test_stage_resume_of_a_running_stage_is_a_no_op(world):
    await world.running()
    await world.svc.resume_stage("stage-1", world.op)
    assert len(world.control.granted(STAGE)) == 1


# --- takeover and handback ---------------------------------------------------------------------


@pytest.mark.parametrize("paused_first", [False, True])
async def test_stage_running_or_paused_to_manual_revokes_rights_and_grants_manual(
    world, paused_first
):
    await world.running()
    if paused_first:
        await world.svc.pause_stage("stage-1", world.op, "x")
    before = world.svc.stage("stage-1")
    runtime = await world.svc.takeover("stage-1", world.op)
    assert runtime.state.value == "manual"
    assert runtime.right_number is None and runtime.care_right is None
    assert runtime.manual_right in world.control.live(MANUAL)
    assert before.care_right in handed(world)
    assert paused_first or before.right_number in handed(world)
    assert world.control.rights[runtime.manual_right].operator == "op-1"
    assert world.svc.interventions("experiment-stage-1")[0]["kind"] == "takeover"


async def test_stage_takeover_is_denied_for_a_stage_waiting_for_review(world):
    await world.pending()
    with pytest.raises(Denied) as caught:
        await world.svc.takeover("stage-1", world.op)
    assert caught.value.code == "state"


async def test_stage_manual_to_running_lists_differences_and_records_an_accepted_intervention(
    world,
):
    await world.running()
    await world.svc.takeover("stage-1", world.op)
    manual = world.svc.stage("stage-1").manual_right
    diff = Difference(channel=Channel.LIGHT, field="level", expected=60, actual=30)
    world.control.diffs = (diff,)
    runtime, listed = await world.svc.handback("stage-1", world.op, accept_as_intervention=True)
    assert listed == (diff,)
    assert runtime.state.value == "running"
    assert runtime.manual_right is None
    assert (manual, "handback") in world.control.handovers
    assert runtime.right_number in world.control.live(STAGE)
    assert runtime.care_right in world.control.live(CARE)
    accepted = [
        row for row in world.svc.interventions("experiment-stage-1") if row["kind"] == "accepted"
    ]
    assert len(accepted) == 1
    assert accepted[0]["differences"] == [diff.model_dump(mode="json")]
    assert accepted[0]["operator"] == "op-1"


async def test_stage_handback_without_accepting_records_no_accepted_intervention(world):
    await world.running()
    await world.svc.takeover("stage-1", world.op)
    diff = Difference(channel=Channel.LIGHT, field="level", expected=60, actual=30)
    world.control.diffs = (diff,)
    runtime, listed = await world.svc.handback("stage-1", world.op, accept_as_intervention=False)
    assert listed == (diff,) and runtime.state.value == "running"
    kinds = [row["kind"] for row in world.svc.interventions("experiment-stage-1")]
    assert "accepted" not in kinds


async def test_stage_handback_compares_with_the_target_of_the_current_moment(world):
    await world.running()
    await world.svc.takeover("stage-1", world.op)
    await world.svc.handback("stage-1", world.op, accept_as_intervention=False)
    assert world.control.expected_seen[-1] == world.sheet().expected_levels(world.clock.now())


async def test_stage_handback_is_denied_unless_the_stage_is_manual(world):
    await world.running()
    with pytest.raises(Denied) as caught:
        await world.svc.handback("stage-1", world.op, accept_as_intervention=False)
    assert caught.value.code == "state"


# --- switching the run sheet -------------------------------------------------------------------


async def test_stage_running_switches_to_a_new_version_with_new_rights_and_effective_time(world):
    await world.running()
    old = world.svc.stage("stage-1")
    world.clock.advance(3600)
    new_sheet = world.sheet(version=2, duration_seconds=3 * 86400)
    runtime = await world.svc.switch_run_sheet("stage-1", new_sheet, world.op)
    assert runtime.state.value == "running"
    assert runtime.run_sheet.version == 2
    assert runtime.right_number != old.right_number and runtime.care_right != old.care_right
    assert old.right_number in handed(world) and old.care_right in handed(world)
    assert world.control.rights[runtime.right_number].run_sheet_digest == new_sheet.digest()
    first, second = world.svc.approvals("stage-1")
    assert first.voided_at is not None and first.run_sheet_version == 1
    assert second.voided_at is None and second.run_sheet_digest == new_sheet.digest()
    switched = [row for row in world.svc.history("stage-1") if row["event"] == "switch_run_sheet"]
    assert switched[0]["at"] == world.clock.now()
    assert switched[0]["detail"]["version"] == 2


async def test_stage_switch_keeps_a_paused_stage_paused(world):
    await world.running()
    await world.svc.pause_stage("stage-1", world.op, "review")
    runtime = await world.svc.switch_run_sheet("stage-1", world.sheet(version=2), world.op)
    assert runtime.state.value == "paused" and runtime.right_number is None
    assert runtime.run_sheet.version == 2


async def test_stage_switch_needs_a_newer_version_and_recent_reauth(world):
    await world.running()
    with pytest.raises(Denied) as caught:
        await world.svc.switch_run_sheet("stage-1", world.sheet(version=1), world.op)
    assert caught.value.code == "state"
    stale = world.op.model_copy(update={"reauth_at": world.clock.now() - REAUTH_SECONDS - 1})
    with pytest.raises(Denied) as caught:
        await world.svc.switch_run_sheet("stage-1", world.sheet(version=2), stale)
    assert caught.value.code == "reauth_required"


async def test_stage_switch_to_a_sheet_with_a_safety_conflict_is_denied(world):
    await world.running()
    world.control.conflicts = ("conflict",)
    with pytest.raises(Denied) as caught:
        await world.svc.switch_run_sheet("stage-1", world.sheet(version=2), world.op)
    assert caught.value.code == "safety_conflict"
    assert world.svc.stage("stage-1").run_sheet.version == 1


async def test_stage_switch_for_another_stage_is_denied(world):
    await world.running()
    with pytest.raises(Denied) as caught:
        await world.svc.switch_run_sheet("stage-1", world.sheet("stage-9", version=2), world.op)
    assert caught.value.code == "state"


# --- stop and revoke ---------------------------------------------------------------------------


async def test_stage_operator_stop_hands_over_the_stage_right(world):
    await world.running()
    before = world.svc.stage("stage-1")
    runtime = await world.svc.stop_stage("stage-1", world.op)
    assert runtime.state.value == "stopped"
    assert runtime.right_number is None
    assert before.right_number in handed(world)


@pytest.mark.parametrize("how", ["pause", "takeover"])
async def test_stage_stop_from_paused_or_manual(world, how):
    await world.running()
    if how == "pause":
        await world.svc.pause_stage("stage-1", world.op, "x")
    else:
        await world.svc.takeover("stage-1", world.op)
    manual = world.svc.stage("stage-1").manual_right
    runtime = await world.svc.stop_stage("stage-1", world.op)
    assert runtime.state.value == "stopped" and runtime.manual_right is None
    if manual is not None:
        assert manual in handed(world)


async def test_stage_stop_from_pending_review(world):
    await world.pending()
    runtime = await world.svc.stop_stage("stage-1", world.op)
    assert runtime.state.value == "stopped"


async def test_stage_stop_of_a_stopped_stage_is_denied(world):
    await world.running()
    await world.svc.stop_stage("stage-1", world.op)
    with pytest.raises(Denied) as caught:
        await world.svc.stop_stage("stage-1", world.op)
    assert caught.value.code == "state"


async def test_stage_revoking_the_approval_of_a_pending_stage_stops_it(world):
    await world.approved()
    world.svc.revoke_approval("stage-1", world.op)
    assert world.state() == "stopped"
    assert world.svc.approvals("stage-1")[0].voided_at is not None


async def test_stage_revoke_needs_an_operator(world):
    await world.approved()
    with pytest.raises(Denied) as caught:
        world.svc.revoke_approval("stage-1", world.actor("model"))
    assert caught.value.code == "model_role"


async def test_stage_revoke_of_a_running_stage_must_go_through_stop(world):
    await world.running()
    with pytest.raises(Denied) as caught:
        world.svc.revoke_approval("stage-1", world.op)
    assert caught.value.code == "state"
    assert world.state() == "running"


async def test_stage_history_records_every_transition_in_order(world):
    await world.running()
    await world.svc.pause_stage("stage-1", world.op, "x")
    await world.svc.resume_stage("stage-1", world.op)
    assert moves(world) == [
        ("pending_review", "running"),
        ("running", "paused"),
        ("paused", "running"),
    ]
