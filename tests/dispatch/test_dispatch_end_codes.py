"""The status entry that ends a model task carries a code and params next to its English reason."""

from growbridge.agents.conversation import ConversationLog
from growbridge.agents.llm import ModelReply
from growbridge.sim.llm import ScriptedClient, text_reply


class Failing:
    async def create(self, **_kwargs) -> ModelReply:
        raise RuntimeError("overloaded")


def ended(env, client, role: str = "planner"):
    log = ConversationLog(env.db, env.clock)
    task = env.task(role)
    dispatcher = env.dispatcher(client)
    dispatcher.conversation = log
    return dispatcher, task, log


def end_detail(log, env) -> dict:
    ends = [e for e in log.entries(env.project_id) if e.kind == "status" and "reason" in e.detail]
    assert len(ends) == 1
    return ends[0].detail


async def test_a_refused_step_says_denied_with_the_refusals_own_code(env):
    dispatcher, task, log = ended(env, ScriptedClient([text_reply("x")]))
    env.db.execute("DELETE FROM call_budget")

    await dispatcher.run_task(task.id)

    detail = end_detail(log, env)
    assert detail["code"] == "denied"
    assert detail["params"] == {"denied_code": "budget"}
    assert detail["reason"].startswith("budget: ")


async def test_a_model_that_cannot_be_reached_says_model_unavailable(env):
    dispatcher, task, log = ended(env, Failing())

    await dispatcher.run_task(task.id)

    detail = end_detail(log, env)
    assert (detail["code"], detail["params"]) == ("model_unavailable", {})
    assert detail["reason"] == "model unavailable: RuntimeError: overloaded"


async def test_a_model_that_stops_early_says_model_stopped_with_the_stop_reason(env):
    reply = ModelReply(stop_reason="max_tokens", text="partial", content=[])
    dispatcher, task, log = ended(env, ScriptedClient([reply]))

    await dispatcher.run_task(task.id)

    detail = end_detail(log, env)
    assert (detail["code"], detail["params"]) == ("model_stopped", {"stop_reason": "max_tokens"})
    assert detail["reason"] == "model stopped without finishing: max_tokens"


async def test_a_role_that_hands_back_nothing_says_undelivered_with_its_role(env):
    dispatcher, task, log = ended(env, ScriptedClient([text_reply("I need the cultivar")]))

    await dispatcher.run_task(task.id)

    detail = end_detail(log, env)
    assert (detail["code"], detail["params"]) == ("undelivered", {"role": "planner"})
    assert detail["reason"].startswith("ended without saving a run sheet draft: ")
    assert "cultivar" not in str(detail["params"])


async def test_a_normal_end_says_run_finished(env):
    dispatcher, task, log = ended(env, ScriptedClient([text_reply("noted")]), role="orchestrator")

    await dispatcher.run_task(task.id)

    detail = end_detail(log, env)
    assert (detail["code"], detail["params"]) == ("run_finished", {})
    assert detail["reason"] == "run finished"
