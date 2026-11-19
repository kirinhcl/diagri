import pytest

from growbridge.dataset.schema import TABLES, table

SENSOR = (
    "time time_source clock_synced sample_id device_id experiment_id stage_id round "
    "variable_id raw_key value quality stuck"
).split()
DEVICE = (
    "time time_source clock_synced sample_id device_id experiment_id stage_id round "
    "key value quality"
).split()
COLUMNS = {
    "variables.csv": (
        "variable_id kind label_en quantity unit_ucum unit_uo method min max refs mapped"
    ).split(),
    "treatments.csv": "treatment_id name is_control variable_id value".split(),
    "units.csv": "round block unit treatment_id".split(),
    "sensor_readings.csv": SENSOR,
    "sensor_readings_untrusted.csv": SENSOR,
    "device_states.csv": DEVICE,
    "device_states_untrusted.csv": DEVICE,
    "measurements.csv": (
        "time record_id corrects experiment_id round batch unit treatment_id plant_id "
        "position layout_version variable_id value method operator"
    ).split(),
    "actions.csv": (
        "request_id channel state trigger planned_level confirmed_level created_at sent_at "
        "confirmed_at ran_seconds error_code ended_early_code supersedes operator"
    ).split(),
    "interventions.csv": "id time stage_id kind detail operator".split(),
    "withheld.csv": "holdout_id batch variable_id".split(),
}


def test_tables_match_the_spec():
    assert [t.file for t in TABLES] == list(COLUMNS)
    for t in TABLES:
        assert [c.name for c in t.columns] == COLUMNS[t.file]
        assert set(t.sort_key) <= {c.name for c in t.columns}
        assert t.description and all(c.description for c in t.columns)


def test_sort_keys():
    assert table("sensor_readings.csv").sort_key == ("time", "sample_id", "raw_key")
    assert table("device_states.csv").sort_key == ("time", "sample_id", "key")
    assert table("actions.csv").sort_key == ("created_at", "request_id")
    assert table("withheld.csv").sort_key == ("holdout_id", "batch", "variable_id")


def test_references():
    for t in TABLES:
        for c in t.columns:
            if c.name == "variable_id" and t.file not in ("variables.csv", "withheld.csv"):
                assert c.references == "variables.csv.variable_id"
            elif c.name == "treatment_id" and t.file in ("units.csv", "measurements.csv"):
                assert c.references == "treatments.csv.treatment_id"
            else:
                assert c.references is None


def test_data_types():
    types = {(t.file, c.name): c.data_type for t in TABLES for c in t.columns}
    assert types["treatments.csv", "value"] == "Text"
    assert types["sensor_readings.csv", "value"] == "Float"
    assert types["actions.csv", "created_at"] == "DateTime"
    assert types["units.csv", "round"] == "Integer"
    assert types["sensor_readings.csv", "stuck"] == "Boolean"


def test_unknown_table_is_a_key_error():
    with pytest.raises(KeyError):
        table("nope.csv")
