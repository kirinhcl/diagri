import asyncio
import json

import pytest
from dispatch_helpers import call, script_calls

from growbridge.agents.llm import ModelReply
from growbridge.archive.models import Budget
from growbridge.sim.llm import ScriptedClient, text_reply, tool_reply
from growbridge.workflow.states import StageState, TaskState


class FailingClient:
    def __init__(self, error: Exception):
        self.error = error
        self.calls = 0

    async def create(self, **_kwargs) -> ModelReply:
        self.calls += 1
        raise self.error


def _reason(env, task_id: str) -> str:
    rows = env.db.query("SELECT reason FROM task_events WHERE task_id = ?", (task_id,))
    return rows[-1]["reason"]


@pytest.mark.parametrize("role", ["orchestrator", "planner", "researcher"])
async def test_a_normal_end_completes_the_task(env, role):
    env.task(role)
    client = ScriptedClient([text_reply("all good")])

    run = await env.dispatcher(client).run_task("task-ev-1")

    assert run is not None and run.text == "all good"
    assert env.tasks.get("task-ev-1").state is TaskState.DONE


async def test_the_user_message_carries_the_task_as_data(env):
    env.task(
        "planner",
        constraints=("no pump",),
        input_refs=("card-1",),
        expected_artifacts=("run_sheet",),
    )
    client = ScriptedClient([text_reply("ok")])

    await env.dispatcher(client).run_task("task-ev-1")

    request = client.requests[0]
    message = request["messages"][0]["content"]
    data = json.loads(message[message.index("{") :])
    assert data["task_id"] == "task-ev-1"
    assert data["goal"] == "does more light speed up canopy growth?"
    assert data["constraints"] == ["no pump"]
    assert data["evidence_refs"] == ["card-1"]
    assert data["expected_artifacts"] == ["run_sheet"]
    assert data["trigger_event_id"] == "ev-1" and data["correlation_id"] == "corr-1"
    assert "planning agent" in request["system"]
    assert "save_plan_draft" in {t["name"] for t in request["tools"]}


async def test_the_same_trigger_is_handled_once(env):
    env.task("planner")
    client = ScriptedClient([text_reply("first"), text_reply("second")])
    dispatcher = env.dispatcher(client)

    first = await dispatcher.run_task("task-ev-1")
    second = await dispatcher.run_task("task-ev-1")

    assert first is not None and second is None
    assert len(client.requests) == 1


async def test_two_concurrent_dispatches_run_the_model_once(env):
    env.task("planner")
    client = ScriptedClient([text_reply("first"), text_reply("second")])
    dispatcher = env.dispatcher(client)

    results = await asyncio.gather(
        dispatcher.run_task("task-ev-1"), dispatcher.run_task("task-ev-1")
    )

    assert sorted(r is None for r in results) == [False, True]
    assert len(client.requests) == 1


async def test_a_task_that_is_not_in_progress_is_ignored(env):
    env.task("planner")
    env.tasks.transition("task-ev-1", TaskState.NEEDS_ATTENTION, "e-1", "operator hold")
    client = ScriptedClient([text_reply("x")])

    assert await env.dispatcher(client).run_task("task-ev-1") is None
    assert client.requests == []


@pytest.mark.parametrize("owner", ["executor", "observer", "operator"])
async def test_a_task_owned_by_a_non_model_role_is_ignored(env, owner):
    env.task(owner)
    client = ScriptedClient([text_reply("x")])

    assert await env.dispatcher(client).run_task("task-ev-1") is None
    assert client.requests == [] and env.tasks.get("task-ev-1").state is TaskState.IN_PROGRESS


async def test_an_unknown_task_is_ignored(env):
    client = ScriptedClient([text_reply("x")])

    assert await env.dispatcher(client).run_task("task-nope") is None
    assert client.requests == []


async def test_model_failure_sends_the_task_to_needs_attention_with_the_reason(env):
    env.task("planner")
    env.task("researcher", "ev-2")
    client = FailingClient(ConnectionError("api unreachable"))

    run = await env.dispatcher(client).run_task("task-ev-1")

    assert run is None
    assert env.tasks.get("task-ev-1").state is TaskState.NEEDS_ATTENTION
    assert "api unreachable" in _reason(env, "task-ev-1")
    assert env.tasks.get("task-ev-2").state is TaskState.IN_PROGRESS  # nothing else is affected
    assert env.workflow.store.find_stage("stage-1") is None


