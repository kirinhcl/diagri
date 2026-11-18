"""Read one frozen snapshot from disk; the live database is never consulted for its records."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from growbridge.archive import snapshot as snapshot_module
from growbridge.archive.models import (
    ActionRecord,
    ManualMeasurement,
    SampleRecord,
    Snapshot,
)
from growbridge.archive.store import Archive

M = TypeVar("M", bound=BaseModel)


class ExportRefused(Exception):
    """The export cannot proceed; the message is shown to the person as is."""


@dataclass(frozen=True)
class SnapshotData:
    snapshot: Snapshot
    manifest: Mapping[str, Any]
    catalog_record: Mapping[str, Any]
    samples: tuple[SampleRecord, ...]
    samples_untrusted: tuple[SampleRecord, ...]
    measurements: tuple[ManualMeasurement, ...]
    actions: tuple[ActionRecord, ...]
    interventions: tuple[Mapping[str, Any], ...]
    frozen_periods: tuple[Mapping[str, Any], ...]


def _lines(archive: Archive, snapshot_id: str, name: str) -> list[Any]:
    path = archive.root / "snapshots" / snapshot_id / name
    try:
        text = path.read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    except (OSError, ValueError) as error:
        raise ExportRefused(f"Snapshot file {name} cannot be read: {error}") from error


def _models(archive: Archive, snapshot_id: str, name: str, model: type[M]) -> tuple[M, ...]:
    try:
        return tuple(model.model_validate(row) for row in _lines(archive, snapshot_id, name))
    except ValidationError as error:
        raise ExportRefused(f"Snapshot file {name} holds an invalid record: {error}") from error


def _dicts(archive: Archive, snapshot_id: str, name: str) -> tuple[Mapping[str, Any], ...]:
    rows = _lines(archive, snapshot_id, name)
    if not all(isinstance(row, dict) for row in rows):
        raise ExportRefused(f"Snapshot file {name} holds a line that is not an object.")
    return tuple(rows)


def _json_file(archive: Archive, snapshot_id: str, name: str) -> Mapping[str, Any]:
    path = archive.root / "snapshots" / snapshot_id / name
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ExportRefused(f"Snapshot file {name} cannot be read: {error}") from error
    if not isinstance(loaded, dict):
        raise ExportRefused(f"Snapshot file {name} is not an object.")
    return loaded


def read_snapshot(archive: Archive, snapshot_id: str) -> SnapshotData:
    try:
        found = snapshot_module.load(archive, snapshot_id)
    except KeyError:
        raise ExportRefused(f"Snapshot {snapshot_id} does not exist.") from None
    if not snapshot_module.verify(archive, snapshot_id):
        raise ExportRefused(
            f"Snapshot {snapshot_id} failed verification: its files no longer match "
            "the recorded digests."
        )
    if snapshot_module.CATALOG_FILE not in found.files:
        raise ExportRefused(
            f"Snapshot {snapshot_id} has no {snapshot_module.CATALOG_FILE}; "
            "it was frozen before the variable catalog was recorded."
        )
    read = (archive, snapshot_id)
    return SnapshotData(
        snapshot=found,
        manifest=_json_file(*read, snapshot_module.MANIFEST),
        catalog_record=_json_file(*read, snapshot_module.CATALOG_FILE),
        samples=_models(*read, "samples.jsonl", SampleRecord),
        samples_untrusted=_models(*read, "samples_untrusted.jsonl", SampleRecord),
        measurements=_models(*read, "measurements.jsonl", ManualMeasurement),
        actions=_models(*read, "actions.jsonl", ActionRecord),
        interventions=_dicts(*read, "interventions.jsonl"),
        frozen_periods=_dicts(*read, "frozen_periods.jsonl"),
    )
