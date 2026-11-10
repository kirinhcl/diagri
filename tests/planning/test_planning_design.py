import math
import random
from collections import Counter
from statistics import NormalDist

import pytest

from growbridge.archive.models import Allocation, Treatment
from growbridge.planning.design import (
    check_experimental_design,
    estimate_sample_size,
    make_up_allocation,
    randomize_series,
    randomize_tents,
)
from growbridge.sim.fixtures import make_protocol

TREATMENTS = ("control", "high", "mid")


def alloc(round_, block, treatment, unit="tent-1"):
    return Allocation(round=round_, block=block, unit=unit, treatment_id=treatment)


def protocol_with(allocations, **fields):
    rounds = len({a.round for a in allocations})
    blocks = len({a.block for a in allocations})
    return make_protocol(allocations=tuple(allocations), rounds=rounds, blocks=blocks, **fields)


def codes(findings, *, blocking=None):
    return [f.code for f in findings if blocking is None or f.blocking is blocking]


def paired_n(effect, sd, alpha=0.05, power=0.8):
    z = NormalDist().inv_cdf
    return ((z(1 - alpha / 2) + z(power)) * sd / effect) ** 2


# --- randomize_series ---------------------------------------------------------------------------


def test_series_each_block_has_each_treatment_once():
    result = randomize_series(TREATMENTS, blocks=4, seed=1)
    assert len(result) == 12
    for block in range(1, 5):
        in_block = [a.treatment_id for a in result if a.block == block]
        assert sorted(in_block) == sorted(TREATMENTS)


def test_series_rounds_are_consecutive_and_unit_is_set():
    result = randomize_series(TREATMENTS, blocks=2, seed=1, unit="tent-9")
    assert [a.round for a in result] == [1, 2, 3, 4, 5, 6]
    assert {a.unit for a in result} == {"tent-9"}
    assert [a.block for a in result] == [1, 1, 1, 2, 2, 2]


def test_series_same_seed_same_result_different_seed_differs():
    first = randomize_series(TREATMENTS, blocks=6, seed=42)
    assert first == randomize_series(TREATMENTS, blocks=6, seed=42)
    assert first != randomize_series(TREATMENTS, blocks=6, seed=43)


def test_series_does_not_depend_on_global_random_state():
    random.seed(1)
    first = randomize_series(TREATMENTS, blocks=3, seed=7)
    random.seed(999)
    assert first == randomize_series(TREATMENTS, blocks=3, seed=7)


@pytest.mark.parametrize("treatments,blocks", [((), 2), (("a", "a"), 2), (("a", "b"), 0)])
def test_series_rejects_bad_arguments(treatments, blocks):
    with pytest.raises(ValueError):
        randomize_series(treatments, blocks=blocks, seed=1)


# --- randomize_tents ----------------------------------------------------------------------------


def test_tents_each_round_assigns_every_treatment_to_distinct_tents():
    units = ("tent-1", "tent-2", "tent-3")
    result = randomize_tents(TREATMENTS, units, rounds=5, seed=3)
    assert len(result) == 15
    for round_ in range(1, 6):
        in_round = [a for a in result if a.round == round_]
        assert sorted(a.treatment_id for a in in_round) == sorted(TREATMENTS)
        assert sorted(a.unit for a in in_round) == sorted(units)
        assert {a.block for a in in_round} == {round_}


def test_tents_are_reproducible_and_vary_by_seed():
    units = ("tent-1", "tent-2")
    first = randomize_tents(("a", "b"), units, rounds=8, seed=5)
    assert first == randomize_tents(("a", "b"), units, rounds=8, seed=5)
    assert first != randomize_tents(("a", "b"), units, rounds=8, seed=6)


def test_tents_more_tents_than_treatments_stays_balanced():
    units = ("t1", "t2", "t3", "t4")
    result = randomize_tents(("a", "b"), units, rounds=2, seed=1)
    for round_ in (1, 2):
        counts = Counter(a.treatment_id for a in result if a.round == round_)
        assert counts == {"a": 2, "b": 2}


@pytest.mark.parametrize("units", [(), ("t1", "t2", "t3")])
def test_tents_reject_units_that_cannot_balance(units):
    with pytest.raises(ValueError):
        randomize_tents(("a", "b"), units, rounds=2, seed=1)


