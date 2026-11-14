"""What the dispatcher tells a model, what it records, and when it wakes the orchestrator."""

import json

from dispatch_helpers import call

from growbridge.agents.context import project_context
from growbridge.agents.conversation import ConversationLog
from growbridge.agents.dispatch import Dispatcher, delivered
from growbridge.agents.tools import ToolOutcome
from growbridge.sim.llm import ScriptedClient, text_reply, tool_reply
from growbridge.workflow.states import TaskState


def dispatcher(env, client, conversation=None, context=None) -> Dispatcher:
    args = (client, env.roles, env.tools(), env.tasks, env.budget, env.clock, env.db)
    return Dispatcher(*args, context=context, conversation=conversation)


def handoff(client, index: int = 0) -> dict:
    message = client.requests[index]["messages"][0]["content"]
    return json.loads(message[message.index("{") :])


def follow_ups(env) -> list:
    return [t for t in env.tasks.list(env.project_id) if t.trigger_event_id.startswith("followup:")]


def saving_planner(env) -> ScriptedClient:
    save = call("save_plan_draft", round_id=env.round_id, run_sheet=env.sheet_json())
    return ScriptedClient([tool_reply(save), text_reply("the draft waits for review")])


async def test_a_delegated_planner_that_saves_a_draft_finishes_and_wakes_the_orchestrator(env):
    parent = env.task("orchestrator", "ev-goal")
    planning = env.task("planner", "ev-plan", parent_task_id=parent.id, input_refs=("round:r",))
    log = ConversationLog(env.db, env.clock)

    await dispatcher(env, saving_planner(env), log).run_task(planning.id)

    assert env.tasks.get(planning.id).state is TaskState.DONE
    (follow,) = follow_ups(env)
    assert follow.owner_role == "orchestrator" and follow.parent_task_id is None
    assert follow.trigger_event_id == f"followup:{planning.id}"
    assert follow.input_refs == ("round:r", f"task:{planning.id}")
    assert "done" in follow.question and "the draft waits for review" in follow.question
    said = [(e.role, e.kind, e.text) for e in log.entries(env.project_id)]
    assert said == [
        ("planner", "tool", "save_plan_draft"),
        ("planner", "reply", "the draft waits for review"),
        ("planner", "status", "done"),
        ("planner", "status", "follow_up"),
    ]


async def test_a_delegated_task_handed_back_also_wakes_the_orchestrator_with_the_reason(env):
    parent = env.task("orchestrator", "ev-goal")
    planning = env.task("planner", "ev-plan", parent_task_id=parent.id)
    client = ScriptedClient([text_reply("I need the cultivar before I can plan")])

    await dispatcher(env, client).run_task(planning.id)

    assert env.tasks.get(planning.id).state is TaskState.NEEDS_ATTENTION
    (follow,) = follow_ups(env)
    assert "needs_attention" in follow.question and "cultivar" in follow.question


async def test_a_task_nobody_delegated_wakes_no_one(env):
    planning = env.task("planner", "ev-plan")

    await dispatcher(env, saving_planner(env)).run_task(planning.id)

    assert env.tasks.get(planning.id).state is TaskState.DONE
    assert follow_ups(env) == []


async def test_an_orchestrator_run_is_followed_by_nothing(env):
    parent = env.task("orchestrator", "ev-goal")
    child = env.task("orchestrator", "ev-sub", parent_task_id=parent.id)

    await dispatcher(env, ScriptedClient([text_reply("noted")])).run_task(child.id)

    assert env.tasks.get(child.id).state is TaskState.DONE and follow_ups(env) == []


def test_only_a_saved_draft_counts_as_the_planners_delivery():
    def outcome(name: str, content: str, error: bool = False) -> ToolOutcome:
        return ToolOutcome(name=name, content=content, is_error=error)

    assert delivered("planner", outcome("save_plan_draft", '{"saved": true}'))
    assert not delivered("planner", outcome("save_plan_draft", '{"saved": false}'))
    assert not delivered("planner", outcome("save_plan_draft", "Error: denied", error=True))
    assert not delivered("planner", outcome("validate_run_sheet", '{"findings": []}'))
    assert delivered("researcher", outcome("freeze_dataset", '{"snapshot_id": "s"}'))
    assert not delivered("orchestrator", outcome("save_plan_draft", '{"saved": true}'))


