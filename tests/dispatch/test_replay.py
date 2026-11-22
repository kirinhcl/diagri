"""Replaying a model trace against the current code (``growbridge.agents.replay``).

A run is recorded with a traced dispatcher on one ``Env``, then replayed on a second ``Env`` built
the same way (other project and round ids) whose clock is the replay clock.
"""

from dataclasses import replace

import pytest
from dispatch_env import Env
from dispatch_helpers import call

from growbridge.agents import handlers_common, handlers_planner
from growbridge.agents.conversation import ConversationLog
from growbridge.agents.dispatch import Dispatcher, TraceSettings
from growbridge.agents.llm import ModelReply
from growbridge.agents.replay import (
    IdMap,
    ReplayClock,
    ReplayToolset,
    mask_ids,
    replay_trace,
    same_result,
)
from growbridge.agents.tools import ToolOutcome, Toolset
from growbridge.agents.trace import Trace, TracingToolset, read_trace
from growbridge.archive.db import Database
from growbridge.ports import Denied
from growbridge.sim.clock import FakeClock
from growbridge.sim.control import FakeControl
from growbridge.sim.llm import ScriptedClient, text_reply, tool_reply
from growbridge.workflow.states import TaskState

TASK_ID = "task-ev-1"


class Failing:
    async def create(self, **_kwargs) -> ModelReply:
        raise RuntimeError("overloaded")


class MovingClock(FakeClock):
    """Wall time that moves a little on every read, as a real clock does during a run."""

    def now(self) -> float:
        self.wall += 0.001
        return self.wall


class FakeSearch:
    def search(self, query: str, limit: int = 5) -> list[dict]:
        return [{"title": "Handbook", "url": "https://example.test/h", "snippet": "lettuce"}]


class ExplodingSearch:
    def __init__(self):
        self.queries: list[str] = []

    def search(self, query: str, limit: int = 5) -> list[dict]:
        self.queries.append(query)
        raise AssertionError("an external tool ran during a replay")


def dispatcher(
    env, client, *, budget=None, roles=None, deps=None, tools=None, trace=None
) -> Dispatcher:
    """A dispatcher as the runtime builds one: context names the round, conversation is kept."""
    return Dispatcher(
        client,
        env.roles if roles is None else roles,
        env.tools(deps) if tools is None else tools,
        env.tasks,
        budget or env.budget,
        env.clock,
        env.db,
        context=lambda task: {"round_id": env.round_id},
        conversation=ConversationLog(env.db, env.clock),
        trace=trace,
    )


def make_for(env, deps=None, tools=None):
    return lambda client, budget, roles: dispatcher(
        env, client, budget=budget, roles=roles, deps=deps, tools=tools
    )


async def record(env, client, tmp_path, *, roles=None, deps=None, tools=None) -> Trace:
    settings = TraceSettings(root=tmp_path / "traces", data_dir=tmp_path / "data")
    traced = dispatcher(env, client, roles=roles, deps=deps, tools=tools, trace=settings)
    await traced.run_task(TASK_ID)
    (path,) = sorted((tmp_path / "traces").rglob("*.jsonl"))
    return read_trace(path)


def with_tool(tools: dict, name: str, **changes) -> dict:
    """The role tools with tool ``name`` changed (as a code change would change it)."""
    return {
        role: [replace(tool, **changes) if tool.name == name else tool for tool in listed]
        for role, listed in tools.items()
    }


def drafting(env) -> ScriptedClient:
    sheet = env.sheet_json()
    return ScriptedClient(
        [
            tool_reply(call("validate_run_sheet", run_sheet=sheet)),
            tool_reply(call("save_plan_draft", "c2", round_id=env.round_id, run_sheet=sheet)),
            text_reply("drafted"),
        ]
    )


def validating(env) -> ScriptedClient:
    """A planner run that only validates: it ends undelivered and writes nothing."""
    sheet = env.sheet_json()
    return ScriptedClient(
        [tool_reply(call("validate_run_sheet", run_sheet=sheet)), text_reply("checked")]
    )


@pytest.fixture
def replay_db(tmp_path):
    database = Database(tmp_path / "replay.db")
    yield database
    database.close()


