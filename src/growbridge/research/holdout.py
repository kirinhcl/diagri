"""Holdout registry for prediction models (architecture doc §9.2).

Holdout batches are registered before development starts. General reads lose the outcome labels of
those batches; a registered model is evaluated on them once as confirmatory, every later
evaluation is exploratory, and every read is logged.
"""

import json
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from growbridge.archive.clock import Clock
from growbridge.archive.db import Database
from growbridge.archive.models import Label, ManualMeasurement, Model
from growbridge.ports import Denied

MIN_DEVELOPMENT_BATCHES = 2

STEPS = (
    "CREATE TABLE holdouts("
    "holdout_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, batch_ids TEXT NOT NULL, "
    "outcome_fields TEXT NOT NULL, registered_at REAL NOT NULL)",
    "CREATE TABLE holdout_models("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, holdout_id TEXT NOT NULL REFERENCES holdouts, "
    "model_sha TEXT NOT NULL, features_sha TEXT NOT NULL, preprocessing_sha TEXT NOT NULL, "
    "registered_at REAL NOT NULL)",
    "CREATE TABLE holdout_reads("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, holdout_id TEXT NOT NULL REFERENCES holdouts, "
    "reader TEXT NOT NULL, at REAL NOT NULL, label TEXT NOT NULL)",
    "ALTER TABLE holdout_reads ADD COLUMN model_sha TEXT NOT NULL DEFAULT ''",
)


class HoldoutRead(Model):
    holdout_id: str
    reader: str
    at: float
    label: Label
    model_sha: str = ""


class HoldoutRegistry:
    def __init__(self, db: Database, clock: Clock):
        self.db = db
        self.clock = clock
        db.migrate("research_holdout", STEPS)

    def register(
        self,
        project_id: str,
        holdout_id: str,
        batch_ids: Sequence[str],
        outcome_fields: Sequence[str],
        development_batches: int,
    ) -> None:
        if development_batches < MIN_DEVELOPMENT_BATCHES or not batch_ids:
            raise Denied(
                "batches",
                f"need >= {MIN_DEVELOPMENT_BATCHES} development batches and a non-empty holdout",
            )
        try:
            self.db.execute(
                "INSERT INTO holdouts VALUES (?, ?, ?, ?, ?)",
                (
                    holdout_id,
                    project_id,
                    json.dumps(list(batch_ids)),
                    json.dumps(list(outcome_fields)),
                    self.clock.now(),
                ),
            )
        except sqlite3.IntegrityError:
            raise Denied("state", f"holdout {holdout_id} is already registered") from None

    def _holdout(self, holdout_id: str) -> sqlite3.Row:
        row = self.db.one("SELECT * FROM holdouts WHERE holdout_id = ?", (holdout_id,))
        if row is None:
            raise Denied("state", f"holdout {holdout_id} is not registered")
        return row

    def filter_development(
        self, holdout_id: str, rows: Sequence[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        """Rows for general use: outcome fields of holdout (or unlabelled) batches are removed."""
        row = self._holdout(holdout_id)
        held = set(json.loads(row["batch_ids"]))
        outcomes = set(json.loads(row["outcome_fields"]))
        result = []
        for item in rows:
            if item.get("batch") in held or "batch" not in item:
                result.append({key: value for key, value in item.items() if key not in outcomes})
            else:
                result.append(dict(item))
        return result

    def register_model(
        self, holdout_id: str, model_sha: str, features_sha: str, preprocessing_sha: str
    ) -> None:
        self._holdout(holdout_id)
        self.db.execute(
            "INSERT INTO holdout_models(holdout_id, model_sha, features_sha, preprocessing_sha, "
            "registered_at) VALUES (?, ?, ?, ?, ?)",
            (holdout_id, model_sha, features_sha, preprocessing_sha, self.clock.now()),
        )

    def development_filter(self, project_id: str) -> Callable[[ManualMeasurement], bool]:
        """Predicate for the data path: False for an outcome of a holdout batch.

        Registrations are read on every call, so holdouts registered later apply at once. A
        measurement without a batch cannot be placed and is treated as held out.
        """

        def keep(measurement: ManualMeasurement) -> bool:
            rows = self.db.query(
                "SELECT batch_ids, outcome_fields FROM holdouts WHERE project_id = ?",
                (project_id,),
            )
            for row in rows:
                if measurement.metric not in json.loads(row["outcome_fields"]):
                    continue
                if not measurement.batch or measurement.batch in json.loads(row["batch_ids"]):
                    return False
            return True

        return keep

    def evaluate(self, holdout_id: str, reader: str, model_sha: str) -> Label:
        """Log one read of the holdout outcomes by a registered model; label what it may be."""
        with self.db.transaction():
            self._holdout(holdout_id)
            model = self.db.one(
                "SELECT 1 FROM holdout_models WHERE holdout_id = ? AND model_sha = ?",
                (holdout_id, model_sha),
            )
            if model is None:
                raise Denied("model_unregistered", "register model, features and preprocessing")
            earlier = self.db.one(
                "SELECT COUNT(*) AS n FROM holdout_reads WHERE holdout_id = ?", (holdout_id,)
            )
            label: Label = "confirmatory" if earlier["n"] == 0 else "exploratory"
            self.db.execute(
                "INSERT INTO holdout_reads(holdout_id, reader, at, label, model_sha) "
                "VALUES (?, ?, ?, ?, ?)",
                (holdout_id, reader, self.clock.now(), label, model_sha),
            )
        return label

    def reads(self, holdout_id: str) -> list[HoldoutRead]:
        rows = self.db.query(
            "SELECT holdout_id, reader, at, label, model_sha FROM holdout_reads "
            "WHERE holdout_id = ? ORDER BY id",
            (holdout_id,),
        )
        return [HoldoutRead(**dict(row)) for row in rows]

    def late_features(
        self, feature_times: Mapping[str, float], prediction_time: float
    ) -> tuple[str, ...]:
        """Features that were only received after the prediction time (data leakage)."""
        return tuple(sorted(name for name, at in feature_times.items() if at > prediction_time))


def refuse_holdout_rows(
    registry: "HoldoutRegistry | None", project_id: str, snapshot_id: str, measurements: Path
) -> None:
    """Refuse a snapshot whose measurements hold an outcome of a held-out batch.

    ``Snapshot`` carries no marker for rows frozen without the development filter (the manifest
    only counts the excluded ones), so the rows are checked against the registry's own predicate.
    The message never quotes a value. Without a registry there is nothing to check.
    """
    if registry is None:
        return
    keep = registry.development_filter(project_id)
    for line in measurements.read_text(encoding="utf-8").splitlines():
        if line and not keep(ManualMeasurement.model_validate_json(line)):
            raise Denied("scope", f"snapshot {snapshot_id} holds outcomes of a held-out batch")
