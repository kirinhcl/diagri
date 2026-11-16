"""Append-only project archive (architecture doc §11.1-11.3).

Raw records are only ever inserted. A correction is a new record that points at the old one, and
a record that other results depend on is flagged ("依赖失效") rather than changed.
"""

import json
from collections.abc import Callable, Iterable, Sequence
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
    FrozenPeriod,
    ManualMeasurement,
    Model,
    SampleRecord,
    Snapshot,
    TaskRecord,
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
    "ALTER TABLE measurements ADD COLUMN recorded_at REAL",  # NULL: recorded before this column
    # Who entered or proposed an evidence card, and who verified it. Both are appended records:
    # the card itself is never edited. One verification per card; the first one stays.
    "CREATE TABLE evidence_sources(card_id TEXT PRIMARY KEY, source TEXT NOT NULL,"
    " task_id TEXT, at REAL NOT NULL)",
    "CREATE INDEX evidence_sources_by_task ON evidence_sources(task_id)",
    "CREATE TABLE evidence_verifications(card_id TEXT PRIMARY KEY, verifier TEXT NOT NULL,"
    " at REAL NOT NULL, note TEXT NOT NULL)",
    # The operator's attestation that the card's value was calibrated against a local
    # measurement, stored with the verification record. Cards from before it count as not attested.
    "ALTER TABLE evidence_verifications ADD COLUMN calibrated INTEGER NOT NULL DEFAULT 0",
    "CREATE INDEX samples_by_time ON samples(at)",
    # A sensor's frozen period is two insert-only rows: when it opened and, later, when it closed.
    "CREATE TABLE frozen_marks(seq INTEGER PRIMARY KEY AUTOINCREMENT, period_id TEXT NOT NULL,"
    " event TEXT NOT NULL CHECK (event IN ('opened', 'closed')), sensor TEXT NOT NULL,"
    " value REAL, sample_at REAL NOT NULL, recorded_at REAL NOT NULL,"
    " UNIQUE (period_id, event))",
    # Why a period closed ('value_changed', 'no_longer_listed' or 'nothing_checked'); rows from
    # before this step have none.
    "ALTER TABLE frozen_marks ADD COLUMN reason TEXT",
    # What happened to each daily occurrence of a manual task; append-only, the latest counts.
    "CREATE TABLE task_records(id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL,"
    " stage_id TEXT NOT NULL, due_at REAL NOT NULL, seq INTEGER NOT NULL, body TEXT NOT NULL)",
    "CREATE INDEX task_records_by_experiment ON task_records(experiment_id, due_at)",
)

FROZEN_CLOSE_REASONS = ("value_changed", "no_longer_listed", "nothing_checked")

MODEL_SOURCE = "model:"  # cards from a model role: it may not vouch for calibration


class EvidenceVerification(Model):
    card_id: str
    verifier: str
    at: float
    note: str = ""
    calibrated: bool = False  # the operator attests the value was calibrated locally


class EvidenceEntry(Model):
    """A card with its trail: who added it, and who verified it (if anyone)."""

    card: EvidenceCard
    source: str | None = None  # ``operator:<id>`` or ``model:<role>``; None for older cards
    task_id: str | None = None
    added_at: float | None = None
    verified_by: str | None = None
    verified_at: float | None = None
    note: str = ""


