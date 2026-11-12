"""The rule behind a confirmatory run: nothing in the snapshot may have been collected before the
analysis script was frozen (architecture §6.5). Data collected earlier can never be confirmatory."""

import pytest

from growbridge.archive.models import ManualMeasurement
from growbridge.ports import Denied
from growbridge.research.preregistration import require_measurements_after, require_stages_after

FROZEN_AT = 100.0


def row(ident: str) -> ManualMeasurement:
    return ManualMeasurement(
        id=ident,
        experiment_id="experiment-1",
        batch="batch-1",
        plant_id="p1",
        layout_version="v1",
        measured_at=500.0,  # typed in; says nothing about when it was recorded
        position="tent-1",
        method="ruler",
        metric="canopy_area_growth",
        value=1.0,
        unit="cm2",
        operator="op-1",
    )


def write(path, *rows) -> None:
    path.write_text("".join(item.model_dump_json() + "\n" for item in rows), encoding="utf-8")


def recorded(times: dict):
    return lambda ids: {i: times[i] for i in ids if i in times}


# --- stages ------------------------------------------------------------------------------------


def test_stages_that_started_at_or_after_the_freeze_are_fine():
    require_stages_after(FROZEN_AT, "snap-1", [100.0, 250.0])


def test_a_stage_that_never_started_adds_no_data_and_no_stage_at_all_is_fine():
    require_stages_after(FROZEN_AT, "snap-1", [None])
    require_stages_after(FROZEN_AT, "snap-1", [])


def test_one_stage_that_started_before_the_freeze_refuses_the_snapshot():
    with pytest.raises(Denied) as caught:
        require_stages_after(FROZEN_AT, "snap-1", [250.0, 99.0])

    assert caught.value.code == "state"
    assert "snap-1" in str(caught.value) and "frozen" in str(caught.value)


# --- measurements ------------------------------------------------------------------------------


def test_measurements_recorded_at_or_after_the_freeze_are_fine(tmp_path):
    path = tmp_path / "measurements.jsonl"
    write(path, row("m1"), row("m2"))

    require_measurements_after(FROZEN_AT, "snap-1", path, recorded({"m1": 100.0, "m2": 300.0}))


def test_an_empty_snapshot_has_nothing_to_check(tmp_path):
    path = tmp_path / "measurements.jsonl"
    write(path)

    require_measurements_after(FROZEN_AT, "snap-1", path, recorded({}))


def test_a_measurement_recorded_before_the_freeze_refuses_even_if_measured_later(tmp_path):
    path = tmp_path / "measurements.jsonl"
    write(path, row("m1"), row("m2"))

    with pytest.raises(Denied) as caught:
        require_measurements_after(FROZEN_AT, "snap-1", path, recorded({"m1": 300.0, "m2": 50.0}))

    assert caught.value.code == "state" and "snap-1" in str(caught.value)


def test_a_measurement_with_no_recording_time_is_treated_as_old(tmp_path):
    path = tmp_path / "measurements.jsonl"
    write(path, row("m1"), row("m-legacy"))

    with pytest.raises(Denied):
        require_measurements_after(FROZEN_AT, "snap-1", path, recorded({"m1": 300.0}))


def test_the_refusal_never_quotes_a_value(tmp_path):
    path = tmp_path / "measurements.jsonl"
    write(path, row("m1"))

    with pytest.raises(Denied) as caught:
        require_measurements_after(FROZEN_AT, "snap-1", path, recorded({"m1": 1.0}))

    assert "cm2" not in str(caught.value) and "canopy" not in str(caught.value)
