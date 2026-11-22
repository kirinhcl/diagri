"""The model trace format, its recorders and its reader (no network)."""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime
from types import SimpleNamespace

import pytest
from agent_helpers import make_tool
from dispatch_helpers import call

from growbridge.agents.tools import Toolset
from growbridge.agents.trace import (
    RunTrace,
    Trace,
    TraceFormatError,
    content_dicts,
    read_trace,
    sha256_json,
)
from growbridge.sim.llm import ScriptedClient, text_reply, tool_reply

LOCAL = datetime(2026, 11, 22, 9, 5, 7)
REQUEST = {
    "model": "m",
    "system": "s",
    "messages": [],
    "tools": [],
    "max_tokens": 1,
    "effort": "low",
}


def lines_of(trace: RunTrace) -> list[dict]:
    return [json.loads(line) for line in trace.path.read_text().splitlines()]


def open_trace(tmp_path, clock, **kw) -> RunTrace:
    trace = RunTrace.open(tmp_path, "task-1", clock, LOCAL, **kw)
    assert trace is not None
    return trace


async def test_records_a_run_line_model_lines_tool_lines_and_an_end(tmp_path, clock):
    trace = open_trace(tmp_path, clock)
    trace.begin({"task_id": "task-1"})
    client = trace.client(
        ScriptedClient([tool_reply(call("echo", "c1", text="x")), text_reply("done")])
    )
    toolset = trace.toolset(Toolset("planner", [make_tool("echo")]))
    reply = await client.create(**REQUEST)
    await toolset.call("echo", {"text": "x"})
    await client.create(**REQUEST)
    trace.end({"code": "run_finished"})
    lines = lines_of(trace)
    assert [line["kind"] for line in lines] == ["run", "model", "tool", "model", "end"]
    assert lines[0]["format"] == 1
    assert lines[2]["tool_use_id"] == "c1" and lines[2]["turn"] == 1
    assert lines[2]["external"] is False and lines[2]["is_error"] is False
    assert lines[1]["tool_calls"] == [
        {"id": "c1", "name": "echo", "input": reply.tool_calls[0].input}
    ]
    assert lines[3]["turn"] == 2
    assert trace.path.parent.name == "2026-11-22"
    assert trace.path.name.startswith("task-1-090507-")


