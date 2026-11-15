"""The live environment view: newest reading, channel levels, trends and the running stage."""

import pytest

from growbridge.archive.models import Channel, SampleRecord
from growbridge.workflow.states import StageState


def reading(bench, name, at, light=60, pump_on=1, experiment="experiment-stage-1", **extra):
    data = {
        "light": {"level": light, "on": int(light > 0)},
        "blower": {"level": 25, "on": 1},
        "fan": {"level": 1, "on": 1},
        "outlet": {"O4": {"on": pump_on}},
        "sensor": {"temp": 22.5, "humi": 55.0, "co2": 500},
        **extra,
    }
    bench.archive.append_sample(
        SampleRecord(
            id=name,
            experiment_id=experiment,
            stage_id=None,
            device_id="d1",
            captured_at=at,
            received_at=at,
            clock_synced=True,
            data=data,
        )
    )


def running(bench, started_at):
    bench.pending()
    store = bench.workflow.store
    store.update_stage(store.find_stage("stage-1"), state=StageState.RUNNING, started_at=started_at)


def test_the_view_needs_a_logged_in_operator(bench):
    assert bench.lan.get("/wb/environment").status_code == 401
    assert bench.lan.get("/wb/environment", headers=bench.model()).status_code == 403


def test_without_samples_there_is_no_reading_and_no_trend(operator):
    body = operator.get("/wb/environment").json()

    assert body["latest"] is None and body["stage"] is None
    assert body["readings"]["samples"] == []


def test_the_newest_sample_gives_readings_levels_and_its_age(bench, operator, monkeypatch):
    caps = bench.control.capabilities().model_copy(update={"outlets": {Channel.PUMP: 4}})
    monkeypatch.setattr(bench.control, "capabilities", lambda: caps)
    reading(bench, "old", 1000.0, light=0, experiment=None)
    reading(bench, "new", 1060.0, light=70, pump_on=0)
    bench.clock.wall = 1075.0

    latest = operator.get("/wb/environment").json()["latest"]

    assert latest["timestamp"] == 1060.0 and latest["age_seconds"] == pytest.approx(15.0)
    assert latest["sensors"] == {"temp": 22.5, "humi": 55.0, "co2": 500}
    channels = latest["channels"]
    assert channels["light"] == {"level": 70.0, "on": True}
    assert channels["exhaust"]["level"] == 25.0 and channels["fan"]["level"] == 1.0
    assert channels["pump"] == {"level": 0.0, "on": False}


def test_trends_cover_samples_in_and_outside_stages_within_the_window(bench, operator):
    reading(bench, "too-old", 100.0, experiment=None)
    reading(bench, "between-stages", 3000.0, experiment=None)
    reading(bench, "in-a-stage", 3500.0)
    bench.clock.wall = 4000.0

    body = operator.get("/wb/environment?window=3600").json()["readings"]

    assert [s["timestamp"] for s in body["samples"]] == [3000.0, 3500.0]
    assert body["window"]["start"] == pytest.approx(400.0)


@pytest.mark.parametrize("query", ["window=10", "window=999999999", "points=1", "points=5000"])
def test_out_of_range_windows_are_rejected(operator, query):
    assert operator.get(f"/wb/environment?{query}").status_code == 422


def test_a_running_stage_says_what_each_channel_should_be_at_now(bench, operator):
    running(bench, started_at=0.0)
    bench.clock.wall = 12 * 3600.0  # noon UTC: the bench sheet's light-on (06:00, 60) applies

    stage = operator.get("/wb/environment").json()["stage"]

    assert stage["stage_id"] == "stage-1" and stage["state"] == "running"
    assert stage["channels"]["light"] == {"ownership": "host", "expected": 60}
    assert stage["ends_at"] == pytest.approx(7 * 86400.0)


def test_open_alerts_are_counted_by_severity(bench, operator):
    bench.alerts.raise_alert("sensor", "temp", "warning", "temperature high")
    bench.alerts.raise_alert("sensor", "humi", "warning", "humidity high")

    assert operator.get("/wb/environment").json()["alerts"] == {"warning": 2}
