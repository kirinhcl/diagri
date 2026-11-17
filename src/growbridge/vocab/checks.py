"""Checks of a protocol against the variable catalog (spec section 6)."""

from growbridge.archive.models import ResearchProtocol
from growbridge.vocab.catalog import Catalog


def check_protocol(
    protocol: ResearchProtocol, catalog: Catalog, declared_before: frozenset[str]
) -> list[str]:
    """Every problem found; an empty list means the protocol may be saved."""
    if not protocol.variables:
        return ["declare the protocol's variables (the `variables` list is empty)"]
    problems: list[str] = []
    seen: set[str] = set()
    for name in protocol.variables:
        if name in seen:
            problems.append(f"variable {name} is listed twice")
        seen.add(name)
        problems.extend(_variable_problems(name, catalog, declared_before))
    endpoint = protocol.analysis.primary_endpoint
    if endpoint not in seen:
        problems.append(f"the primary endpoint {endpoint} must be listed in variables")
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
        return [f"variable {name} is deprecated: use {entry.replaced_by}"]
    return []


def _factor_problems(treatment_id: str, key: str, catalog: Catalog) -> list[str]:
    entry = catalog.get(key)
    if entry is not None and entry.kind == "factor":
        return []
    found = catalog.resolve(key)
    hint = (
        f" (use the standard ID {found.id})" if found is not None and found.kind == "factor" else ""
    )
    return [f"treatment {treatment_id}: factor {key} is not a factor in the catalog{hint}"]
