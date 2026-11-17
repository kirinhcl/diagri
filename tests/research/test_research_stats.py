import pytest

from growbridge.archive.models import Allocation, ManualMeasurement
from growbridge.research.stats import paired_block_estimate, unit_means, unit_table
from growbridge.sim.fixtures import make_protocol

METRIC = "canopy_area_growth"
ROUND_OF = {"exp-1": 1, "exp-2": 2, "exp-3": 3, "exp-4": 4}


def measurement(index: int, experiment: str, plant: str, value: float, **extra):
    fields = {
        "id": f"m{index}",
        "experiment_id": experiment,
        "batch": "batch-1",
        "plant_id": plant,
        "layout_version": "v1",
        "measured_at": 1_800_000_000.0 + index,
        "position": "tent-1",
        "method": "ruler",
        "metric": METRIC,
        "value": value,
        "unit": "cm2",
        "operator": "op",
    }
    return ManualMeasurement(**{**fields, **extra})


def series(high: float, control: float, plants: int = 1, days: int = 1):
    rows = []
    index = 0
    for experiment, value in (
        ("exp-1", high),
        ("exp-2", control),
        ("exp-3", control + 0.2),
        ("exp-4", high + 0.2),
    ):
        for plant in range(plants):
            for _day in range(days):
                index += 1
                rows.append(measurement(index, experiment, f"p{plant}", value))
    return rows


def test_unit_means_collapse_plants_and_days_into_one_value_per_unit():
    protocol = make_protocol()

    single = unit_means(series(2.0, 1.0), protocol.allocations, METRIC, ROUND_OF)
    many = unit_means(series(2.0, 1.0, plants=6, days=5), protocol.allocations, METRIC, ROUND_OF)

    assert set(many) == set(single)
    for key, value in single.items():
        assert abs(many[key] - value) < 1e-9
    assert set(single) == {(1, "high"), (1, "control"), (2, "control"), (2, "high")}
    assert abs(single[(2, "control")] - 1.2) < 1e-9


def test_unit_means_ignore_other_metrics_unknown_rounds_and_corrected_records():
    protocol = make_protocol()
    rows = [
        measurement(1, "exp-1", "p0", 5.0),
        measurement(2, "exp-1", "p0", 3.0, corrects="m1"),
        measurement(3, "exp-1", "p0", 99.0, metric="height"),
        measurement(4, "exp-9", "p0", 99.0),
    ]

    result = unit_means(rows, protocol.allocations, METRIC, ROUND_OF)

    assert result == {(1, "high"): 3.0}


def test_unit_means_separate_units_in_the_same_round_by_position():
    allocations = (
        Allocation(round=1, block=1, unit="tent-1", treatment_id="high"),
        Allocation(round=1, block=1, unit="tent-2", treatment_id="control"),
    )
    rows = [
        measurement(1, "exp-1", "p0", 4.0, position="tent-1"),
        measurement(2, "exp-1", "p0", 2.0, position="tent-2"),
    ]

    result = unit_means(rows, allocations, METRIC, {"exp-1": 1})

    assert result == {(1, "high"): 4.0, (1, "control"): 2.0}


def test_protocol_data_yields_a_treatment_effect():
    protocol = make_protocol()
    values = unit_means(series(2.0, 1.0), protocol.allocations, METRIC, ROUND_OF)

    estimate = paired_block_estimate(values, "control", "high")

    assert estimate.estimable is True
    assert estimate.blocks == 2
    assert abs(estimate.effect - 1.0) < 1e-9
    assert estimate.p_value == 0.5  # two blocks: the smallest possible exact p


def test_exact_permutation_p_value_with_five_consistent_blocks():
    values = {}
    for block in range(1, 6):
        values[(block, "control")] = 1.0
        values[(block, "high")] = 1.0 + block
    estimate = paired_block_estimate(values, "control", "high")

    assert estimate.p_value == 2 / 32


def test_single_block_is_not_estimable():
    estimate = paired_block_estimate({(1, "control"): 1.0, (1, "high"): 2.0}, "control", "high")

    assert estimate.estimable is False
    assert estimate.p_value is None
    assert estimate.note