def fresh_env(replay_db, tmp_path, trace: Trace) -> tuple[Env, ReplayClock]:
    clock = ReplayClock(trace.run["at"], trace.run["clock_synced"])
    env = Env(replay_db, clock, FakeControl(clock), tmp_path / "work-2", tmp_path / "archive-2")
    return env, clock


def refuse(*_args, **_kwargs):
    raise Denied("state", "this check changed after the recording")


async def test_same_code_replays_clean_on_a_fresh_state(env, replay_db, tmp_path):
    env.task("planner")
    trace = await record(env, drafting(env), tmp_path)
    fresh, clock = fresh_env(replay_db, tmp_path, trace)
    fresh.task("planner")
    assert (fresh.project_id, fresh.round_id) != (env.project_id, env.round_id)

    report = await replay_trace(trace, make_for(fresh), clock)

    assert report.warnings == ()
    assert [(s.name, s.same, s.external) for s in report.steps] == [
        ("validate_run_sheet", True, False),
        ("save_plan_draft", True, False),
    ]
    assert report.replayed_end is not None and report.replayed_end.code == "run_finished"
    assert report.recorded_end == trace.end and report.stopped is None
    assert report.exit_code == 0
    assert fresh.workflow.store.find_stage("stage-1") is not None  # the draft really ran
    assert fresh.tasks.get(TASK_ID).state is TaskState.IN_PROGRESS  # a replay never ends a task


async def test_moving_clock_still_replays_clean(db, replay_db, tmp_path):
    moving = MovingClock()
    env = Env(db, moving, FakeControl(moving), tmp_path / "work", tmp_path / "archive")
    env.task("planner")
    trace = await record(env, drafting(env), tmp_path)
    assert trace.tools[0]["at"] > trace.models[0]["at"] > trace.run["at"]
    fresh, clock = fresh_env(replay_db, tmp_path, trace)
    fresh.task("planner")

    report = await replay_trace(trace, make_for(fresh), clock)

    assert [s.same for s in report.steps] == [True, True]
    assert report.exit_code == 0


async def test_a_changed_handler_stops_at_its_step(env, replay_db, tmp_path, monkeypatch):
    env.task("planner")
    trace = await record(env, drafting(env), tmp_path)
    fresh, clock = fresh_env(replay_db, tmp_path, trace)
    fresh.task("planner")
    monkeypatch.setattr(handlers_planner, "check_evidence", refuse)

    report = await replay_trace(trace, make_for(fresh), clock)

    assert len(report.steps) == 1
    step = report.steps[-1]
    assert step.name == "validate_run_sheet" and step.same is False
    assert step.denied_code == "state" and step.replayed is not None
    assert step.recorded == trace.tools[0]["content"]
    assert report.stopped is not None and report.replayed_end is None
    assert report.exit_code == 1
    assert fresh.workflow.store.find_stage("stage-1") is None  # nothing ran after the stop


async def test_keep_going_reports_every_mismatch(env, replay_db, tmp_path, monkeypatch):
    env.task("planner")
    trace = await record(env, drafting(env), tmp_path)
    fresh, clock = fresh_env(replay_db, tmp_path, trace)
    fresh.task("planner")
    monkeypatch.setattr(handlers_planner, "check_evidence", refuse)
    monkeypatch.setattr(handlers_common, "check_sheet", refuse)

    report = await replay_trace(trace, make_for(fresh), clock, keep_going=True)

    assert [(s.name, s.same) for s in report.steps] == [
        ("validate_run_sheet", False),
        ("save_plan_draft", False),
    ]
    assert report.stopped is None
    assert report.replayed_end is not None and report.replayed_end.code == "undelivered"
    assert report.exit_code == 1


