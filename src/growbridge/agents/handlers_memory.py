"""``read_round_history``: every role may read one round of its own project in full (memory design
2026-11-17, section 5.5). Read-only; another project's round reads exactly as an unknown one.
"""

from __future__ import annotations

from growbridge.agents.handlers_common import Deps, ToolInput, bound_task
from growbridge.agents.memory_rounds import round_record
from growbridge.agents.tools import Tool
from growbridge.observer.episodes import project_episodes, stage_window
from growbridge.ports import Denied


class RoundHistoryInput(ToolInput):
    round_id: str


def read_round_history(deps: Deps, data: RoundHistoryInput) -> dict:
    task = bound_task(deps)
    src = deps.memory
    if src is None:
        raise Denied("state", "history is not available")
    record = round_record(src, task.project_id, data.round_id)
    return {**record, "episodes": _round_episodes(src, task.project_id, data.round_id)}


def _round_episodes(src, project_id: str, round_id: str) -> list[dict]:
    """The episodes while this round's stages ran; only those windows are read."""
    store, now = src.workflow.store, src.clock.now()
    started = [s for s in store.stages_of_round(round_id) if s.started_at is not None]
    windows = [stage_window(stage, now) for stage in started]
    if not windows:
        return []
    since, until = min(a for a, _, _ in windows), max(b for _, b, _ in windows)
    reads = (store, src.archive, src.book, project_id, since, until, src.multi_user)
    found = project_episodes(*reads, windows=windows)
    inside = [e for e in found if any(a <= e.start <= b for a, b, _ in windows)]
    return [e.model_dump(mode="json") for e in inside]


def memory_tools(deps: Deps) -> list[Tool]:
    return [
        Tool(
            "read_round_history",
            "Read one earlier round of this project in full: its report (or why it cannot be "
            "used: invalid, held_out, unavailable), the decisions people made and the device's "
            "episodes while it ran. Background only.",
            RoundHistoryInput,
            lambda data: read_round_history(deps, data),
        )
    ]
