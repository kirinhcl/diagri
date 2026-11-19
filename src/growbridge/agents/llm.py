"""Model client port and the Anthropic adapter (architecture doc §11.7).

Credentials are never passed in: ``anthropic.AsyncAnthropic()`` resolves them from the
environment. The SDK is imported lazily so the package works without the optional dependency.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from growbridge.archive.models import Model

DEFAULT_MODEL = "claude-opus-5-5"
CACHE_WRITE_FACTOR = 1.25  # a 5-minute cache write, per unit of input price
CACHE_READ_FACTOR = 0.1  # the highest documented cache read rate, per unit of input price


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
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0


class TokenPrice(Model):
    """USD per million tokens, used for budget accounting only.

    The defaults are the list price of ``claude-opus-5-5`` (the default model), with the cache
    written for 5 minutes. A role that runs another model must pass that model's price to
    ``run_agent``.
    """

    input_per_mtok: float = 4.0
    output_per_mtok: float = 20.0
    cache_write_per_mtok: float = 5.0
    cache_read_per_mtok: float = 0.2

    @classmethod
    def from_stated(cls, input_per_mtok: float, output_per_mtok: float) -> TokenPrice:
        """A configured model's price. Its cache prices follow from its input price: a 5-minute
        write is 1.25 times the input price, and a read is charged at 0.1 times, the highest
        documented read rate, so the budget never charges less than the model costs."""
        return cls(
            input_per_mtok=input_per_mtok,
            output_per_mtok=output_per_mtok,
            cache_write_per_mtok=input_per_mtok * CACHE_WRITE_FACTOR,
            cache_read_per_mtok=input_per_mtok * CACHE_READ_FACTOR,
        )

    def cost(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_write_tokens: int = 0,
        cache_read_tokens: int = 0,
    ) -> float:
        return (
            input_tokens * self.input_per_mtok
            + output_tokens * self.output_per_mtok
            + cache_write_tokens * self.cache_write_per_mtok
            + cache_read_tokens * self.cache_read_per_mtok
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
        cache_write_tokens=_count(response.usage, "cache_creation_input_tokens"),
        cache_read_tokens=_count(response.usage, "cache_read_input_tokens"),
    )


def _count(usage: Any, field: str) -> int:
    """A cache usage field; the API leaves it empty (None) when there was nothing to count."""
    return getattr(usage, field, None) or 0


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
        # The role's system prompt (and the tools before it) is cached on its own, so tasks of
        # the same role share it; the top-level marker caches the conversation as it grows.
        # Both are 5-minute entries, the write ``TokenPrice`` charges for: a "1h" ttl would bill
        # writes at twice the input price, so change CACHE_WRITE_FACTOR with it.
        request: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": list(messages),
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": effort},
            "cache_control": {"type": "ephemeral"},
        }
        if tools:
            request["tools"] = list(tools)
        return parse_response(await self.client.messages.create(**request))
