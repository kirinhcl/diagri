"""``read_round_history``: a model reads one round of its own project, and nothing of another's."""

import json

from test_dispatch_researcher import (
    _deps_with_confirmatory_runs,
    _payload,
    _publish,
    _registry,
    _rounds,
    _to_analysis,
)

from growbridge.agents.memory import build_history
from growbridge.agents.memory_rounds import load_report
from growbridge.agents.memory_sources import MemorySources
from growbridge.agents.tools import ROLE_TOOLS
from growbridge.workflow.states import RoundState

TOOL = "read_round_history"


def memory(env, holdout=None) -> MemorySources:
    return MemorySources(
        workflow=env.workflow,
        archive=env.archive,
        book=None,
        notes=None,
        holdout=holdout,
        clock=env.clock,
        timezone="UTC",
        device_id=None,
        multi_user=False,
    )


async def test_reads_a_round_of_its_own_project(env):
    deps = env.make_deps(memory=memory(env))

    outcome = await env.invoke("planner", TOOL, deps, round_id=env.round_id)

    body = json.loads(outcome.content)
    assert not outcome.is_error and body["round_id"] == env.round_id
    assert body["report"] is None and body["decisions"] == []
    assert isinstance(body["episodes"], list)


async def test_other_project_round_reads_as_unknown(env):
    _, theirs = env.other_project()
    deps = env.make_deps(memory=memory(env))

    seen = await env.invoke("planner", TOOL, deps, round_id=theirs)
    absent = await env.invoke("planner", TOOL, deps, round_id="round-nowhere")

    assert seen.is_error and absent.is_error
    assert seen.content.replace(theirs, "<id>") == absent.content.replace("round-nowhere", "<id>")


async def test_every_role_has_the_tool(env):
    deps = env.make_deps(memory=memory(env))

    for role, built in env.tools(deps).items():
        assert TOOL in ROLE_TOOLS[role] and TOOL in {tool.name for tool in built}


async def test_outside_a_dispatch_it_is_refused(env):
    deps = env.make_deps(memory=memory(env))

    outcome = await env.invoke_unbound("planner", TOOL, deps, round_id=env.round_id)

    assert outcome.is_error and "no task is running" in outcome.content


async def test_without_memory_it_says_so(env):
    outcome = await env.invoke("planner", TOOL, env.make_deps(), round_id=env.round_id)

    assert outcome.is_error and "history is not available" in outcome.content


async def test_held_out_round_through_tool_and_context(env, tmp_path):
    registry = _registry(env)
    mem = memory(env, holdout=registry)
    rounds = _rounds(env, holdout=registry)
    _to_analysis(env)
    deps = _deps_with_confirmatory_runs(env, rounds, tmp_path, holdout=registry, memory=mem)
    read = {"holdout_id": "hold-1", "model_sha": "model-sha"}
    held = env.task("researcher")
    await _publish(env, held.id, rounds, deps, round_id=env.round_id, **read)
    assert env.workflow.round_state(env.round_id) is RoundState.DELIVERED
    plain = _payload(await _publish(env, env.task("researcher", "ev-2").id, rounds, deps))

    tool = json.loads((await env.invoke("planner", TOOL, deps, round_id=env.round_id)).content)
    (summary,) = build_history(mem, env.project_id, ())["rounds"]

    for shown in (tool["report"], summary["report"]):
        assert set(shown) == {"held_out", "label"} and shown["held_out"] is True
    assert "effect" not in json.dumps(tool) and "p_value" not in json.dumps(summary)
    downgrade, body = load_report(mem, env.project_id, plain["artifact_id"])
    assert downgrade is None and body["estimate"]["effect"] is not None
