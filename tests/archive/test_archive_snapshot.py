import json

import pytest

from growbridge.archive import snapshot as snap
from growbridge.archive.models import ManualMeasurement, SampleRecord
from growbridge.ports import Denied
from growbridge.sim.clock import START

STEP = 60.0
FREEZE = dict(expected_interval=STEP, max_gap=STEP * 1.5)


def put(archive, index, at, **fields):
    base = dict(
        id=f"d:{index}",
        experiment_id="exp-1",
        stage_id="veg",
        device_id="d",
        captured_at=at,
        received_at=at,
        clock_synced=True,
        data={"t": 24.0},
    )
    archive.append_sample(SampleRecord(**{**base, **fields}))


def fill(archive, count, start=START):
    for i in range(count):
        put(archive, i, start + i * STEP)


def freeze(archive, clock, end_minutes=10, **kwargs):
    return snap.freeze(
        archive, "exp-1", clock, START, START + end_minutes * STEP, **{**FREEZE, **kwargs}
    )


def measurement(id="m1"):
    return ManualMeasurement(
        id=id,
        experiment_id="exp-1",
        batch="b",
        plant_id="p",
        layout_version="L",
        measured_at=START + 5,
        position="top",
        method="ruler",
        metric="height",
        value=3.0,
        unit="cm",
        operator="alice",
    )


def test_complete_data_freezes_with_full_coverage(archive, clock):
    fill(archive, 10)

    frozen = freeze(archive, clock)

    assert frozen.complete is True
    assert frozen.coverage == pytest.approx(1.0)
    assert frozen.gaps == ()
    assert frozen.version == 1


def test_freeze_writes_files_and_manifest_under_snapshot_directory(archive, clock):
    fill(archive, 3)
    frozen = freeze(archive, clock, end_minutes=3)

    directory = archive.root / "snapshots" / frozen.id
    assert (directory / "manifest.json").exists()
    assert "samples.jsonl" in frozen.files
    lines = (directory / "samples.jsonl").read_text().splitlines()
    assert [json.loads(line)["id"] for line in lines] == ["d:0", "d:1", "d:2"]
    manifest = json.loads((directory / "manifest.json").read_text())
    assert manifest["files"] == frozen.files


def test_verify_is_true_for_untouched_snapshot(archive, clock):
    fill(archive, 3)
    frozen = freeze(archive, clock, end_minutes=3)

    assert snap.verify(archive, frozen.id) is True


def test_verify_is_false_after_data_file_is_modified(archive, clock):
    fill(archive, 3)
    frozen = freeze(archive, clock, end_minutes=3)
    path = archive.root / "snapshots" / frozen.id / "samples.jsonl"
    path.write_text(path.read_text().replace("24.0", "25.0"))

    assert snap.verify(archive, frozen.id) is False


def test_verify_is_false_after_manifest_is_modified_or_file_missing(archive, clock):
    fill(archive, 3)
    frozen = freeze(archive, clock, end_minutes=3)
    directory = archive.root / "snapshots" / frozen.id
    manifest = directory / "manifest.json"
    original = manifest.read_text()
    manifest.write_text(original + " ")
    assert snap.verify(archive, frozen.id) is False

    manifest.write_text(original)
    (directory / "samples.jsonl").unlink()
    assert snap.verify(archive, frozen.id) is False


def test_verify_unknown_snapshot_is_false(archive):
    assert snap.verify(archive, "missing") is False


def test_low_coverage_is_marked_incomplete_with_gaps(archive, clock):
    fill(archive, 4)  # minutes 0-3 only; 4-10 missing

    frozen = freeze(archive, clock)

    assert frozen.complete is False
    assert frozen.coverage < 0.9
    assert frozen.gaps and frozen.gaps[-1][1] == START + 10 * STEP


def test_coverage_counts_duration_not_rows(archive, clock):
    for i in range(30):  # 30 rows within the first 30 s
        put(archive, i, START + i)

    frozen = freeze(archive, clock)

    assert frozen.coverage < 0.2


def test_unsynced_and_invalid_samples_do_not_count_toward_coverage(archive, clock):
    for i in range(10):
        put(archive, i, START + i * STEP, clock_synced=i % 3 != 0)
    put(archive, 99, START + 5 * STEP + 1, quality="invalid")

    frozen = freeze(archive, clock)

    assert frozen.complete is False
    assert frozen.gaps


def test_query_samples_do_not_count_toward_coverage(archive, clock):
    for i in range(10):
        put(archive, i, START + i * STEP, source="query")

    assert freeze(archive, clock).coverage == 0.0


def test_empty_window_is_one_gap(archive, clock):
    frozen = freeze(archive, clock)

    assert frozen.complete is False
    assert frozen.coverage == 0.0
    assert frozen.gaps == ((START, START + 10 * STEP),)


def test_freezing_again_creates_a_new_version(archive, clock):
    fill(archive, 10)
    first = freeze(archive, clock)
    put(archive, 50, START + 5 * STEP + 1)
    second = freeze(archive, clock)

    assert (first.version, second.version) == (1, 2)
    assert first.id != second.id
    assert snap.verify(archive, first.id) and snap.verify(archive, second.id)
    assert snap.load(archive, first.id).files != snap.load(archive, second.id).files


