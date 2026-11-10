"""Shared helpers for the model-role tests (no network, no credentials)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from growbridge.agents.tools import Tool
from growbridge.ports import Denied


class EchoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    count: int = 1


class FakeBudget:
    """Records reserve/charge calls; refuses once ``max_calls`` reservations were made."""

    def __init__(self, max_calls: int = 100):
        self.max_calls = max_calls
        self.reserved = 0
        self.charges: list[tuple[str, float]] = []

    def reserve(self, project_id: str, calls: int = 1) -> None:
        if self.reserved + calls > self.max_calls:
            raise Denied("budget", "model call budget exhausted")
        self.reserved += calls

    def charge(self, project_id: str, cost: float) -> None:
        self.charges.append((project_id, cost))


def make_tool(name: str, result: object = None, **kw) -> Tool:
    async def handler(args: EchoInput):
        return result if result is not None else {"echo": args.text * args.count}

    return Tool(name=name, description=f"{name} tool", input_model=EchoInput, handler=handler, **kw)
