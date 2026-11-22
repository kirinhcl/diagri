"""Tracing in ``Dispatcher.run_task``: what a trace holds, and that it never changes a run."""

import json

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


class FlakyFile:
    """The trace's file object, failing every write of one kind of line (after the header)."""

    def __init__(self, inner, fail_kind: str):
        self._inner, self._fail_kind = inner, fail_kind

    def write(self, text: str) -> int:
        if json.loads(text)["kind"] == self._fail_kind:
            raise OSError("disk full")
        return self._inner.write(text)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _inject(monkeypatch, failure: str) -> None:
    real_open = RunTrace.open.__func__
    if failure == "no_file":
        monkeypatch.setattr(RunTrace, "open", classmethod(lambda cls, *a, **k: None))
        return

    def flaky(cls, *args, **kwargs):
        trace = real_open(cls, *args, **kwargs)
        trace._file = FlakyFile(trace._file, failure)
        return trace

    monkeypatch.setattr(RunTrace, "open", classmethod(flaky))


def _delegated_planner(env, event: str):
    """A planner task the orchestrator delegated, so its end also creates a follow-up."""
    env.task("orchestrator", f"orch-{event}")
    return env.task("planner", event, parent_task_id=f"task-orch-{event}")


def _summary(env, task) -> dict:
    """What a run leaves behind: task state, end entry, conversation, follow-up tasks."""
    entries = ConversationLog(env.db, env.clock).entries(env.project_id)
    mine = [e for e in entries if e.task_id == task.id]
    ends = [e.detail for e in mine if e.kind == "status" and "reason" in e.detail]
    follow_ups = [
        (t.owner_role, t.state.value)
        for t in env.tasks.list(env.project_id)
        if t.trigger_event_id == f"followup:{task.id}"
    ]
    return {
        "state": env.tasks.get(task.id).state,
        "conversation": [(e.kind, e.role, e.text) for e in mine],
        "end": [(d["code"], d["reason"], d["params"]) for d in ends],
        "follow_ups": follow_ups,
    }


@pytest.mark.parametrize("failure", ["no_file", "run", "model", "tool", "end"])
async def test_trace_failure_leaves_the_run_unchanged(env, tmp_path, monkeypatch, failure):
    baseline = _delegated_planner(env, "ev-a")
    untraced = env.dispatcher(drafting(env))
    untraced.conversation = ConversationLog(env.db, env.clock)
    await untraced.run_task(baseline.id)
    expected = _summary(env, baseline)
    assert expected["follow_ups"] and expected["end"][0][0] == "run_finished"
    second = _delegated_planner(env, "ev-b")
    _inject(monkeypatch, failure)

    run = await _traced(env, drafting(env), tmp_path).run_task(second.id)

    assert run is not None and run.stop_reason == "end_turn"
    assert _summary(env, second) == expected
    kinds = [
        json.loads(line)["kind"]
        for f in traces(tmp_path)
        for line in f.read_text().split("\n")
        if line
    ]
    assert failure not in kinds  # the injected failure really hit: that line never reached the file


def test_last_seq_is_none_for_an_empty_project_and_the_max_otherwise(db, clock):
    log = ConversationLog(db, clock)
    assert log.last_seq("p") is None

    log.add("p", "user", "message", "a")
    second = log.add("p", "user", "message", "b")
    log.add("other", "user", "message", "c")

    assert log.last_seq("p") == second