async def test_external_handlers_are_never_called(env, replay_db, tmp_path):
    env.task("planner")
    client = ScriptedClient(
        [
            tool_reply(call("search_and_verify_sources", query="lettuce light")),
            text_reply("read"),
        ]
    )
    trace = await record(env, client, tmp_path, deps=env.make_deps(search=FakeSearch()))
    fresh, clock = fresh_env(replay_db, tmp_path, trace)
    fresh.task("planner")
    exploding = ExplodingSearch()

    report = await replay_trace(trace, make_for(fresh, fresh.make_deps(search=exploding)), clock)

    assert exploding.queries == []
    (step,) = report.steps
    assert step.name == "search_and_verify_sources" and step.external and step.same
    assert step.replayed == trace.tools[0]["content"]
    assert report.exit_code == 0


class StricterSearchInput(handlers_planner.SearchInput):
    source: str  # a new required field: the call recorded without it is now refused


def searching_then_saving(env) -> ScriptedClient:
    sheet = env.sheet_json()
    return ScriptedClient(
        [
            tool_reply(call("search_and_verify_sources", query="lettuce light")),
            tool_reply(call("save_plan_draft", "c2", round_id=env.round_id, run_sheet=sheet)),
            text_reply("done"),
        ]
    )


async def test_a_gate_that_now_opens_is_a_mismatch_and_runs_no_external_handler(
    env, replay_db, tmp_path
):
    """A web read hides the write tools for the rest of the run. No role holds both a web tool
    and an external write tool (submit_compute_job), so save_plan_draft is marked external here
    to stand in for one."""
    env.task("planner")
    recorded_tools = with_tool(
        env.tools(env.make_deps(search=FakeSearch())), "save_plan_draft", external=True
    )
    trace = await record(env, searching_then_saving(env), tmp_path, tools=recorded_tools)
    assert trace.tools[1]["is_error"] and "is not available" in trace.tools[1]["content"]
    fresh, clock = fresh_env(replay_db, tmp_path, trace)
    fresh.task("planner")
    saved: list = []
    replay_tools = with_tool(
        fresh.tools(fresh.make_deps(search=ExplodingSearch())),
        "save_plan_draft",
        external=True,
        handler=lambda data: saved.append(data) or {"saved": True},
    )

    unchanged = await replay_trace(trace, make_for(fresh, tools=replay_tools), clock)
    regressed = await replay_trace(
        trace,
        make_for(
            fresh, tools=with_tool(replay_tools, "search_and_verify_sources", reads_web=False)
        ),
        clock,
    )

    assert [s.same for s in unchanged.steps] == [True, True] and unchanged.exit_code == 0
    assert [s.same for s in regressed.steps] == [True, False]
    step = regressed.steps[-1]
    assert step.name == "save_plan_draft" and step.external and step.replayed is None
    assert "gate" in step.note and "not run" in step.note
    assert regressed.stopped is not None and regressed.exit_code == 1
    assert saved == []  # the external handler never ran in either replay


async def test_a_stricter_gate_is_a_mismatch_and_runs_no_external_handler(env, replay_db, tmp_path):
    env.task("planner")
    client = ScriptedClient(
        [tool_reply(call("search_and_verify_sources", query="lettuce light")), text_reply("x")]
    )
    trace = await record(env, client, tmp_path, deps=env.make_deps(search=FakeSearch()))
    fresh, clock = fresh_env(replay_db, tmp_path, trace)
    fresh.task("planner")
    exploding = ExplodingSearch()
    stricter = with_tool(
        fresh.tools(fresh.make_deps(search=exploding)),
        "search_and_verify_sources",
        input_model=StricterSearchInput,
    )

    report = await replay_trace(trace, make_for(fresh, tools=stricter), clock)

    (step,) = report.steps
    assert step.external and not step.same
    assert step.replayed is not None and "invalid input" in step.replayed
    assert exploding.queries == [] and report.exit_code == 1
    assert any("tool definitions" in w for w in report.warnings)


def test_toolset_wrappers_offer_the_whole_toolset_api():
    public = {name for name in dir(Toolset) if not name.startswith("_")}
    assert {"call", "gate", "schemas", "external", "reads_web", "names"} <= public
    for wrapper in (TracingToolset, ReplayToolset):
        assert public <= set(dir(wrapper)), wrapper


