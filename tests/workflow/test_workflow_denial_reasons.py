"""Every refusal of the workflow service carries a registered reason and the params the console
builds its text from; the coarse code and the English message stay as they were."""

import pytest
from test_workflow_reconcile import unknown_action

from growbridge.archive.models import Channel
from growbridge.ports import Denied, Difference, Finding
from growbridge.workflow.states import StageState
from growbridge.workflow.store import Plan

TWO = ("vegetative", "flowering")


async def refused(call, code: str) -> Denied:
    with pytest.raises(Denied) as exc:
        await call
    assert exc.value.code == code
    return exc.value


def refused_now(call, code: str) -> Denied:
    with pytest.raises(Denied) as exc:
        call()
    assert exc.value.code == code
    return exc.value


# --- design ----------------------------------------------------------------------------------


def test_project_name_required_carries_no_params(world):
    exc = refused_now(lambda: world.svc.create_project("  ", world.op), "state")
    assert exc.reason == "project_name_required" and exc.params == {}


async def test_record_not_found_carries_the_kind_and_id_of_the_missing_project(world):
    from growbridge.sim.fixtures import make_protocol

    protocol = make_protocol(project_id="nowhere")
    exc = refused_now(lambda: world.svc.save_protocol(protocol, world.op), "state")
    assert exc.reason == "record_not_found"
    assert exc.params == {"record_kind": "project", "record_id": "nowhere"}


async def test_protocol_version_exists_carries_the_protocol_and_version(world):
    from growbridge.sim.fixtures import make_protocol

    await world.design()
    changed = make_protocol(project_id=world.project_id, question="another question")
    exc = refused_now(lambda: world.svc.save_protocol(changed, world.op), "state")
    assert exc.reason == "protocol_version_exists"
    assert exc.params == {"protocol_id": "protocol-1", "version": 1}


async def test_protocol_not_found_carries_the_protocol_and_project(world):
    project = world.svc.create_project("p", world.op)
    exc = refused_now(lambda: world.svc.create_round(project, "ghost", world.op), "state")
    assert exc.reason == "protocol_not_found"
    assert exc.params == {"protocol_id": "ghost", "project_id": project}


async def test_drafter_only_carries_the_drafting_role(world):
    await world.design()
    model = world.actor("model")
    exc = refused_now(
        lambda: world.svc.submit_run_sheet(world.round_id, world.sheet(), model), "model_role"
    )
    assert exc.reason == "drafter_only" and exc.params == {"role": "planner"}


async def test_round_not_accepting_run_sheets_carries_the_round_and_its_state(world):
    await world.design()
    await world.svc.abort_round(world.round_id, world.op)
    exc = refused_now(
        lambda: world.svc.submit_run_sheet(world.round_id, world.sheet(), world.op), "state"
    )
    assert exc.reason == "round_not_accepting_run_sheets"
    assert exc.params == {"round_id": world.round_id, "state": "aborted"}


@pytest.mark.parametrize(
    ("fields", "kind"),
    [({"protocol_id": "other"}, "protocol"), ({"project_id": "other"}, "project")],
)
async def test_run_sheet_mismatch_carries_the_sheet_and_the_differing_kind(world, fields, kind):
    await world.design()
    sheet = world.sheet(**fields)
    exc = refused_now(lambda: world.svc.submit_run_sheet(world.round_id, sheet, world.op), "state")
    assert exc.reason == "run_sheet_mismatch"
    assert exc.params == {"run_sheet_id": sheet.id, "record_kind": kind}


async def test_not_this_project_carries_the_project_of_the_run_sheet(world):
    from growbridge.sim.fixtures import make_protocol, make_run_sheet

    await world.pending("stage-1")
    project = world.svc.create_project("other", world.op)
    world.svc.save_protocol(make_protocol(project_id=project, id="protocol-2"), world.op)
    round_id = world.svc.create_round(project, "protocol-2", world.op)
    sheet = make_run_sheet(
        id="sheet-x",
        project_id=project,
        protocol_id="protocol-2",
        stage_id="stage-x",
        experiment_id="experiment-stage-1",
    )
    exc = refused_now(lambda: world.svc.submit_run_sheet(round_id, sheet, world.op), "scope")
    assert exc.reason == "not_this_project" and exc.params == {"project_id": project}


async def test_run_sheet_version_in_use_carries_the_sheet_and_version(world):
    await world.pending("stage-1")
    reused = world.sheet("stage-x", id="sheet-stage-1")
    exc = refused_now(lambda: world.svc.submit_run_sheet(world.round_id, reused, world.op), "state")
    assert exc.reason == "run_sheet_version_in_use"
    assert exc.params == {"run_sheet_id": "sheet-stage-1", "version": 1}


async def test_run_sheet_version_conflict_carries_the_sheet_and_version(world):
    await world.pending("stage-1")
    other = world.sheet("stage-1", duration_seconds=3 * 86400)
    exc = refused_now(lambda: world.svc.submit_run_sheet(world.round_id, other, world.op), "state")
    assert exc.reason == "run_sheet_version_conflict"
    assert exc.params == {"run_sheet_id": "sheet-stage-1", "version": 1}