def test_freeze_is_denied_while_clock_is_unsynced(archive, clock):
    fill(archive, 10)
    clock.synced = False

    with pytest.raises(Denied) as caught:
        freeze(archive, clock)

    assert caught.value.code == "clock_unsynced"
    assert archive.snapshots("exp-1") == ()


def test_clock_unsynced_carries_no_params(archive, clock):
    fill(archive, 10)
    clock.synced = False

    with pytest.raises(Denied) as caught:
        freeze(archive, clock)

    assert (caught.value.reason, caught.value.params) == ("clock_unsynced", {})


def test_freeze_rejects_empty_or_reversed_window(archive, clock):
    with pytest.raises(ValueError):
        snap.freeze(archive, "exp-1", clock, START, START, **FREEZE)


def test_snapshot_includes_actions_measurements_and_interventions(archive, clock):
    fill(archive, 10)
    archive.add_measurement(measurement())
    archive.record_intervention("exp-1", "veg", "water", {"ml": 100}, "alice")

    frozen = freeze(archive, clock)

    expected = {"samples.jsonl", "actions.jsonl", "measurements.jsonl", "interventions.jsonl"}
    assert expected <= set(frozen.files)
    assert snap.load(archive, frozen.id) == frozen


def test_load_unknown_snapshot_raises_key_error(archive):
    with pytest.raises(KeyError):
        snap.load(archive, "missing")


def test_later_correction_marks_frozen_snapshot_invalid(archive, clock):
    fill(archive, 10)
    archive.add_measurement(measurement())
    frozen = freeze(archive, clock)

    corrected = measurement("m2").model_copy(update={"value": 4.0, "corrects": "m1"})
    archive.add_measurement(corrected)

    assert archive.is_invalid(frozen.id)
    assert snap.verify(archive, frozen.id) is True  # the frozen files themselves are unchanged


def ids_in(archive, frozen, name):
    path = archive.root / "snapshots" / frozen.id / name
    return [json.loads(line)["id"] for line in path.read_text().splitlines()]


def test_untrusted_samples_go_to_a_separate_file(archive, clock):
    fill(archive, 6)
    put(archive, 90, START + 10, clock_synced=False)
    put(archive, 91, START + 20, source="query")
    put(archive, 92, START + 30, quality="invalid")
    put(archive, 93, START + 40, quality="suspect")

    frozen = freeze(archive, clock)

    assert ids_in(archive, frozen, "samples.jsonl") == [f"d:{i}" for i in range(6)]
    assert sorted(ids_in(archive, frozen, "samples_untrusted.jsonl")) == [
        "d:90",
        "d:91",
        "d:92",
        "d:93",
    ]
    assert {"samples.jsonl", "samples_untrusted.jsonl"} <= set(frozen.files)
    assert snap.verify(archive, frozen.id)


def test_measurement_filter_leaves_records_out_and_counts_them(archive, clock):
    fill(archive, 10)
    archive.add_measurement(measurement("m1"))
    archive.add_measurement(measurement("m2").model_copy(update={"plant_id": "holdout"}))

    frozen = freeze(archive, clock, measurement_filter=lambda m: m.plant_id != "holdout")

    assert ids_in(archive, frozen, "measurements.jsonl") == ["m1"]
    manifest = json.loads((archive.root / "snapshots" / frozen.id / "manifest.json").read_text())
    assert manifest["measurements_excluded"] == 1
    assert archive.mark_dependents_invalid("m2") == ()  # not part of the snapshot


def test_manifest_records_zero_exclusions_without_a_filter(archive, clock):
    fill(archive, 3)
    frozen = freeze(archive, clock, end_minutes=3)

    manifest = json.loads((archive.root / "snapshots" / frozen.id / "manifest.json").read_text())
    assert manifest["measurements_excluded"] == 0


def test_preview_groups_alias_with_id(archive):
    fill(archive, 11)
    for index, metric in enumerate(("temp", "air_temperature", "heigth")):
        item = measurement(f"m{index}").model_copy(update={"metric": metric, "unit": "Cel"})
        archive.add_measurement(item)

    summary = snap.preview(archive, "exp-1", START, START + 10 * STEP, STEP, STEP * 1.5)

    groups = summary["measurements"]
    assert set(groups) == {"air_temperature", "heigth"}
    assert groups["air_temperature"]["plants"] == 1


def test_freeze_writes_catalog_json(archive, clock):
    archive.add_measurement(measurement("m1").model_copy(update={"metric": "canopy_area_growth"}))
    archive.add_measurement(measurement("m2").model_copy(update={"metric": "heigth"}))
    put(archive, 1, START + 1, data={"sensor": {"temp": 21.0}, "light": {"level": 40}})

    frozen = freeze(archive, clock, declared={"canopy_area_growth"})

    record = json.loads((archive.root / "snapshots" / frozen.id / "catalog.json").read_text())
    assert [v["id"] for v in record["variables"]] == ["air_temperature", "canopy_area_growth"]
    assert record["unresolved"] == ["heigth"]
    assert "catalog.json" in frozen.files
    assert snap.verify(archive, frozen.id)


def test_sample_without_sensor_key_adds_no_names(archive, clock):
    put(archive, 1, START + 1, data={})

    frozen = freeze(archive, clock)

    record = json.loads((archive.root / "snapshots" / frozen.id / "catalog.json").read_text())
    assert record["variables"] == []
    assert record["unresolved"] == []
