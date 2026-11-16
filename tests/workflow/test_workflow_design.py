import pytest

from growbridge.archive.models import RunSheet
from growbridge.ports import Denied, Finding
from growbridge.sim.fixtures import make_protocol
from growbridge.workflow.service import WorkflowService


def test_design_create_project_returns_an_id(world):
    project_id = world.svc.create_project("lettuce", world.op)
    assert project_id


def test_design_protocol_with_same_version_and_other_content_is_denied(world):
    project_id = world.svc.create_project("lettuce", world.op)
    world.svc.save_protocol(make_protocol(project_id=project_id), world.op)
    changed = make_protocol(project_id=project_id, question="a different question")
    with pytest.raises(Denied) as caught:
        world.svc.save_protocol(changed, world.op)
    assert caught.value.code == "state"


def test_design_protocol_with_same_content_is_idempotent_and_new_version_is_kept(world):
    project_id = world.svc.create_project("lettuce", world.op)
    first = make_protocol(project_id=project_id)
    assert world.svc.save_protocol(first, world.op) == first
    assert world.svc.save_protocol(first, world.op) == first
    second = make_protocol(project_id=project_id, version=2, question="revised")
    assert world.svc.save_protocol(second, world.op) == second


def test_design_round_needs_a_saved_protocol_of_the_same_project(world):
    project_id = world.svc.create_project("lettuce", world.op)
    other = world.svc.create_project("basil", world.op)
    world.svc.save_protocol(make_protocol(project_id=project_id), world.op)
    with pytest.raises(Denied) as caught:
        world.svc.create_round(project_id, "missing", world.op)
    assert caught.value.code == "state"
    with pytest.raises(Denied):
        world.svc.create_round(other, "protocol-1", world.op)


async def test_design_new_round_starts_in_designing(world):
    await world.design()
    assert world.round_state() == "designing"
    assert world.svc.active_stage() is None


async def test_round_designing_to_stage_review_when_first_run_sheet_is_submitted(world):
    await world.design()
    findings = world.svc.submit_run_sheet(world.round_id, world.sheet(), world.op)
    assert findings == ()
    assert world.round_state() == "stage_review"
    assert world.state() == "pending_review"


async def test_design_blocking_finding_keeps_the_round_in_designing(db, clock, control, world):
    blocking = Finding(code="rule_conflict", message="two rules fight over exhaust")
    warning = Finding(code="note", message="long stage", blocking=False)
    world.svc = WorkflowService(
        db, clock, control, validate=lambda sheet: (warning, blocking), check_treatments=False
    )
    await world.design()
    findings = world.svc.submit_run_sheet(world.round_id, world.sheet(), world.op)
    assert findings == (warning, blocking)
    assert world.round_state() == "designing"
    with pytest.raises(Denied):
        world.svc.stage("stage-1")


async def test_design_non_blocking_findings_do_not_stop_review(db, clock, control, world):
    warning = Finding(code="note", message="long stage", blocking=False)
    world.svc = WorkflowService(
        db, clock, control, validate=lambda sheet: (warning,), check_treatments=False
    )
    await world.design()
    assert world.svc.submit_run_sheet(world.round_id, world.sheet(), world.op) == (warning,)
    assert world.round_state() == "stage_review"


async def test_design_validator_sees_the_submitted_run_sheet(db, clock, control, world):
    seen: list[RunSheet] = []
    world.svc = WorkflowService(
        db, clock, control, validate=lambda s: seen.append(s) or (), check_treatments=False
    )
    await world.design()
    sheet = world.sheet()
    world.svc.submit_run_sheet(world.round_id, sheet, world.op)
    assert seen == [sheet]


async def test_design_run_sheet_of_another_project_is_denied(world):
    await world.design()
    foreign = world.sheet(project_id="somebody-else")
    with pytest.raises(Denied) as caught:
        world.svc.submit_run_sheet(world.round_id, foreign, world.op)
    assert caught.value.code == "state"


async def test_stage_pending_new_version_voids_the_approval_and_stays_pending(world):
    await world.approved()
    world.svc.submit_run_sheet(world.round_id, world.sheet(version=2), world.op)
    assert world.state() == "pending_review"
    (approval,) = world.svc.approvals("stage-1")
    assert approval.run_sheet_version == 1
    assert approval.voided_at is not None
    assert world.svc.stage("stage-1").run_sheet.version == 2


async def test_design_same_version_with_other_content_is_denied(world):
    await world.pending()
    changed = world.sheet(duration_seconds=3600)
    with pytest.raises(Denied) as caught:
        world.svc.submit_run_sheet(world.round_id, changed, world.op)
    assert caught.value.code == "state"


async def test_design_resubmitting_the_same_sheet_keeps_the_approval(world):
    await world.approved()
    world.svc.submit_run_sheet(world.round_id, world.sheet(), world.op)
    (approval,) = world.svc.approvals("stage-1")
    assert approval.voided_at is None


async def test_design_older_version_is_denied(world):
    await world.pending(version=2)
    with pytest.raises(Denied) as caught:
        world.svc.submit_run_sheet(world.round_id, world.sheet(version=1), world.op)
    assert caught.value.code == "state"


async def test_stage_pending_capability_change_voids_the_approval_on_revalidation(world):
    await world.approved()
    world.control.capability_version = "caps-2"
    findings = world.svc.revalidate("stage-1")
    assert findings == ()
    assert world.state() == "pending_review"
    (approval,) = world.svc.approvals("stage-1")
    assert approval.voided_at is not None


async def test_design_revalidation_keeps_a_still_valid_approval(world):
    await world.approved()
    world.svc.revalidate("stage-1")
    (approval,) = world.svc.approvals("stage-1")
    assert approval.voided_at is None


async def test_design_submit_is_denied_for_a_running_stage(world):
    await world.running()
    with pytest.raises(Denied) as caught:
        world.svc.submit_run_sheet(world.round_id, world.sheet(version=2), world.op)
    assert caught.value.code == "state"


async def test_design_state_survives_a_new_service_instance(world, db, clock, control):
    await world.running()
    again = WorkflowService(db, clock, control)
    assert again.stage("stage-1").state.value == "running"
    assert again.active_stage().stage_id == "stage-1"