async def test_run_sheet_too_old_carries_both_versions(world):
    await world.pending("stage-1")
    world.svc.submit_run_sheet(world.round_id, world.sheet("stage-1", version=2), world.op)
    old = world.sheet("stage-1", version=1, duration_seconds=3 * 86400)
    exc = refused_now(lambda: world.svc.submit_run_sheet(world.round_id, old, world.op), "state")
    assert exc.reason == "run_sheet_too_old"
    assert exc.params == {"run_sheet_id": "sheet-stage-1", "version": 1, "current_version": 2}


async def test_run_sheet_needs_switch_carries_the_stage_and_its_state(world):
    await world.design(TWO)
    await world.approved("stage-1")
    world.svc.revoke_approval("stage-1", world.op)
    await world.svc.choose_after_stop(world.round_id, "redo", world.op)
    sheet = world.sheet("stage-1", version=2)
    exc = refused_now(lambda: world.svc.submit_run_sheet(world.round_id, sheet, world.op), "state")
    assert exc.reason == "run_sheet_needs_switch"
    assert exc.params == {"stage_id": "stage-1", "state": "stopped"}


# --- approval --------------------------------------------------------------------------------


async def test_stage_not_awaiting_approval_carries_the_stage_and_its_state(world):
    await world.running()
    exc = refused_now(lambda: world.svc.approve("stage-1", world.op), "state")
    assert exc.reason == "stage_not_awaiting_approval"
    assert exc.params == {"stage_id": "stage-1", "state": "running"}


async def test_run_sheet_changed_since_review_carries_both_digests(world):
    await world.pending()
    exc = refused_now(lambda: world.svc.approve("stage-1", world.op, "stale-digest"), "state")
    assert exc.reason == "run_sheet_changed_since_review"
    assert exc.params == {
        "stage_id": "stage-1",
        "expected_digest": "stale-digest",
        "current_digest": world.sheet().digest(),
    }


async def test_approval_blocking_findings_carries_the_number_of_findings(world):
    await world.pending()
    block = Finding(code="rule_conflict", message="two rules fight")
    world.svc.validate = lambda _sheet: (block, block)
    exc = refused_now(lambda: world.svc.approve("stage-1", world.op), "approval_invalid")
    assert exc.reason == "approval_blocking_findings"
    assert exc.params == {"stage_id": "stage-1", "count": 2}


async def test_approval_none_valid_carries_the_stage(world):
    await world.pending()
    exc = await refused(world.svc.start_stage("stage-1", world.op), "approval_invalid")
    assert exc.reason == "approval_none_valid" and exc.params == {"stage_id": "stage-1"}


async def test_capabilities_changed_carries_the_stage_and_the_original_sentence(world):
    await world.approved()
    world.control.capability_version = "caps-2"
    exc = await refused(world.svc.start_stage("stage-1", world.op), "approval_invalid")
    assert exc.reason == "capabilities_changed"
    assert exc.params == {"stage_id": "stage-1", "detail": "device capabilities changed"}


async def test_approval_recovery_changed_carries_the_stage(world):
    await world.approved()
    world.control.bump_recovery("host changed")
    exc = await refused(world.svc.start_stage("stage-1", world.op), "approval_invalid")
    assert exc.reason == "approval_recovery_changed" and exc.params == {"stage_id": "stage-1"}


async def test_approval_run_sheet_changed_carries_the_stage(world):
    await world.approved()
    stage = world.svc.store.stage("stage-1")
    approval = world.svc.store.valid_approval("stage-1")
    changed = world.sheet(duration_seconds=3 * 86400)
    problem = world.svc._approval_problem(approval, stage, changed)
    assert problem.reason == "approval_run_sheet_changed"
    assert problem.code == "approval_invalid" and problem.params == {"stage_id": "stage-1"}


async def test_approval_other_target_carries_the_stage(world):
    await world.approved()
    stage = world.svc.store.stage("stage-1")
    approval = world.svc.store.valid_approval("stage-1").model_copy(update={"device_id": "other"})
    problem = world.svc._approval_problem(approval, stage, world.sheet())
    assert problem.reason == "approval_other_target"
    assert problem.code == "approval_invalid" and problem.params == {"stage_id": "stage-1"}


# --- stage control ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reason", "state", "act"),
    [
        ("stage_not_pausable", "pending_review", lambda w: w.svc.pause_stage("stage-1", w.op, "x")),
        ("stage_not_resumable", "pending_review", lambda w: w.svc.resume_stage("stage-1", w.op)),
        ("stage_not_takeoverable", "pending_review", lambda w: w.svc.takeover("stage-1", w.op)),
        (
            "stage_not_in_manual",
            "pending_review",
            lambda w: w.svc.handback("stage-1", w.op, accept_as_intervention=False),
        ),
        (
            "stage_not_switchable",
            "pending_review",
            lambda w: w.svc.switch_run_sheet("stage-1", w.sheet(version=2), w.op),
        ),
    ],
)
async def test_stage_state_reasons_carry_the_stage_and_its_state(world, reason, state, act):
    await world.pending()
    exc = await refused(act(world), "state")
    assert exc.reason == reason and exc.params == {"stage_id": "stage-1", "state": state}


