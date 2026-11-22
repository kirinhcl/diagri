"""Rendering a model trace for the terminal (no network)."""

from __future__ import annotations

import json

from trace_sample import TOOL_RESULT, write_sample

from growbridge.agents.trace import read_trace
from growbridge.agents.trace_show import SHORT_CHARS, render_trace, strip_controls


async def test_steps_come_out_in_order(tmp_path, clock):
    out = render_trace(read_trace(await write_sample(tmp_path, clock)))
    positions = [out.index(t) for t in ("hmm", "I will look first.", "echo", "run_finished")]
    assert positions == sorted(positions)
    assert "task-1" in out and "planner" in out and "model-a" in out and "9.9" in out
    assert "all done" in out and "[redacted thinking]" in out


async def test_long_values_are_cut_unless_full(tmp_path, clock):
    trace = read_trace(await write_sample(tmp_path, clock))
    short = render_trace(trace)
    assert TOOL_RESULT not in short
    assert f"… ({len(TOOL_RESULT) - SHORT_CHARS} more characters, use --full)" in short
    assert TOOL_RESULT in render_trace(trace, full=True)


def test_control_characters_and_ansi_are_removed():
    assert strip_controls("a\x1b[31mred\x1b[0m\x07b\n") == "aredb\n"
    assert strip_controls("x\x1b]0;title\x07y\tz\x9bq\x00") == "xy\tzq"


async def test_web_content_cannot_control_the_terminal(tmp_path, clock):
    path = await write_sample(tmp_path, clock, thinking="\x1b[2Jboo\x1b]0;pwn\x07")
    out = render_trace(read_trace(path))
    assert "\x1b" not in out and "\x07" not in out and "boo" in out


async def test_missing_end_says_incomplete(tmp_path, clock):
    out = render_trace(read_trace(await write_sample(tmp_path, clock, ended=False)))
    assert out.rstrip().endswith("Record incomplete: the run has no end line.")


def test_format_characters_and_separators_are_shown_not_dropped():
    assert strip_controls("a\u202eb") == "a<U+202E>b"
    assert strip_controls("x\u2028y\u2029z") == "x<U+2028>y<U+2029>z"
    assert strip_controls("a\u2066b\u2069") == "a<U+2066>b<U+2069>"


def test_ordinary_text_passes_through_unchanged():
    assert strip_controls("温度传感器 \u00e9 \t ok\n") == "温度传感器 \u00e9 \t ok\n"


async def test_a_hostile_turn_field_cannot_control_the_terminal(tmp_path, clock):
    path = await write_sample(tmp_path, clock)
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    for line in lines:
        if line["kind"] == "model":
            line["turn"] = "\x1b[2J\x1b]0;pwn\x07\u202e7"
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    out = render_trace(read_trace(path))
    assert "\x1b" not in out and "\x07" not in out and "\u202e" not in out
    assert "Turn <U+202E>7" in out
