"""Shared helpers for the model-role wiring tests (no network, no credentials)."""

from __future__ import annotations

from growbridge.agents.llm import ToolCall
from growbridge.agents.loop import AgentRun
from growbridge.archive.models import Budget, ResearchTask
from growbridge.sim.llm import text_reply, tool_reply


def call(name: str, call_id: str = "c1", **fields) -> ToolCall:
    return ToolCall(id=call_id, name=name, input=fields)


def script_calls(*calls: ToolCall) -> list:
    """One turn of tool calls followed by a closing text reply."""
    return [tool_reply(*calls), text_reply("done")]


def make_task(owner: str, event: str = "ev-1", **fields) -> ResearchTask:
    values = {
        "id": f"task-{event}",
        "project_id": "project-x",
        "question": "does more light speed up canopy growth?",
        "owner_role": owner,
        "budget": Budget(max_calls=10, max_cost=5.0),
        "trigger_event_id": event,
        "correlation_id": "corr-1",
        **fields,
    }
    return ResearchTask(**values)


def tool_errors(run: AgentRun) -> dict[str, bool]:
    return {record.name: record.is_error for record in run.tool_calls}


def result_blocks(client, request_index: int = -1) -> list[dict]:
    """The tool_result blocks the model received in a given request."""
    message = client.requests[request_index]["messages"][-1]
    assert message["role"] == "user"
    return message["content"]
