"""``growbridge trace show`` (no configuration file, no network)."""

from __future__ import annotations

import sys

from trace_sample import write_sample

from growbridge.cli import main


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
