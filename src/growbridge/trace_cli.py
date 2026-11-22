"""The ``trace`` subcommand group of the growbridge command line."""

from __future__ import annotations

import asyncio
import difflib
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .agents.replay import ReplayReport, StepResult
from .agents.trace import TraceFormatError, read_trace
from .agents.trace_show import render_trace, strip_controls
from .config import Settings
from .replay_runtime import ReplaySource, replay_file


def add_trace_parser(sub: Any) -> None:
    trace = sub.add_parser("trace", help="Read the model traces of model-role runs")
    trace_sub = trace.add_subparsers(dest="trace_command", required=True)
    show = trace_sub.add_parser("show", help="List one trace step by step")
    show.add_argument("file", type=Path, help="A trace .jsonl file")
    show.add_argument("--full", action="store_true", help="Do not cut long values")
    replay = trace_sub.add_parser("replay", help="Re-run a trace against the current code")
    replay.add_argument("file", type=Path, help="A trace .jsonl file")
    replay.add_argument("--data-dir", type=Path, help="Replay on a copy of this data directory")
    replay.add_argument("--keep-going", action="store_true", help="Go on after a mismatch")
    replay.add_argument("--keep-copy", action="store_true", help="Keep the temporary copy")


def _error(message: str) -> None:
    print(strip_controls(message), file=sys.stderr)


def _show(args: Any) -> int:
    try:
        print(render_trace(read_trace(args.file), full=args.full), end="")
    except TraceFormatError as exc:
        if exc.partial is not None:
            print(render_trace(exc.partial, full=args.full), end="")
        _error(f"{args.file}: {exc}")
        return 2
    except (OSError, UnicodeDecodeError) as exc:
        _error(f"cannot read {args.file}: {exc}")
        return 2
    return 0


def _pretty(text: str | None) -> list[str]:
    """Indented JSON lines when ``text`` parses, else the text's own lines."""
    text = text or ""
    try:
        text = json.dumps(json.loads(text), indent=2, sort_keys=True, ensure_ascii=False)
    except ValueError:
        pass
    return text.splitlines()


def _step_line(step: StepResult) -> str:
    where = " (external)" if step.external else ""
    head = f"  step {step.index} turn {step.turn} {step.name}{where}: "
    return strip_controls(head + ("ok" if step.same else "DIFFERENT"))


def _mismatch_lines(step: StepResult) -> list[str]:
    diff = difflib.unified_diff(
        _pretty(step.recorded), _pretty(step.replayed), "recorded", "replayed", lineterm=""
    )
    lines = [f"First difference: {step.name}", "  input:"]
    lines += [f"    {line}" for line in _pretty(json.dumps(step.input, default=str))]
    if step.denied_code:
        lines.append(f"  replayed refusal: {step.denied_code}")
    if step.note:
        lines.append(f"  note: {step.note}")
    lines += [f"  {line}" for line in diff]
    return [strip_controls(line) for line in lines]


def _end_line(label: str, end: object) -> str:
    code = end.get("code") if isinstance(end, dict) else getattr(end, "code", None)
    return strip_controls(f"{label} end: {code if code is not None else 'none'}")


def _print_report(source: ReplaySource, report: ReplayReport, copy: Path | None) -> None:
    print(strip_controls(f"Replaying on a copy of {source.path} ({source.kind})"))
    if not source.reliable:
        print(f"Replay from {source.kind}: results are for reference only (no pre-run copy).")
    for warning in report.warnings:
        print(strip_controls(warning))
    for step in report.steps:
        print(_step_line(step))
    first = next((step for step in report.steps if not step.same), None)
    if first is not None:
        print("\n".join(_mismatch_lines(first)))
    if report.stopped:
        print(strip_controls(f"Stopped: {report.stopped}"))
    print(_end_line("Recorded", report.recorded_end))
    print(_end_line("Replayed", report.replayed_end))
    if copy is not None:
        print(strip_controls(f"Copy kept at {copy}"))


def _replay(args: Any, load_settings: Callable[[], Settings]) -> int:
    try:
        settings = load_settings()
    except Exception as exc:  # a missing or invalid config: one line, exit 2
        reason = (str(exc).splitlines() or [type(exc).__name__])[0]
        _error(f"cannot load the configuration: {reason}")
        return 2
    try:
        outcome = asyncio.run(
            replay_file(
                args.file,
                settings,
                data_dir=args.data_dir,
                keep_going=args.keep_going,
                keep_copy=args.keep_copy,
            )
        )
    except TraceFormatError as exc:
        _error(f"{args.file}: {exc}")
        return 2
    except (OSError, UnicodeDecodeError) as exc:
        _error(f"cannot replay {args.file}: {exc}")
        return 2
    _print_report(*outcome)
    return outcome[1].exit_code


def run_trace(args: Any, load_settings: Callable[[], Settings]) -> int:
    """Run a ``trace`` subcommand; ``show`` never needs the configuration."""
    if args.trace_command == "show":
        return _show(args)
    if args.trace_command == "replay":
        return _replay(args, load_settings)
    raise ValueError(f"unknown trace command {args.trace_command!r}")
