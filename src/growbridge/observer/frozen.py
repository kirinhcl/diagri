"""Pure rules for finding a frozen sensor reading.

A reading is frozen when its value stays exactly the same across an unbroken run of samples. These
functions only look at ``(timestamp, value)`` pairs; wiring them to stored samples happens
elsewhere.
"""

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

# Derived sensors and the source sensors they are computed from.
DERIVED: dict[str, tuple[str, ...]] = {"vpd": ("temp", "humi")}


@dataclass(frozen=True)
class FlatRun:
    value: float
    first_at: float
    last_at: float


def _is_valid(value: object) -> bool:
    """True for a finite int or float (not bool). Never raises."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:  # an int too large to convert to float
        return False


def flat_tail(points: Sequence[tuple[float, object]], max_gap_seconds: float) -> FlatRun | None:
    """Longest unchanged run ending at the last point, or None if that point is invalid.

    Invalid points inside the run are skipped. The run breaks at a valid point with a different
    value, at time going backwards, or at a gap above ``max_gap_seconds`` measured between
    consecutive valid points.
    """
    if not points:
        return None
    last_at, last_value = points[-1]
    if not isinstance(last_value, int | float) or not _is_valid(last_value):
        return None
    first_at = last_at
    for at, value in reversed(points[:-1]):
        if not _is_valid(value):
            continue  # an invalid sample carries no information; the gap is between valid ones
        gap = first_at - at
        if value != last_value or gap < 0 or gap > max_gap_seconds:
            break
        first_at = at
    return FlatRun(float(last_value), first_at, last_at)


def first_change(points: Sequence[tuple[float, object]], value: float) -> float | None:
    """Time of the first valid point differing from ``value``; invalid points are skipped."""
    for at, candidate in points:
        if _is_valid(candidate) and candidate != value:
            return at
    return None


def sensors_used(sensors: Iterable[str]) -> frozenset[str]:
    """The given sensors plus the source sensors of any derived ones."""
    used = set(sensors)
    for name in tuple(used):
        used.update(DERIVED.get(name, ()))
    return frozenset(used)
