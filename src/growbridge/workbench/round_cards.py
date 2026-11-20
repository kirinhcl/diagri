"""The workbench route that turns a delivered round's report conclusion into an evidence card.

``POST /wb/rounds/{round_id}/evidence``: an operator who owns the round's project vouches for the
conclusion; the card is verified at once and scoped to that project. A round the caller cannot
see is answered as an unknown round. Operators only: a model role is refused.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends

from growbridge.archive.store import Archive
from growbridge.ports import Actor
from growbridge.research.round_cards import RoundCardInput, convert_round, round_card_sources
from growbridge.vocab.card_checks import CardUnit, Conditions, ConditionsNote, GrowthStage
from growbridge.workbench.common import Body
from growbridge.workbench.rounds import PathId
from growbridge.workbench.scope import project_write
from growbridge.workflow import denials
from growbridge.workflow.access import Access

Dependency = Callable[..., Awaitable[Actor]]


class RoundCardIn(Body):
    growth_stage: GrowthStage = ""
    conditions: Conditions = ()
    conditions_note: ConditionsNote = ""
    value: float | None = None
    unit: CardUnit | None = None


def add_round_card_routes(
    router: APIRouter,
    operator: Dependency,
    archive: Archive,
    workflow,
    holdout,
    access: Access | None = None,
) -> None:
    """Mount the route on ``router``; ``holdout`` is the registry that keeps a report out."""
    Operator = Annotated[Actor, Depends(operator)]  # noqa: N806

    @router.post("/rounds/{round_id}/evidence")
    async def convert_round_to_card(round_id: PathId, body: RoundCardIn, actor: Operator):
        project_id = workflow.store.round(round_id).project_id  # unknown round: refused
        unknown = denials.unknown("round", round_id)
        project_write(access, actor, project_id, lambda: unknown)
        src = round_card_sources(workflow, archive, holdout, access is not None)
        card = convert_round(
            src, workflow.catalog, round_id, RoundCardInput(**body.model_dump()), actor.id
        )
        origin = archive.ledger.origin(card.id)
        return {"card_id": card.id, "verified": True, "label": origin.label if origin else None}
