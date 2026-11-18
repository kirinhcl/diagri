from growbridge.archive.models import SampleRecord
from growbridge.dataset.rows_samples import sample_rows, time_of
from growbridge.dataset.schema import table
from growbridge.vocab.catalog import packaged_catalog


def sample(**overrides):
    fields = {
        "id": "s1",
        "experiment_id": "exp-1",
        "stage_id": "veg",
        "device_id": "dev",
        "captured_at": 10.0,
        "received_at": 11.0,
        "clock_synced": True,
        "data": {"sensor": {"temp": 24.0}},
    }
    return SampleRecord(**{**fields, **overrides})


def test_time_source():
    assert time_of(sample(captured_at=10.0, received_at=11.0, clock_synced=True)) == (
        10.0,
        "captured",
    )
    assert time_of(sample(captured_at=10.0, received_at=11.0, clock_synced=False)) == (
        11.0,
        "received",
    )
    assert time_of(sample(captured_at=None, received_at=11.0, clock_synced=True)) == (
        11.0,
        "received",
    )


def test_rows_use_the_schema_columns():
    rows = sample_rows(
        [sample(data={"sensor": {"temp": 1.0}, "light": {"on": 1}})], 2, packaged_catalog(), []
    )

    assert set(rows.sensor[0]) == {c.name for c in table("sensor_readings.csv").columns}
    assert set(rows.device[0]) == {c.name for c in table("device_states.csv").columns}
    assert rows.sensor[0]["time_source"] == "captured" and rows.sensor[0]["device_id"] == "dev"


def test_sensor_keys_resolve_through_aliases():
    rows = sample_rows(
        [sample(data={"sensor": {"temp": 24.0, "leafwet": 1.0}})], 2, packaged_catalog(), []
    )
    by_key = {r["raw_key"]: r for r in rows.sensor}
    assert by_key["temp"]["variable_id"] == "air_temperature" and by_key["temp"]["round"] == 2
    assert by_key["leafwet"]["variable_id"] is None and rows.unresolved_keys == 1


def test_non_numeric_sensor_values_are_counted_not_exported():
    data = {"sensor": {"temp": "n/a", "humi": None, "co2": True, "vpd": float("nan")}}
    rows = sample_rows([sample(data=data)], 1, packaged_catalog(), [])
    assert [r["raw_key"] for r in rows.sensor] == ["vpd"] and rows.non_numeric == 3


def test_device_states():
    data = {
        "sensor": {"temp": 20.0},
        "light": {"level": 70, "on": 1},
        "outlet": {"O1": {"on": 0}},
        "mode": "auto",
    }
    rows = sample_rows([sample(data=data)], 1, packaged_catalog(), [])
    assert sorted(r["key"] for r in rows.device) == ["light.level", "light.on", "outlet.O1.on"]
    assert rows.non_numeric == 1
    assert {r["key"]: r["value"] for r in rows.device}["light.level"] == 70


def test_stuck_readings():
    period = {
        "period_id": "f1",
        "sensor": "temp",
        "value": 20.0,
        "first_at": 100.0,
        "last_at": None,
        "opened_at": 160.0,
        "closed_at": None,
        "close_reason": None,
    }
    s = [
        sample(id="a", captured_at=90.0, data={"sensor": {"temp": 20.0, "humi": 50.0}}),
        sample(id="b", captured_at=110.0, data={"sensor": {"temp": 20.0, "humi": 50.0}}),
    ]
    rows = sample_rows(s, 1, packaged_catalog(), [period])
    stuck = {(r["sample_id"], r["raw_key"]): r["stuck"] for r in rows.sensor}
    assert stuck == {
        ("a", "temp"): False,
        ("a", "humi"): False,
        ("b", "temp"): True,
        ("b", "humi"): False,
    }


def test_a_closed_period_ends_at_last_at():
    period = {
        "period_id": "f1",
        "sensor": "air_temperature",
        "value": 20.0,
        "first_at": 100.0,
        "last_at": 120.0,
        "opened_at": 160.0,
        "closed_at": 200.0,
        "close_reason": "value_changed",
    }
    s = [
        sample(id=i, captured_at=t, data={"sensor": {"temp": 20.0}})
        for i, t in (("a", 120.0), ("b", 130.0))
    ]
    rows = sample_rows(s, 1, packaged_catalog(), [period])
    assert {r["sample_id"]: r["stuck"] for r in rows.sensor} == {"a": True, "b": False}


def test_a_sensor_value_that_is_not_an_object_is_counted_once_per_sample():
    s = [
        sample(id="a", data={"sensor": [24.0, 60.0]}),
        sample(id="b", data={"sensor": "offline"}),
        sample(id="c", data={"sensor": None}),
        sample(id="d", data={"light": {"on": 1}}),
    ]
    rows = sample_rows(s, 1, packaged_catalog(), [])
    assert rows.sensor == () and rows.non_numeric == 3
    assert [r["sample_id"] for r in rows.device] == ["d"]


def test_stuck_uses_the_archive_sample_time_even_when_the_clock_is_unsynced():
    """Frozen periods are stamped with the capture time whenever there is one, synchronised or
    not (``archive.store._sample_time``); ``time`` still shows the received time."""
    period = {
        "period_id": "f1",
        "sensor": "temp",
        "value": 20.0,
        "first_at": 100.0,
        "last_at": 120.0,
        "opened_at": 160.0,
        "closed_at": 200.0,
        "close_reason": "value_changed",
    }
    s = [
        sample(id="in", captured_at=110.0, received_at=300.0, clock_synced=False),
        sample(id="out", captured_at=90.0, received_at=115.0, clock_synced=False),
        sample(id="none", captured_at=None, received_at=115.0, clock_synced=False),
    ]
    rows = sample_rows(s, 1, packaged_catalog(), [period])
    by_id = {r["sample_id"]: r for r in rows.sensor}
    assert {i: r["stuck"] for i, r in by_id.items()} == {"in": True, "out": False, "none": True}
    assert (by_id["in"]["time"], by_id["in"]["time_source"]) == (300.0, "received")
