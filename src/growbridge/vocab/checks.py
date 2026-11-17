"""Checks of a protocol and of a manual measurement against the variable catalog (spec §6)."""

from growbridge.archive.models import ManualMeasurement, ResearchProtocol
from growbridge.vocab.catalog import Catalog, Variable


def check_protocol(
    protocol: ResearchProtocol, catalog: Catalog, declared_before: frozenset[str]
) -> list[str]:
    """Every problem found; an empty list means the protocol may be saved."""
    problems: list[str] = []
    if not protocol.variables:
        problems.append("declare the protocol's variables (the `variables` list is empty)")
    seen: set[str] = set()
    for name in protocol.variables:
        if name in seen:
            problems.append(f"variable {name} is listed twice")
        seen.add(name)
        problems.extend(_variable_problems(name, catalog, declared_before))
    problems.extend(_endpoint_problems(protocol.analysis.primary_endpoint, seen, catalog))
    for treatment in protocol.treatments:
        for key in treatment.factors:
            problems.extend(_factor_problems(treatment.id, key, catalog))
    return problems


def _variable_problems(name: str, catalog: Catalog, declared_before: frozenset[str]) -> list[str]:
    entry = catalog.get(name)
    if entry is None:
        found = catalog.resolve(name)
        if found is not None:
            return [f"variable {name} is an alias: use the standard ID {found.id}"]
        return [f"variable {name} is not in the catalog"]
    if entry.deprecated and name not in declared_before:
        replacement = f": use {entry.replaced_by}" if entry.replaced_by else ""
        return [f"variable {name} is deprecated{replacement}"]
    return []


def _endpoint_problems(endpoint: str, declared: set[str], catalog: Catalog) -> list[str]:
    """The endpoint is analysed from manual measurements only, so it must be a manual variable."""
    problems: list[str] = []
    if endpoint not in declared:
        problems.append(f"the primary endpoint {endpoint} must be listed in variables")
    entry = catalog.get(endpoint)
    if entry is not None and entry.kind != "manual":
        problems.append(
            f"the primary endpoint {endpoint} is a {entry.kind} variable: it must be a manual one"
        )
    return problems


def _factor_problems(treatment_id: str, key: str, catalog: Catalog) -> list[str]:
    entry = catalog.get(key)
    if entry is not None and entry.kind == "factor":
        return []
    found = catalog.resolve(key)
    hint = (
        f" (use the standard ID {found.id})" if found is not None and found.kind == "factor" else ""
    )
    return [f"treatment {treatment_id}: factor {key} is not a factor in the catalog{hint}"]


def check_measurement(
    record: ManualMeasurement, catalog: Catalog, declared: frozenset[str]
) -> list[str]:
    """Every problem found; an empty list means the measurement may be stored.

    The metric must be a variable the experiment's protocol declared, matched exactly. A declared
    variable that has since been deprecated is still accepted: deprecation is not checked at entry.
    """
    if not declared:
        return [
            f"the protocol of experiment {record.experiment_id} declares no variables:"
            " save a protocol version that declares them and run a new round with it first"
        ]
    entry = catalog.get(record.metric) if record.metric in declared else None
    if entry is None:
        names = ", ".join(sorted(declared))
        return [f"metric {record.metric!r} is not a declared variable; declared: {names}"]
    return _entry_problems(record, entry)


def _entry_problems(record: ManualMeasurement, entry: Variable) -> list[str]:
    problems: list[str] = []
    if entry.kind != "manual":
        problems.append(f"variable {entry.id} is a {entry.kind} variable, not a manual one")
    if record.unit != entry.unit:
        problems.append(f"variable {entry.id} is recorded in {entry.unit}, not {record.unit}")
    if entry.min is not None and record.value < entry.min:
        problems.append(f"value {record.value} is below the minimum {entry.min} of {entry.id}")
    if entry.max is not None and record.value > entry.max:
        problems.append(f"value {record.value} is above the maximum {entry.max} of {entry.id}")
    return problems
