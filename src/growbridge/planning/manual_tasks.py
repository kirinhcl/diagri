"""The daily occurrences of a run sheet's manual tasks and whether each one was done in time.

Pure functions: the workbench lists the occurrences with their state, a data snapshot freezes
them with the records, and the report counts an experiment whose manual tasks were often not
done in time as a protocol deviation.
"""

from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from growbridge.archive.models import Model, RunSheet, TaskKind, TaskRecord

ON_TIME_SECONDS = 2 * 3600.0  # a task done up to two hours after it was due is on time
EARLY_SECONDS = 3600.0  # it may be recorded up to an hour before it is due
MAX_MISSED_SHARE = 0.1  # above this share of occurrences not done in time: a deviation

Status = Literal["upcoming", "open", "done", "late", "skipped", "missed"]


class Occurrence(Model):
    task_id: str
    kind: TaskKind
    due_at: float  # UTC
    make_up_allowed: bool = False
    seconds: float | None = None


def occurrences(sheet: RunSheet, start: float, end: float) -> tuple[Occurrence, ...]:
    """Every occurrence due in ``[start, end)``, in time order, by the sheet's time zone."""
    zone = ZoneInfo(sheet.timezone)
    first = datetime.fromtimestamp(start, zone).date() - timedelta(days=1)
    last = datetime.fromtimestamp(end, zone).date() + timedelta(days=1)
    found = []
    day = first
    while day <= last:
        for task in sheet.manual_tasks:
            hour, minute = int(task.at[:2]), int(task.at[3:])
            due = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone).timestamp()
            if start <= due < end:
                found.append(
                    Occurrence(
                        task_id=task.id,
                        kind=task.kind,
                        due_at=due,
                        make_up_allowed=task.make_up_allowed,
                        seconds=task.seconds,
                    )
                )
        day += timedelta(days=1)
    return tuple(sorted(found, key=lambda item: (item.due_at, item.task_id)))


def key(task_id: str, due_at: float) -> tuple[str, int]:
    return task_id, round(due_at)


def latest(records: Iterable[TaskRecord]) -> dict[tuple[str, int], TaskRecord]:
    """The record that counts for each occurrence: the one recorded last."""
    found: dict[tuple[str, int], TaskRecord] = {}
    for record in sorted(records, key=lambda r: r.recorded_at):
        found[key(record.task_id, record.due_at)] = record
    return found


def deadline(item: Occurrence, end: float) -> float:
    """The last moment the occurrence counts as done in time. ``end`` is the end of the stage:
    a task that may be made up counts until then."""
    return (end if item.make_up_allowed else item.due_at) + ON_TIME_SECONDS


def status(item: Occurrence, record: TaskRecord | None, now: float, end: float) -> Status:
    last = deadline(item, end)
    if record is not None:
        if record.outcome == "skipped":
            return "skipped"
        return "done" if record.done_at is not None and record.done_at <= last else "late"
    if now < item.due_at:
        return "upcoming"
    return "open" if now <= last else "missed"


def statuses(
    items: Iterable[Occurrence], records: Iterable[TaskRecord], now: float, end: float
) -> list[tuple[Occurrence, TaskRecord | None, Status]]:
    counted = latest(records)
    rows = []
    for item in items:
        record = counted.get(key(item.task_id, item.due_at))
        rows.append((item, record, status(item, record, now, end)))
    return rows


def missed(
    items: Iterable[Occurrence], records: Iterable[TaskRecord], end: float
) -> tuple[int, int, dict[str, int]]:
    """(not done in time, all occurrences, not done in time by kind), judged at ``end``.

    Anything but "done" counts: late, skipped, never recorded.
    """
    rows = statuses(items, records, end + ON_TIME_SECONDS, end)
    not_done = Counter(item.kind for item, _, state in rows if state != "done")
    return sum(not_done.values()), len(rows), dict(sorted(not_done.items()))


def deviates(missed_count: int, total: int) -> bool:
    return total > 0 and missed_count / total > MAX_MISSED_SHARE


def by_kind_text(counts: Mapping[str, int]) -> str:
    return ", ".join(f"{kind} {count}" for kind, count in counts.items())
