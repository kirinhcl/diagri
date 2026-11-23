"""Append-only storage for evidence relations, reviews, withdrawals and round-card origins.

The card body is never edited; a relation between cards, the review that confirms or rejects it,
and the withdrawal that ends it are each their own appended row. The first review and the first
withdrawal stay (``INSERT OR IGNORE``). Times are epoch seconds.
"""

import json
from typing import Literal

from pydantic import Field

from growbridge.archive.clock import Clock
from growbridge.archive.db import Database
from growbridge.archive.models import Label, Model

NAMESPACE = "evidence_ledger"
STEPS = (
    "CREATE TABLE evidence_relations(id TEXT PRIMARY KEY, seq INTEGER NOT NULL,"
    " kind TEXT NOT NULL CHECK (kind IN ('supersedes','contradicts','retracts')),"
    " subject_id TEXT NOT NULL, object_id TEXT, reason TEXT NOT NULL, source TEXT NOT NULL,"
    " task_id TEXT, project_id TEXT, proposed_in TEXT, at REAL NOT NULL)",
    "CREATE INDEX evidence_relations_by_subject ON evidence_relations(subject_id)",
    "CREATE INDEX evidence_relations_by_object ON evidence_relations(object_id)",
    "CREATE TABLE evidence_relation_reviews(relation_id TEXT PRIMARY KEY,"
    " decision TEXT NOT NULL CHECK (decision IN ('confirmed','rejected')),"
    " reviewer TEXT NOT NULL, note TEXT NOT NULL, at REAL NOT NULL)",
    "CREATE TABLE evidence_relation_withdrawals(relation_id TEXT PRIMARY KEY,"
    " actor TEXT NOT NULL, reason TEXT NOT NULL, at REAL NOT NULL)",
    "CREATE TABLE evidence_origins(card_id TEXT PRIMARY KEY, project_id TEXT NOT NULL,"
    " round_id TEXT NOT NULL, report_artifact_id TEXT NOT NULL UNIQUE,"
    " snapshot_ids TEXT NOT NULL, label TEXT NOT NULL, at REAL NOT NULL)",
)

RelationKind = Literal["supersedes", "contradicts", "retracts"]
Decision = Literal["confirmed", "rejected"]
RelationState = Literal["pending", "confirmed", "rejected", "withdrawn"]


class EvidenceRelation(Model):
    id: str
    kind: RelationKind
    subject_id: str
    object_id: str | None
    reason: str
    source: str
    task_id: str | None
    project_id: str | None
    proposed_in: str | None
    at: float


def foreign_proposal(relation: EvidenceRelation, viewer: str | None) -> bool:
    """A model's proposal made in another project than the viewer's (None: the global view).
    Its reason stays in that project, and while it is not confirmed the viewer does not see it."""
    return relation.proposed_in not in (None, viewer)


class RelationReview(Model):
    relation_id: str
    decision: Decision
    reviewer: str = Field(min_length=1)
    note: str = ""
    at: float


class RelationWithdrawal(Model):
    relation_id: str
    actor: str = Field(min_length=1)
    reason: str
    at: float


class RelationRecord(Model):
    relation: EvidenceRelation
    review: RelationReview | None
    withdrawal: RelationWithdrawal | None

    @property
    def state(self) -> RelationState:
        if self.withdrawal is not None:
            return "withdrawn"
        return self.review.decision if self.review is not None else "pending"


class EvidenceOrigin(Model):
    card_id: str
    project_id: str
    round_id: str
    report_artifact_id: str
    snapshot_ids: tuple[str, ...]
    label: Label
    at: float


_RELATION_FIELDS = tuple(EvidenceRelation.model_fields)
_RELATION_COLUMNS = ", ".join(_RELATION_FIELDS)