async def test_more_model_calls_than_recorded_is_a_mismatch(env, replay_db, tmp_path):
    env.task("planner")
    trace = await record(env, drafting(env), tmp_path)
    cut = trace.model_copy(update={"models": trace.models[:-1]})
    fresh, clock = fresh_env(replay_db, tmp_path, cut)
    fresh.task("planner")

    report = await replay_trace(cut, make_for(fresh), clock)

    assert [s.same for s in report.steps] == [True, True]
    assert report.stopped is not None and "model repl" in report.stopped
    assert report.replayed_end is None
    assert report.exit_code == 1


async def test_budget_refusal_replays_as_the_same_refusal(env, replay_db, tmp_path):
    env.task("planner")
    env.db.execute("DELETE FROM call_budget")
    trace = await record(env, ScriptedClient([]), tmp_path)
    assert trace.end is not None and trace.end["denied"]["code"] == "budget"
    fresh, clock = fresh_env(replay_db, tmp_path, trace)
    fresh.task("planner")  # the fresh state has a budget: the refusal comes from the record

    report = await replay_trace(trace, make_for(fresh), clock)

    assert report.replayed_end is not None and report.replayed_end.code == "denied"
    assert report.replayed_end.params == {"denied_code": "budget"}
    assert report.steps == () and report.exit_code == 0


async def test_unconfigured_role_replays_as_the_same_refusal(env, replay_db, tmp_path):
    env.task("planner")
    trace = await record(env, ScriptedClient([]), tmp_path, roles={})
    assert trace.run["role_config"] is None
    fresh, clock = fresh_env(replay_db, tmp_path, trace)
    fresh.task("planner")

    report = await replay_trace(trace, make_for(fresh), clock)

    assert report.replayed_end is not None
    assert report.replayed_end.params == {"denied_code": "model_role"}
    assert report.warnings == () and report.exit_code == 0


async def test_model_error_replays_as_model_unavailable(env, replay_db, tmp_path):
    env.task("planner")
    trace = await record(env, Failing(), tmp_path)
    assert "error" in trace.models[0]
    fresh, clock = fresh_env(replay_db, tmp_path, trace)
    fresh.task("planner")

    report = await replay_trace(trace, make_for(fresh), clock)

    assert report.replayed_end is not None and report.replayed_end.code == "model_unavailable"
    assert "RuntimeError: overloaded" in report.replayed_end.reason
    assert report.exit_code == 0


async def test_newer_state_warns(env, tmp_path):
    env.task("planner")
    trace = await record(env, validating(env), tmp_path)

    report = await replay_trace(trace, make_for(env), ReplayClock(trace.run["at"]))

    assert len(report.warnings) == 2
    assert any("needs_attention" in w for w in report.warnings)
    assert any("conversation" in w for w in report.warnings)
    assert report.exit_code == 0  # warnings never change the exit code


async def test_incomplete_trace_exits_2(env, tmp_path):
    env.task("planner")
    trace = await record(env, drafting(env), tmp_path)
    cut = trace.model_copy(update={"end": None})

    def never(*_args):
        raise AssertionError("an incomplete record is never replayed")

    report = await replay_trace(cut, never, ReplayClock(trace.run["at"]))

    assert report.exit_code == 2 and report.steps == ()
    assert any("incomplete" in w.lower() for w in report.warnings)


async def test_missing_task_exits_2(env, replay_db, tmp_path):
    env.task("planner")
    trace = await record(env, drafting(env), tmp_path)
    fresh, clock = fresh_env(replay_db, tmp_path, trace)  # no task created here

    report = await replay_trace(trace, make_for(fresh), clock)

    assert report.exit_code == 2 and report.replayed_end is None
    assert any(TASK_ID in w for w in report.warnings)


async def test_a_role_configuration_the_code_no_longer_accepts_exits_2(env, tmp_path):
    env.task("planner")
    trace = await record(env, drafting(env), tmp_path)
    run = {**trace.run, "role_config": {**trace.run["role_config"], "retired_field": 1}}
    old = trace.model_copy(update={"run": run})

    def never(*_args):
        raise AssertionError("no dispatcher is built for a configuration that does not load")

    report = await replay_trace(old, never, ReplayClock(trace.run["at"]))

    assert report.exit_code == 2 and report.replayed_end is None
    assert any("role configuration" in w for w in report.warnings)


