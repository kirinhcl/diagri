"""Table schema of the training dataset; the CSV writer and the Croissant metadata both read it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DataType = Literal["Text", "Float", "Integer", "Boolean", "DateTime"]


@dataclass(frozen=True)
class Column:
    name: str
    data_type: DataType
    description: str
    references: str | None = None  # "<file>.<column>"


@dataclass(frozen=True)
class Table:
    file: str
    description: str
    columns: tuple[Column, ...]
    sort_key: tuple[str, ...]


_VAR = "variables.csv.variable_id"
_TREATMENT = "treatments.csv.treatment_id"
_OPERATOR = (
    "Pseudonym of the person who recorded this (`op-` plus 12 hex characters), "
    "stable within one installation; the name itself is never exported."
)
_STAMP = "UTC time, millisecond precision."
_LEVELS = (
    "Keys the controller reports. "
    "`light.level`: 0-100, on the scale of the level DiAGRI commands; scale not documented. "
    "`light.on`: 0 or 1. "
    "`fan.level`: 0-10, on the scale of the level DiAGRI commands; scale not documented. "
    "`fan.on`: 0 or 1. "
    "`blower.level`: 0-100 manual speed, on the scale of the level DiAGRI commands. "
    "`blower.on`: 0 or 1. "
    "`outlet.O1.on` to `outlet.O5.on`: 0 or 1."
)


def _t(name: str, description: str, references: str | None = None) -> Column:
    return Column(name, "Text", description, references)


def _f(name: str, description: str) -> Column:
    return Column(name, "Float", description)


def _i(name: str, description: str) -> Column:
    return Column(name, "Integer", description)


def _b(name: str, description: str) -> Column:
    return Column(name, "Boolean", description)


def _d(name: str, description: str) -> Column:
    return Column(name, "DateTime", f"{description} {_STAMP}")


def _variable_id(description: str = "Variable this row is about.") -> Column:
    return _t("variable_id", description, _VAR)


_STATE_COLUMNS = (
    _d("time", "Time of the reading."),
    _t(
        "time_source",
        "`captured` when the device gave a capture time on a synchronised clock, "
        "otherwise `received` (the time the bridge received the reading).",
    ),
    _b("clock_synced", "True when the device clock was synchronised when it reported."),
    _t("sample_id", "Identifier of the sample this reading came from; groups readings."),
    _t("device_id", "Device that produced the reading."),
    _t("experiment_id", "Experiment running when the reading was taken. Empty when none."),
    _t("stage_id", "Stage of the experiment at that time. Empty when none."),
    _i("round", "Round of the experiment at that time. Empty when none."),
)

_SENSOR_COLUMNS = (
    *_STATE_COLUMNS,
    _variable_id("Variable the sensor key was mapped to."),
    _t("raw_key", "Sensor key exactly as the controller reports it."),
    _f("value", "Reading in the variable's unit (`unit_ucum`). Empty when not finite."),
    _t("quality", "Quality flag of the reading as reported by the controller. Empty when none."),
    _b(
        "stuck",
        "True when the reading falls inside a period in which the sensor kept reporting "
        "the same value (frozen sensor); such readings are unreliable.",
    ),
)

_DEVICE_COLUMNS = (
    *_STATE_COLUMNS,
    _t("key", f"Device state key. {_LEVELS}"),
    _f("value", "State value for the key; see `key` for the range. Empty when not finite."),
    _t("quality", "Quality flag of the reading as reported by the controller. Empty when none."),
)

TABLES: tuple[Table, ...] = (
    Table(
        "variables.csv",
        "Catalog of measured and controlled variables with units and ontology terms.",
        (
            _t("variable_id", "Stable identifier of the variable."),
            _t("kind", "Kind of variable."),
            _t("label_en", "English label."),
            _t("quantity", "Physical or biological quantity measured. Empty when unspecified."),
            _t("unit_ucum", "Unit as a UCUM code. Empty when dimensionless or unknown."),
            _t("unit_uo", "Unit as a Units Ontology term. Empty when not confirmed."),
            _t("method", "How the variable is measured. Empty when unspecified."),
            _f("min", "Lowest plausible value, in `unit_ucum`. Empty when unbounded."),
            _f("max", "Highest plausible value, in `unit_ucum`. Empty when unbounded."),
            _t(
                "refs",
                "Ontology terms for the variable as space-separated CURIEs; prefixes are "
                "declared in the @context. Empty when no term has been confirmed.",
            ),
            _b("mapped", "True when `refs` holds at least one confirmed ontology term."),
        ),
        ("variable_id",),
    ),
    Table(
        "treatments.csv",
        "Treatments of the experiment, one row per factor setting.",
        (
            _t("treatment_id", "Identifier of the treatment."),
            _t("name", "Treatment name."),
            _b("is_control", "True when this treatment is the control."),
            _variable_id("Factor variable this setting applies to."),
            _t(
                "value",
                "Factor value as text, since a factor may be a string; numbers are written "
                "with their shortest exact decimal form.",
            ),
        ),
        ("treatment_id", "variable_id"),
    ),
    Table(
        "units.csv",
        "Experimental units: which treatment each unit received in each round.",
        (
            _i("round", "Round of the experiment."),
            _i("block", "Block the unit belongs to. Empty when the design has no blocks."),
            _t("unit", "Identifier of the experimental unit."),
            _t("treatment_id", "Treatment applied to the unit.", _TREATMENT),
        ),
        ("round", "unit"),
    ),
    Table(
        "sensor_readings.csv",
        "Sensor readings in long format, one row per reading and variable.",
        _SENSOR_COLUMNS,
        ("time", "sample_id", "raw_key"),
    ),
    Table(
        "sensor_readings_untrusted.csv",
        "Sensor readings kept apart as untrusted; same columns as sensor_readings.csv.",
        _SENSOR_COLUMNS,
        ("time", "sample_id", "raw_key"),
    ),
    Table(
        "device_states.csv",
        "Actuator state readings (light, fan, blower, outlets) in long format.",
        _DEVICE_COLUMNS,
        ("time", "sample_id", "key"),
    ),
    Table(
        "device_states_untrusted.csv",
        "Actuator state readings kept apart as untrusted; same columns as device_states.csv.",
        _DEVICE_COLUMNS,
        ("time", "sample_id", "key"),
    ),
    Table(
        "measurements.csv",
        "Manual measurements recorded by people, including corrections to earlier records.",
        (
            _d("time", "Time of the measurement."),
            _t("record_id", "Identifier of the record."),
            _t(
                "corrects",
                "record_id of the record this one corrects. Empty when not a correction.",
            ),
            _t("experiment_id", "Experiment the measurement belongs to."),
            _i("round", "Round of the experiment."),
            _t("batch", "Batch label. Empty when none."),
            _t(
                "unit",
                "Experimental unit; with `round`, matches (`round`, `unit`) in units.csv. "
                "Empty when the position matched no unit.",
            ),
            _t("treatment_id", "Treatment of the unit. Empty when unplaced.", _TREATMENT),
            _t("plant_id", "Plant identifier. Empty when not per plant."),
            _t("position", "Position as recorded. Empty when none."),
            _t("layout_version", "Layout version the position refers to. Empty when none."),
            _variable_id("Variable measured."),
            _f("value", "Measured value in the variable's unit. Empty when not finite."),
            _t("method", "Measurement method. Empty when unspecified."),
            _t("operator", _OPERATOR),
        ),
        ("time", "record_id"),
    ),
    Table(
        "actions.csv",
        "Actuation requests and their outcome, one row per request.",
        (
            _t("request_id", "Identifier of the request."),
            _t("channel", "Actuator channel: light, exhaust, fan or pump."),
            _t("state", "Final state of the request."),
            _t("trigger", "Cleaned trigger category, with operators' notes removed."),
            _i("planned_level", "Level the request asked for. Empty when not a level."),
            _i("confirmed_level", "Level the controller confirmed. Empty when unconfirmed."),
            _d("created_at", "When the request was created."),
            _d("sent_at", "When it was sent. Empty when never sent."),
            _d("confirmed_at", "When the controller confirmed it. Empty when unconfirmed."),
            _f("ran_seconds", "Seconds the action ran. Empty when unknown."),
            _t("error_code", "Registered error code. Empty when none."),
            _t(
                "ended_early_code", "Registered code for why it ended early. Empty when it did not."
            ),
            _t("supersedes", "request_id of the request this one replaced. Empty when none."),
            _t("operator", _OPERATOR),
        ),
        ("created_at", "request_id"),
    ),
    Table(
        "interventions.csv",
        "Interventions applied to stages of the experiment, such as watering or pruning.",
        (
            _t("id", "Identifier of the intervention."),
            _d("time", "Time of the intervention."),
            _t("stage_id", "Stage it was applied to."),
            _t("kind", "Kind of intervention."),
            _t(
                "detail",
                "Detail the system recorded, as JSON with sorted keys. Empty when none.",
            ),
            _t("operator", _OPERATOR),
        ),
        ("time", "id"),
    ),
    Table(
        "withheld.csv",
        "These batches' outcome variables are withheld by design (held-out test data), "
        "not missing at random.",
        (
            _t("holdout_id", "Identifier of the holdout."),
            _t("batch", "Batch whose outcome is withheld."),
            _t("variable_id", "Withheld variable, or `*` for all outcome variables."),
        ),
        ("holdout_id", "batch", "variable_id"),
    ),
)

_BY_FILE = {t.file: t for t in TABLES}


def table(file: str) -> Table:
    return _BY_FILE[file]
