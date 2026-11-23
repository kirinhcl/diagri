"""What a run sheet's evidence citations are worth now: blocks for stale cards, hints for weak fit.

``check_evidence_validity`` blocks a citation of a superseded, retracted or dependency-invalid
card. ``check_evidence_fit`` only hints: a contested or pending card, or a card that does not
match the rule's variable, unit or the protocol's crop. Both are pure; the archive-reading
wrappers (``evidence_gate``, ``evidence_hints``, ``stale_evidence_lines``) fetch the cards,
statuses and origins the viewing project may see, then call them.
"""

import logging
from collections.abc import Iterator, Mapping
from typing import Any

from growbridge.archive.evidence_book import card_statuses, visible_cards
from growbridge.archive.evidence_ledger import EvidenceOrigin
from growbridge.archive.evidence_status import CardStatus
from growbridge.archive.models import EvidenceCard, FeedbackRule, ResearchProtocol, RunSheet
from growbridge.archive.store import Archive
from growbridge.planning.findings import block as _block
from growbridge.planning.findings import hint as _hint
from growbridge.planning.findings import source_text
from growbridge.planning.validate import USER_INPUT_PREFIX, _evidence_refs, check_evidence
from growbridge.ports import Finding
from growbridge.vocab import Catalog

log = logging.getLogger(__name__)

Point = tuple[str, str, str]  # source kind, source name, cited card id

# The codes ``check_evidence_validity`` blocks with: the one list every caller uses, so a stage
# past review shows each of them as information (workbench/rounds.py), a new one included.
GATE_CODES = frozenset({"superseded_source", "retracted_source", "dependency_invalid_source"})


def _points(sheet: RunSheet) -> Iterator[Point]:
    """Each place that cites a card (user input and empty references are not cards)."""
    for kind, source, ref in _evidence_refs(sheet):
        if ref and not ref.startswith(USER_INPUT_PREFIX):
            yield kind, source, ref


def cited_card_ids(sheet: RunSheet) -> tuple[str, ...]:
    return tuple(dict.fromkeys(ref for _, _, ref in _points(sheet)))


def _validity_finding(kind: str, source: str, status: CardStatus) -> Finding | None:
    card_id, label = status.card_id, source_text(kind, source)
    if status.validity == "retracted":
        return _block(
            "retracted_source",
            f"{label}: card {card_id} is retracted",
            source_kind=kind,
            source=source,
            card_id=card_id,
            reason=status.retracted_reason or "",
        )
    if status.validity == "dependency_invalid":
        return _block(
            "dependency_invalid_source",
            f"{label}: card {card_id} rests on invalidated data {status.invalid_dependency}",
            source_kind=kind,
            source=source,
            card_id=card_id,
            dependency_id=status.invalid_dependency,
        )
    if status.validity == "superseded":
        return _superseded(kind, source, status)
    return None


def _superseded(kind: str, source: str, status: CardStatus) -> Finding:
    replacement = status.current_replacement
    return _block(
        "superseded_source",
        f"{source_text(kind, source)}: card {status.card_id} is superseded",
        source_kind=kind,
        source=source,
        card_id=status.card_id,
        replacement_id=replacement.card_id if replacement else None,
        replacement_validity=replacement.validity if replacement else None,
    )


def check_evidence_validity(
    sheet: RunSheet, statuses: Mapping[str, CardStatus]
) -> tuple[Finding, ...]:
    """One blocking finding per citation of a card that is no longer active."""
    found = (
        _validity_finding(kind, source, statuses[ref])
        for kind, source, ref in _points(sheet)
        if ref in statuses
    )
    return tuple(f for f in found if f is not None)


def _status_hints(kind: str, source: str, status: CardStatus) -> Iterator[Finding]:
    label = source_text(kind, source)
    if status.contested_with:
        yield _hint(
            "contested_source",
            f"{label}: card {status.card_id} is contested by {', '.join(status.contested_with)}",
            source_kind=kind,
            source=source,
            card_id=status.card_id,
            others=",".join(status.contested_with),
        )
    if status.pending:
        yield _hint(
            "pending_relation",
            f"{label}: card {status.card_id} has relations awaiting review",
            source_kind=kind,
            source=source,
            card_id=status.card_id,
            relations=",".join(status.pending),
        )


def _same_variable(catalog: Catalog, rule_sensor: str, card_variable: str) -> bool:
    rule_current, card_current = catalog.current(rule_sensor), catalog.current(card_variable)
    return rule_current is not None and card_current is not None and rule_current == card_current


def _unit_hint(
    kind: str, source: str, rule: FeedbackRule, card: EvidenceCard, catalog: Catalog
) -> Iterator[Finding]:
    aliases = catalog.unit_aliases
    if card.unit and aliases.get(card.unit, card.unit) != aliases.get(rule.unit, rule.unit):
        yield _hint(
            "evidence_unit_mismatch",
            f"{source_text(kind, source)}: card {card.id} is in {card.unit}, rule in {rule.unit}",
            source_kind=kind,
            source=source,
            card_id=card.id,
            rule_unit=rule.unit,
            card_unit=card.unit,
        )


