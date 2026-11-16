from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from growbridge.agents.roles import AUDITOR, INTENTS, ORCHESTRATOR, PLANNER, RESEARCHER, Handoff
from growbridge.agents.tools import CONTROL_TOOLS, ROLE_TOOLS
from growbridge.archive.models import Budget


def handoff(**over) -> Handoff:
    fields = dict(
        goal="compare blue light fractions",
        constraints=("no new hardware",),
        evidence_refs=("artifact:a1",),
        expected_artifacts=("plan_draft",),
        budget=Budget(max_calls=10, max_cost=2.0),
        parent_task_id="task-1",
        trigger_event_id="evt-1",
        correlation_id="corr-1",
    )
    return Handoff(**{**fields, **over})


def test_four_roles_named_after_their_tool_sets():
    assert {r.name for r in (ORCHESTRATOR, PLANNER, RESEARCHER, AUDITOR)} == set(ROLE_TOOLS)


@pytest.mark.parametrize("role", [ORCHESTRATOR, PLANNER, RESEARCHER, AUDITOR])
def test_prompt_states_duties_limits_and_data_rule(role):
    prompt = role.system.lower()
    assert "data" in prompt and "instruction" in prompt
    assert "approv" in prompt  # chat messages never count as approval
    assert not any(name in role.system for name in CONTROL_TOOLS)


def test_intents_are_the_five_from_the_spec():
    assert set(INTENTS) == {
        "new_goal",
        "design_change",
        "run_query",
        "anomaly",
        "result_analysis",
    }


def test_handoff_is_frozen_and_closed():
    item = handoff()
    with pytest.raises(ValidationError):
        item.goal = "other"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        handoff(unknown_field=1)


def test_handoff_requires_trigger_and_correlation_ids():
    with pytest.raises(ValidationError):
        Handoff(goal="g", budget=Budget(max_calls=1, max_cost=1.0))  # type: ignore[call-arg]


def test_handoff_renders_as_json_user_message_with_every_field():
    payload = json.loads(handoff().as_user_message())
    assert payload["trigger_event_id"] == "evt-1" and payload["correlation_id"] == "corr-1"
    assert payload["budget"]["max_calls"] == 10
    assert payload["parent_task_id"] == "task-1"


def test_the_auditor_prompt_points_to_the_tools_that_hold_history_and_interventions():
    lines = " ".join(AUDITOR.system.split())

    assert "get_run_status for the stage's history" in lines
    assert "inspect_stage_data for the data's coverage, gaps and intervention counts" in lines
    assert "get_stage_records for the run sheet, the manual tasks and their records" in lines
