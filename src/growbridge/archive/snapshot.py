"""Freeze the inputs of one analysis (architecture doc §11.1, §11.3).

A snapshot is a directory of JSON-lines files plus a manifest holding every file's SHA-256.
Late additions never change a snapshot; freezing again writes a new version.
"""

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from growbridge.archive.clock import Clock
from growbridge.archive.ids import canonical_json, file_digest, new_id
from growbridge.archive.models import ManualMeasurement, Model, SampleRecord, Snapshot
from growbridge.archive.store import Archive
from growbridge.ports import Denied
from growbridge.vocab import Catalog, packaged_catalog

MANIFEST = "manifest.json"


def _sample_time(sample: SampleRecord) -> float:
    return sample.captured_at if sample.captured_at is not None else sample.received_at


def _is_valid(sample: SampleRecord) -> bool:
    """Counts toward coverage: a trusted-time, usable, planned sample."""
    return sample.clock_synced and sample.quality == "ok" and sample.source == "planned"


def coverage_of(
    times: list[float], start: float, end: float, expected_interval: float, max_gap: float
) -> tuple[float, tuple[tuple[float, float], ...]]:
    """Valid duration over window duration, and the stretches with no valid data.

    Two neighbouring samples no further apart than ``max_gap`` cover the time between them. After
    a longer silence the earlier sample is only credited ``expected_interval``.
    """
    if not times:
        return 0.0, ((start, end),)
    covered = 0.0
    gaps: list[tuple[float, float]] = []
    previous, from_sample = start, False
    for at in [*sorted(times), end]:
        span = at - previous
        if span <= max_gap:
            covered += span
        else:
            credit = min(expected_interval, span) if from_sample else 0.0
            covered += credit
            gaps.append((previous + credit, at))
        previous, from_sample = at, True
    return covered / (end - start), tuple(gaps)


def _collect(
    archive: Archive,
    experiment_id: str,
    start: float,
    end: float,
    measurement_filter: Callable[[ManualMeasurement], bool] | None,
    schedule: Sequence[Model] | None = None,
    measurement_grace: float = 0.0,
) -> tuple[dict[str, list], int]:
    """The rows of each file, and how many measurements the filter left out.

    Manual measurements count up to ``measurement_grace`` seconds after ``end`` (one taken when
    the stage ends, a harvest weight say, is recorded a little later). With a ``schedule`` (the
    manual task occurrences the run sheet plans in the window) the snapshot also holds it and
    the task records of those occurrences."""
    samples = archive.samples(experiment_id, start, end)
    measured = [
        m
        for m in archive.measurements(experiment_id, include_corrected=True)
        if start <= m.measured_at <= end + measurement_grace
    ]
    kept = [m for m in measured if measurement_filter is None or measurement_filter(m)]
    data = {
        "samples": [s for s in samples if _is_valid(s)],
        "samples_untrusted": [s for s in samples if not _is_valid(s)],
        "actions": [a for a in archive.actions(experiment_id) if start <= a.created_at <= end],
        "measurements": kept,
        "interventions": [
            i for i in archive.interventions(experiment_id) if start <= i["at"] <= end
        ],
        "frozen_periods": list(archive.frozen_periods(start, end)),
    }
    if schedule is not None:
        data["manual_tasks"] = list(schedule)
        data["task_records"] = list(archive.task_records(experiment_id, start, end))
    return data, len(measured) - len(kept)


def _write_files(directory: Path, data: dict[str, list]) -> dict[str, str]:
    directory.mkdir(parents=True)
    files = {}
    for name, items in data.items():
        rows = [i if isinstance(i, dict) else i.model_dump(mode="json") for i in items]
        path = directory / f"{name}.jsonl"
        path.write_text("".join(canonical_json(row) + "\n" for row in rows), encoding="utf-8")
        files[path.name] = file_digest(path)
    return files


def freeze(
    archive: Archive,
    experiment_id: str,
    clock: Clock,
    start: float,
    end: float,
    expected_interval: float,
    max_gap: float,
    min_coverage: float = 0.9,
    measurement_filter: Callable[[ManualMeasurement], bool] | None = None,
    schedule: Sequence[Model] | None = None,
    measurement_grace: float = 0.0,
) -> Snapshot:
    """Freeze the window. Trusted samples (synced, ok, planned) go to ``samples.jsonl``, the
    rest to ``samples_untrusted.jsonl``; ``measurement_filter`` returning False leaves a
    measurement out (the count is recorded in the manifest)."""
    if not clock.synced:
        raise Denied("clock_unsynced", "the clock is not synchronised; data cannot be frozen")
    if end <= start:
        raise ValueError("snapshot window must have end > start")
    with archive.db.transaction():
        data, excluded = _collect(
            archive, experiment_id, start, end, measurement_filter, schedule, measurement_grace
        )
        times = [_sample_time(s) for s in data["samples"]]
        coverage, gaps = coverage_of(times, start, end, expected_interval, max_gap)
        snapshot_id = new_id("snap")
        directory = archive.root / "snapshots" / snapshot_id
        fields: dict[str, Any] = {
            "id": snapshot_id,
            "experiment_id": experiment_id,
            "version": len(archive.snapshots(experiment_id)) + 1,
            "created_at": clock.now(),
            "complete": coverage >= min_coverage,
            "coverage": coverage,
            "gaps": [list(gap) for gap in gaps],
            "files": _write_files(directory, data),
        }
        manifest = directory / MANIFEST
        extra = {
            "window": [start, end],
            "measurement_grace_seconds": measurement_grace,
            "min_coverage": min_coverage,
            "measurements_excluded": excluded,
        }
        if schedule is not None:  # the manual tasks are judged with the records present now
            extra["manual_tasks_judged_at"] = fields["created_at"]
        manifest.write_text(canonical_json({**fields, **extra}), encoding="utf-8")
        snapshot = Snapshot(**fields, manifest_sha256=file_digest(manifest))
        kept = ("samples", "samples_untrusted", "measurements")
        record_ids = [r.id for name in kept for r in data[name]]
        archive.save_snapshot(snapshot, record_ids)
    return snapshot


