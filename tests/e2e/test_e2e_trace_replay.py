"""Replay a traced planner run on a copy of the data: clean, read-only, nothing started."""

import asyncio
import gc
import hashlib
import json
import shutil
import sys
import warnings
from argparse import Namespace

from test_e2e_trace_record import _planner_run, _trace_files

from growbridge.agents.trace import read_trace
from growbridge.archive.datacopy import copy_data_dir, relocate_paths
from growbridge.archive.models import Artifact
from growbridge.cli import main
from growbridge.replay_runtime import build_replay_runtime, close_runtime, replay_file
from growbridge.runtime import Runtime, build_runtime
from growbridge.trace_cli import run_trace


async def _traced(world, settings):
    settings.model_trace = True
    runtime = await world.boot()
    runtime.pre_run_copies = True
    await _planner_run(world, runtime)
    (trace_path,) = _trace_files(settings)
    return runtime, trace_path


def _digests(root, live: bool = False) -> dict:
    """sha256 of every file; for a directory a running runtime holds open, SQLite's own
    -shm/-wal bookkeeping files (which any reader of a live database touches) are left out."""
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file() and not (live and p.name.endswith(("-shm", "-wal")))
    }


async def test_end_to_end_replay_from_the_pre_run_copy_is_clean(world, settings):
    _, trace_path = await _traced(world, settings)

    source, report, copy = await replay_file(trace_path, lambda: settings)

    assert source.kind == "pre_run_copy" and source.reliable
    assert report.exit_code == 0, report
    assert report.steps and all(step.same for step in report.steps)
    assert copy is None


async def test_replay_uses_the_recorded_settings_not_the_configured_ones(
    world, settings, tmp_path, monkeypatch
):
    _, trace_path = await _traced(world, settings)
    other = settings.model_copy(
        update={
            "device": "OTHER-DEVICE",
            "report_timezone": "Europe/Helsinki",
            "data_dir": tmp_path / "elsewhere",
        }
    )
    built = []

    def spy(own, *args, **kwargs):
        built.append(own)
        return build_runtime(own, *args, **kwargs)

    monkeypatch.setattr("growbridge.replay_runtime.build_runtime", spy)
    loads = []

    def config():
        loads.append(other)
        return other

    source, report, _ = await replay_file(trace_path, config)

    assert source.kind == "pre_run_copy" and source.reliable
    assert not loads  # with a pre-run copy the configuration file is never read
    assert report.warnings == () and report.exit_code == 0, report
    (own,) = built
    assert (own.device, own.report_timezone) == (settings.device, settings.report_timezone)
    assert own.token != settings.token and len(own.token) >= 24  # a fresh one


async def test_a_trace_without_settings_replays_under_the_config_with_a_warning(world, settings):
    _, trace_path = await _traced(world, settings)
    lines = trace_path.read_text().splitlines()
    run = json.loads(lines[0])
    del run["settings"]
    trace_path.write_text("\n".join([json.dumps(run), *lines[1:]]) + "\n")
    loads = []

    def config():
        loads.append(settings)
        return settings

    source, report, _ = await replay_file(trace_path, config)

    assert source.kind == "pre_run_copy" and len(loads) == 1
    assert any("settings" in warning for warning in report.warnings)
    assert report.exit_code == 0, report


async def test_cli_replays_a_workbench_trace_without_a_config_file(
    world, settings, capsys, monkeypatch
):
    _, trace_path = await _traced(world, settings)
    argv = ["growbridge", "--config", "/nonexistent/c.toml", "trace", "replay", str(trace_path)]
    monkeypatch.setattr(sys, "argv", argv)

    def run() -> object:
        try:
            main()
        except SystemExit as exc:
            return exc.code
        return 0

    assert await asyncio.to_thread(run) == 0  # main drives its own event loop
    captured = capsys.readouterr()
    assert "pre_run_copy" in captured.out and "configuration" not in captured.err


async def test_replay_closes_every_database_it_opened(world, settings):
    _, trace_path = await _traced(world, settings)
    gc.collect()  # whatever earlier tests left behind is reported before, not inside, the check

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ResourceWarning)
        await replay_file(trace_path, lambda: settings)
        gc.collect()

    unclosed = [str(w.message) for w in caught if issubclass(w.category, ResourceWarning)]
    assert not [message for message in unclosed if "unclosed database" in message]


async def test_source_and_pre_run_copy_are_unchanged(world, settings):
    _, trace_path = await _traced(world, settings)
    pre = trace_path.with_suffix(".pre")
    before = (_digests(pre), _digests(settings.data_dir, live=True))

    await replay_file(trace_path, lambda: settings)
    await replay_file(trace_path, lambda: settings, data_dir=settings.data_dir)

    assert _digests(pre) == before[0]  # a pre-run copy stays byte for byte, side files included
    assert _digests(settings.data_dir, live=True) == before[1]


