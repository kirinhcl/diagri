"""The ``history`` a model task starts with (memory design 2026-11-17, section 5.4).

Computed by code from stored records and read-only for the model: the project's closed rounds,
the device's recurring problems and recent episodes, and the notes people wrote about the device.
Bounded to ``HISTORY_CHARS`` characters of JSON, trimmed least important first. A history that
cannot be built never stops the task: it becomes ``{"error": "history unavailable"}``.
"""

from __future__ import annotations

import copy
import json
import logging
from collections.abc import Callable, Collection
from datetime import datetime
from zoneinfo import ZoneInfo

from growbridge.agents.memory_rounds import round_summaries
from growbridge.agents.memory_sources import MemorySources
from growbridge.observer.episodes import DAY, EPISODE_DAYS, Episode, patterns, project_episodes

log = logging.getLogger(__name__)

HISTORY_CHARS = 6000
NOTE_DAYS = 30
MAX_EPISODES = 10
MAX_NOTES = 5
UNAVAILABLE = {"error": "history unavailable"}


def build_history(src: MemorySources, project_id: str, skip_rounds: Collection[str]) -> dict:
    try:
        return trim(_history(src, project_id, skip_rounds))
    except Exception:  # background only: the task goes on without it
        log.exception("the history of project %s could not be built", project_id)
        return dict(UNAVAILABLE)


def _history(src: MemorySources, project_id: str, skip: Collection[str]) -> dict:
    now = src.clock.now()
    since = now - EPISODE_DAYS * DAY
    store = src.workflow.store
    found = project_episodes(store, src.archive, src.book, project_id, since, now, src.multi_user)
    newest = sorted(found, key=lambda e: e.start, reverse=True)[:MAX_EPISODES]
    return {
        "rounds": round_summaries(src, project_id, skip),
        "patterns": [p.model_dump(mode="json") for p in patterns(found, now, src.timezone)],
        "episodes": [episode_line(e, src.timezone) for e in newest],
        "notes": _notes(src, now),
    }


def _notes(src: MemorySources, now: float) -> list[dict]:
    if src.notes is None or src.device_id is None:
        return []
    recent = src.notes.recent(src.device_id, since=now - NOTE_DAYS * DAY, limit=MAX_NOTES)
    zone = ZoneInfo(src.timezone)
    return [
        {"at": _local(n.at, zone), "by": n.actor, "sensor": n.sensor, "text": n.text}
        for n in recent
    ]


def _local(at: float, zone: ZoneInfo) -> str:
    return datetime.fromtimestamp(at, zone).strftime("%Y-%m-%d %H:%M")


def episode_line(e: Episode, timezone: str) -> str:
    """One line per episode, local time first."""
    when = _local(e.start, ZoneInfo(timezone))
    minutes = None if e.end is None else round((e.end - e.start) / 60)
    if e.kind == "protection":
        return f"{when} protect:{e.subject} {e.detail['channel']} -> {e.detail['level']}"
    if e.kind == "data_gap":
        return f"{when} no countable samples for {minutes} min"
    value = f" at {e.detail['value']:g}" if "value" in e.detail else ""
    span = " (still frozen)" if minutes is None else f" for {minutes} min"
    notes = f"; notes: {' | '.join(e.notes)}" if e.notes else ""
    return f"{when} {e.subject} frozen{value}{span}{notes}"


# --- size bound ----------------------------------------------------------------------------------


def trim(history: dict, limit: int = HISTORY_CHARS) -> dict:
    """Drop entries until the JSON fits: episodes, then notes, then each round's decisions, then
    patterns; the rounds themselves (oldest first) only when nothing else is left."""
    trimmed = copy.deepcopy(history)
    steps: tuple[Callable[[dict], bool], ...] = (
        lambda h: _pop(h["episodes"]),
        lambda h: _pop(h["notes"]),
        _drop_decision,
        lambda h: _pop(h["patterns"]),
        lambda h: _pop(h["rounds"]),
    )
    for step in steps:
        while _size(trimmed) > limit and step(trimmed):
            pass
    return trimmed


def _size(history: dict) -> int:
    return len(json.dumps(history, ensure_ascii=False))


def _pop(items: list) -> bool:
    """Drop the last (oldest or least important) entry; False when there is none."""
    if not items:
        return False
    items.pop()
    return True


def _drop_decision(history: dict) -> bool:
    """The oldest decision of the round that has the most."""
    rounds = [r for r in history["rounds"] if r.get("decisions")]
    if not rounds:
        return False
    return _pop(max(rounds, key=lambda r: len(r["decisions"]))["decisions"])