async def test_stage_not_startable_carries_the_stage_and_its_state(world):
    await world.approved()
    world.svc.revoke_approval("stage-1", world.op)
    exc = await refused(world.svc.start_stage("stage-1", world.op), "state")
    assert exc.reason == "stage_not_startable"
    assert exc.params == {"stage_id": "stage-1", "state": "stopped"}


async def test_stage_already_ended_carries_the_stage_and_its_state(world):
    await world.running()
    await world.svc.stop_stage("stage-1", world.op)
    exc = await refused(world.svc.stop_stage("stage-1", world.op), "state")
    assert exc.reason == "stage_already_ended"
    assert exc.params == {"stage_id": "stage-1", "state": "stopped"}


async def test_safety_conflict_carries_the_stage(world):
    await world.approved()
    world.control.conflicts = ("overheat-light-off acts on light",)
    exc = await refused(world.svc.start_stage("stage-1", world.op), "safety_conflict")
    assert exc.reason == "safety_conflict" and exc.params == {"stage_id": "stage-1"}


async def test_pump_unconfirmed_carries_the_device(world):
    await world.approved()
    world.control.interlock = True
    exc = await refused(world.svc.start_stage("stage-1", world.op), "interlock")
    assert exc.reason == "pump_unconfirmed"
    assert exc.params == {"device_id": world.sheet().device_id}


async def test_device_busy_carries_the_stage_the_device_and_the_other_stage(world):
    await world.approved("stage-1")
    await world.approved("stage-2")
    await world.svc.start_stage("stage-1", world.op)
    exc = await refused(world.svc.start_stage("stage-2", world.op), "state")
    assert exc.reason == "device_busy"
    assert exc.params == {
        "stage_id": "stage-2",
        "device_id": world.sheet().device_id,
        "other_stage_id": "stage-1",
    }


async def test_unsettled_actions_carries_the_stage_and_the_number_of_actions(world, control):
    await world.running()
    await world.svc.pause_stage("stage-1", world.op, "check")
    control.unsettled = (unknown_action(world),)
    exc = await refused(world.svc.resume_stage("stage-1", world.op), "state")
    assert exc.reason == "unsettled_actions"
    assert exc.params == {"stage_id": "stage-1", "count": 1}


async def test_device_differs_from_run_sheet_carries_channels_and_structured_diffs(world):
    await world.running()
    await world.svc.pause_stage("stage-1", world.op, "check")
    world.control.diffs = (Difference(channel=Channel.LIGHT, field="level", expected=60, actual=0),)
    exc = await refused(world.svc.resume_stage("stage-1", world.op), "state")
    assert exc.reason == "device_differs_from_run_sheet"
    assert exc.params == {
        "stage_id": "stage-1",
        "channels": ["light"],
        "diffs": [{"channel": "light", "field": "level", "expected": 60, "actual": 0}],
    }
    assert str(exc) == "device differs from the run sheet: light.level 60 != 0"


async def test_stage_changed_concurrently_carries_the_stage(world):
    await world.running()
    stale = world.svc.store.stage("stage-1")
    world.svc.store.update_stage(stale, paused_at=1.0)
    plan = Plan(StageState.PAUSED, "pause")
    exc = refused_now(lambda: world.svc._commit(stale, plan, None, {}), "state")
    assert exc.reason == "stage_changed_concurrently" and exc.params == {"stage_id": "stage-1"}


# --- rounds ----------------------------------------------------------------------------------


async def test_no_choice_pending_carries_the_round(world):
    await world.design()
    exc = await refused(world.svc.choose_after_stop(world.round_id, "redo", world.op), "state")
    assert exc.reason == "no_choice_pending" and exc.params == {"round_id": world.round_id}


async def test_no_next_stage_carries_the_round(world):
    await world.running()
    await world.svc.stop_stage("stage-1", world.op)
    exc = await refused(world.svc.choose_after_stop(world.round_id, "next", world.op), "state")
    assert exc.reason == "no_next_stage" and exc.params == {"round_id": world.round_id}


async def test_unknown_choice_carries_the_choice(world):
    await world.running()
    await world.svc.stop_stage("stage-1", world.op)
    exc = await refused(world.svc.choose_after_stop(world.round_id, "bogus", world.op), "state")
    assert exc.reason == "unknown_choice" and exc.params == {"choice": "bogus"}


async def test_round_already_ended_carries_the_round_and_its_state(world):
    await world.design()
    await world.svc.abort_round(world.round_id, world.op)
    exc = await refused(world.svc.abort_round(world.round_id, world.op), "state")
    assert exc.reason == "round_already_ended"
    assert exc.params == {"round_id": world.round_id, "state": "aborted"}
