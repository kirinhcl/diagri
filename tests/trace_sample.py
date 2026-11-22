"""Write a small model trace with RunTrace, for the viewer tests (no network)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from growbridge.agents.llm import ModelReply, ToolCall
from growbridge.agents.tools import Tool, Toolset
from growbridge.agents.trace import RunTrace
from growbridge.sim.llm import ScriptedClient, text_reply

REQUEST = {
    "model": "m",
    "system": "s",
    "messages": [],
    "tools": [],
    "max_tokens": 1,
    "effort": "low",
}
TOOL_RESULT = "r" * 1000


class EchoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str


def make_tool(name: str, result: object) -> Tool:
    async def handler(args: EchoInput):
        return result

    return Tool(name=name, description=f"{name} tool", input_model=EchoInput, handler=handler)


def thinking_reply(thinking: str, call: ToolCall) -> ModelReply:
    return ModelReply(
        stop_reason="tool_use",
        text="I will look first.",
        tool_calls=(call,),
        content=[
            {"type": "thinking", "thinking": thinking, "signature": "sig"},
            {"type": "redacted_thinking", "data": "xx"},
            {"type": "text", "text": "I will look first."},
            {"type": "tool_use", "id": call.id, "name": call.name, "input": call.input},
        ],
        input_tokens=10,
        output_tokens=5,
    )


async def write_sample(root: Path, clock, *, ended: bool = True, thinking: str = "hmm") -> Path:
    trace = RunTrace.open(root, "task-1", clock, datetime(2026, 11, 22, 9, 5, 7))
    assert trace is not None
    trace.begin(
        {
            "task_id": "task-1",
            "project_id": "project-x",
            "role": "planner",
            "role_config": {"model": "model-a", "effort": "low"},
            "growbridge_version": "9.9",
            "git_commit": None,
            "at": 1_795_000_000.0,
            "pre_run_copy": "copy-1",
            "system": "s",
            "user": "u",
        }
    )
    call = ToolCall(id="c1", name="echo", input={"text": "x"})
    client = trace.client(ScriptedClient([thinking_reply(thinking, call), text_reply("all done")]))
    toolset = trace.toolset(Toolset("planner", [make_tool("echo", result=TOOL_RESULT)]))
    await client.create(**REQUEST)
    await toolset.call("echo", {"text": "x"})
    await client.create(**REQUEST)
    if ended:
        trace.end(
            {
                "state": "done",
                "code": "run_finished",
                "reason": "finished",
                "turns": 2,
                "input_tokens": 20,
                "output_tokens": 10,
                "cost": 0.5,
                "seconds": 1.5,
                "at": 1_795_000_002.0,
            }
        )
    return trace.path
