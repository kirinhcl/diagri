"""Replay a recorded model run on a copy of the data, with nothing that reaches outside."""

from __future__ import annotations

import functools
import secrets
import shutil
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from .agents.replay import (
    ReplayBudget,
    ReplayClock,
    ReplayReport,
    replay_trace,
)
from .agents.trace import PRE_RUN_SUFFIX, Trace, TraceFormatError, read_trace
from .archive.datacopy import copy_data_dir, relocate_paths
from .archive.models import Model
from .config import Settings
from .runtime import Runtime, build_runtime, private_dir
from .runtime_agents import make_dispatcher
from .sim.device import SimulatedTransport

ConfigLoader = Callable[[], Settings]  # loads the configuration file (it may raise)
NO_SETTINGS = (
    "the trace does not record its settings: replaying under the configuration file's "
    "settings, results may differ"
)


class ReplaySource(Model):
    path: Path
    kind: Literal["option", "pre_run_copy", "config"]
    reliable: bool  # only a pre-run copy holds the state the recorded run started from


def is_pre_run_copy(path: Path) -> bool:
    """A directory named ``<stem>.pre`` with a sibling ``<stem>.jsonl``: nothing writes it, so it
    is opened immutably and stays byte for byte as it was."""
    path = Path(path)
    return path.name.endswith(PRE_RUN_SUFFIX) and path.with_suffix(".jsonl").is_file()


def choose_source(
    trace_path: Path, trace: Trace, option: Path | None, config: ConfigLoader
) -> ReplaySource:
    """The ``--data-dir`` option, else the run's own pre-run copy, else the configured data
    directory: only that last one reads the configuration."""
    copy = trace_path.with_suffix(PRE_RUN_SUFFIX)
    if option is not None:
        own = copy.is_dir() and option.resolve() == copy.resolve()
        return ReplaySource(path=option, kind="option", reliable=own)
    if trace.run.get("pre_run_copy") and copy.is_dir():
        return ReplaySource(path=copy, kind="pre_run_copy", reliable=True)
    return ReplaySource(path=config().data_dir, kind="config", reliable=False)


def recorded_settings(trace: Trace) -> Settings | None:
    """The settings the run was recorded under, with a fresh random token (the trace never
    holds one); None for a trace that does not record them."""
    recorded = trace.run.get("settings")
    if recorded is None:
        return None
    if not isinstance(recorded, Mapping):
        raise TraceFormatError("the recorded settings are not an object")
    try:
        return Settings.model_validate({**recorded, "token": secrets.token_urlsafe(32)})
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise TraceFormatError(f"the recorded settings are not valid now: {problems}") from exc


def replay_settings(trace: Trace, config: ConfigLoader) -> tuple[Settings, str | None]:
    """The recorded settings, else the configuration's with a warning saying so."""
    recorded = recorded_settings(trace)
    if recorded is not None:
        return recorded, None
    return config(), NO_SETTINGS


def build_replay_runtime(
    trace: Trace, settings: Settings, copy_dir: Path
) -> tuple[Runtime, ReplayClock]:
    """A runtime on the copy with no notification channel, heartbeat, compute service or device.

    It is never started: replay only needs its stores, tools and dispatcher."""
    own = settings.model_copy(
        update={
            "data_dir": copy_dir,
            "model_trace": False,
            "backup_dir": None,
            "compute_templates_dir": None,
            "compute_member": None,
        }
    )
    clock = ReplayClock(trace.run["at"], trace.run.get("clock_synced"))
    runtime = build_runtime(
        own, lambda _: SimulatedTransport(), clock, channels={}, heartbeats=None
    )
    return runtime, clock


async def _replay_on(
    trace: Trace, settings: Settings, copy: Path, keep_going: bool
) -> ReplayReport:
    old = str(trace.run.get("data_dir") or "")
    if old:
        relocate_paths(copy, old, str(copy))
    runtime, clock = build_replay_runtime(trace, settings, copy)
    work_root = private_dir(copy / "agent_work")

    def make(client, budget: ReplayBudget, roles):
        return make_dispatcher(
            runtime, client, work_root, roles=roles, budget=budget, tracing=False
        )

    try:
        return await replay_trace(trace, make, clock, copy_dir=str(copy), keep_going=keep_going)
    finally:
        close_runtime(runtime)


def close_runtime(runtime: Runtime) -> None:
    """Close what a replay runtime opened: its databases and the bridge's sample store."""
    for database in runtime.databases:
        database.close()
    runtime.bridge.store.close()


async def replay_file(
    trace_path: Path,
    config: ConfigLoader,
    *,
    data_dir: Path | None = None,
    keep_going: bool = False,
    keep_copy: bool = False,
) -> tuple[ReplaySource, ReplayReport, Path | None]:
    """Replay ``trace_path`` on a temporary copy of the chosen source; the source is only read.

    The runtime is built from the settings the run was recorded under. ``config`` loads the
    configuration file; it is called only for the configured data directory or for a trace
    that does not record its settings. Raises ``TraceFormatError`` (or ``OSError``) when the
    trace cannot be read."""
    trace = read_trace(trace_path)  # an unreadable trace raises, nothing is copied
    load = functools.cache(config)  # read at most once
    source = choose_source(trace_path, trace, data_dir, load)
    settings, note = replay_settings(trace, load)
    root = Path(tempfile.mkdtemp(prefix="growbridge-replay-"))
    try:
        copy = root / "data"
        copy_data_dir(source.path, copy, immutable=is_pre_run_copy(source.path))
        report = await _replay_on(trace, settings, copy, keep_going)
    except BaseException:
        shutil.rmtree(root, ignore_errors=True)
        raise
    if note is not None:
        report = report.model_copy(update={"warnings": (note, *report.warnings)})
    if keep_copy:
        return source, report, root
    shutil.rmtree(root, ignore_errors=True)
    return source, report, None
