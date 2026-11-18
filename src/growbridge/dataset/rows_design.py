"""Rows for variables.csv, treatments.csv and units.csv."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from growbridge.archive.models import ResearchProtocol
from growbridge.dataset.source import ExportRefused
from growbridge.vocab.catalog import Catalog, Variable


def _entry(variable_id: str, catalog_record: Mapping[str, Any], current: Catalog) -> Variable:
    """The entry the snapshot froze, else the current one; defining fields cannot differ."""
    for raw in catalog_record.get("variables", ()):
        if raw.get("id") == variable_id:
            return Variable.model_validate(raw)
    found = current.get(variable_id)
    if found is None:
        raise ExportRefused(
            f"Variable {variable_id} is in neither the snapshot's catalog nor the current one."
        )
    return found


def variable_rows(
    referenced: Iterable[str], catalog_record: Mapping[str, Any], current: Catalog
) -> tuple[dict, ...]:
    rows = []
    for variable_id in sorted(set(referenced)):
        entry = _entry(variable_id, catalog_record, current)
        now = current.get(variable_id)
        refs = now.refs if now else ()
        rows.append(
            {
                "variable_id": entry.id,
                "kind": entry.kind,
                "label_en": entry.label_en,
                "quantity": entry.quantity,
                "unit_ucum": entry.unit,
                "unit_uo": current.unit_refs.get(entry.unit),
                "method": entry.method,
                "min": entry.min,
                "max": entry.max,
                "refs": " ".join(refs),
                "mapped": bool(refs),
            }
        )
    return tuple(rows)


def treatment_rows(protocol: ResearchProtocol) -> tuple[dict, ...]:
    rows = []
    for treatment in protocol.treatments:
        base = {
            "treatment_id": treatment.id,
            "name": treatment.name,
            "is_control": treatment.id == protocol.control_treatment_id,
        }
        factors = sorted(treatment.factors.items()) or [(None, None)]
        rows.extend({**base, "variable_id": key, "value": value} for key, value in factors)
    return tuple(rows)


def unit_rows(protocol: ResearchProtocol) -> tuple[dict, ...]:
    return tuple(
        {"round": a.round, "block": a.block, "unit": a.unit, "treatment_id": a.treatment_id}
        for a in protocol.allocations
    )