async def test_temporary_copy_is_removed_unless_keep_copy(world, settings):
    _, trace_path = await _traced(world, settings)

    _, _, gone = await replay_file(trace_path, lambda: settings)
    _, _, kept = await replay_file(trace_path, lambda: settings, keep_copy=True)

    assert gone is None
    try:
        assert kept is not None and (kept / "data").is_dir()
        assert oct(kept.stat().st_mode & 0o777) == "0o700"
    finally:
        shutil.rmtree(kept, ignore_errors=True)


async def test_replay_runtime_is_never_started_and_has_no_outside_backends(
    world, settings, tmp_path, monkeypatch
):
    _, trace_path = await _traced(world, settings)
    trace = read_trace(trace_path)

    async def forbidden(self):
        raise AssertionError("the replay runtime must never start")

    monkeypatch.setattr(Runtime, "start", forbidden)
    _, report, _ = await replay_file(trace_path, lambda: settings)
    assert report.exit_code == 0

    runtime, _ = build_replay_runtime(trace, settings, tmp_path / "copy")
    try:
        assert runtime.compute is None
        assert not runtime.channels
        assert runtime.settings.model_trace is False
        assert runtime.settings.backup_dir is None
        assert runtime.settings.data_dir == tmp_path / "copy"
    finally:
        close_runtime(runtime)


async def test_stored_report_paths_follow_the_copy(world, settings, tmp_path):
    """A report is stored with an absolute path under the source; on the copy that path is
    rewritten so the file reads there (stands in for replaying a traced read_artifact)."""
    runtime, trace_path = await _traced(world, settings)
    report_file = settings.data_dir / "archive" / "report.md"
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text("findings")
    runtime.archive.add_artifact(
        Artifact(
            id="art-1",
            task_id="task-ev-plan",
            kind="report",
            path=str(report_file),
            sha256=hashlib.sha256(b"findings").hexdigest(),
            label="exploratory",
        )
    )
    trace = read_trace(trace_path)
    copy = tmp_path / "copy"
    copy_data_dir(settings.data_dir, copy)
    relocate_paths(copy, trace.run["data_dir"], str(copy))

    replay_runtime, _ = build_replay_runtime(trace, settings, copy)
    try:
        stored = replay_runtime.archive.artifact("art-1")
        assert stored is not None
        assert stored.path == str(copy / "archive" / "report.md")
        assert (copy / "archive" / "report.md").read_text() == "findings"
    finally:
        close_runtime(replay_runtime)


async def test_without_a_pre_run_copy_the_source_is_unreliable(world, settings):
    _, trace_path = await _traced(world, settings)
    shutil.rmtree(trace_path.with_suffix(".pre"))

    source, _, _ = await replay_file(trace_path, lambda: settings)

    assert source.kind == "config" and not source.reliable


def _args(path):
    return Namespace(
        trace_command="replay", file=path, data_dir=None, keep_going=False, keep_copy=False
    )


async def test_cli_replay_exit_codes(world, settings, capsys, monkeypatch):
    _, trace_path = await _traced(world, settings)

    async def run(path):  # run_trace drives its own event loop, so it runs in a thread
        return await asyncio.to_thread(run_trace, _args(path), lambda: settings)

    assert await run(trace_path) == 0
    out = capsys.readouterr().out
    assert "pre_run_copy" in out and "ok" in out and "Replay from" not in out

    monkeypatch.setattr("growbridge.agents.replay.same_result", lambda *a, **k: False)
    assert await run(trace_path) == 1
    out = capsys.readouterr().out
    assert "DIFFERENT" in out and "First difference: save_plan_draft" in out
    assert '"round_id"' in out  # the recorded tool input is shown, indented
    monkeypatch.undo()

    cut = trace_path.with_name("cut.jsonl")
    cut.write_text("\n".join(trace_path.read_text().splitlines()[:2]) + "\n{broken\n")
    assert await run(cut) == 2
    captured = capsys.readouterr()
    assert captured.out == ""  # no source line, no report for a file that cannot be read
    assert captured.err.startswith(f"{cut}: ") and "not valid JSON" in captured.err
    assert "Traceback" not in captured.err


async def test_data_dir_option_on_a_pre_run_copy_leaves_it_byte_identical(world, settings):
    _, trace_path = await _traced(world, settings)
    pre = trace_path.with_suffix(".pre")
    before = _digests(pre)

    source, report, _ = await replay_file(trace_path, lambda: settings, data_dir=pre)

    assert source.kind == "option" and source.reliable  # the trace's own pre-run copy
    assert report.exit_code == 0
    assert _digests(pre) == before  # side files included: no -wal or -shm appeared


async def test_data_dir_option_elsewhere_is_not_reliable(world, settings):
    _, trace_path = await _traced(world, settings)

    source, _, _ = await replay_file(trace_path, lambda: settings, data_dir=settings.data_dir)

    assert source.kind == "option" and not source.reliable
