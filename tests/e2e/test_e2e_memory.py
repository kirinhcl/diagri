"""A model task starts with its project's history (memory design 2026-11-17)."""

import json

from test_e2e_agents import design, task

from growbridge.agents.dispatch import INTRO
from growbridge.sim.llm import ScriptedClient, text_reply


def task_record(client) -> dict:
    """The record of the first request's task message, as the model received it."""
    first = client.requests[0]["messages"][0]["content"]
    return json.loads(first[len(INTRO) :])


async def test_a_task_message_carries_the_history(world):
    runtime = await world.boot()
    project, _, _ = await design(world, runtime)
    runtime.notes.add(runtime.settings.device, "alice", "changed the CO2 probe")
    runtime.tasks.create(task(project, "planner", "ev-plan"))

    client = ScriptedClient([text_reply("ok")])
    await runtime.run_agents(client)

    history = task_record(client)["context"]["history"]
    assert set(history) == {"rounds", "patterns", "episodes", "notes"}
    assert [n["text"] for n in history["notes"]] == ["changed the CO2 probe"]