# --- make_up_allocation -------------------------------------------------------------------------


def test_make_up_repeats_same_block_treatment_with_new_round():
    result = make_up_allocation(make_protocol(), failed_round=2)
    assert result == Allocation(round=5, block=1, unit="tent-1", treatment_id="control")


def test_make_up_numbers_after_existing_make_ups():
    protocol = make_protocol()
    extra = protocol.allocations + (make_up_allocation(protocol, 1),)
    protocol = protocol.model_copy(update={"allocations": extra})
    assert make_up_allocation(protocol, 3).round == 6


def test_make_up_leaves_protocol_untouched_and_rejects_unknown_round():
    protocol = make_protocol()
    before = protocol.digest()
    make_up_allocation(protocol, 1)
    assert protocol.digest() == before
    with pytest.raises(ValueError):
        make_up_allocation(protocol, 99)


# --- check_experimental_design ------------------------------------------------------------------


def test_fixture_protocol_has_no_blocking_findings():
    assert codes(check_experimental_design(make_protocol()), blocking=True) == []


def test_generated_allocations_pass_and_match_seed():
    allocations = randomize_series(("control", "high"), blocks=3, seed=11)
    findings = check_experimental_design(protocol_with(allocations, randomization_seed=11))
    assert codes(findings) == []


def test_all_rounds_same_treatment_is_no_replication():
    allocations = [alloc(i, 1 + (i - 1) // 2, "high") for i in range(1, 5)]
    findings = check_experimental_design(protocol_with(allocations))
    assert "no_replication" in codes(findings, blocking=True)


def test_single_run_per_treatment_is_no_replication():
    allocations = [alloc(1, 1, "control"), alloc(2, 1, "high")]
    assert "no_replication" in codes(check_experimental_design(protocol_with(allocations)))


def test_all_of_a_then_all_of_b_is_confounded_with_time():
    allocations = [
        alloc(1, 1, "control"),
        alloc(2, 1, "control"),
        alloc(3, 2, "high"),
        alloc(4, 2, "high"),
    ]
    findings = check_experimental_design(protocol_with(allocations))
    assert "confounded_with_time" in codes(findings, blocking=True)


def test_alternating_order_is_not_confounded():
    allocations = [
        alloc(1, 1, "control"),
        alloc(2, 1, "high"),
        alloc(3, 2, "control"),
        alloc(4, 2, "high"),
    ]
    findings = check_experimental_design(protocol_with(allocations))
    assert "confounded_with_time" not in codes(findings)


def test_parallel_tents_in_same_round_are_not_confounded_with_time():
    allocations = randomize_tents(("control", "high"), ("t1", "t2"), rounds=3, seed=2)
    findings = check_experimental_design(protocol_with(allocations))
    assert codes(findings, blocking=True) == []


def test_block_missing_a_treatment_is_unbalanced():
    allocations = [
        alloc(1, 1, "control"),
        alloc(2, 1, "control"),
        alloc(3, 2, "high"),
        alloc(4, 2, "control"),
        alloc(5, 3, "high"),
        alloc(6, 3, "control"),
        alloc(7, 4, "control"),
        alloc(8, 4, "high"),
    ]
    findings = check_experimental_design(protocol_with(allocations))
    unbalanced = [f for f in findings if f.code == "unbalanced_block"]
    assert unbalanced
    assert unbalanced[0].blocking
    assert "block 1" in unbalanced[0].message


def test_unknown_treatment_in_allocation_blocks():
    allocations = [*make_protocol().allocations, alloc(5, 3, "ghost")]
    findings = check_experimental_design(protocol_with(allocations))
    assert "unknown_treatment" in codes(findings, blocking=True)


def test_control_not_among_treatments_is_missing_control():
    protocol = make_protocol(control_treatment_id="placebo")
    assert "missing_control" in codes(check_experimental_design(protocol), blocking=True)


def test_control_never_allocated_is_missing_control():
    treatments = (*make_protocol().treatments, Treatment(id="extra", name="x"))
    protocol = make_protocol(treatments=treatments, control_treatment_id="extra")
    assert "missing_control" in codes(check_experimental_design(protocol), blocking=True)


def test_seed_mismatch_is_reported_when_allocations_do_not_follow_the_seed():
    allocations = randomize_series(("control", "high"), blocks=12, seed=11)
    findings = check_experimental_design(protocol_with(allocations, randomization_seed=12))
    assert codes(findings).count("seed_mismatch") == 1


def test_seed_check_ignores_make_up_rounds():
    base = protocol_with(
        randomize_series(("control", "high"), blocks=3, seed=11), randomization_seed=11
    )
    extra = (*base.allocations, make_up_allocation(base, 2))
    protocol = base.model_copy(update={"allocations": extra})
    assert "seed_mismatch" not in codes(check_experimental_design(protocol))


# --- estimate_sample_size -----------------------------------------------------------------------


def test_sample_size_paired_adds_small_sample_correction():
    z = NormalDist().inv_cdf(0.975)
    expected = math.ceil(paired_n(0.5, 1.0) + z**2 / 2)
    assert estimate_sample_size(effect=0.5, sd=1.0) == expected == 34


def test_sample_size_paired_floor_matches_permutation_test_resolution():
    assert estimate_sample_size(effect=1.0, sd=0.3, alpha=0.05) >= 6
    assert estimate_sample_size(effect=1.0, sd=0.3, alpha=0.01) >= 8
    assert estimate_sample_size(effect=100.0, sd=0.1, alpha=0.05) == 6


def test_sample_size_two_group_is_twice_paired_per_group():
    paired = estimate_sample_size(0.5, 1.0, design="paired_block")
    two_group = estimate_sample_size(0.5, 1.0, design="two_group")
    assert two_group == math.ceil(2 * paired_n(0.5, 1.0))
    assert two_group > paired


def test_two_group_sample_size_has_floor_of_two():
    assert estimate_sample_size(effect=100.0, sd=0.1, design="two_group") == 2


def test_sample_size_monotone_in_effect_and_sd():
    sizes = [estimate_sample_size(e, 1.0) for e in (0.2, 0.4, 0.8, 1.6, 3.2)]
    assert sizes == sorted(sizes, reverse=True)
    sizes = [estimate_sample_size(1.0, s) for s in (0.1, 0.3, 0.6, 1.0, 2.0)]
    assert sizes == sorted(sizes)


def test_sample_size_monotonic_in_inputs():
    base = estimate_sample_size(0.5, 1.0)
    assert estimate_sample_size(0.5, 2.0) > base
    assert estimate_sample_size(0.5, 1.0, power=0.9) > base
    assert estimate_sample_size(1.0, 1.0) < base
    assert estimate_sample_size(0.5, 1.0, alpha=0.01) > base


@pytest.mark.parametrize(
    "kwargs",
    [
        {"effect": 0, "sd": 1},
        {"effect": -1, "sd": 1},
        {"effect": 1, "sd": 0},
        {"effect": 1, "sd": 1, "alpha": 0},
        {"effect": 1, "sd": 1, "alpha": 1},
        {"effect": 1, "sd": 1, "power": 1},
        {"effect": 1, "sd": 1, "power": 0},
    ],
)
def test_sample_size_rejects_invalid_inputs(kwargs):
    with pytest.raises(ValueError):
        estimate_sample_size(**kwargs)


# --- failed rounds ------------------------------------------------------------------------------


def _with_make_up():
    base = make_protocol()
    extra = (*base.allocations, make_up_allocation(base, 2))
    return base.model_copy(update={"allocations": extra, "rounds": 5})


def test_make_up_without_declaring_failed_round_is_unbalanced():
    assert "unbalanced_block" in codes(check_experimental_design(_with_make_up()), blocking=True)


def test_make_up_with_failed_round_declared_has_no_blocking_finding():
    findings = check_experimental_design(_with_make_up(), failed_rounds=[2])
    assert codes(findings, blocking=True) == []
    assert "seed_mismatch" not in codes(findings)


def test_failed_round_is_ignored_for_replication():
    allocations = [alloc(1, 1, "control"), alloc(2, 1, "high"), alloc(3, 1, "high")]
    findings = check_experimental_design(protocol_with(allocations), failed_rounds={3})
    assert "no_replication" in codes(findings)
