"""Build the training dataset of one snapshot: the CSV tables and ``croissant.json`` as bytes."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from growbridge.archive.models import ManualMeasurement, ResearchProtocol
from growbridge.dataset.croissant import croissant
from growbridge.dataset.csvfmt import write_csv
from growbridge.dataset.pseudonym import Pseudonymizer
from growbridge.dataset.rows_design import treatment_rows, unit_rows, variable_rows
from growbridge.dataset.rows_records import (
    ALL_OUTCOMES,
    action_rows,
    intervention_rows,
    measurement_rows,
    withheld_rows,
)
from growbridge.dataset.rows_samples import sample_rows
from growbridge.dataset.schema import TABLES
from growbridge.dataset.source import ExportRefused, SnapshotData
from growbridge.research.holdout import Holdout
from growbridge.vocab.catalog import Catalog
from growbridge.vocab.curie import taxon_problems

METADATA_FILE = "croissant.json"
COUNT_NAMES: tuple[str, ...] = (
    "unmapped_variables",
    "unresolved_sensor_keys",
    "non_numeric_values",
    "excluded_at_freeze",
    "withheld_at_export",
    "superseded_records",
    "corrected_after_freeze",
    "notes_dropped",
    "other_triggers",
    "unplaced_measurements",
)


@dataclass(frozen=True)
class ExportInputs:
    data: SnapshotData
    protocol: ResearchProtocol
    round_number: int
    catalog: Catalog
    holdouts: tuple[Holdout, ...]
    keep: Callable[[ManualMeasurement], bool]  # the holdout filter as registered now
    pseudonym: Pseudonymizer
    licence: str
    creator: str
    url: str | None
    corrected_after_freeze: tuple[str, ...]  # snapshot record ids corrected after the freeze
    software_version: str


def _refuse_incomplete(inputs: ExportInputs) -> None:
    protocol = inputs.protocol
    problems = taxon_problems(protocol.crop_taxon, protocol.cultivar)
    if problems:
        raise ExportRefused(
            f"Protocol {protocol.id} version {protocol.version} cannot describe the dataset: "
            + "; ".join(problems)
        )
    if not inputs.licence.strip():
        raise ExportRefused("Name the licence the dataset is released under; it is empty.")
    if not inputs.creator.strip():
        raise ExportRefused("Name the creator of the dataset; it is empty.")


def _variable_ids(*row_sets: Iterable[Mapping[str, object]]) -> set[str]:
    return {str(row["variable_id"]) for rows in row_sets for row in rows if row["variable_id"]}


def build_dataset(inputs: ExportInputs) -> dict[str, bytes]:
    """File name to content: every table of ``schema.TABLES`` and ``croissant.json``."""
    _refuse_incomplete(inputs)
    data, catalog, round_number = inputs.data, inputs.catalog, inputs.round_number
    trusted = sample_rows(data.samples, round_number, catalog, data.frozen_periods)
    untrusted = sample_rows(data.samples_untrusted, round_number, catalog, data.frozen_periods)
    measured = measurement_rows(
        data.measurements, inputs.keep, inputs.protocol, round_number, catalog, inputs.pseudonym
    )
    actions = action_rows(data.actions, inputs.pseudonym)
    treatments = treatment_rows(inputs.protocol)
    withheld = withheld_rows(inputs.holdouts, catalog)
    referenced = _variable_ids(
        trusted.sensor, untrusted.sensor, measured.rows, treatments, withheld
    ) | set(inputs.protocol.variables)
    referenced.discard(ALL_OUTCOMES)
    variables = variable_rows(referenced, data.catalog_record, catalog)
    rows = {
        "variables.csv": variables,
        "treatments.csv": treatments,
        "units.csv": unit_rows(inputs.protocol),
        "sensor_readings.csv": trusted.sensor,
        "sensor_readings_untrusted.csv": untrusted.sensor,
        "device_states.csv": trusted.device,
        "device_states_untrusted.csv": untrusted.device,
        "measurements.csv": measured.rows,
        "actions.csv": actions.rows,
        "interventions.csv": intervention_rows(data.interventions, inputs.pseudonym),
        "withheld.csv": withheld,
    }
    tables = {t.file: write_csv(t, rows[t.file]) for t in TABLES}
    counts = {
        "unmapped_variables": sum(not row["mapped"] for row in variables),
        "unresolved_sensor_keys": trusted.unresolved_keys + untrusted.unresolved_keys,
        "non_numeric_values": trusted.non_numeric + untrusted.non_numeric,
        "excluded_at_freeze": int(data.manifest["measurements_excluded"]),
        "withheld_at_export": measured.withheld_at_export,
        "superseded_records": measured.superseded,
        "corrected_after_freeze": len(set(inputs.corrected_after_freeze)),
        "notes_dropped": actions.notes_dropped,
        "other_triggers": actions.other_triggers,
        "unplaced_measurements": measured.unplaced,
    }
    metadata = croissant(tables, inputs, counts)
    text = json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return {**tables, METADATA_FILE: text.encode("utf-8")}