async def test_budget_exhaustion_sends_the_task_to_needs_attention(env):
    env.budget.set(env.project_id, Budget(max_calls=1, max_cost=50.0))
    env.task("planner")
    client = ScriptedClient(
        [tool_reply(call("get_device_capabilities")), text_reply("never reached")]
    )

    await env.dispatcher(client).run_task("task-ev-1")

    assert env.tasks.get("task-ev-1").state is TaskState.NEEDS_ATTENTION
    assert "budget" in _reason(env, "task-ev-1")
    assert len(client.requests) == 1


async def test_a_project_without_a_budget_never_reaches_the_model(env):
    env.task("planner")
    client = ScriptedClient([text_reply("x")])
    env.db.execute("DELETE FROM call_budget")

    await env.dispatcher(client).run_task("task-ev-1")

    assert client.requests == []
    assert env.tasks.get("task-ev-1").state is TaskState.NEEDS_ATTENTION


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
async def test_refusal_or_truncation_sends_the_task_to_needs_attention(env, stop):
    env.task("planner")
    client = ScriptedClient([ModelReply(stop_reason=stop, text="partial", content=[])])

    run = await env.dispatcher(client).run_task("task-ev-1")

    assert run is not None and run.stop_reason == stop
    assert env.tasks.get("task-ev-1").state is TaskState.NEEDS_ATTENTION
    assert stop in _reason(env, "task-ev-1")


async def test_running_out_of_turns_sends_the_task_to_needs_attention(env):
    env.task("planner")
    env.budget.set(env.project_id, Budget(max_calls=100, max_cost=50.0))
    looping = [tool_reply(call("get_device_capabilities", call_id=f"c{n}")) for n in range(30)]

    await env.dispatcher(ScriptedClient(looping)).run_task("task-ev-1")

    assert env.tasks.get("task-ev-1").state is TaskState.NEEDS_ATTENTION


async def test_a_task_moved_elsewhere_during_the_run_is_left_where_it_is(env):
    env.task("researcher")
    client = ScriptedClient(script_calls(call("get_compute_job", attempt_id="a")))
    original = client.create

    async def create_then_expire(**kwargs):
        reply = await original(**kwargs)
        if len(client.requests) == 2:
            env.tasks.transition("task-ev-1", TaskState.NEEDS_ATTENTION, "e-x", "deadline")
        return reply

    client.create = create_then_expire

    run = await env.dispatcher(client).run_task("task-ev-1")

    assert run is not None
    assert env.tasks.get("task-ev-1").state is TaskState.NEEDS_ATTENTION


async def test_a_dispatched_run_leaves_the_device_and_stages_alone(env):
    env.workflow.submit_run_sheet(env.round_id, env.sheet(), env.operator)
    env.task("orchestrator")
    client = ScriptedClient(
        script_calls(
            call("get_run_status", stage_id="stage-1"),
            call("approve_run_sheet", call_id="c2", stage_id="stage-1"),
        )
    )

    await env.dispatcher(client).run_task("task-ev-1")

    assert env.workflow.stage("stage-1").state is StageState.PENDING_REVIEW
    assert env.workflow.approvals("stage-1") == () and env.control.log == []


async def test_a_claimed_trigger_is_not_run_again_by_a_new_dispatcher(env):
    env.task("planner")
    first = ScriptedClient([text_reply("first")])
    await env.dispatcher(first).run_task("task-ev-1")
    second = ScriptedClient([text_reply("second")])

    again = await env.dispatcher(second).run_task("task-ev-1")

    assert again is None and second.requests == []


async def test_a_crash_after_the_claim_leaves_the_task_open_and_does_not_rerun(env):
    env.task("planner")
    crashing = FailingClient(KeyboardInterrupt())  # not an Exception: escapes like a crash
    with pytest.raises(KeyboardInterrupt):
        await env.dispatcher(crashing).run_task("task-ev-1")
    assert env.tasks.get("task-ev-1").state is TaskState.IN_PROGRESS
    restarted = ScriptedClient([text_reply("again")])

    assert await env.dispatcher(restarted).run_task("task-ev-1") is None
    assert restarted.requests == []