def outside_window(
    archive: Archive,
    experiment_id: str,
    start: float,
    end: float,
    measurement_grace: float = 0.0,
    measurement_filter: Callable[[ManualMeasurement], bool] | None = None,
) -> list[dict[str, Any]]:
    """The experiment's measurements a freeze of this window leaves out by their time, oldest
    first. Ones the filter leaves out (held-out outcomes) are not described at all."""
    last = end + measurement_grace
    return [
        {"id": m.id, "metric": m.metric, "measured_at": m.measured_at}
        for m in sorted(
            archive.measurements(experiment_id, include_corrected=True),
            key=lambda m: m.measured_at,
        )
        if not start <= m.measured_at <= last
        and (measurement_filter is None or measurement_filter(m))
    ]


MAX_CHANNELS = 30
MAX_LISTED_GAPS = 5


def _stats(values: list[float]) -> dict[str, float | int]:
    return {
        "n": len(values),
        "min": min(values),
        "max": max(values),
        "mean": round(sum(values) / len(values), 6),
    }


def _numbers(data: dict[str, Any], prefix: str = "") -> list[tuple[str, float]]:
    """Numeric leaves of a device reading, nested keys joined with dots (``light.level``)."""
    found = []
    for key, value in data.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            found.extend(_numbers(value, f"{name}."))
        elif isinstance(value, int | float) and not isinstance(value, bool):
            found.append((name, float(value)))
    return found


def _channels(samples: list[SampleRecord]) -> dict[str, dict]:
    """Numeric readings per data key (booleans are not numbers here)."""
    found: dict[str, list[float]] = {}
    for sample in samples:
        for key, value in _numbers(sample.data):
            found.setdefault(key, []).append(value)
    return {key: _stats(found[key]) for key in sorted(found)[:MAX_CHANNELS]}


def _counts(items: list[str]) -> dict[str, int]:
    counted: dict[str, int] = {}
    for item in items:
        counted[item] = counted.get(item, 0) + 1
    return counted


def preview(
    archive: Archive,
    experiment_id: str,
    start: float,
    end: float,
    expected_interval: float,
    max_gap: float,
    min_coverage: float = 0.9,
    measurement_filter: Callable[[ManualMeasurement], bool] | None = None,
    measurement_grace: float = 0.0,
    catalog: Catalog | None = None,
) -> dict[str, Any]:
    """What ``freeze`` would see in the window, summarised; writes nothing.

    Measurements the filter leaves out (held-out outcomes) are only counted, never described.
    """
    if end <= start:
        raise ValueError("snapshot window must have end > start")
    data, excluded = _collect(
        archive, experiment_id, start, end, measurement_filter, None, measurement_grace
    )
    trusted, untrusted = data["samples"], data["samples_untrusted"]
    coverage, gaps = coverage_of(
        [_sample_time(s) for s in trusted], start, end, expected_interval, max_gap
    )
    catalog = catalog or packaged_catalog()
    by_metric: dict[str, list[ManualMeasurement]] = {}
    for m in data["measurements"]:
        by_metric.setdefault(catalog.canonical(m.metric) or m.metric, []).append(m)
    return {
        "window": [start, end],
        "expected_interval_seconds": expected_interval,
        "max_gap_seconds": max_gap,
        "coverage": round(coverage, 6),
        "would_be_complete": coverage >= min_coverage,
        "min_coverage": min_coverage,
        "gap_count": len(gaps),
        "longest_gap_seconds": max((b - a for a, b in gaps), default=0.0),
        "gaps": [list(gap) for gap in gaps[:MAX_LISTED_GAPS]],
        "samples": {
            "trusted": len(trusted),
            "untrusted": len(untrusted),
            "untrusted_reasons": {
                "clock_unsynced": sum(not s.clock_synced for s in untrusted),
                "quality": _counts([s.quality for s in untrusted if s.quality != "ok"]),
                "source": _counts([s.source for s in untrusted if s.source != "planned"]),
            },
            "channels": _channels(trusted),
        },
        "measurements": {
            metric: {
                **_stats([m.value for m in items]),
                "units": sorted({m.unit for m in items}),
                "plants": len({m.plant_id for m in items}),
                "corrections": sum(m.corrects is not None for m in items),
            }
            for metric, items in sorted(by_metric.items())
        },
        "measurements_withheld": excluded,
        "actions": _counts([a.state.value for a in data["actions"]]),
        "interventions": len(data["interventions"]),
    }


def load(archive: Archive, snapshot_id: str) -> Snapshot:
    found = archive.snapshot(snapshot_id)
    if found is None:
        raise KeyError(snapshot_id)
    return found


def verify(archive: Archive, snapshot_id: str) -> bool:
    """True only when the manifest and every listed file still match their recorded digests."""
    found = archive.snapshot(snapshot_id)
    if found is None:
        return False
    directory = archive.root / "snapshots" / snapshot_id
    try:
        if file_digest(directory / MANIFEST) != found.manifest_sha256:
            return False
        listed = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))["files"]
        if listed != found.files:
            return False
        return all(file_digest(directory / name) == digest for name, digest in listed.items())
    except (OSError, ValueError, KeyError):
        return False
