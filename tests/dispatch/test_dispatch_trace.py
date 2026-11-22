"""Tracing in ``Dispatcher.run_task``: what a trace holds, and that it never changes a run."""

import pytest
from dispatch_helpers import call

from growbridge.agents.conversation import ConversationLog
from growbridge.agents.dispatch import TraceSettings
from growbridge.agents.llm import ModelReply
from growbridge.agents.trace import RunTrace, read_trace
from growbridge.config import RoleModel
from growbridge.sim.llm import ScriptedClient, text_reply, tool_reply

HEADER_FIELDS = {
    "task_id",
    "project_id",
    "role",
    "role_config",
    "system",
    "system_sha256",
    "tools",
    "tools_sha256",
    "user",
    "conversation_seq",
    "clock_synced",
    "data_dir",
    "pre_run_copy",
    "growbridge_version",
    "git_commit",
    "at",
}


class Failing:
    async def create(self, **_kwargs) -> ModelReply:
        raise RuntimeError("overloaded")


def settings(tmp_path) -> TraceSettings:
    return TraceSettings(root=tmp_path / "traces", data_dir=tmp_path / "data")


def traces(tmp_path) -> list:
    return sorted((tmp_path / "traces").rglob("*.jsonl"))


def drafting(env) -> ScriptedClient:
    sheet = env.sheet_json()
    return ScriptedClient(
        [
            tool_reply(call("validate_run_sheet", run_sheet=sheet)),
            tool_reply(call("save_plan_draft", round_id=env.round_id, run_sheet=sheet)),
            text_reply("drafted"),
        ]
    )


def _traced(env, client, tmp_path):
    dispatcher = env.dispatcher(client, trace=settings(tmp_path))
    dispatcher.conversation = ConversationLog(env.db, env.clock)
    return dispatcher


async def test_trace_off_writes_nothing(env, tmp_path):
    env.task("planner")

    await env.dispatcher(ScriptedClient([text_reply("x")])).run_task("task-ev-1")

    assert not (tmp_path / "traces").exists()


async def test_trace_on_writes_a_complete_file(env, tmp_path):
    task = env.task("planner")
    dispatcher = env.dispatcher(drafting(env), trace=settings(tmp_path))

    await dispatcher.run_task(task.id)

    (path,) = traces(tmp_path)
    trace = read_trace(path)
    assert set(trace.run) >= HEADER_FIELDS
    assert trace.run["task_id"] == task.id and trace.run["role"] == "planner"
    assert trace.run["role_config"] == RoleModel().model_dump(mode="json")
    assert trace.run["user"] == dispatcher.message_for(task)
    assert "validate_run_sheet" in trace.run["tools"]
    assert trace.run["pre_run_copy"] is None and trace.run["conversation_seq"] is None
    assert [t["name"] for t in trace.tools] == ["validate_run_sheet", "save_plan_draft"]
    assert trace.end is not None and trace.end["code"] == "run_finished"
    assert trace.end["state"] == "done" and trace.end["turns"] == 3
    assert trace.end["seconds"] >= 0 and "at" in trace.end


@pytest.mark.parametrize(
    "case, code",
    [
        ("stopped", "model_stopped"),
        ("undelivered", "undelivered"),
        ("finished", "run_finished"),
        ("denied", "denied"),
        ("error", "model_unavailable"),
    ],
)
async def test_end_line_carries_each_end_code(env, tmp_path, case, code):
    task = env.task("orchestrator" if case == "finished" else "planner")
    if case == "stopped":
        client = ScriptedClient([ModelReply(stop_reason="max_tokens", text="p", content=[])])
    elif case == "error":
        client = Failing()
    else:
        client = ScriptedClient([text_reply("x")])
    if case == "denied":
        env.db.execute("DELETE FROM call_budget")

    await env.dispatcher(client, trace=settings(tmp_path)).run_task(task.id)

    (path,) = traces(tmp_path)
    end = read_trace(path).end
    assert end is not None and end["code"] == code
    if case in ("denied", "error"):
        assert (end["turns"], end["input_tokens"], end["output_tokens"], end["cost"]) == (0,) * 4


async def test_budget_refusal_records_the_whole_denied(env, tmp_path):
    task = env.task("planner")
    env.db.execute("DELETE FROM call_budget")

    await env.dispatcher(ScriptedClient([]), trace=settings(tmp_path)).run_task(task.id)

    end = read_trace(traces(tmp_path)[0]).end
    assert end is not None and end["denied"]["code"] == "budget"
    assert end["params"] == {"denied_code": "budget"}


def _break_write(monkeypatch):
    def broken(self, line):
        raise OSError("disk full")

    monkeypatch.setattr(RunTrace, "_write", broken)


@pytest.mark.parametrize("failure", ["no_file", "write_error"])
async def test_trace_failure_leaves_the_run_unchanged(env, tmp_path, monkeypatch, failure):
    first = env.task("planner")
    await _traced(env, drafting(env), tmp_path / "x").run_task(first.id)
    log = ConversationLog(env.db, env.clock)
    expected = [(e.kind, e.role) for e in log.entries(env.project_id)]
    second = env.task("planner", event="ev-2")
    if failure == "no_file":
        monkeypatch.setattr(RunTrace, "open", classmethod(lambda cls, *a, **k: None))
    else:
        _break_write(monkeypatch)

    run = await _traced(env, drafting(env), tmp_path).run_task(second.id)

    assert run is not None and run.stop_reason == "end_turn"
    assert env.tasks.get(second.id).state is env.tasks.get(first.id).state
    entries = [(e.kind, e.role) for e in log.entries(env.project_id)]
    assert len(entries) == 2 * len(expected) and entries[len(expected) :] == expected


def test_last_seq_is_none_for_an_empty_project_and_the_max_otherwise(db, clock):
    log = ConversationLog(db, clock)
    assert log.last_seq("p") is None

    log.add("p", "user", "message", "a")
    second = log.add("p", "user", "message", "b")
    log.add("other", "user", "message", "c")

    assert log.last_seq("p") == second
