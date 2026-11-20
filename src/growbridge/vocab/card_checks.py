"""What is wrong with an evidence card's variable, unit, applicability conditions and crop."""

from growbridge.archive.models import ApplicabilityRange, EvidenceCard
from growbridge.ports import Denied
from growbridge.vocab.catalog import Catalog
from growbridge.vocab.checks import _variable_problems
from growbridge.vocab.curie import taxon_problems

MAX_CONDITIONS = 8
GROWTH_STAGE_MAX = 100
CONDITIONS_NOTE_MAX = 500


def card_problems(card: EvidenceCard, catalog: Catalog) -> list[str]:
    """Every reason the catalog refuses this card; empty when it is fine."""
    problems: list[str] = []
    if card.variable is not None:
        problems.extend(_card_variable_problems(card.variable, catalog))
        problems.extend(_unit_problems(card, catalog))
    problems.extend(_conditions_problems(card.conditions, catalog))
    if card.crop_taxon or card.cultivar:
        problems.extend(taxon_problems(card.crop_taxon, card.cultivar))
    if len(card.growth_stage) > GROWTH_STAGE_MAX:
        problems.append(f"growth_stage is longer than {GROWTH_STAGE_MAX} characters")
    if len(card.conditions_note) > CONDITIONS_NOTE_MAX:
        problems.append(f"conditions_note is longer than {CONDITIONS_NOTE_MAX} characters")
    return problems


def with_catalog_unit(card: EvidenceCard, catalog: Catalog) -> EvidenceCard:
    """The card with its unit spelled the catalog way; unchanged without a variable or unit."""
    if not card.variable or not card.unit:
        return card
    return card.model_copy(update={"unit": catalog.unit_aliases.get(card.unit, card.unit)})


def checked_card(card: EvidenceCard, catalog: Catalog) -> EvidenceCard:
    """The card with its catalog unit, or a ``Denied`` naming every problem it has."""
    problems = card_problems(card, catalog)
    if problems:
        raise Denied("param", "; ".join(problems), reason="evidence_card_invalid", params={})
    return with_catalog_unit(card, catalog)


def _card_variable_problems(name: str, catalog: Catalog) -> list[str]:
    problems = _variable_problems(name, catalog, frozenset())
    entry = catalog.get(name)
    if entry is not None and entry.kind == "factor":
        problems.append(
            f"variable {name} is a factor: its levels are not comparable across sources"
        )
    return problems


def _unit_problems(card: EvidenceCard, catalog: Catalog) -> list[str]:
    entry = catalog.get(card.variable or "")
    if entry is None or card.value is None:
        return []
    if not card.unit:
        return [f"a value of {entry.id} needs its unit {entry.unit}"]
    unit = catalog.unit_aliases.get(card.unit, card.unit)
    if unit != entry.unit:
        return [f"unit {card.unit} is not the catalog unit {entry.unit} of {entry.id}"]
    return []


def _conditions_problems(conditions: tuple[ApplicabilityRange, ...], catalog: Catalog) -> list[str]:
    problems: list[str] = []
    if len(conditions) > MAX_CONDITIONS:
        problems.append(f"at most {MAX_CONDITIONS} conditions")
    seen: set[str] = set()
    for condition in conditions:
        prefix = f"condition {condition.variable}: "
        problems.extend(prefix + text for text in _condition_problems(condition, catalog))
        canonical = catalog.canonical(condition.variable)
        if canonical is not None and canonical in seen:
            problems.append(prefix + "a condition variable appears only once")
        if canonical is not None:
            seen.add(canonical)
    return problems


def _condition_problems(condition: ApplicabilityRange, catalog: Catalog) -> list[str]:
    problems = _card_variable_problems(condition.variable, catalog)
    low, high = condition.min, condition.max
    if low is None and high is None:
        problems.append("give min, max or both")
    if low is not None and high is not None and low > high:
        problems.append(f"min {low:g} is above max {high:g}")
    entry = catalog.get(condition.variable)
    if entry is not None:
        problems.extend(_outside_problems((low, high), entry.min, entry.max))
    return problems


def _outside_problems(
    values: tuple[float | None, float | None], floor: float | None, ceiling: float | None
) -> list[str]:
    span = f"{floor:g}–{ceiling:g}" if floor is not None and ceiling is not None else None
    problems: list[str] = []
    for value in values:
        if value is None:
            continue
        if (floor is not None and value < floor) or (ceiling is not None and value > ceiling):
            bounds = span or (f"≥ {floor:g}" if floor is not None else f"≤ {ceiling:g}")
            problems.append(f"{value:g} is outside {bounds}")
    return problems
