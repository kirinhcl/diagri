"""The orchestrator's project state names the active stage only when it belongs to that project:
another project's running stage stays out of this project's tool results and conversation."""

import json


async def _running_main_stage(env) -> str:
    env.workflow.submit_run_sheet(env.round_id, env.sheet("stage-1"), env.operator)
    env.workflow.approve("stage-1", env.operator)
    await env.workflow.start_stage("stage-1", env.operator)
    return "stage-1"


async def test_active_stage_of_other_project_is_hidden(env):
    await _running_main_stage(env)
    other, _ = env.other_project()
    bound = env.task_in(other, "orchestrator", "ev-other").id

    outcome = await env.invoke_as(bound, "orchestrator", "get_project_state", project_id=other)

    assert not outcome.is_error, outcome.content
    assert json.loads(outcome.content)["active_stage"] is None


async def test_active_stage_of_own_project_is_named(env):
    stage = await _running_main_stage(env)

    outcome = await env.invoke("orchestrator", "get_project_state", project_id=env.project_id)

    assert json.loads(outcome.content)["active_stage"] == stage
