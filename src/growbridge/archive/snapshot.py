"""Freeze the inputs of one analysis (architecture doc §11.1, §11.3).

A snapshot is a directory of JSON-lines files plus a manifest holding every file's SHA-256.
Late additions never change a snapshot; freezing again writes a new version.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from growbridge.archive.clock import Clock
from growbridge.archive.ids import canonical_json, file_digest, new_id
from growbridge.archive.models import ManualMeasurement, SampleRecord, Snapshot
from growbridge.archive.store import Archive
from growbridge.ports import Denied

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
) -> tuple[dict[str, list], int]:
    """The rows of each file, and how many measurements the filter left out."""
    samples = archive.samples(experiment_id, start, end)
    measured = [
        m
        for m in archive.measurements(experiment_id, include_corrected=True)
        if start <= m.measured_at <= end
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
) -> Snapshot:
    """Freeze the window. Trusted samples (synced, ok, planned) go to ``samples.jsonl``, the
    rest to ``samples_untrusted.jsonl``; ``measurement_filter`` returning False leaves a
    measurement out (the count is recorded in the manifest)."""
    if not clock.synced:
        raise Denied("clock_unsynced", "the clock is not synchronised; data cannot be frozen")
    if end <= start:
        raise ValueError("snapshot window must have end > start")
    with archive.db.transaction():
        data, excluded = _collect(archive, experiment_id, start, end, measurement_filter)
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
            "min_coverage": min_coverage,
            "measurements_excluded": excluded,
        }
        manifest.write_text(canonical_json({**fields, **extra}), encoding="utf-8")
        snapshot = Snapshot(**fields, manifest_sha256=file_digest(manifest))
        kept = ("samples", "samples_untrusted", "measurements")
        record_ids = [r.id for name in kept for r in data[name]]
        archive.save_snapshot(snapshot, record_ids)
    return snapshot


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
