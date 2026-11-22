"""A traced model run on the simulator, and the pre-run copy the dev workbench asks for."""

import sqlite3
from contextlib import closing
from pathlib import Path

from test_e2e_agents import call, design, sheet_json, task

from growbridge.agents.trace import read_trace
from growbridge.sim.llm import ScriptedClient, text_reply, tool_reply


async def _planner_run(world, runtime):
    project, protocol, round_id = await design(world, runtime)
    runtime.tasks.create(task(project, "planner", "ev-plan"))
    sheet = sheet_json(world, project, protocol)
    client = ScriptedClient(
        [
            tool_reply(call("save_plan_draft", round_id=round_id, run_sheet=sheet)),
            text_reply("drafted"),
        ]
    )
    assert await runtime.run_agents(client) == 1


def _trace_files(settings) -> list:
    return sorted((settings.data_dir / "model_traces").rglob("*.jsonl"))


def _stage_count(directory) -> int:
    total = 0
    for path in directory.glob("*.sqlite3"):
        with closing(sqlite3.connect(path)) as conn:  # sqlite3's own `with` never closes
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
            if "wf_stages" in tables:
                total += conn.execute("SELECT COUNT(*) FROM wf_stages").fetchone()[0]
    return total


async def test_pre_run_copy_holds_the_state_before_the_first_model_call(world, settings):
    settings.model_trace = True
    runtime = await world.boot()
    runtime.pre_run_copies = True

    await _planner_run(world, runtime)

    (trace_path,) = _trace_files(settings)
    run = read_trace(trace_path).run
    copy = trace_path.with_suffix(".pre")
    assert run["pre_run_copy"] == copy.name and copy.is_dir()
    assert not (copy / "model_traces").exists()
    assert _stage_count(copy) == 0  # no draft yet when the copy was made
    assert _stage_count(settings.data_dir) == 1  # the live run did save one
    assert oct(copy.stat().st_mode & 0o777) == "0o700"


async def test_serve_settings_never_make_a_copy(world, settings):
    settings.model_trace = True
    runtime = await world.boot()
    assert runtime.pre_run_copies is False

    await _planner_run(world, runtime)

    (trace_path,) = _trace_files(settings)
    assert read_trace(trace_path).run["pre_run_copy"] is None
    assert not list(trace_path.parent.glob("*.pre"))
    assert oct(trace_path.stat().st_mode & 0o777) == "0o600"


async def test_copy_failure_keeps_the_run_and_records_null(world, settings, monkeypatch):
    settings.model_trace = True
    runtime = await world.boot()
    runtime.pre_run_copies = True

    def broken(source, target):
        raise OSError("no space")

    monkeypatch.setattr("growbridge.agents.dispatch.copy_data_dir", broken)

    await _planner_run(world, runtime)

    (trace_path,) = _trace_files(settings)
    trace = read_trace(trace_path)
    assert trace.run["pre_run_copy"] is None
    assert trace.end is not None and trace.end["code"] == "run_finished"
    assert runtime.tasks.get("task-ev-plan").state.value == "done"


async def test_an_uncreatable_trace_root_leaves_the_run_untraced(world, settings):
    settings.model_trace = True
    runtime = await world.boot()
    (settings.data_dir / "model_traces").write_text("a file where the trace root should be")

    await _planner_run(world, runtime)  # the task still runs and nothing is raised

    assert runtime.tasks.get("task-ev-plan").state.value == "done"
    assert (settings.data_dir / "model_traces").is_file()


async def test_header_records_the_settings_but_not_the_token(world, settings):
    settings.model_trace = True
    runtime = await world.boot()

    await _planner_run(world, runtime)

    (trace_path,) = _trace_files(settings)
    recorded = read_trace(trace_path).run["settings"]
    assert recorded == settings.model_dump(mode="json", exclude={"token"})
    assert "token" not in recorded and settings.token not in trace_path.read_text()


async def test_a_relative_data_dir_is_absolute_in_the_header(
    world, settings, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    settings.data_dir = Path("data")
    settings.model_trace = True
    runtime = await world.boot()

    await _planner_run(world, runtime)

    (trace_path,) = _trace_files(settings)
    recorded = read_trace(trace_path).run["data_dir"]
    assert Path(recorded).is_absolute() and recorded == str(Path.cwd() / "data")