async def test_a_different_tool_name_is_a_mismatch(env, replay_db, tmp_path):
    env.task("planner")
    trace = await record(env, drafting(env), tmp_path)
    renamed = {**trace.tools[0], "name": "estimate_sample_size"}
    changed = trace.model_copy(update={"tools": (renamed, *trace.tools[1:])})
    fresh, clock = fresh_env(replay_db, tmp_path, changed)
    fresh.task("planner")

    report = await replay_trace(changed, make_for(fresh), clock)

    (step,) = report.steps
    assert step.name == "validate_run_sheet" and not step.same
    assert "estimate_sample_size" in step.note and step.replayed is None
    assert report.stopped is not None and report.exit_code == 1


async def test_unused_recorded_lines_are_mismatches(env, replay_db, tmp_path):
    env.task("planner")
    trace = await record(env, drafting(env), tmp_path)
    extra_tool = {**trace.tools[-1], "tool_use_id": "c9"}
    extra_model = {**trace.models[-1], "turn": trace.models[-1]["turn"] + 1}
    longer = trace.model_copy(
        update={"tools": (*trace.tools, extra_tool), "models": (*trace.models, extra_model)}
    )
    fresh, clock = fresh_env(replay_db, tmp_path, longer)
    fresh.task("planner")

    report = await replay_trace(longer, make_for(fresh), clock)

    assert [s.same for s in report.steps] == [True, True, False]
    left = report.steps[-1]
    assert left.index == 2 and left.name == "save_plan_draft" and left.replayed is None
    assert left.note
    assert any("model repl" in w for w in report.warnings)
    assert report.replayed_end is not None and report.replayed_end.code == "run_finished"
    assert report.stopped is None and report.exit_code == 1


def test_mask_ids_and_timestamp_tolerance():
    assert mask_ids("draft_" + "a" * 32) == "draft_*"
    assert mask_ids("x draft_" + "A" * 32) == "x draft_" + "A" * 32  # upper case is no id
    rec = {"is_error": False, "content": '{"at": 1795000000.0}', "seconds": 0.2}
    later = ToolOutcome(name="x", content='{"at": 1795000001.1}')
    too_late = ToolOutcome(name="x", content='{"at": 1795000002.0}')
    assert same_result(rec, later, copy_dir="", data_dir="")
    assert not same_result(rec, too_late, copy_dir="", data_dir="")


def test_same_result_compares_errors_paths_and_small_numbers():
    rec = {"is_error": False, "content": '{"path": "/data/a.csv", "n": 3}', "seconds": 0.0}
    moved = ToolOutcome(name="x", content='{"path": "/tmp/copy/a.csv", "n": 3}')
    assert same_result(rec, moved, copy_dir="/tmp/copy", data_dir="/data")
    assert not same_result(rec, moved, copy_dir="", data_dir="")
    near = ToolOutcome(name="x", content='{"path": "/data/a.csv", "n": 3.5}')
    assert not same_result(rec, near, copy_dir="", data_dir="")  # only timestamps get slack
    failed = ToolOutcome(name="x", content=rec["content"], is_error=True)
    assert not same_result(rec, failed, copy_dir="", data_dir="")


def test_id_map_pairs_ids_in_order_and_builds_new_values():
    old_p, new_p = "project_" + "1" * 32, "project_" + "2" * 32
    old_r, new_r = "round_" + "3" * 32, "round_" + "4" * 32
    ids = IdMap()
    ids.learn(f"{old_r} {old_p}", f"{new_r} {new_p}")
    ids.learn("draft_" + "5" * 32, "no ids here")  # counts differ: nothing learned
    assert ids.pairs == {old_r: new_r, old_p: new_p}
    value = {"project_id": old_p, "list": [f"in {old_r}"], "n": 1}

    mapped = ids.apply(value)

    assert mapped == {"project_id": new_p, "list": [f"in {new_r}"], "n": 1}
    assert value == {"project_id": old_p, "list": [f"in {old_r}"], "n": 1}  # not mutated
