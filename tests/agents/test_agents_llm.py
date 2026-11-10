from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from growbridge.agents.llm import AnthropicClient, ModelReply, ToolCall
from growbridge.sim.llm import ScriptedClient, text_reply, tool_reply

CREATE_ARGS = dict(
    model="m", system="s", messages=[{"role": "user", "content": "q"}], tools=[],
    max_tokens=256, effort="low",
)  # fmt: skip


async def test_scripted_client_replays_and_records_requests():
    client = ScriptedClient([text_reply("one"), text_reply("two")])
    first = await client.create(**CREATE_ARGS)
    second = await client.create(**CREATE_ARGS)
    assert (first.text, second.text) == ("one", "two")
    assert len(client.requests) == 2 and client.requests[0]["model"] == "m"


async def test_scripted_client_fails_loudly_when_script_runs_out():
    client = ScriptedClient([])
    with pytest.raises(AssertionError):
        await client.create(**CREATE_ARGS)


def test_tool_reply_builds_tool_use_reply():
    reply = tool_reply(ToolCall(id="t1", name="get_project_state", input={}))
    assert reply.stop_reason == "tool_use" and reply.tool_calls[0].id == "t1"
    assert isinstance(reply, ModelReply)


def stubbed_client(monkeypatch, response):
    pytest.importorskip("anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-real-key")
    client = AnthropicClient()
    stub = AsyncMock(return_value=response)
    monkeypatch.setattr(client.client.messages, "create", stub)
    return client, stub


async def test_anthropic_client_request_shape_and_reply_parsing(monkeypatch):
    blocks = [
        SimpleNamespace(type="thinking", thinking="", signature="sig"),
        SimpleNamespace(type="text", text="hello"),
        SimpleNamespace(type="tool_use", id="toolu_1", name="get_project_state", input={"a": 1}),
    ]
    response = SimpleNamespace(
        stop_reason="tool_use",
        content=blocks,
        usage=SimpleNamespace(input_tokens=11, output_tokens=7),
    )
    client, stub = stubbed_client(monkeypatch, response)

    tools = [{"name": "get_project_state", "strict": True, "input_schema": {"type": "object"}}]
    reply = await client.create(
        model="claude-opus-5-5",
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        tools=tools,
        max_tokens=2048,
        effort="high",
    )

    sent = stub.await_args.kwargs
    assert sent["model"] == "claude-opus-5-5"
    assert sent["system"] == "sys" and sent["max_tokens"] == 2048
    assert sent["thinking"] == {"type": "adaptive"}
    assert sent["output_config"] == {"effort": "high"}
    assert sent["tools"] == tools
    assert not {"temperature", "top_p", "top_k", "tool_choice"} & set(sent)
    assert reply.stop_reason == "tool_use" and reply.text == "hello"
    assert reply.tool_calls == (ToolCall(id="toolu_1", name="get_project_state", input={"a": 1}),)
    assert reply.content is blocks
    assert (reply.input_tokens, reply.output_tokens) == (11, 7)


async def test_anthropic_client_omits_tools_when_there_are_none(monkeypatch):
    response = SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text="ok")],
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    client, stub = stubbed_client(monkeypatch, response)
    await client.create(**CREATE_ARGS)
    assert "tools" not in stub.await_args.kwargs
