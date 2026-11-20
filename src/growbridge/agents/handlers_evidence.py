"""The planner's evidence tools (architecture doc §6.4): query the cards, propose a new one.

A model never produces a verified card. ``propose_evidence_card`` stores what the planner read as
an unverified card, whatever the input says (the input has no verification field, and unknown
fields are rejected), with the planner and the bound task as its source. The card id is made by
the server. An operator verifies a card later through the workbench; that is a record of its own.
A planner that read web content loses this write tool for the rest of the run (it is ``writes``),
so propose a card before searching.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from growbridge.agents.evidence_query import EvidenceInput, query_cards
from growbridge.agents.handlers_common import Deps, ToolInput, require_bound
from growbridge.agents.tools import Tool
from growbridge.archive.evidence_relations import (
    RelationRefused,
    RelationRequest,
    as_denied,
    propose_relation,
)
from growbridge.archive.ids import new_id
from growbridge.archive.models import ApplicabilityRange, EvidenceCard, ResearchTask
from growbridge.ports import Denied
from growbridge.vocab.card_checks import checked_card

ROLE = "planner"
SOURCE = "model:planner"
MAX_PROPOSALS_PER_TASK = 20
# The same limits as the operator's entry in the workbench (workbench/evidence.py).
CITATION_MAX = 500
CLAIM_MAX = 1000
UNIT_MAX = 40

Citation = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=CITATION_MAX)
]
Claim = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=CLAIM_MAX)]
Unit = Annotated[str, StringConstraints(strip_whitespace=True, max_length=UNIT_MAX)]


class ProposeCardInput(ToolInput):
    task_id: str  # compared with the task the dispatcher is running
    source_class: Literal["handbook", "paper", "local"]
    citation: Citation
    claim: Claim
    value: float | None = Field(default=None, allow_inf_nan=False)
    unit: Unit | None = None
    variable: str | None = None  # a catalog variable by its standard ID
    conditions: tuple[ApplicabilityRange, ...] = ()
    crop_taxon: str = ""
    cultivar: str = ""  # lengths and the rest are checked by ``checked_card``
    growth_stage: str = ""
    conditions_note: str = ""
    # No ``calibrated`` here: a model cannot vouch for calibration. A proposed card is stored
    # uncalibrated, and an operator attests it when verifying.


class ProposeRelationInput(ToolInput):
    task_id: str  # compared with the task the dispatcher is running
    kind: Literal["supersedes", "contradicts", "retracts"]
    card_id: str
    other_card_id: str | None = None
    reason: str  # its length and shape are checked by ``propose_relation``


def _planner_task(deps: Deps, task_id: str, what: str) -> ResearchTask:
    task = require_bound(deps, task_id)
    if task.owner_role != ROLE:
        raise Denied(
            "scope",
            f"only a planner task may propose {what}",
            reason="wrong_task_kind",
            params={"task_kind": None},
        )
    return task


def _check_may_propose(deps: Deps, data: ProposeCardInput) -> ResearchTask:
    task = _planner_task(deps, data.task_id, "evidence cards")
    if data.source_class == "local":
        # A model cannot have taken a local measurement; such a card would also look trusted.
        raise Denied(
            "param",
            "only an operator can record a local measurement as evidence; "
            "propose a handbook or paper card",
            reason="operator_only_evidence",
            params={},
        )
    if deps.archive.evidence_count_from(task.id) >= MAX_PROPOSALS_PER_TASK:
        raise Denied(
            "quota",
            f"a task may propose at most {MAX_PROPOSALS_PER_TASK} cards",
            reason="quota_proposal_limit",
            params={"max_proposals": MAX_PROPOSALS_PER_TASK},
        )
    return task


def _unverified_card(data: ProposeCardInput) -> EvidenceCard:
    return EvidenceCard(
        id=new_id("evidence"),
        source_class=data.source_class,
        citation=data.citation,
        claim=data.claim,
        value=data.value,
        unit=data.unit or None,
        variable=data.variable,
        conditions=data.conditions,
        crop_taxon=data.crop_taxon,
        cultivar=data.cultivar,
        growth_stage=data.growth_stage,
        conditions_note=data.conditions_note,
        verified=False,
        calibrated=False,
    )


def propose_card(deps: Deps, data: ProposeCardInput) -> dict:
    task = _check_may_propose(deps, data)
    card = checked_card(_unverified_card(data), deps.workflow.catalog)
    deps.archive.add_evidence(card, source=SOURCE, task_id=task.id)
    return {
        "card_id": card.id,
        "verified": False,
        "calibrated": False,
        "note": (
            "stored unverified and uncalibrated; an operator must verify it, and attest its "
            "calibration, before it counts as verified or calibrated"
        ),
    }


def propose_evidence_relation(deps: Deps, data: ProposeRelationInput) -> dict:
    task = _planner_task(deps, data.task_id, "evidence relations")
    request = RelationRequest(
        kind=data.kind, card_id=data.card_id, other_card_id=data.other_card_id, reason=data.reason
    )
    try:
        record = propose_relation(deps.archive, request, task.id, task.project_id)
    except RelationRefused as error:
        raise as_denied(error) from error
    return {
        "relation_id": record.relation.id,
        "state": "pending",
        "note": "an operator must confirm it before it changes any card",
    }


def build_evidence_tools(deps: Deps) -> list[Tool]:
    return [
        Tool(
            "query_evidence",
            "Search the evidence cards in the archive; each card says whether it is verified.",
            EvidenceInput,
            lambda d: query_cards(deps, d),
        ),
        Tool(
            "propose_evidence_card",
            "Store a source you read as an UNVERIFIED evidence card and get its id to cite in a "
            "run sheet. You cannot verify a card or claim it is calibrated; an operator does "
            "both. A local measurement cannot be proposed (only an operator records one): use "
            "source_class handbook or paper. Pass the planner task_id you are working on.",
            ProposeCardInput,
            lambda d: propose_card(deps, d),
            writes=True,
        ),
        Tool(
            "propose_evidence_relation",
            "Propose that a card supersedes or contradicts another, or retracts itself, with a "
            "reason grounded in what you read, never a guess. It stays pending until an operator "
            "confirms it; nothing changes before. Pass the planner task_id you are working on.",
            ProposeRelationInput,
            lambda d: propose_evidence_relation(deps, d),
            writes=True,
        ),
    ]
