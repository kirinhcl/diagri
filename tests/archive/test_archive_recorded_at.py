"""When a manual measurement was recorded, as opposed to when it was measured: the confirmatory
gate needs the first, because ``measured_at`` is typed in by the operator."""

from growbridge.archive.db import Database
from growbridge.archive.models import ManualMeasurement
from growbridge.archive.store import STEPS, Archive
from growbridge.sim.clock import START, FakeClock


def row(ident: str, measured_at: float = 1.0, **fields) -> ManualMeasurement:
    values = {
        "id": ident,
        "experiment_id": "experiment-1",
        "batch": "batch-1",
        "plant_id": "p1",
        "layout_version": "v1",
        "measured_at": measured_at,
        "position": "tent-1",
        "method": "ruler",
        "metric": "canopy_area_growth",
        "value": 1.0,
        "unit": "cm2",
        "operator": "op-1",
    }
    return ManualMeasurement(**{**values, **fields})


def test_the_time_of_recording_is_the_archive_clock_not_the_measured_at(archive, clock):
    archive.add_measurement(row("m1", measured_at=5.0))  # typed in as long ago
    clock.advance(60)
    archive.add_measurement(row("m2", measured_at=5.0))

    assert archive.measurement_recorded_at(["m1", "m2"]) == {"m1": START, "m2": START + 60}


def test_a_repeated_record_keeps_its_first_recording_time(archive, clock):
    archive.add_measurement(row("m1"))
    clock.advance(60)
    archive.add_measurement(row("m1"))  # an identical repeat is a no-op

    assert archive.measurement_recorded_at(["m1"]) == {"m1": START}


def test_a_correction_has_its_own_recording_time(archive, clock):
    archive.add_measurement(row("m1"))
    clock.advance(60)
    archive.add_measurement(row("m2", corrects="m1"))

    assert archive.measurement_recorded_at(["m1", "m2"]) == {"m1": START, "m2": START + 60}


def test_unknown_ids_are_not_in_the_answer_and_an_empty_list_is_fine(archive):
    archive.add_measurement(row("m1"))

    assert archive.measurement_recorded_at(["nope"]) == {}
    assert archive.measurement_recorded_at([]) == {}


def test_measurements_recorded_before_the_column_existed_have_no_time(tmp_path):
    database = Database(tmp_path / "old.db")
    database.migrate("archive", STEPS[:-1])  # the schema before recorded_at
    body = row("m-old").model_dump_json()
    database.execute(
        "INSERT INTO measurements(id, experiment_id, corrects, seq, body) VALUES (?, ?, ?, ?, ?)",
        ("m-old", "experiment-1", None, 1, body),
    )
    try:
        archive = Archive(database, tmp_path / "archive", FakeClock())

        assert archive.measurement_recorded_at(["m-old"]) == {"m-old": None}
    finally:
        database.close()
