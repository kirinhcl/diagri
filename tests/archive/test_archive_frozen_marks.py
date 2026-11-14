import json

from growbridge.archive import snapshot as snap
from growbridge.archive.models import SampleRecord
from growbridge.sim.clock import START


def sample(id, at, experiment_id="e1", data=None):
    return SampleRecord(
        id=id,
        experiment_id=experiment_id,
        stage_id=None,
        device_id="d",
        captured_at=at,
        received_at=at,
        clock_synced=True,
        data={"sensor": {"temp": 24.0}} if data is None else data,
    )


def marks(archive):
    return [dict(r) for r in archive.db.query("SELECT * FROM frozen_marks ORDER BY seq")]


def test_open_then_close_adds_two_rows_and_changes_none(archive):
    period = archive.open_frozen("temp", 24.0, 100.0)
    before = marks(archive)

    archive.close_frozen(period, "temp", 200.0)

    after = marks(archive)
    assert len(before) == 1 and len(after) == 2
    assert after[0] == before[0]
    assert after[0]["event"] == "opened" and after[1]["event"] == "closed"
    assert after[1]["sample_at"] == 200.0


def test_open_periods_leave_out_closed_ones(archive):
    closed = archive.open_frozen("temp", 24.0, 100.0)
    still_open = archive.open_frozen("humi", 55.0, 120.0)
    archive.close_frozen(closed, "temp", 200.0)

    periods = archive.open_frozen_periods()

    assert [p.period_id for p in periods] == [still_open]
    assert (periods[0].sensor, periods[0].value, periods[0].first_at) == ("humi", 55.0, 120.0)
    assert periods[0].opened_at == archive.clock.now()


def test_closing_twice_is_harmless(archive):
    period = archive.open_frozen("temp", 24.0, 100.0)
    archive.close_frozen(period, "temp", 200.0)

    archive.close_frozen(period, "temp", 250.0)

    rows = marks(archive)
    assert len(rows) == 2
    assert rows[1]["sample_at"] == 200.0


def test_frozen_periods_overlap_the_window(archive):
    closed = archive.open_frozen("temp", 24.0, 100.0)
    archive.close_frozen(closed, "temp", 200.0)
    opened = archive.open_frozen("humi", 55.0, 500.0)

    def ids(start, end):
        return {p["period_id"] for p in archive.frozen_periods(start, end)}

    assert closed in ids(150.0, 300.0)
    assert closed not in ids(201.0, 300.0)
    assert opened in ids(0.0, 500.0)
    assert opened in ids(600.0, 9000.0)
    assert opened not in ids(0.0, 499.0)
    row = next(p for p in archive.frozen_periods(150.0, 300.0) if p["period_id"] == closed)
    assert (row["last_at"], row["first_at"]) == (200.0, 100.0)
    assert row["closed_at"] is not None and row["opened_at"] is not None
    live = next(p for p in archive.frozen_periods(0.0, 600.0) if p["period_id"] == opened)
    assert live["last_at"] is None and live["closed_at"] is None


def test_sensor_points_are_in_time_order_across_experiments(archive):
    archive.append_sample(sample("s2", 20.0, experiment_id=None))
    archive.append_sample(sample("s1", 10.0))
    archive.append_sample(sample("s0", 1.0))

    points = archive.sensor_points(5.0)

    assert [at for at, _ in points] == [10.0, 20.0]
    assert points[0][1] == {"temp": 24.0}


def test_sensor_points_tolerate_samples_without_a_sensor_block(archive):
    archive.append_sample(sample("a", 10.0, data={}))
    archive.append_sample(sample("b", 11.0, data={"sensor": "x"}))

    assert archive.sensor_points(0.0) == ((10.0, {}), (11.0, {}))


def test_snapshot_lists_overlapping_frozen_periods(archive, clock):
    for i in range(10):
        archive.append_sample(sample(f"s{i}", START + i * 60))
    period = archive.open_frozen("temp", 24.0, START + 60)
    archive.close_frozen(period, "temp", START + 120)

    frozen = snap.freeze(
        archive, "e1", clock, START, START + 600, expected_interval=60.0, max_gap=90.0
    )

    assert "frozen_periods.jsonl" in frozen.files
    path = archive.root / "snapshots" / frozen.id / "frozen_periods.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [r["period_id"] for r in rows] == [period]


def test_samples_are_untouched(archive):
    archive.append_sample(sample("s1", 10.0))
    before = [dict(r) for r in archive.db.query("SELECT * FROM samples ORDER BY id")]

    period = archive.open_frozen("temp", 24.0, 10.0)
    archive.close_frozen(period, "temp", 10.0)

    assert [dict(r) for r in archive.db.query("SELECT * FROM samples ORDER BY id")] == before