def test_files_are_0600_and_dirs_0700(tmp_path, clock):
    trace = open_trace(tmp_path, clock)
    assert stat.S_IMODE(os.stat(trace.path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(trace.path.parent).st_mode) == 0o700


def test_thinking_blocks_are_kept_whole_from_objects_and_dicts():
    class SdkLike:
        def model_dump(self, mode="python"):
            return {"type": "thinking", "thinking": "t", "signature": "sig"}

    result = content_dicts([SdkLike(), {"type": "redacted_thinking", "data": "x"}])
    assert result == [
        {"type": "thinking", "thinking": "t", "signature": "sig"},
        {"type": "redacted_thinking", "data": "x"},
    ]
    assert content_dicts(None) == []
    assert content_dicts([SimpleNamespace()])[0]["type"] == "unknown"


def test_sha256_json_ignores_key_order():
    assert sha256_json({"a": 1, "b": 2}) == sha256_json({"b": 2, "a": 1})


async def test_tool_results_are_not_clipped(tmp_path, clock):
    trace = open_trace(tmp_path, clock)
    big = "y" * 20_000
    toolset = trace.toolset(Toolset("planner", [make_tool("echo", result=big)]))
    outcome = await toolset.call("echo", {"text": "x"})
    assert big in outcome.content
    assert big in lines_of(trace)[0]["content"]


async def test_model_error_is_recorded_and_re_raised(tmp_path, clock):
    class Boom:
        async def create(self, **request):
            raise RuntimeError("down")

    trace = open_trace(tmp_path, clock)
    with pytest.raises(RuntimeError, match="down"):
        await trace.client(Boom()).create(**REQUEST)
    assert lines_of(trace)[0]["error"] == "RuntimeError: down"


async def test_a_failing_write_never_raises_and_stops_writing(tmp_path, clock):
    class Broken:
        def write(self, text):
            raise OSError("disk full")

        def flush(self):
            pass

        def close(self):
            pass

    trace = open_trace(tmp_path, clock)
    real = trace._file
    trace._file = Broken()
    client = trace.client(ScriptedClient([text_reply("a"), text_reply("b")]))
    assert (await client.create(**REQUEST)).text == "a"
    assert (await client.create(**REQUEST)).text == "b"
    trace.end({"code": "x"})
    real.close()
    assert trace.path.read_text() == ""


async def test_invalid_first_call_keeps_the_second_id(tmp_path, clock):
    trace = open_trace(tmp_path, clock)
    client = trace.client(
        ScriptedClient([tool_reply(call("echo", "c1", bad=1), call("echo", "c2", text="x"))])
    )
    toolset = trace.toolset(Toolset("planner", [make_tool("echo")]))
    await client.create(**REQUEST)
    first = await toolset.call("echo", {"bad": 1})
    await toolset.call("echo", {"text": "x"})
    tools = [line for line in lines_of(trace) if line["kind"] == "tool"]
    assert first.is_error and tools[0]["is_error"] is True
    assert [t["tool_use_id"] for t in tools] == ["c1", "c2"]
    await toolset.call("echo", {"text": "x"})
    assert lines_of(trace)[-1]["tool_use_id"] is None


def test_same_second_runs_get_different_files(tmp_path, clock):
    suffixes = iter(["aaaa", "aaaa", "bbbb"])
    first = open_trace(tmp_path, clock, suffix=lambda: next(suffixes))
    second = open_trace(tmp_path, clock, suffix=lambda: next(suffixes))
    assert first.path.name.endswith("-aaaa.jsonl")
    assert second.path.name.endswith("-bbbb.jsonl")


def test_open_returns_none_when_the_root_is_unusable(tmp_path, clock):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert RunTrace.open(blocker, "t", clock, LOCAL) is None


def test_the_toolset_wrapper_mirrors_the_toolset_api(tmp_path, clock):
    trace = open_trace(tmp_path, clock)
    inner = Toolset("planner", [make_tool("echo", external=True)])
    wrapped = trace.toolset(inner)
    assert wrapped.names == inner.names
    assert wrapped.schemas(restricted=True) == inner.schemas(restricted=True)
    assert wrapped.reads_web("echo") == inner.reads_web("echo")
    assert wrapped.external("echo") is True and wrapped.external("nope") is False


def write_lines(tmp_path, *lines: str):
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(lines) + "\n")
    return path


RUN = json.dumps({"kind": "run", "format": 1, "task_id": "t"})
MODEL = json.dumps({"kind": "model", "turn": 1})


def test_read_trace_rejects_a_cut_off_last_line(tmp_path):
    path = write_lines(tmp_path, RUN, MODEL, '{"kind": "tool", "na')
    with pytest.raises(TraceFormatError) as info:
        read_trace(path)
    partial = info.value.partial
    assert isinstance(partial, Trace)
    assert partial.run["task_id"] == "t" and len(partial.models) == 1


def test_read_trace_accepts_a_file_without_end(tmp_path):
    trace = read_trace(write_lines(tmp_path, RUN, MODEL))
    assert trace.end is None and len(trace.models) == 1 and trace.tools == ()


def test_read_trace_reads_an_end_line(tmp_path):
    end = json.dumps({"kind": "end", "code": "run_finished"})
    assert read_trace(write_lines(tmp_path, RUN, end)).end == {
        "kind": "end",
        "code": "run_finished",
    }


def test_read_trace_rejects_unknown_format(tmp_path):
    bad = json.dumps({"kind": "run", "format": 2})
    with pytest.raises(TraceFormatError) as info:
        read_trace(write_lines(tmp_path, bad))
    assert info.value.partial is None


def test_read_trace_rejects_an_unknown_kind(tmp_path):
    with pytest.raises(TraceFormatError):
        read_trace(write_lines(tmp_path, RUN, json.dumps({"kind": "zzz"})))
