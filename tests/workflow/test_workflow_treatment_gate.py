"""Every save and approval path checks that a run sheet applies its round's treatment, and only
the planner among the model roles may file a run sheet."""

import pytest

from growbridge.archive.models import Channel, TimedAction, Treatment
from growbridge.ports import Actor, Denied
from growbridge.sim.fixtures import make_protocol
from growbridge.workflow.service import WorkflowService

# make_protocol allocates treatment "high" (light 70 %) to round 1; the fixture day runs at 60
HIGH = (
    TimedAction(id="light-on", channel=Channel.LIGHT, at="06:00", level=70),
    TimedAction(id="light-off", channel=Channel.LIGHT, at="22:00", level=0),
)


@pytest.fixture
def checked(world):
    world.svc = WorkflowService(world.db, world.clock, world.control)  # the default service
    return world


def codes(findings) -> list[tuple[str, bool]]:
    return [(finding.code, finding.blocking) for finding in findings]


async def test_a_sheet_that_skips_the_rounds_treatment_is_not_saved(checked):
    round_id = await checked.design()

    findings = checked.svc.submit_run_sheet(round_id, checked.sheet(), checked.op)

    assert ("treatment_not_applied", True) in codes(findings)
    assert checked.svc.store.find_stage("stage-1") is None


async def test_a_sheet_that_applies_the_rounds_treatment_is_saved(checked):
    round_id = await checked.design()

    findings = checked.svc.submit_run_sheet(round_id, checked.sheet(timed_actions=HIGH), checked.op)

    assert not any(finding.blocking for finding in findings)
    assert checked.svc.store.find_stage("stage-1") is not None


async def test_approval_refuses_a_saved_sheet_that_skips_the_treatment(world):
    world.svc = WorkflowService(world.db, world.clock, world.control, check_treatments=False)
    await world.pending()  # saved by a service that did not check, e.g. before this check existed
    checked = WorkflowService(world.db, world.clock, world.control)

    with pytest.raises(Denied) as denied:
        checked.approve("stage-1", world.op)

    assert denied.value.code == "approval_invalid"
    assert ("treatment_not_applied", True) in codes(checked.revalidate("stage-1"))


@pytest.mark.parametrize("role", ["orchestrator", "researcher", "analyst"])
async def test_a_model_role_other_than_the_planner_may_not_file_a_run_sheet(checked, role):
    round_id = await checked.design()
    sheet = checked.sheet(timed_actions=HIGH)

    with pytest.raises(Denied) as denied:
        checked.svc.submit_run_sheet(round_id, sheet, Actor(kind="model", id=role))

    assert denied.value.code == "model_role"
    assert checked.svc.store.find_stage("stage-1") is None


async def test_the_planner_may_file_a_run_sheet(checked):
    round_id = await checked.design()
    planner = Actor(kind="model", id="planner")

    findings = checked.svc.submit_run_sheet(round_id, checked.sheet(timed_actions=HIGH), planner)

    assert not any(finding.blocking for finding in findings)
    assert checked.svc.store.find_stage("stage-1") is not None


async def test_a_live_switch_to_a_sheet_of_another_protocol_is_refused(checked):
    """The treatment is the round's: a sheet naming another protocol, whose round 1 runs the
    fixture day's light 60, must not pass the check against that protocol instead."""
    await checked.running(timed_actions=HIGH)
    sixty = (
        Treatment(id="control", name="light 40 %", factors={"light": 40}),
        Treatment(id="high", name="light 60 %", factors={"light": 60}),
    )
    checked.svc.save_protocol(
        make_protocol(id="protocol-60", project_id=checked.project_id, treatments=sixty),
        checked.op,
    )
    sheet = checked.sheet(version=2, protocol_id="protocol-60")

    with pytest.raises(Denied):
        await checked.svc.switch_run_sheet("stage-1", sheet, checked.op)

    assert checked.svc.stage("stage-1").run_sheet.version == 1
