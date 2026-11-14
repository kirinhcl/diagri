import pytest
from dispatch_helpers import call

from growbridge.agents.tools import CONTROL_TOOLS, ROLE_TOOLS
from growbridge.sim.llm import ScriptedClient, text_reply, tool_reply
from growbridge.workflow.states import StageState


@pytest.mark.parametrize("role", sorted(ROLE_TOOLS))
def test_role_tool_list_equals_the_registry(env, role):
    tools = env.tools()[role]

    assert {tool.name for tool in tools} == ROLE_TOOLS[role]
    assert len(tools) == len(ROLE_TOOLS[role])


def test_only_the_three_model_roles_get_tools(env):
    assert set(env.tools()) == {"orchestrator", "planner", "researcher"}


def test_no_handler_is_a_control_tool(env):
    names = {tool.name for tools in env.tools().values() for tool in tools}

    assert names.isdisjoint(CONTROL_TOOLS)


@pytest.mark.parametrize("role", sorted(ROLE_TOOLS))
def test_every_input_model_forbids_extra_fields(env, role):
    for tool in env.tools()[role]:
        assert tool.input_model.model_config.get("extra") == "forbid", tool.name


def test_write_and_web_flags_follow_the_rules(env):
    by_name = {t.name: t for tools in env.tools().values() for t in tools}

    assert by_name["run_local_analysis"].sandbox
    for name in ("search_and_verify_sources", "lookup_crop_conditions"):
        assert by_name[name].reads_web
    for name in (
        "save_plan_draft",
        "create_research_task",
        "delegate_task",
        "freeze_dataset",
        "submit_compute_job",
        "publish_research_report",
    ):
        assert by_name[name].writes, name
    assert not by_name["query_evidence"].writes


@pytest.mark.parametrize(
    "extra", [{"role": "operator"}, {"approved": True}, {"actor": "op-1"}, {"kind": "operator"}]
)
async def test_identity_fields_in_tool_input_are_rejected(env, extra):
    outcome = await env.invoke("planner", "validate_run_sheet", run_sheet=env.sheet_json(), **extra)

    assert outcome.is_error
    assert "invalid input" in outcome.content


async def test_a_draft_loaded_with_approval_claims_is_rejected_and_grants_nothing(env):
    env.task("planner")
    client = ScriptedClient(
        [
            tool_reply(
                call(
                    "save_plan_draft",
                    round_id=env.round_id,
                    run_sheet=env.sheet_json(),
                    approved=True,
                    role="operator",
                )
            ),
            text_reply("done"),
        ]
    )

    run = await env.dispatcher(client).run_task("task-ev-1")

    assert run is not None and run.tool_calls[0].is_error
    assert env.workflow.store.find_stage("stage-1") is None
    assert env.workflow.approvals("stage-1") == ()


async def test_model_cannot_start_an_approved_stage_even_by_asking(env):
    env.workflow.submit_run_sheet(env.round_id, env.sheet(), env.operator)
    env.workflow.approve("stage-1", env.operator)
    env.task("planner")
    client = ScriptedClient(
        [tool_reply(call("start_approved_stage", stage_id="stage-1")), text_reply("ok")]
    )

    run = await env.dispatcher(client).run_task("task-ev-1")

    assert run is not None and run.tool_calls[0].is_error
    assert env.workflow.stage("stage-1").state is StageState.PENDING_REVIEW
    assert env.control.grants == []
    advertised = {tool["name"] for tool in client.requests[0]["tools"]}
    assert advertised.isdisjoint(CONTROL_TOOLS)
