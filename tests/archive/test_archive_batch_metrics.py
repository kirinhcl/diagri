"""Which (experiment, metric) pairs a batch holds: answered in SQL over the stored measurements, so
a holdout registration never reads and validates every measurement of a project."""

from growbridge.archive.models import ManualMeasurement

QUOTED = 'y"; select 1; --'


def row(ident: str, experiment="exp-1", batch="b3", metric="yield_g", **fields):
    values = {
        "id": ident,
        "experiment_id": experiment,
        "batch": batch,
        "plant_id": "p1",
        "layout_version": "v1",
        "measured_at": 1.0,
        "position": "tent-1",
        "method": "ruler",
        "metric": metric,
        "value": 12.5,
        "unit": "g",
        "operator": "op-1",
    }
    return ManualMeasurement(**{**values, **fields})


def test_the_pairs_of_a_batch_are_listed_once_each_sorted(archive):
    archive.add_measurement(row("m1", experiment="exp-1"))
    archive.add_measurement(row("m1b", experiment="exp-1"))
    archive.add_measurement(row("m2", experiment="exp-1", metric="canopy_score"))
    archive.add_measurement(row("m3", experiment="exp-2"))

    assert archive.batch_metrics(("b3",)) == (
        ("exp-1", "canopy_score"),
        ("exp-1", "yield_g"),
        ("exp-2", "yield_g"),
    )


def test_other_batches_do_not_match(archive):
    archive.add_measurement(row("x", batch="b1"))

    assert archive.batch_metrics(("b3",)) == ()


def test_a_measurement_without_a_batch_matches_any_batch(archive):
    archive.add_measurement(row("m1", batch=""))

    assert archive.batch_metrics(("b3",)) == (("exp-1", "yield_g"),)


def test_a_corrected_measurement_still_matches_and_so_does_its_correction(archive):
    archive.add_measurement(row("m1", experiment="exp-1"))
    archive.add_measurement(row("m2", experiment="exp-2", corrects="m1"))

    assert archive.batch_metrics(("b3",)) == (("exp-1", "yield_g"), ("exp-2", "yield_g"))


def test_names_with_quotes_are_matched_as_data_not_as_sql(archive):
    archive.add_measurement(row("m1", batch="b'3", metric=QUOTED))

    assert archive.batch_metrics(("b'3",)) == (("exp-1", QUOTED),)
    assert archive.batch_metrics(("b3",)) == ()
    assert archive.measurements("exp-1")  # the table is still there


def test_a_long_list_of_names_is_matched_without_hitting_a_variable_limit(archive):
    archive.add_measurement(row("m1", batch="b-777", metric="m-777"))
    batches = tuple(f"b-{i}" for i in range(1500))

    assert archive.batch_metrics(batches) == (("exp-1", "m-777"),)


def test_an_empty_list_matches_nothing(archive):
    archive.add_measurement(row("m1"))

    assert archive.batch_metrics(()) == ()
