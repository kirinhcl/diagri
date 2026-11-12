import pytest

from growbridge.archive.db import Database
from growbridge.archive.models import ManualMeasurement
from growbridge.ports import Denied
from growbridge.research.holdout import HoldoutRegistry, refuse_holdout_rows
from growbridge.sim.clock import FakeClock

OUTCOMES = ("yield_g", "canopy_score")
DEV = ("dev-1", "dev-2")
DEV3 = ("dev-1", "dev-2", "dev-3")


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "holdout.db")
    yield database
    database.close()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def registry(db, clock):
    return HoldoutRegistry(db, clock)


@pytest.fixture
def registered(registry):
    registry.register("project-1", "hold-1", ("b3",), OUTCOMES, development_batch_ids=DEV)
    return registry


def test_fewer_than_two_development_batches_is_denied(registry):
    with pytest.raises(Denied) as caught:
        registry.register(
            "project-1", "hold-1", ("b2",), OUTCOMES, development_batch_ids=("dev-1",)
        )

    assert caught.value.code == "batches"


def test_an_empty_holdout_is_denied(registry):
    with pytest.raises(Denied) as caught:
        registry.register("project-1", "hold-1", (), OUTCOMES, development_batch_ids=DEV3)

    assert caught.value.code == "batches"


def test_registering_the_same_holdout_twice_is_denied(registered):
    with pytest.raises(Denied) as caught:
        registered.register("project-1", "hold-1", ("b4",), OUTCOMES, development_batch_ids=DEV3)

    assert caught.value.code == "state"


def test_general_reads_do_not_see_holdout_outcome_labels(registered):
    rows = [
        {"batch": "b1", "temp": 24.0, "yield_g": 50.0},
        {"batch": "b3", "temp": 24.5, "yield_g": 55.0, "canopy_score": 3},
        {"temp": 25.0, "yield_g": 60.0},
    ]

    result = registered.filter_development("hold-1", rows)

    assert result[0] == {"batch": "b1", "temp": 24.0, "yield_g": 50.0}
    assert result[1] == {"batch": "b3", "temp": 24.5}  # environment stays, outcomes go
    assert result[2] == {"temp": 25.0}  # unknown batch: fail closed
    assert rows[1]["yield_g"] == 55.0  # input is not mutated


def test_filtering_an_unregistered_holdout_is_denied(registry):
    with pytest.raises(Denied) as caught:
        registry.filter_development("nope", [])

    assert caught.value.code == "state"


def test_features_after_prediction_time_are_listed(registry):
    late = registry.late_features(
        {"temp_mean": 100.0, "humi_mean": 100.0, "yield_prev": 150.0, "ppfd": 99.0},
        prediction_time=100.0,
    )

    assert late == ("yield_prev",)


def test_evaluating_an_unregistered_model_is_denied_and_not_logged(registered):
    with pytest.raises(Denied) as caught:
        registered.evaluate("hold-1", "evaluator", "m" * 64)

    assert caught.value.code == "model_unregistered"
    assert registered.reads("hold-1") == []


def test_first_evaluation_is_confirmatory_and_later_ones_exploratory(registered, clock):
    registered.register_model("hold-1", "m" * 64, "f" * 64, "p" * 64)

    first = registered.evaluate("hold-1", "script-a", "m" * 64)
    clock.advance(60)
    second = registered.evaluate("hold-1", "script-b", "m" * 64)
    third = registered.evaluate("hold-1", "script-a", "m" * 64)

    assert (first, second, third) == ("confirmatory", "exploratory", "exploratory")


def test_every_read_is_logged_with_time_and_reader(registered, clock):
    registered.register_model("hold-1", "m" * 64, "f" * 64, "p" * 64)
    registered.evaluate("hold-1", "script-a", "m" * 64)
    clock.advance(60)
    registered.evaluate("hold-1", "script-b", "m" * 64)

    reads = registered.reads("hold-1")

    assert [read.reader for read in reads] == ["script-a", "script-b"]
    assert [read.label for read in reads] == ["confirmatory", "exploratory"]
    assert reads[1].at - reads[0].at == 60


def test_holdouts_count_reads_independently(registered):
    registered.register("project-1", "hold-2", ("b4",), OUTCOMES, development_batch_ids=DEV)
    for holdout in ("hold-1", "hold-2"):
        registered.register_model(holdout, "m" * 64, "f" * 64, "p" * 64)

    assert registered.evaluate("hold-1", "a", "m" * 64) == "confirmatory"
    assert registered.evaluate("hold-2", "a", "m" * 64) == "confirmatory"


