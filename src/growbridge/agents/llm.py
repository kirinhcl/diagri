"""Model client port and the Anthropic adapter (architecture doc §11.7).

Credentials are never passed in: ``anthropic.AsyncAnthropic()`` resolves them from the
environment. The SDK is imported lazily so the package works without the optional dependency.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from growbridge.archive.models import Model

DEFAULT_MODEL = "claude-opus-5-5"


class ToolCall(Model):
    id: str
    name: str
    input: dict[str, Any]


class ModelReply(Model):
    stop_reason: str
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    content: Any = None  # the assistant content, replayed verbatim on the next request
    input_tokens: int = 0
    output_tokens: int = 0


class TokenPrice(Model):
    """USD per million tokens, used for budget accounting only.

    The defaults are the list price of ``claude-opus-5-5`` (the default model). A role that
    runs another model must pass that model's price to ``run_agent``.
    """

    input_per_mtok: float = 4.0
    output_per_mtok: float = 20.0

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.input_per_mtok + output_tokens * self.output_per_mtok
        ) / 1_000_000


DEFAULT_PRICE = TokenPrice()


class ModelClient(Protocol):
    async def create(
        self,
        *,
        model: str,
        system: str,
        messages: Sequence[dict],
        tools: Sequence[dict],
        max_tokens: int,
        effort: str,
    ) -> ModelReply: ...


def parse_response(response: Any) -> ModelReply:
    """Turn an SDK message into a ``ModelReply``; the content blocks are kept as they came."""
    blocks = list(response.content)
    text = "".join(b.text for b in blocks if b.type == "text")
    calls = tuple(
        ToolCall(id=b.id, name=b.name, input=dict(b.input)) for b in blocks if b.type == "tool_use"
    )
    return ModelReply(
        stop_reason=str(response.stop_reason),
        text=text,
        tool_calls=calls,
        content=response.content,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )


class AnthropicClient:
    """``ModelClient`` over the official SDK. No sampling parameters, no forced tool choice."""

    def __init__(self, client: Any = None):
        if client is None:
            import anthropic  # optional dependency, imported on first use

            client = anthropic.AsyncAnthropic()
        self.client = client

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
        request: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": list(messages),
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": effort},
        }
        if tools:
            request["tools"] = list(tools)
        return parse_response(await self.client.messages.create(**request))
