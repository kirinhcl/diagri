"""Environment episodes and recurring patterns (memory design 2026-11-17, section 5.3).

Three kinds of episode, all from records the system already keeps:

- ``protection``: a protection rule wrote to a channel (``actions`` with trigger
  ``protect:<rule>``); writes of one rule within ``MERGE_SECONDS`` of each other are one episode.
  The rule's release leaves no record, so a protection episode has no end.
- ``frozen``: a frozen-reading period (``frozen_marks``), from its first flat sample.
- ``data_gap``: a span of this project's stages without countable samples, of at least
  ``GAP_MIN_SECONDS``.

Everything is cut at ``now``: nothing detected, written or sampled after it is used, so a daily
report made late for an earlier day sees only what was known at that day's end. Protection and
gaps belong to the project's own stage windows; a frozen period is about the device and is kept
across projects, without its value outside the project's windows when ``hide_values`` is set.
Patterns are counted by code over the last ``EPISODE_DAYS`` days; nothing here is written by a
model.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from datetime import datetime
from statistics import median
from typing import Any, Literal
from zoneinfo import ZoneInfo

from growbridge.archive.models import Model
from growbridge.observer.metrics import coverage_gaps
from growbridge.workflow.store import FINISHED_STATES

DAY = 86400.0
EPISODE_DAYS = 7
MERGE_SECONDS = 900.0
GAP_MIN_SECONDS = 1800.0
RECUR_DAYS = 3
RECUR_SPREAD_SECONDS = 7200.0
MAX_PATTERNS = 10
MAX_RECURRING_LINES = 3
PROTECT = "protect:"
log = logging.getLogger(__name__)
Window = tuple[float, float, Any]  # (start, end, StageRow)


class Episode(Model):
    kind: Literal["protection", "frozen", "data_gap"]
    subject: str  # the rule id (protection), the sensor (frozen) or "samples" (data_gap)
    start: float
    end: float | None
    in_project: bool
    detail: dict[str, Any]
    notes: tuple[str, ...] = ()


class Pattern(Model):
    kind: str
    subject: str
    days: int
    typical_start: str  # local "HH:MM"
    typical_minutes: float | None
    last: str  # local date
    recurring: bool


def stage_windows(store: Any, project_id: str, now: float) -> tuple[Window, ...]:
    """When each started stage of the project ran, cut at ``now``."""
    rows = store.db.query(
        "SELECT stage_id FROM wf_stages WHERE project_id = ? AND started_at IS NOT NULL"
        " AND started_at < ? ORDER BY started_at",
        (project_id, now),
    )
    return tuple(stage_window(store.stage(row["stage_id"]), now) for row in rows)


def stage_window(stage: Any, now: float) -> Window:
    """When ``stage`` (started) ran: to its end, or to ``now`` while it has not finished."""
    end = stage.state_at if stage.state in FINISHED_STATES else now
    return (stage.started_at, min(end, now), stage)


def project_episodes(
    store: Any,
    archive: Any,
    book: Any,
    project_id: str,
    since: float,
    now: float,
    hide_values: bool,
    windows: Sequence[Window] | None = None,
) -> list[Episode]:
    """Episodes of ``[since, now]`` in ``windows`` (default: the project's stage windows)."""
    if windows is None:
        windows = stage_windows(store, project_id, now)
    found = [
        *_protection(archive, windows, since, now),
        *_frozen(archive, book, windows, since, now, hide_values),
        *_gaps(store, archive, windows, since, now),
    ]
    return sorted(found, key=lambda e: e.start)


# --- protection ----------------------------------------------------------------------------------


def _protection(archive: Any, windows: Sequence[Window], since: float, now: float) -> list[Episode]:
    writes = sorted(
        (record for a, b, stage in windows for record in _writes(archive, stage, a, b, since, now)),
        key=lambda r: (r.trigger, r.created_at),
    )
    episodes: list[Episode] = []
    last: dict[str, float] = {}
    for record in writes:
        rule = record.trigger[len(PROTECT) :]
        if record.created_at - last.get(rule, -MERGE_SECONDS - 1) > MERGE_SECONDS:
            detail = {"channel": record.channel.value, "level": record.planned_level}
            episodes.append(_episode("protection", rule, record.created_at, None, detail))
        last[rule] = record.created_at
    return episodes


def _writes(
    archive: Any, stage: Any, a: float, b: float, since: float, now: float
) -> Iterator[Any]:
    lo, hi = max(a, since), min(b, now)
    if hi <= lo:
        return  # the window is outside the period looked at: nothing is read
    for record in archive.actions_between(stage.experiment_id, lo, hi):
        if record.trigger.startswith(PROTECT):
            yield record


def _episode(kind: str, subject: str, start: float, end: float | None, detail: dict) -> Episode:
    return Episode(kind=kind, subject=subject, start=start, end=end, in_project=True, detail=detail)


# --- frozen --------------------------------------------------------------------------------------


def _frozen(
    archive: Any, book: Any, windows: Sequence[Window], since: float, now: float, hide: bool
) -> list[Episode]:
    found = []
    for period in archive.frozen_periods(since, now):
        if period["opened_at"] > now:
            continue  # not yet detected at ``now``
        closed = _closed_by(period, now)
        end = period["last_at"] if closed else None
        inside = any(period["first_at"] < b and (end or now) > a for a, b, _ in windows)
        detail = {} if hide and not inside else {"value": period["value"]}
        found.append(
            Episode(
                kind="frozen",
                subject=period["sensor"],
                start=period["first_at"],
                end=end,
                in_project=inside,
                detail=detail,
                notes=_notes(book, period, now, closed),
            )
        )
    return found


def _closed_by(period: dict, now: float) -> bool:
    closed_at, last_at = period["closed_at"], period["last_at"]
    return closed_at is not None and closed_at <= now and last_at is not None and last_at <= now


def _notes(book: Any, period: dict, now: float, closed: bool) -> tuple[str, ...]:
    """Read notes of the alert raised for this period, matched on the detection timeline: the
    period's opening and closing records against the alert's raise and resolve times."""
    if book is None:
        return ()
    seen_from, seen_to = period["opened_at"], period["closed_at"] if closed else now
    return tuple(
        n.note
        for n in book.notes_of("frozen_reading", period["sensor"])
        if n.at <= now and n.first_at <= seen_to and (n.resolved_at or now) >= seen_from
    )


# --- gaps ----------------------------------------------------------------------------------------


def _gaps(
    store: Any, archive: Any, windows: Sequence[Window], since: float, now: float
) -> list[Episode]:
    found = []
    for a, b, stage in windows:
        if b < since:
            continue  # ended before the period looked at: its samples are not read
        lo, hi = max(a, since), min(b, now)
        sheet = store.run_sheet(stage.run_sheet_id, stage.run_sheet_version)
        samples = archive.samples(stage.experiment_id, lo, hi)
        for start, end in coverage_gaps(samples, lo, hi, sheet.sampling.max_gap_seconds):
            if end - start >= GAP_MIN_SECONDS:
                found.append(_episode("data_gap", "samples", start, end, {}))
    return found


# --- patterns ------------------------------------------------------------------------------------


def patterns(episodes: Sequence[Episode], now: float, timezone: str) -> list[Pattern]:
    """Groups of the last ``EPISODE_DAYS`` days by kind and subject; recurring ones first."""
    groups: dict[tuple[str, str], list[Episode]] = {}
    for e in episodes:
        if now - EPISODE_DAYS * DAY <= e.start < now:
            groups.setdefault((e.kind, e.subject), []).append(e)
    zone = ZoneInfo(timezone)
    found = [
        _pattern(kind, subject, _occurrences(items), zone)
        for (kind, subject), items in groups.items()
    ]
    found.sort(key=lambda p: (not p.recurring, -p.days, p.kind, p.subject))
    return found[:MAX_PATTERNS]


def _occurrences(items: Sequence[Episode]) -> list[tuple[float, float | None]]:
    """Episodes that follow each other within ``MERGE_SECONDS`` are one occurrence."""
    merged: list[tuple[float, float | None]] = []
    for e in sorted(items, key=lambda e: e.start):
        if merged and e.start - (merged[-1][1] or merged[-1][0]) <= MERGE_SECONDS:
            merged[-1] = (merged[-1][0], e.end)
        else:
            merged.append((e.start, e.end))
    return merged


def _pattern(
    kind: str, subject: str, found: list[tuple[float, float | None]], zone: ZoneInfo
) -> Pattern:
    local = [datetime.fromtimestamp(start, zone) for start, _ in found]
    seconds = [t.hour * 3600 + t.minute * 60 + t.second for t in local]
    middle = circular_median(seconds)
    days = len({t.date() for t in local})
    near = all(_circular(s, middle) <= RECUR_SPREAD_SECONDS for s in seconds)
    lasting = [(end - start) / 60 for start, end in found if end is not None]
    return Pattern(
        kind=kind,
        subject=subject,
        days=days,
        typical_start=f"{int(middle) // 3600:02d}:{int(middle) % 3600 // 60:02d}",
        typical_minutes=median(lasting) if lasting else None,
        last=max(local).date().isoformat(),
        recurring=days >= RECUR_DAYS and near,
    )


def _circular(a: float, b: float) -> float:
    return min(abs(a - b), DAY - abs(a - b))


def circular_median(seconds_of_day: Sequence[float]) -> float:
    """The start with the least summed circular distance to all starts (ties: the earliest)."""
    return min(sorted(seconds_of_day), key=lambda c: sum(_circular(s, c) for s in seconds_of_day))


def recurring_lines(found: Sequence[Pattern]) -> tuple[str, ...]:
    labels = {"protection": "protect:{}", "frozen": "{} frozen", "data_gap": "data gap"}
    return tuple(
        f"{labels.get(p.kind, '{}').format(p.subject)} on {p.days} of the last "
        f"{EPISODE_DAYS} days, around {p.typical_start}"
        for p in found
        if p.recurring
    )[:MAX_RECURRING_LINES]


def recurring_for_report(
    store: Any, archive: Any, book: Any, project_id: str, end: float, timezone: str
) -> tuple[str, ...]:
    """The recurring problems a daily report ending at ``end`` lists, as known at ``end``."""
    since = end - EPISODE_DAYS * DAY
    found = project_episodes(store, archive, book, project_id, since, end, hide_values=False)
    return recurring_lines(patterns(found, end, timezone))


def report_recurring(runtime: Any, stage: Any, end: float, timezone: str) -> tuple[str, ...]:
    """``recurring_for_report`` for the daily report of ``stage``'s project; a failure here is
    logged and leaves the section out, never the report."""
    try:
        reads = (runtime.workflow.store, runtime.archive, runtime.book)
        return recurring_for_report(*reads, stage.project_id, end, timezone)
    except Exception:
        log.exception("the recurring section of the daily report could not be built")
        return ()
