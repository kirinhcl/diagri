"""Which experiments hold an outcome of a batch: answered in SQL over the stored measurements, so
a holdout registration never reads and validates every measurement of a project."""

import pytest

from growbridge.archive.models import ManualMeasurement

OUTCOMES = ("yield_g", "canopy_score")
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


def test_the_experiments_with_a_matching_outcome_are_listed_once_each(archive):
    archive.add_measurement(row("m1", experiment="exp-1"))
    archive.add_measurement(row("m2", experiment="exp-1", metric="canopy_score"))
    archive.add_measurement(row("m3", experiment="exp-2"))

    assert archive.outcome_experiments(("b3",), OUTCOMES) == ("exp-1", "exp-2")


@pytest.mark.parametrize(
    "other", [row("x", metric="temp"), row("x", batch="b1")], ids=["other-metric", "other-batch"]
)
def test_other_measurements_do_not_match(archive, other):
    archive.add_measurement(other)

    assert archive.outcome_experiments(("b3",), OUTCOMES) == ()


def test_a_measurement_without_a_batch_matches_any_held_out_batch(archive):
    archive.add_measurement(row("m1", batch=""))

    assert archive.outcome_experiments(("b3",), OUTCOMES) == ("exp-1",)


def test_a_corrected_measurement_still_matches_and_so_does_its_correction(archive):
    archive.add_measurement(row("m1", experiment="exp-1"))
    archive.add_measurement(row("m2", experiment="exp-2", corrects="m1"))

    assert archive.outcome_experiments(("b3",), OUTCOMES) == ("exp-1", "exp-2")


def test_names_with_quotes_are_matched_as_data_not_as_sql(archive):
    archive.add_measurement(row("m1", batch="b'3", metric=QUOTED))

    assert archive.outcome_experiments(("b'3",), (QUOTED,)) == ("exp-1",)
    assert archive.outcome_experiments(("b3",), OUTCOMES) == ()
    assert archive.measurements("exp-1")  # the table is still there


def test_a_long_list_of_names_is_matched_without_hitting_a_variable_limit(archive):
    archive.add_measurement(row("m1", batch="b-777", metric="m-777"))
    batches = tuple(f"b-{i}" for i in range(1500))
    metrics = tuple(f"m-{i}" for i in range(1500))

    assert archive.outcome_experiments(batches, metrics) == ("exp-1",)


def test_an_empty_list_matches_nothing(archive):
    archive.add_measurement(row("m1"))

    assert archive.outcome_experiments((), OUTCOMES) == ()
    assert archive.outcome_experiments(("b3",), ()) == ()
