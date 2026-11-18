"""The ``export-dataset`` command: resolve the inputs from the data directory, write the files."""

from __future__ import annotations

import csv
import io
import json
import secrets
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from growbridge.archive.clock import SystemClock
from growbridge.archive.db import Database
from growbridge.archive.store import Archive
from growbridge.dataset.build import COUNT_NAMES, METADATA_FILE, ExportInputs, build_dataset
from growbridge.dataset.pseudonym import Pseudonymizer, load_or_create_key
from growbridge.dataset.schema import TABLES
from growbridge.dataset.source import ExportRefused, SnapshotData, read_snapshot
from growbridge.research.holdout import HoldoutRegistry
from growbridge.vocab import packaged_catalog
from growbridge.workflow.store import WorkflowStore

DATABASES = ("archive", "workflow", "agents")


@dataclass(frozen=True)
class ExportSummary:
    out: Path
    rows: Mapping[str, int]
    counts: Mapping[str, int]


def _check_out(data_dir: Path, out: Path) -> None:
    if out.exists():
        raise ExportRefused(f"{out} already exists; name a directory that does not.")
    if not out.parent.is_dir():
        raise ExportRefused(f"The parent of {out} does not exist.")
    resolved = out.resolve()
    root = data_dir.resolve()
    if resolved == root or root in resolved.parents:
        raise ExportRefused(f"{out} lies inside the data directory {data_dir}; write it elsewhere.")


def _check_databases(data_dir: Path) -> None:
    for name in DATABASES:
        if not (data_dir / f"{name}.sqlite3").is_file():
            raise ExportRefused(
                f"{name}.sqlite3 is missing from {data_dir}; this is not a daemon data directory "
                "(it would be created empty, and a missing holdout registry exports no holdouts)."
            )


def _only(found: Sequence[object], what: str, experiment_id: str) -> object:
    if len(found) != 1:
        listed = ", ".join(str(item) for item in found) or "none"
        raise ExportRefused(
            f"Experiment {experiment_id} must run under exactly one {what}; found {listed}."
        )
    return found[0]


def _corrected_after_freeze(
    archive: Archive, experiment_id: str, data: SnapshotData
) -> tuple[str, ...]:
    frozen = {m.id for m in data.measurements}
    return tuple(
        sorted(
            m.corrects
            for m in archive.measurements(experiment_id, include_corrected=True)
            if m.corrects in frozen and m.id not in frozen
        )
    )


def _row_counts(files: Mapping[str, bytes]) -> dict[str, int]:
    """Data rows of each table, read back from the CSV so quoted newlines count once."""
    text = {t.file: files[t.file].decode("utf-8") for t in TABLES}
    return {file: len(list(csv.reader(io.StringIO(t, newline="")))) - 1 for file, t in text.items()}


def _counts(files: Mapping[str, bytes]) -> dict[str, int]:
    metadata = json.loads(files[METADATA_FILE])
    values = {p["name"]: p["value"] for p in metadata["additionalProperty"]}
    return {name: int(values[name]) for name in COUNT_NAMES}


def _write(files: Mapping[str, bytes], out: Path) -> None:
    partial = out.parent / f".{out.name}.partial-{secrets.token_hex(4)}"
    try:
        partial.mkdir()
        for name, content in files.items():
            (partial / name).write_bytes(content)
        partial.rename(out)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise


def _inputs(
    data_dir: Path, snapshot_id: str, dbs: Mapping[str, Database], extra: Mapping[str, object]
) -> ExportInputs:
    archive = Archive(dbs["archive"], data_dir / "archive", SystemClock())
    store = WorkflowStore(dbs["workflow"])
    catalog = packaged_catalog()
    data = read_snapshot(archive, snapshot_id)
    experiment_id = data.snapshot.experiment_id
    project_id = str(_only(store.projects_of_experiment(experiment_id), "project", experiment_id))
    protocol_id, version = _only(
        store.protocol_versions_of(experiment_id), "protocol version", experiment_id
    )  # type: ignore[misc]
    round_id = str(_only(store.round_ids_of_experiment(experiment_id), "round", experiment_id))
    protocol = store.protocol(protocol_id, version)
    if protocol is None:
        raise ExportRefused(f"Protocol {protocol_id} version {version} is not saved.")
    holdouts = HoldoutRegistry(dbs["agents"], SystemClock(), None, catalog)
    key = load_or_create_key(data_dir / "export" / "pseudonym.key")
    return ExportInputs(
        data=data,
        protocol=protocol,
        round_number=store.round_number(round_id),
        catalog=catalog,
        holdouts=holdouts.holdouts(project_id),
        keep=holdouts.development_filter(project_id),
        pseudonym=Pseudonymizer(key),
        corrected_after_freeze=_corrected_after_freeze(archive, experiment_id, data),
        **extra,  # type: ignore[arg-type]
    )


def export_dataset(
    data_dir: Path,
    snapshot_id: str,
    out: Path,
    licence: str,
    creator: str,
    url: str | None,
    software_version: str,
) -> ExportSummary:
    _check_out(data_dir, out)
    _check_databases(data_dir)
    dbs = {name: Database(data_dir / f"{name}.sqlite3") for name in DATABASES}
    try:
        extra = {
            "licence": licence,
            "creator": creator,
            "url": url,
            "software_version": software_version,
        }
        inputs = _inputs(data_dir, snapshot_id, dbs, extra)
        files = build_dataset(inputs)
    finally:
        for db in dbs.values():
            db.close()
    _write(files, out)
    return ExportSummary(out=out, rows=_row_counts(files), counts=_counts(files))
