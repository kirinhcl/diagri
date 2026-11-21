"""A planner's sheet names only its own project: another project's protocol never surfaces."""

import pytest

from growbridge.archive.models import Allocation, Treatment
from growbridge.sim.fixtures import make_protocol

# Project Q's treatments use names and ids no other project uses, and round 1 is allocated a
# light level the standard sheet (light 70) does not apply: any check against Q's protocol names
# them in a ``treatment_not_applied`` finding.
Q_TREATMENTS = (
    Treatment(id="q-shade", name="Q-only shade 20 %", factors={"light": 20}),
    Treatment(id="q-flood", name="Q-only flood 90 %", factors={"light": 90}),
)
Q_MARKS = ("q-shade", "q-flood", "Q-only")


@pytest.fixture
def project_q(env) -> str:
    """A second project with protocol ``protocol-q``, whose round 1 is allocated ``q-flood``."""
    project_id = env.workflow.create_project("other", env.operator)
    protocol = make_protocol(
        project_id=project_id,
        id="protocol-q",
        treatments=Q_TREATMENTS,
        control_treatment_id="q-shade",
        allocations=(
            Allocation(round=1, block=1, unit="tent-1", treatment_id="q-flood"),
            Allocation(round=2, block=1, unit="tent-1", treatment_id="q-shade"),
            Allocation(round=3, block=2, unit="tent-1", treatment_id="q-shade"),
            Allocation(round=4, block=2, unit="tent-1", treatment_id="q-flood"),
        ),
    )
    env.workflow.save_protocol(protocol, env.operator)
    return project_id


def _leaks(content: str) -> list[str]:
    return [mark for mark in Q_MARKS if mark in content]


async def test_the_owning_projects_planner_sees_its_treatment_finding(env, project_q):
    """The control: Q's protocol does produce a finding naming Q's treatment, for Q."""
    round_q = env.workflow.create_round(project_q, "protocol-q", env.operator)
    planner_q = env.task_in(project_q, "planner", "ev-planner-q")
    sheet = env.sheet_json(stage_id="stage-q", project_id=project_q, protocol_id="protocol-q")

    outcome = await env.invoke_as(
        planner_q.id, "planner", "validate_run_sheet", round_id=round_q, run_sheet=sheet
    )

    assert "treatment_not_applied" in outcome.content and "Q-only flood" in outcome.content


async def test_a_draft_whose_sheet_names_another_project_is_refused(env, project_q):
    planner = env.task("planner", "ev-planner")
    sheet = env.sheet_json(stage_id="stage-q", project_id=project_q, protocol_id="protocol-q")

    exc = await env.refusal(
        "planner", "save_plan_draft", bound=planner.id, round_id=env.round_id, run_sheet=sheet
    )

    assert (exc.code, exc.reason) == ("scope", "not_this_project")
    assert exc.params == {"project_id": project_q}


async def test_a_refused_foreign_draft_names_none_of_the_other_projects_treatments(env, project_q):
    planner = env.task("planner", "ev-planner")
    sheet = env.sheet_json(stage_id="stage-q", project_id=project_q, protocol_id="protocol-q")

    outcome = await env.invoke_as(
        planner.id, "planner", "save_plan_draft", round_id=env.round_id, run_sheet=sheet
    )

    assert outcome.is_error and "denied (scope)" in outcome.content
    assert _leaks(outcome.content) == []
    assert env.workflow.store.find_stage("stage-q") is None


@pytest.mark.parametrize("name", ["save_plan_draft", "validate_run_sheet"])
async def test_a_sheet_naming_another_projects_protocol_gets_no_finding_on_it(env, project_q, name):
    """The sheet is this project's, but its protocol is Q's: that protocol reads as unknown."""
    planner = env.task("planner", "ev-planner")
    sheet = env.sheet_json(stage_id="stage-q", protocol_id="protocol-q")

    outcome = await env.invoke_as(
        planner.id, "planner", name, round_id=env.round_id, run_sheet=sheet
    )

    assert _leaks(outcome.content) == []
    assert env.workflow.store.find_stage("stage-q") is None
