"""Holdout registry for prediction models (architecture doc §9.2).

Holdout batches are registered before development starts. General reads lose the outcome labels of
those batches; a registered model is evaluated on them once as confirmatory, every later
evaluation is exploratory, and every read is logged.
"""

import json
import sqlite3
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

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
    "ALTER TABLE holdouts ADD COLUMN development_batches TEXT",  # NULL: registered before this
    "ALTER TABLE holdouts ADD COLUMN registered_by TEXT",
)


class HoldoutRead(Model):
    holdout_id: str
    reader: str
    at: float
    label: Label
    model_sha: str = ""


class Holdout(Model):
    holdout_id: str
    project_id: str
    batch_ids: tuple[str, ...]
    outcome_fields: tuple[str, ...]
    development_batch_ids: tuple[str, ...] | None  # None: registered before these were kept
    registered_at: float
    registered_by: str | None


class OutcomeSource(Protocol):
    """Whether outcome data of the given batches already exists in a project."""

    def has_outcomes(
        self, project_id: str, batch_ids: Collection[str], outcome_fields: Collection[str]
    ) -> bool: ...


class _ProjectOutcomes:
    def __init__(
        self,
        matching: Callable[[Collection[str], Collection[str]], Iterable[str]],
        owners_of: Callable[[str], Iterable[str]],
    ):
        self.matching = matching
        self.owners_of = owners_of

    def has_outcomes(
        self, project_id: str, batch_ids: Collection[str], outcome_fields: Collection[str]
    ) -> bool:
        """Whether an outcome of a held-out batch is already recorded that may belong to this
        project: in an experiment one of its stages runs, or in an experiment no stage runs.

        Data with no owner counts because it cannot be shown to belong to another project, and
        a stage of this project may take that experiment over later; a measurement for an
        experiment is accepted only when a stage owns it, so this is a second line of defence
        for records that predate that rule or arrived another way. A measurement with no batch
        matches (it cannot be placed, and the development filter hides it too).
        """
        for experiment in self.matching(batch_ids, outcome_fields):
            owners = tuple(self.owners_of(experiment))
            if not owners or project_id in owners:
                return True
        return False


def project_outcomes(
    matching: Callable[[Collection[str], Collection[str]], Iterable[str]],
    owners_of: Callable[[str], Iterable[str]],
) -> OutcomeSource:
    """An ``OutcomeSource``. ``matching(batch_ids, outcome_fields)`` lists the experiments that
    hold such a measurement (the archive answers it in SQL); ``owners_of(experiment)`` lists the
    projects whose stages run it (the workflow store)."""
    return _ProjectOutcomes(matching, owners_of)


def _named_once(names: Sequence[str]) -> bool:
    return all(name for name in names) and len(set(names)) == len(names)


def _check_lists(
    batch_ids: Sequence[str], outcome_fields: Sequence[str], development: Sequence[str]
) -> None:
    if not batch_ids or not _named_once(batch_ids):
        raise Denied(
            "batches",
            "name at least one held-out batch; names are not empty or repeated",
            reason="batches_no_holdout",
            params={},
        )
    if len(development) < MIN_DEVELOPMENT_BATCHES or not _named_once(development):
        raise Denied(
            "batches",
            f"name at least {MIN_DEVELOPMENT_BATCHES} development batches, not empty or repeated",
            reason="batches_too_few_development",
            params={"min_batches": MIN_DEVELOPMENT_BATCHES},
        )
    if set(batch_ids) & set(development):
        raise Denied(
            "batches",
            "a batch cannot be both held out and a development batch",
            reason="batches_overlap",
            params={},
        )
    if not outcome_fields or not _named_once(outcome_fields):
        raise Denied(
            "param",
            "name the outcome fields; names are not empty or repeated",
            reason="outcome_fields_invalid",
            params={},
        )


class HoldoutRegistry:
    def __init__(self, db: Database, clock: Clock, outcomes: OutcomeSource | None = None):
        self.db = db
        self.clock = clock
        self.outcomes = outcomes
        db.migrate("research_holdout", STEPS)

    def register(
        self,
        project_id: str,
        holdout_id: str,
        batch_ids: Sequence[str],
        outcome_fields: Sequence[str],
        development_batch_ids: Sequence[str],
        registered_by: str = "",
    ) -> None:
        """Register a holdout. It must come before any of its outcome data: if an outcome metric
        of a held-out batch already exists in the project, that data may already have been seen
        and the registration is refused (``state``). Nothing in the message quotes a value."""
        _check_lists(batch_ids, outcome_fields, development_batch_ids)
        if self.outcomes is not None and self.outcomes.has_outcomes(
            project_id, tuple(batch_ids), tuple(outcome_fields)
        ):
            raise Denied(
                "state",
                "outcome data of these batches already exists in the project and may already "
                "have been seen: a holdout is registered before its outcome data exists",
                reason="holdout_outcomes_exist",
                params={"project_id": project_id},
            )
        try:
            self.db.execute(
                "INSERT INTO holdouts(holdout_id, project_id, batch_ids, outcome_fields, "
                "registered_at, development_batches, registered_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    holdout_id,
                    project_id,
                    json.dumps(list(batch_ids)),
                    json.dumps(list(outcome_fields)),
                    self.clock.now(),
                    json.dumps(list(development_batch_ids)),
                    registered_by or None,
                ),
            )
        except sqlite3.IntegrityError:
            raise Denied(
                "state",
                f"holdout {holdout_id} is already registered",
                reason="holdout_already_registered",
                params={"holdout_id": holdout_id},
            ) from None

    def holdouts(self, project_id: str) -> tuple[Holdout, ...]:
        rows = self.db.query(
            "SELECT * FROM holdouts WHERE project_id = ? ORDER BY rowid", (project_id,)
        )
        return tuple(_holdout(row) for row in rows)

    def _holdout(self, holdout_id: str) -> sqlite3.Row:
        row = self.db.one("SELECT * FROM holdouts WHERE holdout_id = ?", (holdout_id,))
        if row is None:
            raise Denied(
                "state",
                f"holdout {holdout_id} is not registered",
                reason="record_not_found",
                params={"record_kind": "holdout", "record_id": holdout_id},
            )
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
                raise Denied(
                    "model_unregistered",
                    "register model, features and preprocessing",
                    reason="model_unregistered",
                    params={},
                )
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
            raise Denied(
                "scope",
                f"snapshot {snapshot_id} holds outcomes of a held-out batch",
                reason="holdout_rows",
                params={"project_id": project_id},
            )


def _holdout(row: sqlite3.Row) -> Holdout:
    development = row["development_batches"]
    return Holdout(
        holdout_id=row["holdout_id"],
        project_id=row["project_id"],
        batch_ids=tuple(json.loads(row["batch_ids"])),
        outcome_fields=tuple(json.loads(row["outcome_fields"])),
        development_batch_ids=None if development is None else tuple(json.loads(development)),
        registered_at=row["registered_at"],
        registered_by=row["registered_by"],
    )
