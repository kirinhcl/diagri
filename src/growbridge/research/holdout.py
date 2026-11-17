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
from growbridge.vocab import Catalog, packaged_catalog

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
    """Which outcome data of the given batches already exists in a project."""

    def existing_outcomes(
        self, project_id: str, batch_ids: Collection[str], outcome_fields: Collection[str]
    ) -> tuple[str, ...]: ...


class _ProjectOutcomes:
    def __init__(
        self,
        matching: Callable[[Collection[str]], Iterable[tuple[str, str]]],
        owners_of: Callable[[str], Iterable[str]],
        catalog: Catalog,
    ):
        self.matching = matching
        self.owners_of = owners_of
        self.catalog = catalog

    def existing_outcomes(
        self, project_id: str, batch_ids: Collection[str], outcome_fields: Collection[str]
    ) -> tuple[str, ...]:
        """The sorted, distinct metric names, as recorded, of outcome data of a held-out batch
        that already exists and may belong to this project: in an experiment one of its stages
        runs, or in an experiment no stage runs.

        A name counts when it resolves to one of the outcome fields, or when the catalog cannot
        resolve it at all: an unknown name may be a misspelt outcome, so it is treated as one.
        Data with no owner counts because it cannot be shown to belong to another project, and
        a stage of this project may take that experiment over later; a measurement for an
        experiment is accepted only when a stage owns it, so this is a second line of defence
        for records that predate that rule or arrived another way. A measurement with no batch
        matches (it cannot be placed, and the development filter hides it too).
        """
        fields = {self.catalog.canonical(field) for field in outcome_fields} - {None}
        found: set[str] = set()
        for experiment, metric in self.matching(batch_ids):
            name = self.catalog.canonical(metric)
            if name is not None and name not in fields:
                continue
            owners = tuple(self.owners_of(experiment))
            if not owners or project_id in owners:
                found.add(metric)
        return tuple(sorted(found))


def project_outcomes(
    matching: Callable[[Collection[str]], Iterable[tuple[str, str]]],
    owners_of: Callable[[str], Iterable[str]],
    catalog: Catalog | None = None,
) -> OutcomeSource:
    """An ``OutcomeSource``. ``matching(batch_ids)`` lists the ``(experiment, metric)`` pairs
    recorded for those batches (the archive answers it in SQL); ``owners_of(experiment)`` lists
    the projects whose stages run it (the workflow store)."""
    return _ProjectOutcomes(matching, owners_of, catalog or packaged_catalog())


def _named_once(names: Sequence[str]) -> bool:
    return all(name for name in names) and len(set(names)) == len(names)


def _check_lists(
    batch_ids: Sequence[str], outcome_fields: Sequence[str], development: Sequence[str]
) -> None:
    if not batch_ids or not _named_once(batch_ids):
        raise Denied("batches", "name at least one held-out batch; names are not empty or repeated")
    if len(development) < MIN_DEVELOPMENT_BATCHES or not _named_once(development):
        raise Denied(
            "batches",
            f"name at least {MIN_DEVELOPMENT_BATCHES} development batches, not empty or repeated",
        )
    if set(batch_ids) & set(development):
        raise Denied("batches", "a batch cannot be both held out and a development batch")
    if not outcome_fields or not _named_once(outcome_fields):
        raise Denied("param", "name the outcome fields; names are not empty or repeated")


class HoldoutRegistry:
    def __init__(
        self,
        db: Database,
        clock: Clock,
        outcomes: OutcomeSource | None = None,
        catalog: Catalog | None = None,
    ):
        self.db = db
        self.clock = clock
        self.outcomes = outcomes
        self.catalog = catalog or packaged_catalog()
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
        unknown = [f for f in outcome_fields if self.catalog.canonical(f) is None]
        if unknown:
            raise Denied(
                "param", "outcome fields not in the variable catalog: " + ", ".join(unknown)
            )
        existing = (
            self.outcomes.existing_outcomes(project_id, tuple(batch_ids), tuple(outcome_fields))
            if self.outcomes is not None
            else ()
        )
        if existing:
            raise Denied(
                "state",
                "outcome data of these batches already exists in the project and may already "
                "have been seen: a holdout is registered before its outcome data exists: "
                + ", ".join(existing),
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
            raise Denied("state", f"holdout {holdout_id} is already registered") from None

    def holdouts(self, project_id: str) -> tuple[Holdout, ...]:
        rows = self.db.query(
            "SELECT * FROM holdouts WHERE project_id = ? ORDER BY rowid", (project_id,)
        )
        return tuple(_holdout(row) for row in rows)

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
        measurement without a batch cannot be placed and is treated as held out. Metrics are
        compared by catalog ID; a name the catalog cannot resolve is treated as an outcome, so a
        misspelt outcome in a held-out batch is hidden (in a development batch it is kept).
        """
        catalog = self.catalog

        def keep(measurement: ManualMeasurement) -> bool:
            name = catalog.canonical(measurement.metric)  # None: unknown, treated as an outcome
            rows = self.db.query(
                "SELECT batch_ids, outcome_fields FROM holdouts WHERE project_id = ?",
                (project_id,),
            )
            for row in rows:
                fields = {catalog.canonical(f) for f in json.loads(row["outcome_fields"])}
                if name is not None and name not in fields:
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
