"""Daily environment metrics (architecture doc section 8.3).

Means, DLI and out-of-range time are time-weighted: each planned sample holds its value until the
next planned sample, but never longer than ``max_gap_seconds``. What is left uncovered is listed as
a gap. Active queries (``source == "query"``), unsynced clocks and invalid samples carry no weight.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from growbridge.archive.models import Model, SampleRecord

PPFD_KEY = "ppfd"
LIGHT_KEY = "light"
EPSILON = 1e-9

Segment = tuple[float, float, SampleRecord]


class Gap(Model):
    start_offset: float  # seconds after local midnight
    end_offset: float


class DailyMetrics(Model):
    date: str
    timezone: str
    coverage: float  # fraction of the local day covered by held samples
    sample_count: int
    means: dict[str, float]
    out_of_range_seconds: dict[str, float]
    dli: float | None  # mol m-2 d-1
    gaps: tuple[Gap, ...]


def day_bounds(day: date, timezone: str) -> tuple[float, float]:
    zone = ZoneInfo(timezone)
    start = datetime(day.year, day.month, day.day, tzinfo=zone).timestamp()
    following = day + timedelta(days=1)
    end = datetime(following.year, following.month, following.day, tzinfo=zone).timestamp()
    return start, end


def _stamp(sample: SampleRecord) -> float:
    return sample.captured_at if sample.captured_at is not None else sample.received_at


def _counts(sample: SampleRecord) -> bool:
    return sample.clock_synced and sample.quality == "ok" and sample.source == "planned"


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _segments(
    samples: Sequence[SampleRecord], start: float, end: float, max_gap: float
) -> list[Segment]:
    """Held interval of every sample, clipped to the day and cut at ``max_gap``."""
    ordered = sorted((s for s in samples if start <= _stamp(s) < end), key=_stamp)
    result: list[Segment] = []
    earlier = [s for s in samples if _stamp(s) < start]
    if earlier:  # the last sample before midnight still holds while the gap allows
        prior = max(earlier, key=_stamp)
        reach = _stamp(prior) + max_gap
        if reach > start:
            first = _stamp(ordered[0]) if ordered else end
            result.append((start, min(reach, first, end), prior))
    for index, sample in enumerate(ordered):
        at = _stamp(sample)
        following = _stamp(ordered[index + 1]) if index + 1 < len(ordered) else at + max_gap
        result.append((at, min(following, at + max_gap, end), sample))
    return result


def coverage_gaps(
    samples: Sequence[SampleRecord], start: float, end: float, max_gap: float
) -> tuple[tuple[float, float], ...]:
    """Uncovered spans of ``[start, end)`` in absolute time, counting only the samples the daily
    metrics count (planned, clock synced, quality ok)."""
    segments = _segments([s for s in samples if _counts(s)], start, end, max_gap)
    return tuple(
        (start + g.start_offset, start + g.end_offset) for g in _gaps(segments, start, end)
    )


def _gaps(segments: Sequence[Segment], start: float, end: float) -> tuple[Gap, ...]:
    gaps: list[Gap] = []
    cursor = start
    for begin, finish, _ in segments:
        if begin - cursor > EPSILON:
            gaps.append(Gap(start_offset=cursor - start, end_offset=begin - start))
        cursor = max(cursor, finish)
    if end - cursor > EPSILON:
        gaps.append(Gap(start_offset=cursor - start, end_offset=end - start))
    return tuple(gaps)


def _light(sample: SampleRecord, per_percent: float | None) -> float | None:
    direct = _number(sample.data.get(PPFD_KEY))
    if direct is not None:
        return direct
    level = _number(sample.data.get(LIGHT_KEY))
    if level is None or per_percent is None:
        return None
    return level * per_percent


def _weighted(
    segments: Sequence[Segment], value_of: Callable[[SampleRecord], float | None]
) -> list[tuple[float, float]]:
    pairs = []
    for begin, finish, sample in segments:
        value = value_of(sample)
        if value is not None and finish > begin:
            pairs.append((value, finish - begin))
    return pairs


def _mean(pairs: Sequence[tuple[float, float]]) -> float | None:
    total = sum(seconds for _, seconds in pairs)
    return sum(value * seconds for value, seconds in pairs) / total if total > 0 else None


def _sensor_stats(
    segments: Sequence[Segment], ranges: Mapping[str, tuple[float, float]]
) -> tuple[dict[str, float], dict[str, float]]:
    keys = sorted({k for _, _, s in segments for k, v in s.data.items() if _number(v) is not None})
    means: dict[str, float] = {}
    outside: dict[str, float] = {}
    for key in keys:
        pairs = _weighted(segments, lambda s, k=key: _number(s.data.get(k)))  # type: ignore[misc]
        mean = _mean(pairs)
        if mean is not None:
            means[key] = mean
        if key in ranges:
            low, high = ranges[key]
            outside[key] = sum(sec for value, sec in pairs if not low <= value <= high)
    return means, outside


def compute_daily_metrics(
    samples: Sequence[SampleRecord],
    day: date,
    timezone: str,
    max_gap_seconds: float,
    ranges: Mapping[str, tuple[float, float]],
    ppfd_per_percent: float | None = None,
) -> DailyMetrics:
    start, end = day_bounds(day, timezone)
    segments = _segments([s for s in samples if _counts(s)], start, end, max_gap_seconds)
    means, outside = _sensor_stats(segments, ranges)
    light = _weighted(segments, lambda s: _light(s, ppfd_per_percent))
    covered = sum(finish - begin for begin, finish, _ in segments)
    return DailyMetrics(
        date=day.isoformat(),
        timezone=timezone,
        coverage=covered / (end - start),
        sample_count=len(segments),
        means=means,
        out_of_range_seconds=outside,
        dli=sum(v * sec for v, sec in light) / 1e6 if light else None,
        gaps=_gaps(segments, start, end),
    )
