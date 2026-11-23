"""The evidence query tool, shared by the researcher and the planner.

Cards are read from the bound task's project only (public cards plus that project's round
cards) and each carries its status there. A superseded, retracted or dependency-invalid card is
not listed by a text or variable search (only counted); asked for by id it comes back without its
claim or value, so it cannot be cited by accident, and says what replaces it.
"""

from __future__ import annotations

from pydantic import Field

from growbridge.agents.handlers_common import (
    MAX_ITEMS,
    Deps,
    ToolInput,
    bound_task,
    clip,
)
from growbridge.archive.evidence_book import card_statuses, visible_cards
from growbridge.archive.evidence_status import CardStatus
from growbridge.archive.models import EvidenceCard
from growbridge.vocab import Catalog

QUERY_EVIDENCE_DESCRIPTION = (
    "Search the evidence cards your task's project can see, by ids, text or catalog "
    "variable. Each card says whether it is verified and gives its status (active, "
    "superseded, retracted or dependency_invalid). A search lists active cards only and "
    "counts the others in hidden_inactive; asked for by id, an inactive card comes back "
    "without its claim or value and names its replacement: cite that, not this one."
)


class EvidenceInput(ToolInput):
    ids: tuple[str, ...] = ()
    text: str = ""
    variable: str = ""  # a catalog variable, by standard ID or alias
    limit: int = Field(default=MAX_ITEMS, ge=1, le=MAX_ITEMS)


def _variable_key(name: str, catalog: Catalog) -> str:
    current = catalog.current(name)
    return current.id if current is not None else name


def _matches(card: EvidenceCard, data: EvidenceInput, catalog: Catalog) -> bool:
    if data.text and data.text.casefold() not in f"{card.claim} {card.citation}".casefold():
        return False
    if not data.variable:
        return True
    if card.variable is None:
        return False
    return _variable_key(card.variable, catalog) == _variable_key(data.variable, catalog)


def _status_fields(status: CardStatus) -> dict:
    replacement = status.current_replacement
    return {
        "status": status.validity,
        "superseded_by": status.superseded_by,
        "current_replacement": None if replacement is None else replacement.model_dump(),
    }


def _inactive_view(card: EvidenceCard, status: CardStatus) -> dict:
    return {
        "id": card.id,
        "source_class": card.source_class,
        "citation": clip(card.citation, 300),
        **_status_fields(status),
    }


def _new_fields(card: EvidenceCard, label: str | None) -> dict:
    extra: dict = {
        "variable": card.variable,
        "conditions": [c.model_dump() for c in card.conditions],
        "crop_taxon": card.crop_taxon,
        "cultivar": card.cultivar,
        "growth_stage": card.growth_stage,
        "conditions_note": card.conditions_note,
        "label": label,
    }
    return {key: value for key, value in extra.items() if value}


def _active_view(card: EvidenceCard, status: CardStatus, label: str | None) -> dict:
    return {
        "id": card.id,
        "source_class": card.source_class,
        "citation": clip(card.citation, 300),
        "claim": clip(card.claim, 300),
        "value": card.value,
        "unit": card.unit,
        "verified": card.verified,
        "calibrated": card.calibrated,
        **_status_fields(status),
        "contested_with": list(status.contested_with),
        "pending": list(status.pending),
        **_new_fields(card, label),
    }


def query_cards(deps: Deps, data: EvidenceInput) -> dict:
    """Search the evidence cards of the bound task's project."""
    project_id = bound_task(deps).project_id
    pool = visible_cards(deps.archive, project_id)
    cards = [pool[i] for i in data.ids if i in pool] if data.ids else list(pool.values())
    cards = [c for c in cards if _matches(c, data, deps.workflow.catalog)]
    statuses = card_statuses(deps.archive, [c.id for c in cards], project_id)
    origins = deps.archive.ledger.origins()
    shown: list[dict] = []
    hidden = 0
    for card in cards:
        status = statuses[card.id]
        if not status.blocks:
            origin = origins.get(card.id)
            shown.append(_active_view(card, status, None if origin is None else origin.label))
        elif data.ids:
            shown.append(_inactive_view(card, status))
        else:
            hidden += 1
    return {"cards": shown[: data.limit], "hidden_inactive": hidden}