def test_blocks_missing_an_arm_are_dropped():
    values = {(1, "control"): 1.0, (1, "high"): 2.0, (2, "high"): 3.0}

    estimate = paired_block_estimate(values, "control", "high")

    assert estimate.blocks == 1
    assert estimate.estimable is False


def test_empty_values_are_not_estimable():
    estimate = paired_block_estimate({}, "control", "high")

    assert estimate.estimable is False
    assert estimate.blocks == 0


def test_sampled_p_value_is_never_zero_with_many_blocks():
    values = {}
    for block in range(1, 26):
        values[(block, "control")] = 1.0
        values[(block, "high")] = 2.0 + block

    estimate = paired_block_estimate(values, "control", "high")

    assert estimate.p_value is not None
    assert estimate.p_value > 0
    assert estimate.note


def test_failed_rounds_are_excluded_so_a_makeup_round_is_not_averaged_with_them():
    allocations = (
        Allocation(round=1, block=1, unit="tent-1", treatment_id="high"),
        Allocation(round=2, block=1, unit="tent-1", treatment_id="control"),
        Allocation(round=5, block=1, unit="tent-1", treatment_id="high"),  # make-up for 1
    )
    rows = [
        measurement(1, "exp-1", "p0", 100.0),
        measurement(2, "exp-2", "p0", 1.0),
        measurement(3, "exp-5", "p0", 2.0),
    ]
    round_of = {"exp-1": 1, "exp-2": 2, "exp-5": 5}

    table = unit_table(rows, allocations, METRIC, round_of, failed_rounds={1})

    assert table.values == {(1, "control"): 1.0, (1, "high"): 2.0}
    assert table.excluded == ("m1",)
    assert table.dropped == ()
    assert unit_means(rows, allocations, METRIC, round_of, failed_rounds={1}) == table.values


def test_unmappable_measurements_are_reported_not_silently_dropped():
    protocol = make_protocol()
    rows = [measurement(1, "exp-1", "p0", 1.0), measurement(2, "exp-9", "p0", 5.0)]

    table = unit_table(rows, protocol.allocations, METRIC, ROUND_OF)

    assert table.dropped == ("m2",)
    assert table.values == {(1, "high"): 1.0}


def test_mixed_units_for_the_metric_are_refused():
    protocol = make_protocol()
    rows = [
        measurement(1, "exp-1", "p0", 1.0, unit="cm2"),
        measurement(2, "exp-1", "p1", 100.0, unit="mm2"),
    ]

    with pytest.raises(ValueError, match="units"):
        unit_means(rows, protocol.allocations, METRIC, ROUND_OF)


def test_units_of_other_metrics_do_not_matter():
    protocol = make_protocol()
    rows = [
        measurement(1, "exp-1", "p0", 1.0),
        measurement(2, "exp-1", "p0", 9.0, metric="h", unit="cm"),
    ]

    assert unit_means(rows, protocol.allocations, METRIC, ROUND_OF) == {(1, "high"): 1.0}


def test_an_estimate_with_too_few_blocks_carries_a_note_code():
    estimate = paired_block_estimate({(1, "control"): 1.0, (1, "high"): 2.0}, "control", "high")

    assert estimate.note_code == "too_few_blocks"
    assert estimate.note_params == {"blocks": 1, "min_blocks": 2}
    assert estimate.note.startswith("fewer than 2 complete blocks")


def test_a_sampled_estimate_names_its_flips_and_exact_has_no_code():
    values = {}
    for block in range(1, 26):
        values[(block, "control")] = 1.0
        values[(block, "high")] = 2.0 + block
    sampled = paired_block_estimate(values, "control", "high")
    exact = paired_block_estimate(
        {(1, "control"): 1.0, (1, "high"): 2.0, (2, "control"): 1.0, (2, "high"): 3.0},
        "control",
        "high",
    )

    assert sampled.note_code == "sampled_p"
    assert sampled.note_params == {"flips": 20_000, "blocks": 25}
    assert exact.note_code == "" and exact.note_params == {} and exact.note == ""
