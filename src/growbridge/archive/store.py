"""Append-only project archive (architecture doc §11.1-11.3).

Raw records are only ever inserted. A correction is a new record that points at the old one, and
a record that other results depend on is flagged ("依赖失效") rather than changed.
"""

import json
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from growbridge.archive.clock import Clock
from growbridge.archive.db import Database
from growbridge.archive.ids import canonical_json, new_id
from growbridge.archive.models import (
    ActionRecord,
    Artifact,
    EvidenceCard,
    ManualMeasurement,
    SampleRecord,
    Snapshot,
)
from growbridge.ports import SampleSource

NAMESPACE = "archive"
STEPS = (
    "CREATE TABLE samples(id TEXT PRIMARY KEY, experiment_id TEXT, at REAL NOT NULL,"
    " body TEXT NOT NULL)",
    "CREATE INDEX samples_by_experiment ON samples(experiment_id, at)",
    "CREATE TABLE ingest_cursor(device_id TEXT PRIMARY KEY, cursor INTEGER NOT NULL)",
    "CREATE TABLE actions(seq INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL,"
    " experiment_id TEXT, created_at REAL NOT NULL, body TEXT NOT NULL)",
    "CREATE TABLE measurements(id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL, corrects TEXT,"
    " seq INTEGER NOT NULL, body TEXT NOT NULL)",
    "CREATE TABLE evidence(id TEXT PRIMARY KEY, seq INTEGER NOT NULL, body TEXT NOT NULL)",
    "CREATE TABLE artifacts(id TEXT PRIMARY KEY, task_id TEXT NOT NULL, snapshot_id TEXT,"
    " seq INTEGER NOT NULL, body TEXT NOT NULL)",
    "CREATE TABLE interventions(seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,"
    " experiment_id TEXT NOT NULL, stage_id TEXT, kind TEXT NOT NULL, detail TEXT NOT NULL,"
    " operator TEXT, at REAL NOT NULL)",
    "CREATE TABLE snapshots(id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL,"
    " version INTEGER NOT NULL, body TEXT NOT NULL)",
    "CREATE TABLE snapshot_records(snapshot_id TEXT NOT NULL, record_id TEXT NOT NULL,"
    " PRIMARY KEY(snapshot_id, record_id))",
    "CREATE INDEX snapshot_records_by_record ON snapshot_records(record_id)",
    "CREATE TABLE invalidations(record_id TEXT NOT NULL, dependent_id TEXT NOT NULL,"
    " at REAL NOT NULL, PRIMARY KEY(record_id, dependent_id))",
    "CREATE TABLE archive_meta(key TEXT PRIMARY KEY, value REAL NOT NULL)",
)


def _body(model: BaseModel) -> str:
    return canonical_json(model.model_dump(mode="json"))


def _sample_time(record: SampleRecord) -> float:
    return record.captured_at if record.captured_at is not None else record.received_at