def test_registering_a_model_for_an_unknown_holdout_is_denied(registry):
    with pytest.raises(Denied) as caught:
        registry.register_model("nope", "m" * 64, "f" * 64, "p" * 64)

    assert caught.value.code == "state"


def test_registrations_survive_reopening_the_database(tmp_path, clock):
    path = tmp_path / "again.db"
    first = Database(path)
    registry = HoldoutRegistry(first, clock)
    registry.register("project-1", "hold-1", ("b3",), OUTCOMES, development_batch_ids=DEV)
    registry.register_model("hold-1", "m" * 64, "f" * 64, "p" * 64)
    registry.evaluate("hold-1", "a", "m" * 64)
    first.close()

    second = Database(path)
    try:
        reopened = HoldoutRegistry(second, clock)
        assert reopened.evaluate("hold-1", "b", "m" * 64) == "exploratory"
    finally:
        second.close()


def test_evaluate_is_bound_to_the_registered_model_hash(registered):
    registered.register_model("hold-1", "m" * 64, "f" * 64, "p" * 64)

    with pytest.raises(Denied) as caught:
        registered.evaluate("hold-1", "script-a", "x" * 64)

    assert caught.value.code == "model_unregistered"
    assert registered.reads("hold-1") == []
    assert registered.evaluate("hold-1", "script-a", "m" * 64) == "confirmatory"
    assert registered.reads("hold-1")[0].model_sha == "m" * 64


def measurement(metric: str, batch: str) -> ManualMeasurement:
    return ManualMeasurement(
        id="m1",
        experiment_id="exp-1",
        batch=batch,
        plant_id="p0",
        layout_version="v1",
        measured_at=1_800_000_000.0,
        position="tent-1",
        method="ruler",
        metric=metric,
        value=1.0,
        unit="g",
        operator="op",
    )


def test_development_filter_hides_holdout_outcomes_only(registered):
    keep = registered.development_filter("project-1")

    assert keep(measurement("yield_g", "b3")) is False  # outcome of a holdout batch
    assert keep(measurement("yield_g", "b1")) is True  # development batch
    assert keep(measurement("temp", "b3")) is True  # not an outcome metric
    assert keep(measurement("yield_g", "")) is False  # no batch: fail closed


def test_development_filter_ignores_other_projects_and_sees_later_registrations(registry):
    keep = registry.development_filter("project-1")
    assert keep(measurement("yield_g", "b3")) is True

    registry.register("project-1", "hold-1", ("b3",), OUTCOMES, development_batch_ids=DEV)
    registry.register("project-2", "hold-9", ("b1",), OUTCOMES, development_batch_ids=DEV)

    assert keep(measurement("yield_g", "b3")) is False
    assert keep(measurement("yield_g", "b1")) is True


# --- the check a snapshot goes through before any analysis -----------------------------------


def write_rows(path, rows):
    path.write_text("".join(row.model_dump_json() + "\n" for row in rows), encoding="utf-8")
    return path


def test_a_snapshot_with_holdout_outcomes_is_refused_without_quoting_a_value(registered, tmp_path):
    path = write_rows(
        tmp_path / "measurements.jsonl",
        [measurement("temp", "b3"), measurement("yield_g", "b3")],
    )

    with pytest.raises(Denied) as caught:
        refuse_holdout_rows(registered, "project-1", "snap-1", path)

    assert caught.value.code == "scope"
    assert "snap-1" in str(caught.value) and "1.0" not in str(caught.value)


def test_a_snapshot_of_development_rows_passes(registered, tmp_path):
    path = write_rows(
        tmp_path / "measurements.jsonl",
        [measurement("yield_g", "b1"), measurement("temp", "b3")],
    )

    refuse_holdout_rows(registered, "project-1", "snap-1", path)


def test_without_a_registry_there_is_nothing_to_check(tmp_path):
    path = write_rows(tmp_path / "measurements.jsonl", [measurement("yield_g", "b3")])

    refuse_holdout_rows(None, "project-1", "snap-1", path)


def test_a_row_without_a_batch_is_refused_when_its_metric_is_an_outcome(registered, tmp_path):
    path = write_rows(tmp_path / "measurements.jsonl", [measurement("yield_g", "")])

    with pytest.raises(Denied):
        refuse_holdout_rows(registered, "project-1", "snap-1", path)
