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

from growbridge.archive.evidence_book import card_project, card_statuses, visible_cards
from growbridge.archive.evidence_status import Validity
from growbridge.archive.ids import new_id
from growbridge.archive.models import ApplicabilityRange, EvidenceCard
from growbridge.archive.store import Archive, EvidenceEntry
from growbridge.ports import Actor, Denied
from growbridge.vocab import Catalog
from growbridge.vocab.card_checks import checked_card
from growbridge.workbench.common import Body
from growbridge.workbench.rounds import PathId
from growbridge.workbench.scope import project_read
from growbridge.workflow import denials
from growbridge.workflow.access import Access

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
    variable: str | None = None
    conditions: tuple[ApplicabilityRange, ...] = ()
    crop_taxon: str = ""
    cultivar: str = ""
    growth_stage: str = ""
    conditions_note: str = ""


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


def pickable_variables(catalog: Catalog) -> list[dict]:
    """The standard variables a card may name: measured or manual, current, not a factor."""
    return [
        {
            "id": v.id,
            "kind": v.kind,
            "unit": v.unit,
            "label_en": v.label_en,
            "label_zh": v.label_zh,
        }
        for v in catalog.variables
        if v.kind in ("sensor", "manual") and not v.deprecated
    ]


class EvidenceRoutes:
    def __init__(self, archive: Archive, catalog: Catalog, access: Access | None = None):
        self.archive = archive
        self.catalog = catalog
        self.access = access

    def enter(self, body: CardIn, actor: Actor) -> dict:
        card = EvidenceCard(
            id=new_id("evidence"),
            source_class=body.source_class,
            citation=body.citation,
            claim=body.claim,
            value=body.value,
            unit=body.unit or None,
            calibrated=body.calibrated,
            variable=body.variable,
            conditions=body.conditions,
            crop_taxon=body.crop_taxon,
            cultivar=body.cultivar,
            growth_stage=body.growth_stage,
            conditions_note=body.conditions_note,
        )
        card = checked_card(card, self.catalog)
        source = f"operator:{actor.id}"
        self.archive.add_evidence(card, source=source, verified_by=actor.id)
        return {"id": card.id, "verified": True, "source": source}

    @staticmethod
    def _not_found(card_id: str) -> Denied:
        return Denied(
            "state",
            f"unknown evidence card {card_id}",
            reason="record_not_found",
            params={"record_kind": "evidence_card", "record_id": card_id},
        )

    def _check_seen(self, actor: Actor, card_id: str) -> None:
        """A round card of a project the caller cannot see answers as a card that does not
        exist, so neither the card nor who converted it is revealed (design §6)."""
        if self.access is None:
            return
        project = card_project(self.archive, card_id)
        if project is not None and not self.access.sees_project(actor, project):
            raise self._not_found(card_id)

    def verify(self, card_id: str, body: VerifyIn, actor: Actor) -> dict:
        self._check_seen(actor, card_id)
        try:
            record = self.archive.verify_evidence(card_id, actor.id, body.note, body.calibrated)
        except ValueError:
            raise self._not_found(card_id) from None
        return {
            "card_id": record.card_id,
            "verified": True,
            "verified_by": record.verifier,
            "verified_at": record.at,
            "note": record.note,
            "calibrated": record.calibrated,
        }

    def listing(
        self,
        actor: Actor,
        project_id: str | None = None,
        as_of: float | None = None,
        status: Validity | None = None,
        variable: str | None = None,
    ) -> dict:
        """The cards visible in the scope (public ones, plus a project's own round cards) with
        their status as of ``as_of``, narrowed by validity and by the variable they name."""
        if project_id is not None:
            project_read(
                self.access, actor, project_id, lambda: denials.unknown("project", project_id)
            )
        visible = visible_cards(self.archive, project_id)
        entries = [e for e in self.archive.evidence_entries() if e.card.id in visible]
        statuses = card_statuses(self.archive, [e.card.id for e in entries], project_id, as_of)
        origins = self.archive.ledger.origins()
        wanted = None if variable is None else self._key(variable)
        cards = []
        for entry in entries:
            state = statuses[entry.card.id]
            if status is not None and state.validity != status:
                continue
            if wanted is not None and self._key(entry.card.variable) != wanted:
                continue
            cards.append(self._row(entry, state, origins.get(entry.card.id)))
        return {"cards": cards, "variables": pickable_variables(self.catalog)}

    def _key(self, name: str | None) -> str | None:
        if name is None:
            return None
        current = self.catalog.current(name)
        return current.id if current else name

    @staticmethod
    def _row(entry: EvidenceEntry, state, origin) -> dict:
        row = {**entry_json(entry), "status": state.model_dump(mode="json")}
        if origin is not None:
            row["origin"] = {
                "round_id": origin.round_id,
                "report_artifact_id": origin.report_artifact_id,
                "label": origin.label,
            }
        return row


def add_evidence_routes(
    router: APIRouter,
    operator: Dependency,
    archive: Archive,
    workflow,
    access: Access | None = None,
) -> None:
    """Mount the routes on ``router``; ``operator`` is the workbench's operator dependency."""
    Operator = Annotated[Actor, Depends(operator)]  # noqa: N806
    routes = EvidenceRoutes(archive, workflow.catalog, access)

    @router.post("/evidence")
    async def enter_card(body: CardIn, actor: Operator):
        return routes.enter(body, actor)

    @router.post("/evidence/{card_id}/verify")
    async def verify_card(card_id: PathId, body: VerifyIn, actor: Operator):
        return routes.verify(card_id, body, actor)

    @router.get("/evidence")
    async def list_cards(
        actor: Operator,
        project_id: str | None = None,
        as_of: float | None = None,
        status: Validity | None = None,
        variable: str | None = None,
    ):
        return routes.listing(actor, project_id, as_of, status, variable)