async def test_the_orchestrator_is_told_the_context_and_what_was_said_before(env):
    log = ConversationLog(env.db, env.clock)
    log.add(env.project_id, "user", "message", "does more light help?", "task-earlier")
    log.add(env.project_id, "orchestrator", "reply", "which crop?", "task-earlier")
    task = env.task("orchestrator", "ev-goal", input_refs=(f"round:{env.round_id}",))
    log.add(env.project_id, "user", "message", "basil", task.id)  # this run's own question
    client = ScriptedClient([text_reply("planning basil")])

    def context(task):
        return project_context(env.workflow, env.control, "Europe/Helsinki", task)

    await dispatcher(env, client, log, context).run_task(task.id)

    data = handoff(client)
    assert data["conversation"] == [
        {"role": "user", "text": "does more light help?"},
        {"role": "orchestrator", "text": "which crop?"},
    ]
    (listed,) = data["context"]["rounds"]
    assert listed["round_id"] == env.round_id
    assert (listed["protocol_id"], listed["protocol_version"]) == (env.protocol.id, 1)
    protocol = data["context"]["protocols"][f"{env.protocol.id} v1"]
    assert protocol["treatments"] == [t.model_dump(mode="json") for t in env.protocol.treatments]
    assert data["context"]["timezone"] == "Europe/Helsinki"
    assert listed["protocol_round"] == 1 and listed["treatment"]["id"] == "high"
    assert listed["treatment"]["factors"] == {"light": 70}
    assert listed["new_stage"] == {
        "stage_name": env.protocol.stages[0],
        "run_sheet_id": f"sheet-{env.round_id}-1",
        "run_sheet_version": 1,
        "stage_id": f"stage-{env.round_id}-1",
        "experiment_id": f"exp-{env.round_id}",
    }


async def test_the_next_stage_keeps_the_rounds_experiment(env):
    env.workflow.submit_run_sheet(env.round_id, env.sheet("stage-a"), env.operator)
    task = env.task("planner", "ev-plan", input_refs=(f"round:{env.round_id}",))

    (listed,) = project_context(env.workflow, env.control, "UTC", task)["rounds"]

    assert [s["stage_id"] for s in listed["stages"]] == ["stage-a"]
    assert listed["new_stage"]["stage_id"] == f"stage-{env.round_id}-2"
    assert listed["new_stage"]["experiment_id"] == "experiment-stage-a"


async def test_a_working_role_gets_the_context_but_not_the_conversation(env):
    log = ConversationLog(env.db, env.clock)
    log.add(env.project_id, "user", "message", "earlier words", "task-earlier")
    task = env.task("planner", "ev-plan")
    client = ScriptedClient([text_reply("x")])

    def context(task):
        return project_context(env.workflow, env.control, "UTC", task)

    await dispatcher(env, client, log, context).run_task(task.id)

    data = handoff(client)
    assert "conversation" not in data and data["context"]["rounds"]


async def test_a_follow_up_may_read_the_task_it_follows_and_no_other(env):
    planning = env.task("planner", "ev-plan")
    other = env.task("planner", "ev-other")
    follow = env.task("orchestrator", "ev-follow", input_refs=(f"task:{planning.id}",))

    read = await env.invoke_as(follow.id, "orchestrator", "get_task_status", task_id=planning.id)
    refused = await env.invoke_as(follow.id, "orchestrator", "get_task_status", task_id=other.id)

    assert not read.is_error and json.loads(read.content)["id"] == planning.id
    assert refused.is_error and "not available" in refused.content


async def test_a_new_task_tells_the_orchestrator_to_end_its_run_instead_of_waiting(env):
    parent = env.task("orchestrator", "ev-goal")
    fields = {
        "project_id": env.project_id,
        "to_role": "planner",
        "goal": "draft a run sheet",
        "budget": {"max_calls": 5, "max_cost": 1.0},
        "trigger_event_id": "ev-new",
        "correlation_id": "corr-1",
        "parent_task_id": parent.id,
    }

    outcome = await env.invoke_as(parent.id, "orchestrator", "delegate_task", **fields)

    assert "End your turn now" in json.loads(outcome.content)["next"]