class EvidenceLedger:
    def __init__(self, db: Database, clock: Clock):
        self.db = db
        self.clock = clock
        db.migrate(NAMESPACE, STEPS)

    # --- relations -----------------------------------------------------------------------------

    def add_relation(
        self, relation: EvidenceRelation, confirmed_by: str | None = None, note: str = ""
    ) -> RelationRecord:
        """Append a relation; with ``confirmed_by`` its confirmation is written in the same step,
        stamped with the relation's own time."""
        with self.db.transaction():
            seq = self.db.one("SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM evidence_relations")["n"]
            marks = ", ".join("?" * (len(_RELATION_FIELDS) + 1))
            self.db.execute(
                f"INSERT INTO evidence_relations({_RELATION_COLUMNS}, seq) VALUES ({marks})",
                (*(getattr(relation, name) for name in _RELATION_FIELDS), seq),
            )
            if confirmed_by is not None:
                self._insert_review(relation.id, "confirmed", confirmed_by, note, relation.at)
        return self._required(relation.id)

    def review(
        self, relation_id: str, decision: Decision, reviewer: str, note: str = ""
    ) -> RelationRecord:
        """Append the review of a relation; repeating it keeps the first one."""
        with self.db.transaction():
            self._required(relation_id)
            self._insert_review(relation_id, decision, reviewer, note, self.clock.now())
        return self._required(relation_id)

    def withdraw(self, relation_id: str, actor: str, reason: str) -> RelationRecord:
        """Append the withdrawal of a relation; repeating it keeps the first one."""
        with self.db.transaction():
            self._required(relation_id)
            withdrawal = RelationWithdrawal(
                relation_id=relation_id, actor=actor, reason=reason, at=self.clock.now()
            )
            self.db.execute(
                "INSERT OR IGNORE INTO evidence_relation_withdrawals VALUES (?, ?, ?, ?)",
                (withdrawal.relation_id, withdrawal.actor, withdrawal.reason, withdrawal.at),
            )
        return self._required(relation_id)

    def record(self, relation_id: str) -> RelationRecord | None:
        row = self.db.one(
            f"SELECT {_RELATION_COLUMNS} FROM evidence_relations WHERE id = ?", (relation_id,)
        )
        return self._assemble(row) if row else None

    def records(self, project_id: str | None) -> tuple[RelationRecord, ...]:
        """The relations without a project and those of ``project_id``, in the order written."""
        rows = self.db.query(
            f"SELECT {_RELATION_COLUMNS} FROM evidence_relations"
            " WHERE project_id IS NULL OR project_id = ? ORDER BY seq",
            (project_id,),
        )
        return tuple(self._assemble(row) for row in rows)

    def proposed_by(self, task_id: str) -> int:
        row = self.db.one(
            "SELECT COUNT(*) AS n FROM evidence_relations WHERE task_id = ?", (task_id,)
        )
        return int(row["n"])

    # --- round-card origins --------------------------------------------------------------------

    def add_origin(self, origin: EvidenceOrigin) -> None:
        """Record where a round card came from; a card and a report each have one origin."""
        self.db.execute(
            "INSERT INTO evidence_origins VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                origin.card_id,
                origin.project_id,
                origin.round_id,
                origin.report_artifact_id,
                json.dumps(list(origin.snapshot_ids)),
                origin.label,
                origin.at,
            ),
        )

    def origin(self, card_id: str) -> EvidenceOrigin | None:
        row = self.db.one("SELECT * FROM evidence_origins WHERE card_id = ?", (card_id,))
        return _origin(row) if row else None

    def origins(self) -> dict[str, EvidenceOrigin]:
        rows = self.db.query("SELECT * FROM evidence_origins")
        return {row["card_id"]: _origin(row) for row in rows}

    def origin_of_report(self, artifact_id: str) -> EvidenceOrigin | None:
        row = self.db.one(
            "SELECT * FROM evidence_origins WHERE report_artifact_id = ?", (artifact_id,)
        )
        return _origin(row) if row else None

    # --- internal ------------------------------------------------------------------------------

    def _insert_review(
        self, relation_id: str, decision: Decision, reviewer: str, note: str, at: float
    ) -> None:
        # The model validates first: OR IGNORE would also swallow CHECK and NOT NULL violations.
        review = RelationReview(
            relation_id=relation_id, decision=decision, reviewer=reviewer, note=note, at=at
        )
        self.db.execute(
            "INSERT OR IGNORE INTO evidence_relation_reviews VALUES (?, ?, ?, ?, ?)",
            (review.relation_id, review.decision, review.reviewer, review.note, review.at),
        )

    def _required(self, relation_id: str) -> RelationRecord:
        found = self.record(relation_id)
        if found is None:
            raise ValueError(f"unknown evidence relation {relation_id}")
        return found

    def _assemble(self, row) -> RelationRecord:
        relation = EvidenceRelation(**dict(row))
        review = self.db.one(
            "SELECT * FROM evidence_relation_reviews WHERE relation_id = ?", (relation.id,)
        )
        withdrawal = self.db.one(
            "SELECT * FROM evidence_relation_withdrawals WHERE relation_id = ?", (relation.id,)
        )
        return RelationRecord(
            relation=relation,
            review=RelationReview(**dict(review)) if review else None,
            withdrawal=RelationWithdrawal(**dict(withdrawal)) if withdrawal else None,
        )


def _origin(row) -> EvidenceOrigin:
    fields = dict(row)
    fields["snapshot_ids"] = tuple(json.loads(fields["snapshot_ids"]))
    return EvidenceOrigin(**fields)
