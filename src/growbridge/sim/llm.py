"""Scripted model client for tests and the simulator: replays canned replies, never networks."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from growbridge.agents.llm import ModelReply, ToolCall


class ScriptedClient:
    """Replays ``replies`` in order and records every request it receives."""

    def __init__(self, replies: Sequence[ModelReply]):
        self._replies = list(replies)
        self.requests: list[dict[str, Any]] = []

    async def create(
        self,
        *,
        model: str,
        system: str,
        messages: Sequence[dict],
        tools: Sequence[dict],
        max_tokens: int,
        effort: str,
    ) -> ModelReply:
        self.requests.append(
            {
                "model": model,
                "system": system,
                "messages": list(messages),
                "tools": list(tools),
                "max_tokens": max_tokens,
                "effort": effort,
            }
        )
        assert self._replies, "ScriptedClient ran out of scripted replies"
        return self._replies.pop(0)


def text_reply(text: str, input_tokens: int = 10, output_tokens: int = 5) -> ModelReply:
    return ModelReply(
        stop_reason="end_turn",
        text=text,
        content=[{"type": "text", "text": text}],
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def tool_reply(*calls: ToolCall, input_tokens: int = 10, output_tokens: int = 5) -> ModelReply:
    content = [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.input} for c in calls]
    return ModelReply(
        stop_reason="tool_use",
        tool_calls=tuple(calls),
        content=content,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
