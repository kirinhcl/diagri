"""The levels a run sheet plans for its host-controlled channels over a span of time."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from growbridge.archive.models import RunSheet


def _boundaries(sheet: RunSheet, start: float, end: float) -> list[float]:
    """UTC instants in ``(start, end]`` at which a timed action's local ``HH:MM`` falls. Each is
    built from the local date and clock time, never by adding minutes to an epoch value, so the
    days the clocks change come out right."""
    zone = ZoneInfo(sheet.timezone)
    first = datetime.fromtimestamp(start, zone).date() - timedelta(days=1)
    last = datetime.fromtimestamp(end, zone).date() + timedelta(days=1)
    minutes = sorted({action.minute for action in sheet.timed_actions})
    instants: set[float] = set()
    day = first
    while day <= last:
        for minute in minutes:
            local = datetime(day.year, day.month, day.day, minute // 60, minute % 60, tzinfo=zone)
            instants.add(local.timestamp())
        day += timedelta(days=1)
    return sorted(t for t in instants if start < t <= end)


def planned_series(sheet: RunSheet, start: float, end: float) -> dict[str, list[tuple[float, int]]]:
    """Level each host channel is planned at: a point at ``start`` and one at every action
    boundary up to ``end``, each evaluated by ``expected_levels``. A point at the same level as
    the one before it is dropped."""
    series: dict[str, list[tuple[float, int]]] = {}
    for at in (start, *_boundaries(sheet, start, end)):
        for channel, level in sheet.expected_levels(at).items():
            points = series.setdefault(channel.value, [])
            if not points or points[-1][1] != level:
                points.append((at, level))
    return series
