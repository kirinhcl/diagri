"""``growbridge trace show`` (no configuration file) and ``trace replay`` errors (no network)."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest
from trace_sample import write_sample

from growbridge.agents.replay import ReplayReport, StepResult
from growbridge.cli import main
from growbridge.replay_runtime import ReplaySource
from growbridge.trace_cli import _print_report, run_trace


def run(monkeypatch, *args) -> int:
    monkeypatch.setattr(sys, "argv", ["growbridge", "--config", "/nonexistent/c.toml", *args])
    try:
        main()
    except SystemExit as exc:
        return exc.code
    return 0


async def test_cli_show_needs_no_config(tmp_path, clock, capsys, monkeypatch):
    path = await write_sample(tmp_path, clock)
    assert run(monkeypatch, "trace", "show", str(path)) == 0
    assert "run_finished" in capsys.readouterr().out


async def test_cli_show_full_flag(tmp_path, clock, capsys, monkeypatch):
    path = await write_sample(tmp_path, clock)
    assert run(monkeypatch, "trace", "show", str(path), "--full") == 0
    assert "use --full" not in capsys.readouterr().out


async def test_cli_show_cut_off_file_exits_2(tmp_path, clock, capsys, monkeypatch):
    path = await write_sample(tmp_path, clock, ended=False)
    path.write_text(path.read_text() + "{not json\n")
    assert run(monkeypatch, "trace", "show", str(path)) == 2
    captured = capsys.readouterr()
    assert "Record incomplete" in captured.out and "not valid JSON" in captured.err


def test_cli_show_missing_file_exits_2(tmp_path, capsys, monkeypatch):
    assert run(monkeypatch, "trace", "show", str(tmp_path / "none.jsonl")) == 2
    captured = capsys.readouterr()
    assert captured.err.strip() and "Traceback" not in captured.err


def test_cli_show_binary_file_exits_2(tmp_path, capsys, monkeypatch):
    path = tmp_path / "bin.jsonl"
    path.write_bytes(b"\xff\xfe\x00\x80")
    assert run(monkeypatch, "trace", "show", str(path)) == 2
    assert capsys.readouterr().err.strip()


def test_cli_show_wrong_format_exits_2(tmp_path, capsys, monkeypatch):
    path = tmp_path / "x.jsonl"
    path.write_text("{}\n")
    assert run(monkeypatch, "trace", "show", str(path)) == 2
    assert capsys.readouterr().err.strip()


def test_importing_the_trace_commands_does_not_import_the_runtime():
    code = (
        "import sys, growbridge.trace_cli\n"
        "heavy = ('growbridge.runtime', 'growbridge.replay_runtime', 'fastapi')\n"
        "print([name for name in heavy if name in sys.modules])"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert done.stdout.strip() == "[]"


def replay_args(path: Path, data_dir: Path | None = None) -> Namespace:
    return Namespace(
        trace_command="replay", file=path, data_dir=data_dir, keep_going=False, keep_copy=False
    )


def test_cli_replay_of_a_corrupt_database_is_one_line_and_exit_2(tmp_path, clock, settings, capsys):
    path = asyncio.run(write_sample(tmp_path / "traces", clock))
    source = tmp_path / "source"
    source.mkdir()
    (source / "archive.sqlite3").write_bytes(b"this is not a database\n" * 200)

    assert run_trace(replay_args(path, source), lambda: settings) == 2

    err = capsys.readouterr().err
    assert err.startswith(f"cannot replay {path}: DatabaseError: ")
    assert len(err.strip().splitlines()) == 1 and "Traceback" not in err


def test_unused_model_replies_are_a_difference_line_after_the_steps(tmp_path, capsys):
    step = StepResult(
        index=0,
        turn=1,
        name="echo",
        external=False,
        same=True,
        recorded="r",
        replayed="r",
        denied_code=None,
    )
    report = ReplayReport(
        warnings=(),
        steps=(step,),
        recorded_end={"code": "run_finished"},
        replayed_end=None,
        stopped=None,
        exit_code=1,
        unused_replies=2,
    )

    _print_report(ReplaySource(path=tmp_path, kind="pre_run_copy", reliable=True), report, None)

    lines = capsys.readouterr().out.splitlines()
    unused = [n for n, line in enumerate(lines) if "unused model replies: 2" in line]
    assert len(unused) == 1 and "DIFFERENT" in lines[unused[0]]
    assert lines[unused[0] - 1].startswith("  step 0 turn 1 echo")


def test_cli_replay_lets_an_interrupt_through(tmp_path, settings, monkeypatch):
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("growbridge.replay_runtime.replay_file", interrupted)

    with pytest.raises(KeyboardInterrupt):
        run_trace(replay_args(tmp_path / "t.jsonl"), lambda: settings)
