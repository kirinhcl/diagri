"""A delivered round's report conclusion as a verified, project-scoped ``local`` evidence card.

An operator reads the report and vouches for its conclusion; the card is written verified, and its
origin ties it to the report and to the snapshots the report rests on, so a later correction to
any of them makes the card ``dependency_invalid``. A report converts once. A report that a
correction invalidated, that a holdout was read for, or whose file is gone gives no card.
"""

from __future__ import annotations

from typing import Any

from growbridge.agents.memory_rounds import load_report, report_snapshots
from growbridge.agents.memory_sources import MemorySources
from growbridge.archive.evidence_ledger import EvidenceOrigin
from growbridge.archive.ids import new_id
from growbridge.archive.models import ApplicabilityRange, EvidenceCard, Model
from growbridge.ports import Denied
from growbridge.vocab import Catalog
from growbridge.vocab.card_checks import checked_card
from growbridge.workflow.states import RoundState

CLAIM_MAX = 1000
Refusal = tuple[str, dict]


class RoundCardInput(Model):
    growth_stage: str = ""
    conditions: tuple[ApplicabilityRange, ...] = ()
    conditions_note: str = ""
    value: float | None = None
    unit: str | None = None


def round_card_refusal(src: MemorySources, round_id: str) -> Refusal | None:
    """``(reason, params)`` when the round cannot be converted now, else None."""
    return _inspect(src, round_id)[0]


def convert_round(
    src: MemorySources, catalog: Catalog, round_id: str, body: RoundCardInput, actor_id: str
) -> EvidenceCard:
    """Write the round's conclusion as a verified local card with its origin, in one step."""
    archive = src.archive
    with archive.db.transaction():
        refused, found = _inspect(src, round_id)
        if refused is not None:
            raise _denied(*refused)
        rnd, artifact, report = found  # type: ignore[misc]  # set whenever nothing is refused
        card = checked_card(_build_card(src, catalog, rnd, artifact, report, body), catalog)
        archive.add_evidence(card, source=f"operator:{actor_id}", verified_by=actor_id)
        snapshots = report_snapshots(src, rnd.project_id, artifact, report)
        origin = EvidenceOrigin(
            card_id=card.id,
            project_id=rnd.project_id,
            round_id=round_id,
            report_artifact_id=artifact.id,
            snapshot_ids=snapshots,
            label=artifact.label,
            at=src.clock.now(),
        )
        archive.ledger.add_origin(origin)
    return card


def _inspect(src: MemorySources, round_id: str) -> tuple[Refusal | None, tuple | None]:
    """The first reason the round cannot be converted, or ``(round, artifact, report)``."""
    rnd = src.workflow.store.round(round_id)
    if rnd.state is not RoundState.DELIVERED:
        return ("round_card_not_delivered", {"round_id": round_id, "state": rnd.state.value}), None
    existing = _origin(src, rnd.report_artifact_id)
    if existing is not None:
        return ("round_card_exists", {"round_id": round_id, "card_id": existing}), None
    downgrade, body = load_report(src, rnd.project_id, rnd.report_artifact_id)
    if body is None:
        problem = _problem(downgrade)
        return ("round_card_report_unusable", {"round_id": round_id, "problem": problem}), None
    if not _has_conclusion(body):
        return ("round_card_no_conclusion", {"round_id": round_id}), None
    return None, (rnd, src.archive.artifact(rnd.report_artifact_id), body)


def _origin(src: MemorySources, artifact_id: str | None) -> str | None:
    origin = None if artifact_id is None else src.archive.ledger.origin_of_report(artifact_id)
    return None if origin is None else origin.card_id


def _problem(downgrade: dict | None) -> str:
    for name in ("invalid", "held_out"):
        if downgrade and downgrade.get(name):
            return name
    return "unavailable"


def _has_conclusion(body: dict) -> bool:
    conclusion = body.get("conclusion")
    return isinstance(conclusion, str) and bool(conclusion.strip())


def _build_card(
    src: MemorySources,
    catalog: Catalog,
    rnd: Any,
    artifact: Any,
    report: dict,
    body: RoundCardInput,
) -> EvidenceCard:
    protocol = src.workflow.store.protocol(rnd.protocol_id, rnd.protocol_version)
    endpoint = None if protocol is None else catalog.current(protocol.analysis.primary_endpoint)
    unit = body.unit or (endpoint.unit if endpoint and body.value is not None else None)
    return EvidenceCard(
        id=new_id("evidence"),
        source_class="local",
        citation=f"{artifact.label} report of round {rnd.id}",
        claim=_claim(report["conclusion"].strip()),
        value=body.value,
        unit=unit,
        calibrated=True,
        variable=None if endpoint is None else endpoint.id,
        conditions=body.conditions,
        crop_taxon="" if protocol is None else protocol.crop_taxon,
        cultivar="" if protocol is None else protocol.cultivar,
        growth_stage=body.growth_stage,
        conditions_note=body.conditions_note,
    )


def _claim(text: str) -> str:
    return text if len(text) <= CLAIM_MAX else text[: CLAIM_MAX - 1] + "…"


def _denied(reason: str, params: dict) -> Denied:
    return _DENIALS[reason](**params)


def _not_delivered(round_id: str, state: str) -> Denied:
    message = f"round {round_id} is {state}: only a delivered round can become a card"
    params = {"round_id": round_id, "state": state}
    return Denied("state", message, reason="round_card_not_delivered", params=params)


def _report_unusable(round_id: str, problem: str) -> Denied:
    message = f"the report of round {round_id} cannot be used for a card ({problem})"
    params = {"round_id": round_id, "problem": problem}
    return Denied("state", message, reason="round_card_report_unusable", params=params)


def _exists(round_id: str, card_id: str) -> Denied:
    message = f"the report of round {round_id} already became card {card_id}"
    params = {"round_id": round_id, "card_id": card_id}
    return Denied("state", message, reason="round_card_exists", params=params)


def _no_conclusion(round_id: str) -> Denied:
    message = f"the report of round {round_id} has no conclusion"
    params = {"round_id": round_id}
    return Denied("state", message, reason="round_card_no_conclusion", params=params)


_DENIALS = {
    "round_card_not_delivered": _not_delivered,
    "round_card_report_unusable": _report_unusable,
    "round_card_exists": _exists,
    "round_card_no_conclusion": _no_conclusion,
}


def round_card_sources(
    workflow: Any, archive: Any, holdout: Any, multi_user: bool
) -> MemorySources:
    """What converting a round reads from: only the workflow store, archive and holdouts count."""
    return MemorySources(
        workflow=workflow,
        archive=archive,
        book=None,
        notes=None,
        holdout=holdout,
        clock=workflow.clock,
        timezone="UTC",
        device_id=None,
        multi_user=multi_user,
    )


def round_card_state(src: MemorySources, round_id: str) -> dict:
    """What the round page shows: ``{"card_id": ...}`` once converted, ``{"refusal": {"reason",
    "params"}}`` when it cannot be, and ``{}`` when it can."""
    refused = round_card_refusal(src, round_id)
    if refused is None:
        return {}
    reason, params = refused
    if reason == "round_card_exists":
        return {"card_id": params["card_id"]}
    return {"refusal": {"reason": reason, "params": params}}
