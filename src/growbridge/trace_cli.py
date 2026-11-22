"""The ``trace`` subcommand group of the growbridge command line."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .agents.trace import TraceFormatError, read_trace
from .agents.trace_show import render_trace, strip_controls
from .config import Settings


def add_trace_parser(sub: Any) -> None:
    trace = sub.add_parser("trace", help="Read the model traces of model-role runs")
    trace_sub = trace.add_subparsers(dest="trace_command", required=True)
    show = trace_sub.add_parser("show", help="List one trace step by step")
    show.add_argument("file", type=Path, help="A trace .jsonl file")
    show.add_argument("--full", action="store_true", help="Do not cut long values")


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


def run_trace(args: Any, load_settings: Callable[[], Settings]) -> int:
    """Run a ``trace`` subcommand; ``show`` never needs the configuration."""
    if args.trace_command == "show":
        return _show(args)
    raise ValueError(f"unknown trace command {args.trace_command!r}")
