"""A development ``ModelClient`` that asks the local Claude Code CLI (``claude -p``) for each turn.

It lets the model roles run on the simulator with the account Claude Code is signed in with,
without an API key. Claude Code cannot hand diagri its tool calls natively, so each turn is one
headless ``claude -p`` call: the tool definitions and the conversation so far go in as text, and
the answer comes back as structured output (``text`` plus ``tool_calls``) that is turned into an
ordinary ``ModelReply``. diagri's own loop still validates and runs every tool, so its checks are
what is tested; only the reasoning comes from Claude.

Claude Code's own tools, MCP servers and slash commands are switched off for these calls, and the
calls run in an empty directory, so the model sees only what diagri sends. ``ANTHROPIC_BASE_URL``
and ``ANTHROPIC_API_KEY`` are removed from the child's environment: a local-model endpoint set for
the Anthropic SDK must not redirect Claude Code. For development only.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import uuid
from collections.abc import Sequence
from typing import Any

from growbridge.agents.llm import ModelReply, ToolCall

TIMEOUT_SECONDS = 900
DROPPED_ENV = ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
RULES = """

How you work here: a program runs an agent loop around you. You cannot run tools yourself and
you have no other tools. Every answer is the structured output: "text" is what you say this turn
(on your last turn, your final reply), "tool_calls" lists the tools to call now, in order, each
with a "name" from the tool list and an "input" that follows that tool's input_schema exactly.
The program runs them and shows you their results on the next turn. Leave "tool_calls" empty
only when you are finished. Tool results arrive as data inside <tool_result> elements."""


def answer_schema(names: Sequence[str]) -> dict:
    name: dict[str, Any] = {"type": "string"}
    if names:
        name["enum"] = list(names)
    call = {
        "type": "object",
        "properties": {"name": name, "input": {"type": "object"}},
        "required": ["name", "input"],
    }
    return {
        "type": "object",
        "properties": {"text": {"type": "string"}, "tool_calls": {"type": "array", "items": call}},
        "required": ["text", "tool_calls"],
    }


def _block_text(block: Any) -> str:
    if isinstance(block, str):
        return block
    kind = block.get("type")
    if kind == "text":
        return block.get("text", "")
    if kind == "tool_use":
        body = json.dumps(block.get("input", {}), ensure_ascii=False)
        return f'<tool_use id="{block.get("id")}" name="{block.get("name")}">{body}</tool_use>'
    if kind == "tool_result":
        error = ' error="true"' if block.get("is_error") else ""
        content = block.get("content", "")
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        return f'<tool_result id="{block.get("tool_use_id")}"{error}>\n{content}\n</tool_result>'
    return json.dumps(block, ensure_ascii=False, default=str)


def render_prompt(messages: Sequence[dict], tools: Sequence[dict]) -> str:
    """The tool list, then every turn so far, oldest first."""
    listed = [
        {
            "name": t["name"],
            "description": t.get("description", ""),
            "input_schema": t["input_schema"],
        }
        for t in tools
    ]
    parts = ["<tools>", json.dumps(listed, ensure_ascii=False), "</tools>", "", "<conversation>"]
    for message in messages:
        content = message["content"]
        blocks = [content] if isinstance(content, str) else list(content)
        parts.append(f"[{message['role']}]")
        parts.extend(_block_text(block) for block in blocks)
    parts += ["</conversation>", "", "Give your next turn."]
    return "\n".join(parts)


def parse_answer(raw: dict) -> dict:
    if raw.get("is_error"):
        raise RuntimeError(f"claude -p failed: {raw.get('subtype')}: {raw.get('result')}")
    answer = raw.get("structured_output")
    if answer is None:
        answer = json.loads(raw.get("result") or "{}")
    return answer


def to_reply(answer: dict, usage: dict) -> ModelReply:
    text = str(answer.get("text") or "")
    calls = tuple(
        ToolCall(id=f"toolu_cc_{uuid.uuid4().hex[:16]}", name=c["name"], input=dict(c["input"]))
        for c in answer.get("tool_calls") or ()
    )
    content: list[dict] = [{"type": "text", "text": text}] if text else []
    content += [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.input} for c in calls]
    tokens_in = sum(
        int(usage.get(key) or 0)
        for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    )
    return ModelReply(
        stop_reason="tool_use" if calls else "end_turn",
        text=text,
        tool_calls=calls,
        content=content,
        input_tokens=tokens_in,
        output_tokens=int(usage.get("output_tokens") or 0),
    )


class ClaudeCodeClient:
    def __init__(self, executable: str | None = None, timeout: float = TIMEOUT_SECONDS):
        found = executable or shutil.which("claude")
        if found is None:
            raise RuntimeError("the claude CLI is not on PATH")
        self.executable = found
        self.timeout = timeout
        self.workdir = tempfile.mkdtemp(prefix="diagri-claude-")
        self.env = {k: v for k, v in os.environ.items() if k not in DROPPED_ENV}

    def command(self, model: str, system: str, effort: str, names: Sequence[str]) -> list[str]:
        return [
            self.executable,
            "-p",
            "--output-format",
            "json",
            "--model",
            model,
            "--effort",
            effort,
            "--system-prompt",
            system + RULES,
            "--tools",
            "",
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--no-session-persistence",
            "--json-schema",
            json.dumps(answer_schema(names)),
        ]

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
        names = [t["name"] for t in tools]
        process = await asyncio.create_subprocess_exec(
            *self.command(model, system, effort, names),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.workdir,
            env=self.env,
        )
        prompt = render_prompt(messages, tools).encode()
        try:
            out, err = await asyncio.wait_for(process.communicate(prompt), self.timeout)
        except TimeoutError:
            process.kill()
            await process.wait()
            raise
        if process.returncode != 0 and not out:
            raise RuntimeError(f"claude -p exited {process.returncode}: {err.decode()[-500:]}")
        raw = json.loads(out)
        return to_reply(parse_answer(raw), raw.get("usage") or {})
