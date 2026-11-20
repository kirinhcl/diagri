"""The rules for proposing, recording, reviewing and withdrawing relations between evidence cards.

A model may only propose a relation (it stays pending); an operator records one in a single step,
or reviews a pending one, or withdraws a confirmed one. Every write is checked against the cards'
status as seen from the viewer's project, and the check is repeated when a pending relation is
confirmed. A refusal is a ``RelationRefused`` carrying a registered denial reason.
"""

from typing import Annotated, Any, Literal

from pydantic import StringConstraints, TypeAdapter

from growbridge.archive.evidence_book import card_project, card_statuses, visible_cards
from growbridge.archive.evidence_ledger import (
    EvidenceRelation,
    RelationKind,
    RelationRecord,
    foreign_proposal,
)
from growbridge.archive.ids import new_id
from growbridge.archive.models import Model
from growbridge.archive.store import MODEL_SOURCE, Archive
from growbridge.denial_codes import DENIAL_CODES
from growbridge.ports import Denied

REASON_MAX = 500
MAX_RELATION_PROPOSALS_PER_TASK = 10
MODEL_RELATION_SOURCE = "model:planner"

Reason = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=REASON_MAX)
]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=REASON_MAX)]
_REASON = TypeAdapter(Reason)
_NOTE = TypeAdapter(Note)


class RelationRequest(Model):
    kind: RelationKind
    card_id: str
    other_card_id: str | None = None
    reason: Reason


class RelationRefused(ValueError):
    def __init__(self, reason: str, message: str, params: dict[str, Any] | None = None):
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.params = params or {}


def as_denied(error: RelationRefused) -> Denied:
    """The refusal as a ``Denied`` with the coarse code its reason is registered under."""
    return Denied(
        DENIAL_CODES[error.reason].of, error.message, reason=error.reason, params=error.params
    )


def _cards(request: RelationRequest) -> tuple[str, ...]:
    return tuple(c for c in (request.card_id, request.other_card_id) if c is not None)


def check_request(request: RelationRequest) -> None:
    """Every check that depends on the request alone (its shape, a card related to itself)."""
    has_other = request.other_card_id is not None
    if has_other != (request.kind != "retracts"):
        raise RelationRefused(
            "relation_shape",
            f"A {request.kind} relation {'must not name' if has_other else 'needs'} another card.",
            {"kind": request.kind},
        )
    if request.card_id == request.other_card_id:
        raise RelationRefused("relation_self", "A card cannot be related to itself.")


def unknown_card(card_id: str) -> RelationRefused:
    """The refusal for a card that does not exist or is not visible to the viewer."""
    return RelationRefused(
        "relation_unknown_card", f"Unknown evidence card {card_id}.", {"card_id": card_id}
    )


def _check_visible(archive: Archive, request: RelationRequest, viewer: str | None) -> None:
    visible = visible_cards(archive, viewer)
    for card_id in _cards(request):
        if card_id not in visible:
            raise unknown_card(card_id)


def relation_scope(archive: Archive, request: RelationRequest) -> str | None:
    """The project of the project card among the two (None when both are public)."""
    projects = {p for c in _cards(request) if (p := card_project(archive, c)) is not None}
    if len(projects) > 1:
        raise RelationRefused(
            "relation_cross_scope",
            "The two cards belong to different projects.",
            {"kind": request.kind},
        )
    return next(iter(projects), None)


def _check_scope(archive: Archive, request: RelationRequest) -> str | None:
    scope = relation_scope(archive, request)
    if request.kind == "supersedes" and card_project(archive, request.card_id) != card_project(
        archive, request.other_card_id or ""
    ):
        raise RelationRefused(
            "relation_cross_scope",
            "A card can only supersede a card in the same scope.",
            {"kind": request.kind},
        )
    return scope


def _inactive(card_id: str, validity: str) -> RelationRefused:
    return RelationRefused(
        "relation_card_inactive",
        f"Card {card_id} is {validity}.",
        {"card_id": card_id, "validity": validity},
    )


def _check_status(archive: Archive, request: RelationRequest, viewer: str | None) -> None:
    if request.kind == "contradicts":
        return
    status = card_statuses(archive, _cards(request), viewer)
    subject = status[request.card_id]
    if request.kind == "retracts" and subject.validity == "retracted":
        raise _inactive(request.card_id, subject.validity)
    if request.kind != "supersedes":
        return
    if subject.validity != "active":
        raise _inactive(request.card_id, subject.validity)
    replacement = status[request.other_card_id or ""].superseded_by
    if replacement is not None:
        raise RelationRefused(
            "relation_already_superseded",
            f"Card {request.other_card_id} is already superseded by {replacement}.",
            {"card_id": request.other_card_id, "replacement_id": replacement},
        )


def _key(kind: str, subject: str, other: str | None) -> tuple[Any, ...]:
    """A contradiction has no direction; the other kinds do."""
    return (kind, frozenset((subject, other))) if kind == "contradicts" else (kind, subject, other)


def _check_duplicate(
    archive: Archive, request: RelationRequest, viewer: str | None, exclude: str | None
) -> None:
    wanted = _key(request.kind, request.card_id, request.other_card_id)
    for record in archive.ledger.records(viewer):
        relation = record.relation
        live = record.state == "confirmed" or (
            record.state == "pending" and not foreign_proposal(relation, viewer)
        )
        same = _key(relation.kind, relation.subject_id, relation.object_id) == wanted
        if live and same and relation.id != exclude:
            raise RelationRefused(
                "relation_duplicate",
                "The same relation is already recorded or waiting for review.",
                {"relation_id": relation.id},
            )


