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

from growbridge.agents.handlers_common import Deps, ToolInput, require_bound
from growbridge.agents.handlers_researcher import EvidenceInput, query_cards
from growbridge.agents.tools import Tool
from growbridge.archive.ids import new_id
from growbridge.archive.models import EvidenceCard
from growbridge.ports import Denied

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
    calibrated: bool = True


def propose_card(deps: Deps, data: ProposeCardInput) -> dict:
    task = require_bound(deps, data.task_id)
    if task.owner_role != ROLE:
        raise Denied("scope", "only a planner task may propose evidence cards")
    if data.source_class == "local":
        # A model cannot have taken a local measurement; such a card would also look trusted.
        raise Denied(
            "param",
            "only an operator can record a local measurement as evidence; "
            "propose a handbook or paper card",
        )
    if deps.archive.evidence_count_from(task.id) >= MAX_PROPOSALS_PER_TASK:
        raise Denied("quota", f"a task may propose at most {MAX_PROPOSALS_PER_TASK} cards")
    card = EvidenceCard(
        id=new_id("evidence"),
        source_class=data.source_class,
        citation=data.citation,
        claim=data.claim,
        value=data.value,
        unit=data.unit or None,
        verified=False,
        calibrated=data.calibrated,
    )
    deps.archive.add_evidence(card, source=SOURCE, task_id=task.id)
    return {
        "card_id": card.id,
        "verified": False,
        "note": "stored unverified; an operator must verify it before it counts as verified",
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
            "run sheet. You cannot verify a card; an operator does. A local measurement cannot be "
            "proposed (only an operator records one): use source_class handbook or paper. Pass "
            "the planner task_id you are working on.",
            ProposeCardInput,
            lambda d: propose_card(deps, d),
            writes=True,
        ),
    ]
