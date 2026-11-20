"""Derive each evidence card's validity at a point in time from append-only relation records.

Pure: the same records and ``as_of`` always give the same statuses. Precedence is
``retracted`` > ``dependency_invalid`` > ``superseded`` > ``active``.
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import Literal

from growbridge.archive.evidence_ledger import EvidenceRelation, RelationRecord
from growbridge.archive.models import Model

Validity = Literal["active", "superseded", "retracted", "dependency_invalid"]


class Replacement(Model):
    card_id: str
    validity: Validity


class CardStatus(Model):
    card_id: str
    validity: Validity = "active"
    superseded_by: str | None = None
    current_replacement: Replacement | None = None
    retracted_reason: str | None = None
    invalid_dependency: str | None = None
    contested_with: tuple[str, ...] = ()
    pending: tuple[str, ...] = ()

    @property
    def blocks(self) -> bool:
        return self.validity != "active"


def _in_force(record: RelationRecord, as_of: float) -> bool:
    """Confirmed by ``as_of`` and not yet withdrawn at ``as_of``."""
    review, withdrawal = record.review, record.withdrawal
    if review is None or review.decision != "confirmed" or review.at > as_of:
        return False
    return withdrawal is None or withdrawal.at > as_of


def _is_pending(record: RelationRecord, as_of: float, viewer_project: str | None) -> bool:
    relation = record.relation
    if relation.at > as_of:
        return False
    if relation.proposed_in not in (None, viewer_project):
        return False
    if record.review is not None and record.review.at <= as_of:
        return False
    return record.withdrawal is None or record.withdrawal.at > as_of


def _retraction_reason(record: RelationRecord, viewer_project: str | None) -> str:
    """A model's own reason stays in the project it was proposed in."""
    relation = record.relation
    if relation.proposed_in in (None, viewer_project):
        return relation.reason
    return record.review.note if record.review is not None else ""


def _affected_card(relation: EvidenceRelation) -> str | None:
    return relation.subject_id if relation.kind == "retracts" else relation.object_id


def _first_by_card(records: Iterable[RelationRecord], kind: str, as_of: float, key: str) -> dict:
    found: dict[str, RelationRecord] = {}
    for record in records:
        relation = record.relation
        if relation.kind == kind and _in_force(record, as_of):
            found.setdefault(getattr(relation, key), record)
    return found


def _pending_by_card(
    records: Sequence[RelationRecord], as_of: float, viewer_project: str | None
) -> dict[str, tuple[str, ...]]:
    pending: dict[str, list[str]] = {}
    for record in records:
        if not _is_pending(record, as_of, viewer_project):
            continue
        relation = record.relation
        cards = [_affected_card(relation)]
        if relation.kind == "contradicts":
            cards.append(relation.subject_id)
        for card in filter(None, cards):
            pending.setdefault(card, []).append(relation.id)
    return {card: tuple(ids) for card, ids in pending.items()}


def _base_validity(card: str, retracted, invalid_at, superseded, as_of: float) -> Validity:
    if card in retracted:
        return "retracted"
    if card in invalid_at and invalid_at[card][0] <= as_of:
        return "dependency_invalid"
    return "superseded" if card in superseded else "active"


def _replacement(card: str, superseded_by: Mapping[str, str], validity) -> Replacement | None:
    if card not in superseded_by:
        return None
    seen, current = {card}, superseded_by[card]
    while current in superseded_by and superseded_by[current] not in seen:
        seen.add(current)
        current = superseded_by[current]
    return Replacement(card_id=current, validity=validity[current])


def _contested(card: str, records, validity, as_of: float) -> tuple[str, ...]:
    others: list[str] = []
    for record in records:
        relation = record.relation
        if relation.kind != "contradicts" or relation.object_id is None:
            continue
        if not _in_force(record, as_of) or card not in (relation.subject_id, relation.object_id):
            continue
        other = relation.object_id if card == relation.subject_id else relation.subject_id
        if validity.get(other, "active") == "active" and other not in others:
            others.append(other)
    return tuple(others)


def _all_cards(card_ids: Iterable[str], records: Sequence[RelationRecord]) -> list[str]:
    cards = list(dict.fromkeys(card_ids))
    for record in records:
        named = (record.relation.subject_id, record.relation.object_id)
        cards.extend(c for c in named if c is not None and c not in cards)
    return cards


def derive_statuses(
    card_ids: Iterable[str],
    records: Sequence[RelationRecord],
    invalid_at: Mapping[str, tuple[float, str]],
    as_of: float,
    viewer_project: str | None,
) -> dict[str, CardStatus]:
    """Every card in ``card_ids`` or named by a record, with its status at ``as_of``.

    ``invalid_at`` maps a card to (when its dependency became invalid, that dependency's id).
    """
    cards = _all_cards(card_ids, records)
    retracted = _first_by_card(records, "retracts", as_of, "subject_id")
    supersedes = _first_by_card(records, "supersedes", as_of, "object_id")
    superseded_by = {card: rec.relation.subject_id for card, rec in supersedes.items()}
    validity = {
        card: _base_validity(card, retracted, invalid_at, superseded_by, as_of) for card in cards
    }
    pending = _pending_by_card(records, as_of, viewer_project)
    reasons = {c: _retraction_reason(r, viewer_project) for c, r in retracted.items()}
    return {
        card: CardStatus(
            card_id=card,
            validity=validity[card],
            superseded_by=superseded_by.get(card),
            current_replacement=_replacement(card, superseded_by, validity),
            retracted_reason=reasons.get(card),
            invalid_dependency=(
                invalid_at[card][1] if validity[card] == "dependency_invalid" else None
            ),
            contested_with=_contested(card, records, validity, as_of),
            pending=pending.get(card, ()),
        )
        for card in cards
    }
