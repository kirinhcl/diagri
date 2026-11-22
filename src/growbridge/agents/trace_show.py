"""Render a model trace as readable terminal text (pure; no web content reaches it raw)."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

from .trace import Trace

SHORT_CHARS = 400
INCOMPLETE = "Record incomplete: the run has no end line."

_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")
_CONTROLS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def _mark_invisible(char: str) -> str:
    if char in "\u2028\u2029" or unicodedata.category(char) == "Cf":
        return f"<U+{ord(char):04X}>"
    return char


def strip_controls(text: str) -> str:
    """Remove ANSI escape sequences and every control character except newline and tab.

    Invisible format characters (category Cf, such as the bidirectional overrides) and the line
    and paragraph separators are shown as ``<U+XXXX>`` so a reader sees that something was there.
    """
    visible = _CONTROLS.sub("", _ANSI.sub("", text))
    return "".join(_mark_invisible(char) for char in visible)


def _clip(value: Any, full: bool) -> str:
    text = strip_controls(value if isinstance(value, str) else json.dumps(value, default=str))
    if full or len(text) <= SHORT_CHARS:
        return text
    return f"{text[:SHORT_CHARS]}… ({len(text) - SHORT_CHARS} more characters, use --full)"


def _indent(text: str, prefix: str = "    ") -> str:
    return "\n".join(prefix + line for line in text.split("\n"))


def _when(at: Any) -> str:
    if not isinstance(at, int | float):
        return "unknown"
    return datetime.fromtimestamp(at, UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _header(run: dict[str, Any], full: bool) -> list[str]:
    config = run.get("role_config") or {}
    copy = run.get("pre_run_copy")
    fields = [
        ("Task", run.get("task_id")),
        ("Project", run.get("project_id")),
        ("Role", run.get("role")),
        ("Model", config.get("model")),
        ("Version", run.get("growbridge_version")),
        ("Commit", run.get("git_commit")),
        ("Started", _when(run.get("at"))),
        ("Pre-run copy", "yes" if copy else "no"),
    ]
    return [f"{name}: {_clip(str(value), full)}" for name, value in fields]


def _thinking(block: dict[str, Any], full: bool) -> str | None:
    if block.get("type") == "thinking":
        return f"  Thinking:\n{_indent(_clip(block.get('thinking', ''), full))}"
    if block.get("type") == "redacted_thinking":
        return "  Thinking: [redacted thinking]"
    return None


def _tool(call: dict[str, Any], results: dict[str, dict[str, Any]], full: bool) -> list[str]:
    out = [f"  Tool call: {_clip(call.get('name', '?'), full)}"]
    out.append(f"    input: {_clip(call.get('input'), full)}")
    result = results.get(call.get("id"))
    if result is None:
        out.append("    result: (none recorded)")
        return out
    flag = " [error]" if result.get("is_error") else ""
    out.append(f"    result{flag}: {_clip(result.get('content', ''), full)}")
    return out


def _turn(model: dict[str, Any], results: dict[str, dict[str, Any]], full: bool) -> list[str]:
    out = [f"Turn {_clip(str(model.get('turn')), full)}"]
    if "error" in model:
        return [*out, f"  Model error: {_clip(model['error'], full)}"]
    for block in model.get("content") or []:
        if isinstance(block, dict) and (line := _thinking(block, full)):
            out.append(line)
    if model.get("text"):
        out.append(f"  Text:\n{_indent(_clip(model['text'], full))}")
    for call in model.get("tool_calls") or []:
        out.extend(_tool(call, results, full))
    return out


def _end(end: dict[str, Any], full: bool) -> list[str]:
    fields = [
        ("State", end.get("state")),
        ("Code", end.get("code")),
        ("Reason", end.get("reason")),
        ("Turns", end.get("turns")),
        ("Input tokens", end.get("input_tokens")),
        ("Output tokens", end.get("output_tokens")),
        ("Cache write tokens", end.get("cache_write_tokens", 0)),
        ("Cache read tokens", end.get("cache_read_tokens", 0)),
        ("Cost", end.get("cost")),
        ("Seconds", end.get("seconds")),
    ]
    return ["End", *(f"  {name}: {_clip(str(value), full)}" for name, value in fields)]


def render_trace(trace: Trace, *, full: bool = False) -> str:
    """The run header, each turn with its tool calls and results, then the end (or a notice)."""
    results = {line.get("tool_use_id"): line for line in trace.tools}
    out = _header(trace.run, full)
    for model in trace.models:
        out.append("")
        out.extend(_turn(model, results, full))
    out.append("")
    out.extend(_end(trace.end, full) if trace.end is not None else [INCOMPLETE])
    return "\n".join(out) + "\n"