class Archive:
    """Implements ``RecordSink``; every write is one transaction and never awaits."""

    def __init__(self, db: Database, root: Path, clock: Clock):
        self.db = db
        self.root = Path(root)
        self.clock = clock
        db.migrate(NAMESPACE, STEPS)

    # --- internal ------------------------------------------------------------------------------

    def _touch(self) -> None:
        self.db.execute(
            "INSERT INTO archive_meta VALUES('last_write_at', ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (self.clock.now(),),
        )

    def _insert_once(self, table: str, key: str, model: BaseModel, extra: dict[str, Any]) -> bool:
        """Insert a record by id; a repeat with identical content is a no-op, else an error."""
        body = _body(model)
        columns = ["id", *extra, "body"]
        marks = ", ".join("?" for _ in columns)
        cursor = self.db.execute(
            f"INSERT OR IGNORE INTO {table}({', '.join(columns)}) VALUES ({marks})",
            (key, *extra.values(), body),
        )
        if cursor.rowcount:
            return True
        row = self.db.one(f"SELECT body FROM {table} WHERE id = ?", (key,))
        if row is None or row["body"] != body:
            raise ValueError(f"{table} record {key!r} already exists with different content")
        return False

    def _next_seq(self, table: str) -> int:
        row = self.db.one(f"SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM {table}")
        return int(row["n"])

    # --- samples and ingestion -----------------------------------------------------------------

    def append_sample(self, record: SampleRecord) -> None:
        extra = {"experiment_id": record.experiment_id, "at": _sample_time(record)}
        with self.db.transaction():
            self._insert_once("samples", record.id, record, extra)
            self._touch()

    def cursor(self, device_id: str) -> int:
        row = self.db.one("SELECT cursor FROM ingest_cursor WHERE device_id = ?", (device_id,))
        return int(row["cursor"]) if row else 0

    def ingest(
        self,
        source: SampleSource,
        device_id: str,
        context: Callable[[float], tuple[str | None, str | None]],
        limit: int = 500,
    ) -> int:
        """Store the next batch and its progress in one transaction; returns new records.

        ``context(received_at)`` names the experiment and stage a sample belongs to; it is asked
        for every sample, so a backlog is attributed by when its rows arrived, not by now.
        """
        batch = list(source.read_after(self.cursor(device_id), limit))
        if not batch:
            return 0
        records = []
        for item in batch:
            experiment_id, stage_id = context(item.received_at)
            records.append(
                SampleRecord(
                    id=f"{device_id}:{item.cursor}",
                    experiment_id=experiment_id,
                    stage_id=stage_id,
                    device_id=device_id,
                    captured_at=item.captured_at,
                    received_at=item.received_at,
                    clock_synced=item.clock_synced,
                    source=item.source,
                    data=item.data,
                )
            )
        stored = 0
        with self.db.transaction():
            for record in records:
                extra = {"experiment_id": record.experiment_id, "at": _sample_time(record)}
                stored += self._insert_once("samples", record.id, record, extra)
            top = max(item.cursor for item in batch)
            self.db.execute(
                "INSERT INTO ingest_cursor VALUES(?, ?) ON CONFLICT(device_id)"
                " DO UPDATE SET cursor = MAX(cursor, excluded.cursor)",
                (device_id, top),
            )
            if stored:
                self._touch()
        return stored

    def samples(
        self, experiment_id: str, start: float | None = None, end: float | None = None
    ) -> tuple[SampleRecord, ...]:
        rows = self.db.query(
            "SELECT body FROM samples WHERE experiment_id = ? AND at >= ? AND at <= ?"
            " ORDER BY at, id",
            (
                experiment_id,
                float("-inf") if start is None else start,
                float("inf") if end is None else end,
            ),
        )
        return tuple(SampleRecord.model_validate_json(row["body"]) for row in rows)

    # --- actions -------------------------------------------------------------------------------

    def append_action(self, record: ActionRecord) -> None:
        with self.db.transaction():
            self.db.execute(
                "INSERT INTO actions(request_id, experiment_id, created_at, body)"
                " VALUES(?, ?, ?, ?)",
                (record.request_id, record.experiment_id, record.created_at, _body(record)),
            )
            self._touch()

    def actions(self, experiment_id: str | None = None) -> tuple[ActionRecord, ...]:
        if experiment_id is None:
            rows = self.db.query("SELECT body FROM actions ORDER BY seq")
        else:
            rows = self.db.query(
                "SELECT body FROM actions WHERE experiment_id = ? ORDER BY seq", (experiment_id,)
            )
        return tuple(ActionRecord.model_validate_json(row["body"]) for row in rows)

    # --- measurements, evidence, artifacts -----------------------------------------------------

    def add_measurement(self, record: ManualMeasurement) -> None:
        with self.db.transaction():
            if record.corrects is not None:
                known = self.db.one("SELECT 1 FROM measurements WHERE id = ?", (record.corrects,))
                if known is None:
                    raise ValueError(f"cannot correct unknown measurement {record.corrects!r}")
            extra = {
                "experiment_id": record.experiment_id,
                "corrects": record.corrects,
                "seq": self._next_seq("measurements"),
            }
            if self._insert_once("measurements", record.id, record, extra):
                if record.corrects is not None:
                    self.mark_dependents_invalid(record.corrects)
                self._touch()

    def measurements(
        self, experiment_id: str, include_corrected: bool = False
    ) -> tuple[ManualMeasurement, ...]:
        sql = "SELECT body FROM measurements m WHERE experiment_id = ?"
        if not include_corrected:
            sql += " AND NOT EXISTS (SELECT 1 FROM measurements c WHERE c.corrects = m.id)"
        rows = self.db.query(sql + " ORDER BY seq", (experiment_id,))
        return tuple(ManualMeasurement.model_validate_json(row["body"]) for row in rows)

    def add_evidence(self, card: EvidenceCard) -> None:
        with self.db.transaction():
            if self._insert_once("evidence", card.id, card, {"seq": self._next_seq("evidence")}):
                self._touch()

    def evidence(self, ids: Iterable[str] | None = None) -> tuple[EvidenceCard, ...]:
        rows = self.db.query("SELECT id, body FROM evidence ORDER BY seq")
        wanted = None if ids is None else set(ids)
        return tuple(
            EvidenceCard.model_validate_json(row["body"])
            for row in rows
            if wanted is None or row["id"] in wanted
        )

    def add_artifact(self, artifact: Artifact) -> None:
        with self.db.transaction():
            extra = {
                "task_id": artifact.task_id,
                "snapshot_id": artifact.snapshot_id,
                "seq": self._next_seq("artifacts"),
            }
            if self._insert_once("artifacts", artifact.id, artifact, extra):
                self._touch()

    def artifact(self, artifact_id: str) -> Artifact | None:
        row = self.db.one("SELECT body FROM artifacts WHERE id = ?", (artifact_id,))
        return Artifact.model_validate_json(row["body"]) if row else None

    def artifacts(self, task_id: str) -> tuple[Artifact, ...]:
        rows = self.db.query(
            "SELECT body FROM artifacts WHERE task_id = ? ORDER BY seq", (task_id,)
        )
        return tuple(Artifact.model_validate_json(row["body"]) for row in rows)

    # --- interventions -------------------------------------------------------------------------

    def record_intervention(
        self,
        experiment_id: str,
        stage_id: str | None,
        kind: str,
        detail: dict,
        operator: str | None,
    ) -> str:
        record_id = new_id("intv")
        with self.db.transaction():
            self.db.execute(
                "INSERT INTO interventions(id, experiment_id, stage_id, kind, detail, operator, at)"
                " VALUES(?, ?, ?, ?, ?, ?, ?)",
                (
                    record_id,
                    experiment_id,
                    stage_id,
                    kind,
                    canonical_json(detail),
                    operator,
                    self.clock.now(),
                ),
            )
            self._touch()
        return record_id

    def interventions(self, experiment_id: str) -> tuple[dict[str, Any], ...]:
        rows = self.db.query(
            "SELECT id, experiment_id, stage_id, kind, detail, operator, at FROM interventions"
            " WHERE experiment_id = ? ORDER BY seq",
            (experiment_id,),
        )
        return tuple({**dict(row), "detail": json.loads(row["detail"])} for row in rows)

    # --- snapshots and dependency invalidation -------------------------------------------------

    def save_snapshot(self, snapshot: Snapshot, record_ids: Iterable[str]) -> None:
        with self.db.transaction():
            self.db.execute(
                "INSERT INTO snapshots VALUES(?, ?, ?, ?)",
                (snapshot.id, snapshot.experiment_id, snapshot.version, _body(snapshot)),
            )
            with self.db.lock:
                self.db.connection.executemany(
                    "INSERT OR IGNORE INTO snapshot_records VALUES(?, ?)",
                    [(snapshot.id, rid) for rid in record_ids],
                )
            self._touch()

    def snapshot(self, snapshot_id: str) -> Snapshot | None:
        row = self.db.one("SELECT body FROM snapshots WHERE id = ?", (snapshot_id,))
        return Snapshot.model_validate_json(row["body"]) if row else None

    def snapshots(self, experiment_id: str) -> tuple[Snapshot, ...]:
        rows = self.db.query(
            "SELECT body FROM snapshots WHERE experiment_id = ? ORDER BY version", (experiment_id,)
        )
        return tuple(Snapshot.model_validate_json(row["body"]) for row in rows)

    def mark_dependents_invalid(self, record_id: str) -> tuple[str, ...]:
        """Flag snapshots built from ``record_id`` and artifacts built from those snapshots."""
        with self.db.transaction():
            snaps = [
                row["snapshot_id"]
                for row in self.db.query(
                    "SELECT snapshot_id FROM snapshot_records WHERE record_id = ?", (record_id,)
                )
            ]
            arts = [
                row["id"]
                for snap in snaps
                for row in self.db.query("SELECT id FROM artifacts WHERE snapshot_id = ?", (snap,))
            ]
            dependents = tuple(sorted({*snaps, *arts}))
            for dependent in dependents:
                self.db.execute(
                    "INSERT OR IGNORE INTO invalidations VALUES(?, ?, ?)",
                    (record_id, dependent, self.clock.now()),
                )
            if dependents:
                self._touch()
        return dependents

    def is_invalid(self, record_id: str) -> bool:
        row = self.db.one("SELECT 1 FROM invalidations WHERE dependent_id = ?", (record_id,))
        return row is not None

    def last_write_at(self) -> float | None:
        row = self.db.one("SELECT value FROM archive_meta WHERE key = 'last_write_at'")
        return float(row["value"]) if row else None