def _validate(
    archive: Archive, request: RelationRequest, viewer: str | None, exclude: str | None = None
) -> str | None:
    """Refuse a relation the rules do not allow; return the project it belongs to."""
    check_request(request)
    _check_visible(archive, request, viewer)
    scope = _check_scope(archive, request)
    _check_status(archive, request, viewer)
    _check_duplicate(archive, request, viewer, exclude)
    return scope


def _relation(
    archive: Archive, request: RelationRequest, scope: str | None, **origin: str | None
) -> EvidenceRelation:
    """The relation as stored; a contradiction keeps the smaller card id as its subject."""
    subject, other = request.card_id, request.other_card_id
    if request.kind == "contradicts" and other is not None:
        subject, other = sorted((subject, other))
    return EvidenceRelation(
        id=new_id("rel"),
        kind=request.kind,
        subject_id=subject,
        object_id=other,
        reason=request.reason,
        project_id=scope,
        at=archive.clock.now(),
        **origin,  # type: ignore[arg-type]
    )


def propose_relation(
    archive: Archive, request: RelationRequest, task_id: str, project_id: str
) -> RelationRecord:
    """Store a model's proposal as pending."""
    with archive.ledger.db.transaction():
        if archive.ledger.proposed_by(task_id) >= MAX_RELATION_PROPOSALS_PER_TASK:
            raise RelationRefused(
                "quota_proposal_limit",
                f"A task may propose at most {MAX_RELATION_PROPOSALS_PER_TASK} relations.",
                {"max_proposals": MAX_RELATION_PROPOSALS_PER_TASK},
            )
        scope = _validate(archive, request, project_id)
        relation = _relation(
            archive,
            request,
            scope,
            source=MODEL_RELATION_SOURCE,
            task_id=task_id,
            proposed_in=project_id,
        )
        return archive.ledger.add_relation(relation)


def record_relation(
    archive: Archive, request: RelationRequest, actor_id: str, viewer_project: str | None
) -> RelationRecord:
    """Store an operator's relation, confirmed in the same step."""
    with archive.ledger.db.transaction():
        scope = _validate(archive, request, viewer_project)
        relation = _relation(
            archive, request, scope, source=f"operator:{actor_id}", task_id=None, proposed_in=None
        )
        return archive.ledger.add_relation(relation, confirmed_by=actor_id)


def relation_not_found(relation_id: str) -> RelationRefused:
    return RelationRefused(
        "record_not_found",
        f"No evidence relation {relation_id}.",
        {"record_kind": "evidence_relation", "record_id": relation_id},
    )


def _visible_record(archive: Archive, relation_id: str, viewer: str | None) -> RelationRecord:
    """The record, or "not found" when its cards are not visible to the viewer."""
    record = archive.ledger.record(relation_id)
    if record is None:
        raise relation_not_found(relation_id)
    relation = record.relation
    # A proposal not confirmed (pending or rejected) is seen only where it was made.
    hidden = record.state in ("pending", "rejected") and foreign_proposal(relation, viewer)
    named = (relation.subject_id, relation.object_id)
    visible = visible_cards(archive, viewer)
    if (
        hidden
        or relation.project_id not in (None, viewer)
        or any(card_id is not None and card_id not in visible for card_id in named)
    ):
        raise relation_not_found(relation_id)
    return record


def _as_request(relation: EvidenceRelation) -> RelationRequest:
    return RelationRequest(
        kind=relation.kind,
        card_id=relation.subject_id,
        other_card_id=relation.object_id,
        reason=relation.reason,
    )


def _check_confirmable(
    archive: Archive, record: RelationRecord, note: str, viewer: str | None
) -> None:
    relation = record.relation
    # A model's proposal about public cards takes effect everywhere; other projects see the note.
    if relation.source.startswith(MODEL_SOURCE) and relation.project_id is None and not note:
        raise RelationRefused(
            "relation_note_required", "Say why you confirm this proposal (a note is required)."
        )
    _validate(archive, _as_request(relation), viewer, exclude=relation.id)


def review_relation(
    archive: Archive,
    relation_id: str,
    decision: Literal["confirmed", "rejected"],
    reviewer: str,
    note: str,
    viewer_project: str | None,
) -> RelationRecord:
    """Confirm or reject a pending relation; confirming re-checks the rules first."""
    note = _NOTE.validate_python(note)
    with archive.ledger.db.transaction():
        record = _visible_record(archive, relation_id, viewer_project)
        if record.state != "pending":
            raise RelationRefused(
                "relation_not_pending",
                f"Relation {relation_id} is {record.state}, not pending.",
                {"relation_id": relation_id, "state": record.state},
            )
        if decision == "confirmed":
            _check_confirmable(archive, record, note, viewer_project)
        return archive.ledger.review(relation_id, decision, reviewer, note)


def withdraw_relation(
    archive: Archive, relation_id: str, actor: str, reason: str, viewer_project: str | None
) -> RelationRecord:
    """End a confirmed relation."""
    reason = _REASON.validate_python(reason)
    with archive.ledger.db.transaction():
        record = _visible_record(archive, relation_id, viewer_project)
        if record.state != "confirmed":
            raise RelationRefused(
                "relation_not_confirmed",
                f"Relation {relation_id} is {record.state}, not confirmed.",
                {"relation_id": relation_id, "state": record.state},
            )
        return archive.ledger.withdraw(relation_id, actor, reason)
