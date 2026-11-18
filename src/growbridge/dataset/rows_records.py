"""Rows for measurements.csv, actions.csv, interventions.csv and withheld.csv."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from growbridge.archive.ids import canonical_json
from growbridge.archive.models import ActionRecord, ManualMeasurement, ResearchProtocol
from growbridge.dataset.pseudonym import Pseudonymizer
from growbridge.dataset.source import ExportRefused
from growbridge.dataset.triggers import clean_trigger
from growbridge.planning.treatment import unit_of
from growbridge.research.holdout import Holdout
from growbridge.vocab.catalog import Catalog

ALL_OUTCOMES = "*"


@dataclass(frozen=True)
class MeasurementRows:
    rows: tuple[dict, ...]
    superseded: int
    withheld_at_export: int
    unplaced: int


@dataclass(frozen=True)
class ActionRows:
    rows: tuple[dict, ...]
    notes_dropped: int
    other_triggers: int


def _variable_id(record: ManualMeasurement, catalog: Catalog) -> str:
    variable = catalog.resolve(record.metric)
    if variable is None:
        raise ExportRefused(
            f"Measurement {record.id} records {record.metric!r}, which the variable catalog "
            "does not define; the export has no column for a raw name."
        )
    if catalog.unit_aliases.get(record.unit, record.unit) != variable.unit:
        raise ExportRefused(
            f"Measurement {record.id} is in {record.unit!r}, but {variable.id} is "
            f"measured in {variable.unit!r}."
        )
    return variable.id


def measurement_rows(
    measurements: Sequence[ManualMeasurement],
    keep: Callable[[ManualMeasurement], bool],
    protocol: ResearchProtocol,
    round_number: int,
    catalog: Catalog,
    pseudonym: Pseudonymizer,
) -> MeasurementRows:
    """Rows for the latest version of each measurement the holdout filter lets through.

    The filter is applied again here: a holdout registered after the snapshot was frozen was
    not applied when it was frozen, and held-out outcomes must never reach the export.
    """
    corrected = {m.corrects for m in measurements if m.corrects is not None}
    rows: list[dict] = []
    superseded = withheld = unplaced = 0
    for record in measurements:
        if record.id in corrected:
            superseded += 1
            continue
        if not keep(record):
            withheld += 1
            continue
        placed = unit_of(protocol, round_number, record.position)
        unplaced += placed is None
        rows.append(
            {
                "time": record.measured_at,
                "record_id": record.id,
                "corrects": record.corrects,
                "experiment_id": record.experiment_id,
                "round": round_number,
                "batch": record.batch,
                "unit": placed.unit if placed else None,
                "treatment_id": placed.treatment_id if placed else None,
                "plant_id": record.plant_id,
                "position": record.position,
                "layout_version": record.layout_version,
                "variable_id": _variable_id(record, catalog),
                "value": record.value,
                "method": record.method,
                "operator": pseudonym(record.operator),
            }
        )
    return MeasurementRows(tuple(rows), superseded, withheld, unplaced)


def withheld_rows(holdouts: Sequence[Holdout], catalog: Catalog) -> tuple[dict, ...]:
    """One row per held-out (holdout, batch, outcome variable): withheld by design, not missing."""
    rows: set[tuple[str, str, str]] = set()
    for holdout in holdouts:
        resolved = [catalog.canonical(name) for name in holdout.outcome_fields]
        variables = (
            {ALL_OUTCOMES}
            if None in resolved or not resolved
            else {v for v in resolved if v is not None}
        )
        rows.update((holdout.holdout_id, b, v) for b in holdout.batch_ids for v in variables)
    return tuple({"holdout_id": h, "batch": b, "variable_id": v} for h, b, v in sorted(rows))


def action_rows(actions: Sequence[ActionRecord], pseudonym: Pseudonymizer) -> ActionRows:
    rows: list[dict] = []
    notes = other = 0
    for action in actions:
        trigger = clean_trigger(action.trigger)
        notes += trigger.note_dropped
        other += trigger.other
        rows.append(
            {
                "request_id": action.request_id,
                "channel": action.channel.value,
                "state": action.state.value,
                "trigger": trigger.value,
                "planned_level": action.planned_level,
                "confirmed_level": action.confirmed_level,
                "created_at": action.created_at,
                "sent_at": action.sent_at,
                "confirmed_at": action.confirmed_at,
                "ran_seconds": action.ran_seconds,
                "error_code": action.error_code,
                "ended_early_code": action.ended_early_code,
                "supersedes": action.supersedes,
                "operator": pseudonym(action.operator),
            }
        )
    return ActionRows(tuple(rows), notes, other)


def intervention_rows(
    interventions: Sequence[Mapping[str, Any]], pseudonym: Pseudonymizer
) -> tuple[dict, ...]:
    return tuple(
        {
            "id": item["id"],
            "time": item["at"],
            "stage_id": item["stage_id"],
            "kind": item["kind"],
            "detail": canonical_json(item["detail"]) if item.get("detail") else None,
            "operator": pseudonym(item.get("operator")),
        }
        for item in interventions
    )
