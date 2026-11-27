import pytest
from dispatch_helpers import call, script_calls

from growbridge.agents.loop import AgentRun
from growbridge.agents.run_end import (
    RunInterrupted,
    end_of_denied,
    end_of_error,
    end_of_run,
)
from growbridge.config import RoleModel
from growbridge.ports import Denied
from growbridge.sim.llm import ScriptedClient, text_reply
from growbridge.workflow.states import TaskState


def _run(text: str = "ok", stop_reason: str = "end_turn") -> AgentRun:
    return AgentRun(
        text=text, stop_reason=stop_reason, turns=1, input_tokens=1, output_tokens=1, cost=0.0
    )


def test_end_of_run_matches_each_branch():
    stopped = end_of_run(_run(stop_reason="max_turns"), "planner", [], [])
    assert stopped.state is TaskState.NEEDS_ATTENTION
    assert stopped.code == "model_stopped"
    assert stopped.reason == "model stopped without finishing: max_turns"
    assert stopped.params == {"stop_reason": "max_turns"}

    silent = end_of_run(_run("which crop?"), "planner", [], [])
    assert silent.code == "undelivered" and silent.params == {"role": "planner"}
    assert silent.reason == "ended without saving a run sheet draft: which crop?"

    empty = end_of_run(_run(""), "researcher", [], [])
    assert empty.reason.endswith(": (no text)")

    done = end_of_run(_run(" fine "), "planner", [], ["save_plan_draft"])
    assert (done.state, done.reason, done.said, done.code) == (
        TaskState.DONE,
        "run finished",
        "fine",
        "run_finished",
    )
    assert end_of_run(_run(), "orchestrator", [], []).state is TaskState.DONE
    reviewed = end_of_run(_run(), "planner", [True], ["save_plan_draft"])
    assert reviewed.state is TaskState.NEEDS_REVIEW


def test_end_of_denied_keeps_the_whole_refusal():
    exc = Denied(
        "budget", "call budget exhausted for project p", reason="budget_calls_exhausted", params={}
    )
    end = end_of_denied(exc)
    assert end.code == "denied" and end.params == {"denied_code": "budget"}
    assert end.state is TaskState.NEEDS_ATTENTION
    assert end.reason == "budget: call budget exhausted for project p"
    assert end.denied == {
        "code": "budget",
        "message": "call budget exhausted for project p",
        "reason": "budget_calls_exhausted",
        "params": exc.params,
    }


def test_end_of_error_is_model_unavailable():
    end = end_of_error(ValueError("boom"))
    assert end.code == "model_unavailable" and end.denied is None
    assert end.reason == "model unavailable: ValueError: boom"


def _claims(env) -> int:
    return env.db.query("SELECT COUNT(*) AS n FROM dispatch_claims")[0]["n"]


async def test_replay_run_runs_a_finished_task_without_claiming_or_moving_it(env):
    env.task("planner")
    first = ScriptedClient(
        script_calls(call("save_plan_draft", round_id=env.round_id, run_sheet=env.sheet_json()))
    )
    dispatcher = env.dispatcher(first)
    await dispatcher.run_task("task-ev-1")
    state, claims = env.tasks.get("task-ev-1").state, _claims(env)
    assert state is not TaskState.IN_PROGRESS

    again = ScriptedClient([text_reply("looked again")])
    replayed = await dispatcher.replay_run("task-ev-1", again, lambda toolset: toolset)

    assert env.tasks.get("task-ev-1").state is state
    assert _claims(env) == claims
    assert replayed.end.code == "undelivered"
    assert replayed.user == dispatcher.message_for(env.tasks.get("task-ev-1"))


async def test_replay_run_reports_a_run_that_finishes(env):
    env.task("orchestrator")
    dispatcher = env.dispatcher(ScriptedClient([]))
    replayed = await dispatcher.replay_run(
        "task-ev-1", ScriptedClient([text_reply("fine")]), lambda toolset: toolset
    )
    assert replayed.end.code == "run_finished"
    assert env.tasks.get("task-ev-1").state is TaskState.IN_PROGRESS


async def test_replay_run_maps_a_refusal(env):
    env.task("planner")
    del env.roles["planner"]
    replayed = await env.dispatcher(None).replay_run("task-ev-1", None, lambda toolset: toolset)
    assert replayed.end.code == "denied"
    assert replayed.end.denied["reason"] == "no_model"


async def test_replay_run_lets_run_interrupted_through(env):
    env.task("orchestrator")

    class Stopping:
        async def create(self, **_kwargs):
            raise RunInterrupted("stop")

    with pytest.raises(RunInterrupted):
        await env.dispatcher(None).replay_run("task-ev-1", Stopping(), lambda toolset: toolset)


def test_schemas_for_a_role_and_for_a_bad_tool_list(env):
    schemas = env.dispatcher(None).schemas_for("planner")
    assert schemas and all("name" in s for s in schemas)
    assert "save_plan_draft" in {s["name"] for s in schemas}

    env.roles["planner"] = RoleModel(tools=["nope"])
    assert env.dispatcher(None).schemas_for("planner") is None
    del env.roles["planner"]
    assert env.dispatcher(None).schemas_for("planner") is None
