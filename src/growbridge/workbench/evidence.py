"""Workbench routes of evidence cards (architecture §6.4), under ``/wb``.

An operator enters a card, verifies a card a model role proposed, and lists every card with its
trail. Operators only: a model role is refused with ``model_role``. None of the writes needs a
recent re-authentication, because they only record what the operator read; a card never gates
an approval by itself (``check_evidence`` hints are advisory).

Whoever enters or verifies is the session's operator, never a body field, and the card id is made
by the server. A card entered here is verified by its author in the same step. A verification is a
record of its own (``Archive.verify_evidence``); the card text is never edited.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import StringConstraints

from growbridge.archive.ids import new_id
from growbridge.archive.models import EvidenceCard
from growbridge.archive.store import Archive, EvidenceEntry
from growbridge.ports import Actor, Denied
from growbridge.workbench.common import Body
from growbridge.workbench.rounds import PathId

CITATION_MAX = 500  # a full reference with a DOI fits; a pasted page does not
CLAIM_MAX = 1000
UNIT_MAX = 40
NOTE_MAX = 500
Dependency = Callable[..., Awaitable[Actor]]


Citation = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=CITATION_MAX)
]
Claim = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=CLAIM_MAX)]
Unit = Annotated[str, StringConstraints(strip_whitespace=True, max_length=UNIT_MAX)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=NOTE_MAX)]


class CardIn(Body):
    source_class: Literal["handbook", "paper", "local"]
    citation: Citation
    claim: Claim
    value: float | None = None  # finite: the body refuses NaN and infinity
    unit: Unit | None = None
    calibrated: bool = True


class VerifyIn(Body):
    note: Note = ""
    # The operator's attestation that the value was calibrated against a local measurement. A
    # model cannot claim it; it is stored with the verification record, and the first one stays.
    calibrated: bool = False


def entry_json(entry: EvidenceEntry) -> dict:
    return {
        **entry.card.model_dump(mode="json"),
        "source": entry.source,
        "task_id": entry.task_id,
        "added_at": entry.added_at,
        "verified_by": entry.verified_by,
        "verified_at": entry.verified_at,
        "note": entry.note,
    }


class EvidenceRoutes:
    def __init__(self, archive: Archive):
        self.archive = archive

    def enter(self, body: CardIn, actor: Actor) -> dict:
        card = EvidenceCard(
            id=new_id("evidence"),
            source_class=body.source_class,
            citation=body.citation,
            claim=body.claim,
            value=body.value,
            unit=body.unit or None,
            calibrated=body.calibrated,
        )
        source = f"operator:{actor.id}"
        self.archive.add_evidence(card, source=source, verified_by=actor.id)
        return {"id": card.id, "verified": True, "source": source}

    def verify(self, card_id: str, body: VerifyIn, actor: Actor) -> dict:
        try:
            record = self.archive.verify_evidence(card_id, actor.id, body.note, body.calibrated)
        except ValueError:
            raise Denied(
                "state",
                f"unknown evidence card {card_id}",
                reason="record_not_found",
                params={"record_kind": "evidence_card", "record_id": card_id},
            ) from None
        return {
            "card_id": record.card_id,
            "verified": True,
            "verified_by": record.verifier,
            "verified_at": record.at,
            "note": record.note,
            "calibrated": record.calibrated,
        }

    def listing(self) -> dict:
        return {"cards": [entry_json(entry) for entry in self.archive.evidence_entries()]}


def add_evidence_routes(router: APIRouter, operator: Dependency, archive: Archive) -> None:
    """Mount the routes on ``router``; ``operator`` is the workbench's operator dependency."""
    Operator = Annotated[Actor, Depends(operator)]  # noqa: N806
    routes = EvidenceRoutes(archive)

    @router.post("/evidence")
    async def enter_card(body: CardIn, actor: Operator):
        return routes.enter(body, actor)

    @router.post("/evidence/{card_id}/verify")
    async def verify_card(card_id: PathId, body: VerifyIn, actor: Operator):
        return routes.verify(card_id, body, actor)

    @router.get("/evidence")
    async def list_cards(actor: Operator):
        return routes.listing()