def _as_reported(body: str, verified: bool, attested: Any, source: str | None) -> EvidenceCard:
    """A stored card with the two flags that come from records, not from the card text."""
    card = EvidenceCard.model_validate_json(body)
    calibrated = card.calibrated
    if source is not None and source.startswith(MODEL_SOURCE):
        calibrated = bool(attested)  # no verification, or none that attests it: not calibrated
    return card.model_copy(update={"verified": verified, "calibrated": calibrated})


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

    def sensor_points(self, since: float) -> tuple[tuple[float, dict[str, Any]], ...]:
        """Sensor values of every sample at or after ``since``, across experiments, oldest first."""
        rows = self.db.query(
            "SELECT at, CASE WHEN json_type(body, '$.data.sensor') = 'object'"
            " THEN json_extract(body, '$.data.sensor') END AS sensor FROM samples"
            " WHERE at >= ? ORDER BY at, id",
            (since,),
        )
        points = []
        for row in rows:
            sensor = json.loads(row["sensor"]) if row["sensor"] is not None else None
            points.append((float(row["at"]), sensor if isinstance(sensor, dict) else {}))
        return tuple(points)

    # --- frozen readings -----------------------------------------------------------------------

    def open_frozen(self, sensor: str, value: float, first_at: float) -> str:
        period_id = new_id("frozen")
        with self.db.transaction():
            self.db.execute(
                "INSERT INTO frozen_marks(period_id, event, sensor, value, sample_at, recorded_at)"
                " VALUES(?, 'opened', ?, ?, ?, ?)",
                (period_id, sensor, value, first_at, self.clock.now()),
            )
            self._touch()
        return period_id

    def close_frozen(self, period_id: str, sensor: str, last_at: float, reason: str) -> None:
        """``reason``: the value changed, the sensor is no longer listed, or nothing is checked.

        Closes only a period opened for this sensor; closing it again is a no-op. A period that
        was never opened for ``sensor`` is refused, so no closing row is left without its opening.
        """
        if reason not in FROZEN_CLOSE_REASONS:
            raise ValueError(f"unknown frozen close reason: {reason!r}")
        opened = (
            "SELECT 1 FROM frozen_marks WHERE period_id = ? AND event = 'opened' AND sensor = ?"
        )
        with self.db.transaction():
            if self.db.one(opened, (period_id, sensor)) is None:
                raise ValueError(f"no frozen period {period_id!r} was opened for {sensor!r}")
            self.db.execute(
                "INSERT OR IGNORE INTO frozen_marks(period_id, event, sensor, value, sample_at,"
                " recorded_at, reason) SELECT ?, 'closed', ?, NULL, ?, ?, ?"
                f" WHERE EXISTS ({opened})",
                (period_id, sensor, last_at, self.clock.now(), reason, period_id, sensor),
            )
            self._touch()

    def open_frozen_periods(self) -> tuple[FrozenPeriod, ...]:
        rows = self.db.query(
            "SELECT o.period_id, o.sensor, o.value, o.sample_at AS first_at,"
            " o.recorded_at AS opened_at FROM frozen_marks o WHERE o.event = 'opened'"
            " AND NOT EXISTS (SELECT 1 FROM frozen_marks c"
            " WHERE c.period_id = o.period_id AND c.event = 'closed') ORDER BY o.seq"
        )
        return tuple(FrozenPeriod(**dict(row)) for row in rows)

    def frozen_periods(self, start: float, end: float) -> tuple[dict[str, Any], ...]:
        """Periods overlapping ``[start, end]``; a still-open one has ``last_at`` None."""
        rows = self.db.query(
            "SELECT o.period_id, o.sensor, o.value, o.sample_at AS first_at,"
            " c.sample_at AS last_at, o.recorded_at AS opened_at, c.recorded_at AS closed_at,"
            " c.reason AS close_reason"
            " FROM frozen_marks o LEFT JOIN frozen_marks c"
            " ON c.period_id = o.period_id AND c.event = 'closed'"
            " WHERE o.event = 'opened' AND o.sample_at <= ?"
            " AND (c.sample_at IS NULL OR c.sample_at >= ?) ORDER BY o.seq",
            (end, start),
        )
        return tuple(dict(row) for row in rows)

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
                known = self.db.one(
                    "SELECT experiment_id FROM measurements WHERE id = ?", (record.corrects,)
                )
                if known is None:
                    raise ValueError(f"cannot correct unknown measurement {record.corrects!r}")
                if known["experiment_id"] != record.experiment_id:
                    raise ValueError("cannot correct a measurement of another experiment")
            extra = {
                "experiment_id": record.experiment_id,
                "corrects": record.corrects,
                "seq": self._next_seq("measurements"),
                "recorded_at": self.clock.now(),
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

    def outcome_experiments(
        self, batch_ids: Sequence[str], outcome_fields: Sequence[str]
    ) -> tuple[str, ...]:
        """The experiments that hold a measurement of one of these metrics for one of these
        batches (a measurement with no batch matches any), corrected ones and corrections
        included. Done in SQL over the stored body, where ``batch`` and ``metric`` live, so the
        measurements are neither loaded nor validated; the names go in as JSON arrays, so there
        is no limit on their number and nothing is spliced into the statement."""
        if not batch_ids or not outcome_fields:
            return ()
        rows = self.db.query(
            "SELECT DISTINCT experiment_id FROM measurements"
            " WHERE json_extract(body, '$.metric') IN (SELECT value FROM json_each(?))"
            " AND (json_extract(body, '$.batch') IN (SELECT value FROM json_each(?))"
            "      OR json_extract(body, '$.batch') = '')"
            " ORDER BY experiment_id",
            (json.dumps(list(outcome_fields)), json.dumps(list(batch_ids))),
        )
        return tuple(row["experiment_id"] for row in rows)

    def measurement_recorded_at(self, ids: Iterable[str]) -> dict[str, float | None]:
        """When each measurement was recorded here (the archive clock, not the ``measured_at``
        an operator typed in). ``None`` for one recorded before this was kept; unknown ids are
        left out."""
        wanted = list(ids)
        found: dict[str, float | None] = {}
        for start in range(0, len(wanted), 500):  # stay under SQLite's variable limit
            chunk = wanted[start : start + 500]
            marks = ", ".join("?" for _ in chunk)
            rows = self.db.query(
                f"SELECT id, recorded_at FROM measurements WHERE id IN ({marks})", chunk
            )
            found.update({row["id"]: row["recorded_at"] for row in rows})
        return found

    def add_evidence(
        self,
        card: EvidenceCard,
        source: str | None = None,
        task_id: str | None = None,
        verified_by: str | None = None,
    ) -> None:
        """Store a card with its source. The card is always stored unverified: a verification
        is its own record, written here only when an operator (``verified_by``) entered it.

        A card from a model role is also stored uncalibrated: a model cannot vouch for it. An
        operator's own value is kept, and is that operator's attestation."""
        stored = card.model_copy(update={"verified": False})
        if source is not None and source.startswith(MODEL_SOURCE):
            stored = stored.model_copy(update={"calibrated": False})
        with self.db.transaction():
            extra = {"seq": self._next_seq("evidence")}
            if not self._insert_once("evidence", stored.id, stored, extra):
                return
            if source is not None:
                self.db.execute(
                    "INSERT INTO evidence_sources(card_id, source, task_id, at)"
                    " VALUES (?, ?, ?, ?)",
                    (stored.id, source, task_id, self.clock.now()),
                )
            if verified_by is not None:
                self.verify_evidence(stored.id, verified_by, calibrated=stored.calibrated)
            self._touch()

    def verify_evidence(
        self, card_id: str, verifier: str, note: str = "", calibrated: bool = False
    ) -> EvidenceVerification:
        """Append the verification of a card, with the operator's attestation that its value was
        calibrated locally (``calibrated``). Repeating it keeps the first record, attestation
        included: a later call changes nothing."""
        with self.db.transaction():
            if self.db.one("SELECT 1 FROM evidence WHERE id = ?", (card_id,)) is None:
                raise ValueError(f"unknown evidence card {card_id}")
            added = self.db.execute(
                "INSERT OR IGNORE INTO evidence_verifications(card_id, verifier, at, note,"
                " calibrated) VALUES (?, ?, ?, ?, ?)",
                (card_id, verifier, self.clock.now(), note, int(calibrated)),
            )
            if added.rowcount:
                self._touch()
            found = self.evidence_verification(card_id)
        assert found is not None  # inserted above or already there
        return found

    def evidence_verification(self, card_id: str) -> EvidenceVerification | None:
        row = self.db.one("SELECT * FROM evidence_verifications WHERE card_id = ?", (card_id,))
        return None if row is None else EvidenceVerification(**dict(row))

    def evidence(self, ids: Iterable[str] | None = None) -> tuple[EvidenceCard, ...]:
        """The cards as reported to the rest of the system.

        ``verified`` is true exactly when a verification record exists. ``calibrated`` is the
        operator's: for a card from a model role it is true only when the verification record
        attests it; for any other card it is the value the operator entered."""
        rows = self.db.query(
            "SELECT e.id, e.body, v.card_id AS verified, v.calibrated AS attested, s.source"
            " FROM evidence e LEFT JOIN evidence_verifications v ON v.card_id = e.id"
            " LEFT JOIN evidence_sources s ON s.card_id = e.id ORDER BY e.seq"
        )
        wanted = None if ids is None else set(ids)
        return tuple(
            _as_reported(row["body"], row["verified"] is not None, row["attested"], row["source"])
            for row in rows
            if wanted is None or row["id"] in wanted
        )

    def evidence_entries(self) -> tuple[EvidenceEntry, ...]:
        """Every card with its source and verification, oldest first."""
        rows = self.db.query(
            "SELECT e.body, s.source, s.task_id, s.at AS added_at, v.verifier,"
            " v.at AS verified_at, v.note, v.calibrated AS attested FROM evidence e"
            " LEFT JOIN evidence_sources s ON s.card_id = e.id"
            " LEFT JOIN evidence_verifications v ON v.card_id = e.id ORDER BY e.seq"
        )
        return tuple(
            EvidenceEntry(
                card=_as_reported(
                    row["body"], row["verifier"] is not None, row["attested"], row["source"]
                ),
                source=row["source"],
                task_id=row["task_id"],
                added_at=row["added_at"],
                verified_by=row["verifier"],
                verified_at=row["verified_at"],
                note=row["note"] or "",
            )
            for row in rows
        )

    def evidence_count_from(self, task_id: str) -> int:
        row = self.db.one(
            "SELECT COUNT(*) AS n FROM evidence_sources WHERE task_id = ?", (task_id,)
        )
        return int(row["n"])

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

    def add_task_record(self, record: TaskRecord) -> None:
        with self.db.transaction():
            extra = {
                "experiment_id": record.experiment_id,
                "stage_id": record.stage_id,
                "due_at": record.due_at,
                "seq": self._next_seq("task_records"),
            }
            if self._insert_once("task_records", record.id, record, extra):
                self._touch()

    def task_records(
        self, experiment_id: str, start: float | None = None, end: float | None = None
    ) -> tuple[TaskRecord, ...]:
        """Records of the occurrences due in ``[start, end)`` (all when not given), in order."""
        rows = self.db.query(
            "SELECT body FROM task_records WHERE experiment_id = ?"
            " AND (? IS NULL OR due_at >= ?) AND (? IS NULL OR due_at < ?) ORDER BY seq",
            (experiment_id, start, start, end, end),
        )
        return tuple(TaskRecord.model_validate_json(row["body"]) for row in rows)

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