def _rule_fit_hints(
    kind: str, source: str, rule: FeedbackRule, card: EvidenceCard, catalog: Catalog
) -> Iterator[Finding]:
    label = source_text(kind, source)
    if not card.variable:
        if card.value is not None:
            yield _hint(
                "uncataloged_card",
                f"{label}: card {card.id} names no catalog variable, so its unit is not checked",
                source_kind=kind,
                source=source,
                card_id=card.id,
            )
    elif catalog.resolve(rule.sensor) is None:
        # a device-only sensor name: no variable to compare, but the units still can be
        yield from _unit_hint(kind, source, rule, card, catalog)
    elif not _same_variable(catalog, rule.sensor, card.variable):
        yield _hint(
            "variable_mismatch",
            f"{label}: card {card.id} is about {card.variable}, the rule reads {rule.sensor}",
            source_kind=kind,
            source=source,
            card_id=card.id,
            rule_variable=rule.sensor,
            card_variable=card.variable,
        )
    else:
        yield from _unit_hint(kind, source, rule, card, catalog)


def _crop_and_origin_hints(
    kind: str,
    source: str,
    card: EvidenceCard,
    origin: EvidenceOrigin | None,
    crop_taxon: str,
) -> Iterator[Finding]:
    label = source_text(kind, source)
    if card.crop_taxon and crop_taxon and card.crop_taxon != crop_taxon:
        yield _hint(
            "crop_mismatch",
            f"{label}: card {card.id} is about {card.crop_taxon}, the protocol grows {crop_taxon}",
            source_kind=kind,
            source=source,
            card_id=card.id,
            card_taxon=card.crop_taxon,
            protocol_taxon=crop_taxon,
        )
    if origin is not None and origin.label != "confirmatory":
        yield _hint(
            "exploratory_finding",
            f"{label}: card {card.id} is a {origin.label} finding, not a confirmed one",
            source_kind=kind,
            source=source,
            card_id=card.id,
            label=origin.label,
        )


def check_evidence_fit(
    sheet: RunSheet,
    cards: Mapping[str, EvidenceCard],
    statuses: Mapping[str, CardStatus],
    origins: Mapping[str, EvidenceOrigin],
    catalog: Catalog,
    crop_taxon: str,
) -> tuple[Finding, ...]:
    """Hints only: how well each cited card fits the rule and the protocol."""
    rules = {rule.id: rule for rule in sheet.feedback_rules}
    findings: list[Finding] = []
    for kind, source, ref in _points(sheet):
        card = cards.get(ref)
        if card is None:
            continue
        if ref in statuses:
            findings.extend(_status_hints(kind, source, statuses[ref]))
        if kind == "feedback_rule":
            findings.extend(_rule_fit_hints(kind, source, rules[source], card, catalog))
        findings.extend(_crop_and_origin_hints(kind, source, card, origins.get(ref), crop_taxon))
    return tuple(findings)


def evidence_gate(sheet: RunSheet, archive: Archive) -> tuple[Finding, ...]:
    statuses = card_statuses(archive, cited_card_ids(sheet), sheet.project_id)
    return check_evidence_validity(sheet, statuses)


def evidence_hints(
    sheet: RunSheet, archive: Archive, catalog: Catalog, crop_taxon: str
) -> tuple[Finding, ...]:
    statuses = card_statuses(archive, cited_card_ids(sheet), sheet.project_id)
    return check_evidence_fit(
        sheet,
        visible_cards(archive, sheet.project_id),
        statuses,
        archive.ledger.origins(),
        catalog,
        crop_taxon,
    )


def evidence_review(
    sheet: RunSheet, archive: Archive, catalog: Catalog, protocol: ResearchProtocol | None
) -> tuple[Finding, ...]:
    """What a reviewer sees about the evidence: the cards the project may cite checked for
    missing, unverified or uncalibrated sources, then the fit hints. None of it blocks."""
    found = check_evidence(sheet, visible_cards(archive, sheet.project_id))
    crop_taxon = protocol.crop_taxon if protocol is not None else ""
    return (*found, *evidence_hints(sheet, archive, catalog, crop_taxon))


def _stale_line(kind: str, source: str, status: CardStatus) -> str:
    line = f"{source_text(kind, source)}: card {status.card_id} is {status.validity}"
    replacement = status.current_replacement
    if replacement is None:
        return line
    if replacement.validity == "active":
        return f"{line}; use {replacement.card_id}"
    return f"{line}; replacement {replacement.card_id} is {replacement.validity}"


def stale_evidence_lines(sheet: RunSheet, archive: Archive, limit: int = 5) -> tuple[str, ...]:
    """Up to ``limit`` lines naming the citations that no longer stand, for the daily report."""
    statuses = card_statuses(archive, cited_card_ids(sheet), sheet.project_id)
    lines = (
        _stale_line(kind, source, statuses[ref])
        for kind, source, ref in _points(sheet)
        if ref in statuses and statuses[ref].blocks
    )
    return tuple(line for _, line in zip(range(limit), lines, strict=False))


def report_stale_evidence(runtime: Any, stage: Any) -> tuple[str, ...]:
    """``stale_evidence_lines`` for the running ``stage``'s run sheet; a failure here is logged
    and leaves the section out, never the report."""
    if stage is None:
        return ()
    try:
        sheet = runtime.workflow.stage(stage.stage_id).run_sheet
        return stale_evidence_lines(sheet, runtime.archive)
    except Exception:
        log.exception("the stale-evidence section of the daily report could not be built")
        return ()
