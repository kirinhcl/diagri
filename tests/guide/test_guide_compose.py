import pytest
from vocab_support import TEST_CATALOG, WITH_OLD

from growbridge.archive.models import Allocation
from growbridge.guide import compose as compose_module
from growbridge.guide.compose import (
    MAX_ALLOCATIONS,
    IncompleteDraft,
    compose,
    edited_fields,
    new_protocol_id,
    next_version,
    review,
)
from growbridge.guide.draft import Chosen, carried_answers
from growbridge.guide.steps import MAX_ROUNDS, MAX_UNITS, StepId
from growbridge.planning.design import randomize_tents
from growbridge.sim.fixtures import make_protocol

KEYS = {"project_id": "project-1", "protocol_id": "protocol-1", "version": 1, "seed": 1}
REVIEW = {"catalog": TEST_CATALOG, "declared_before": frozenset()}


def chosen_from(answers: dict[StepId, dict]) -> dict[StepId, Chosen]:
    return {
        step: Chosen(step=step, answer=answer, source="carried", option_ids=(), seq=seq)
        for seq, (step, answer) in enumerate(answers.items(), start=1)
    }


def tents_scale(units, rounds=3):
    return {
        "layout": "tents",
        "units": list(units),
        "blocks": None,
        "rounds": rounds,
        "stages": ["vegetative"],
        "experimental_unit": "tent",
        "randomization_seed": None,
        "allocations": None,
    }


def with_scale(scale):
    return {**carried_answers(make_protocol()), "scale": scale}


def test_composing_the_carried_example_gives_back_the_same_protocol():
    p = make_protocol()
    composed = compose(
        chosen_from(carried_answers(p)),
        project_id=p.project_id,
        protocol_id=p.id,
        version=p.version,
        seed=1,
    )
    assert composed.digest() == p.digest()


def test_a_series_has_blocks_times_treatments_rounds():
    answers = carried_answers(make_protocol())
    # a changed count goes without the carried rounds, as the page sends it
    answers["scale"] = {**answers["scale"], "blocks": 3, "rounds": None, "randomization_seed": None}
    composed = compose(chosen_from(answers), **KEYS)
    assert composed.blocks == 3 and composed.rounds == 6
    assert len(composed.allocations) == 6 and composed.randomization_seed == 1


def test_tents_use_one_block_per_round():
    units = ["t1", "t2", "t3", "t4"]
    composed = compose(chosen_from(with_scale(tents_scale(units))), **KEYS)
    assert composed.blocks == 3 and composed.rounds == 3
    assert composed.allocations == randomize_tents(["control", "high"], units, 3, 1)


def test_the_answers_own_seed_beats_the_session_seed():
    scale = {**tents_scale(["t1", "t2"]), "randomization_seed": 77}
    composed = compose(chosen_from(with_scale(scale)), **KEYS)
    assert composed.randomization_seed == 77
    assert composed.allocations == randomize_tents(["control", "high"], ["t1", "t2"], 3, 77)


def test_hand_written_allocations_come_back_exactly():
    hand = (
        Allocation(round=1, block=1, unit="tent-1", treatment_id="control"),
        Allocation(round=2, block=1, unit="tent-1", treatment_id="high"),
        Allocation(round=3, block=2, unit="tent-1", treatment_id="control"),
        Allocation(round=4, block=2, unit="tent-1", treatment_id="high"),
    )
    # the same order in both blocks: no seed shuffles two blocks this way, so it is hand-written
    p = make_protocol(allocations=hand, randomization_seed=20261118)
    answers = carried_answers(p)
    assert answers["scale"]["allocations"] is not None
    composed = compose(chosen_from(answers), **{**KEYS, "seed": 9})
    assert composed.allocations == hand
    assert composed.digest() == p.digest()


def test_a_carried_table_that_no_longer_fits_the_scale_is_a_review_problem():
    hand = (
        Allocation(round=1, block=1, unit="tent-1", treatment_id="control"),
        Allocation(round=2, block=1, unit="tent-1", treatment_id="high"),
        Allocation(round=3, block=2, unit="tent-1", treatment_id="control"),
        Allocation(round=4, block=2, unit="tent-1", treatment_id="high"),
    )
    answers = carried_answers(make_protocol(allocations=hand, randomization_seed=20261118))
    fits = review(chosen_from(answers), **KEYS, **REVIEW)
    assert fits.protocol is not None and fits.protocol.allocations == hand
    for change in ({"blocks": 3}, {"units": ["tent-9"]}):
        stale = {**answers, "scale": {**answers["scale"], **change}}
        r = review(chosen_from(stale), **KEYS, **REVIEW)
        assert r.protocol is None and not r.ready
        assert any("no longer fits the scale" in problem for problem in r.problems)


@pytest.mark.parametrize("overrides", [{"rounds": 6}, {"rounds": 3, "blocks": 1}])
def test_a_carried_version_comes_back_with_its_own_rounds_and_blocks(overrides):
    allocations = make_protocol().allocations
    if "blocks" in overrides:  # tents: two tents side by side, three rounds in one block
        allocations = tuple(
            Allocation(round=r, block=1, unit=u, treatment_id=t)
            for r in (1, 2, 3)
            for u, t in (("tent-1", "control"), ("tent-2", "high"))
        )
    p = make_protocol(allocations=allocations, **overrides)
    composed = compose(chosen_from(carried_answers(p)), **{**KEYS, "seed": 9})
    assert (composed.rounds, composed.blocks) == (p.rounds, p.blocks)
    assert composed.digest() == p.digest()


def test_a_kept_table_with_a_make_up_round_fits_its_carried_rounds():
    hand = (
        Allocation(round=1, block=1, unit="tent-1", treatment_id="control"),
        Allocation(round=2, block=1, unit="tent-1", treatment_id="high"),
        Allocation(round=3, block=2, unit="tent-1", treatment_id="control"),
        Allocation(round=4, block=2, unit="tent-1", treatment_id="high"),
        Allocation(round=5, block=2, unit="tent-1", treatment_id="high"),  # round 4 made up
    )
    p = make_protocol(allocations=hand, rounds=5)
    r = review(chosen_from(carried_answers(p)), **KEYS, **REVIEW)
    assert r.problems == () and r.protocol is not None
    assert r.protocol.allocations == hand and r.protocol.rounds == 5


def test_a_layout_above_the_allocation_cap_is_a_review_problem_not_a_stall(monkeypatch):
    units = [f"tent-{i}" for i in range(MAX_UNITS)]
    assert MAX_ROUNDS * len(units) > MAX_ALLOCATIONS

    def refuse(*args, **kwargs):
        raise AssertionError("randomized above the allocation cap")

    monkeypatch.setattr(compose_module, "randomize_tents", refuse)
    r = review(chosen_from(with_scale(tents_scale(units, rounds=MAX_ROUNDS))), **KEYS, **REVIEW)
    assert r.protocol is None and not r.ready
    assert any(str(MAX_ALLOCATIONS) in problem for problem in r.problems)


def test_a_kept_table_above_the_allocation_cap_is_a_review_problem():
    table = [
        {"round": r, "block": r, "unit": u, "treatment_id": tid}
        for r in range(1, MAX_ROUNDS + 1)
        for u, tid in [(f"tent-{i}", ("control", "high")[i % 2]) for i in range(12)]
    ]
    scale = {**tents_scale([f"tent-{i}" for i in range(12)], MAX_ROUNDS), "allocations": table}
    r = review(chosen_from(with_scale(scale)), **KEYS, **REVIEW)
    assert r.protocol is None
    assert any(str(MAX_ALLOCATIONS) in problem for problem in r.problems)


def test_a_missing_step_is_named():
    answers = carried_answers(make_protocol())
    del answers["scale"]
    with pytest.raises(IncompleteDraft) as e:
        compose(chosen_from(answers), **KEYS)
    assert e.value.missing == ("scale",)


def test_missing_steps_come_in_step_order():
    answers = carried_answers(make_protocol())
    del answers["analysis"], answers["crop"]
    with pytest.raises(IncompleteDraft) as e:
        compose(chosen_from(answers), **KEYS)
    assert e.value.missing == ("crop", "analysis")


def test_new_protocol_ids_match_the_web_form():
    assert new_protocol_id("project-abcdef123456", taken=[], count=0) == "protocol-1-123456"
    taken = ["protocol-2-123456"]
    assert new_protocol_id("project-abcdef123456", taken=taken, count=1) == "protocol-3-123456"


def test_next_version_follows_the_highest_saved():
    assert next_version([]) == 1
    assert next_version([1, 3, 2]) == 4


def test_review_is_ready_for_a_complete_valid_draft():
    r = review(chosen_from(carried_answers(make_protocol())), **KEYS, **REVIEW)
    assert r.ready and r.protocol is not None and not r.missing and not r.problems


def test_review_names_a_missing_step_without_a_protocol():
    answers = carried_answers(make_protocol())
    del answers["measures"]
    r = review(chosen_from(answers), **KEYS, **REVIEW)
    assert not r.ready and r.protocol is None and r.missing == ("measures",)


def test_review_lists_catalog_problems_instead_of_failing():
    answers = carried_answers(make_protocol())
    answers["measures"] = {
        "variables": ["canopy_growth_old"],
        "primary_endpoint": "canopy_growth_old",
    }
    r = review(chosen_from(answers), **KEYS, catalog=WITH_OLD, declared_before=frozenset())
    assert not r.ready and r.protocol is not None
    assert any("canopy_growth_old" in problem for problem in r.problems)


def test_review_reports_a_layout_that_cannot_be_randomized():
    r = review(chosen_from(with_scale(tents_scale(["t1", "t2", "t3"]))), **KEYS, **REVIEW)
    assert not r.ready and r.protocol is None and r.problems


def test_review_reports_a_bad_taxon_once():
    answers = carried_answers(make_protocol())
    answers["crop"] = {**answers["crop"], "crop_taxon": "lettuce"}
    r = review(chosen_from(answers), **KEYS, **REVIEW)
    assert not r.ready and len([p for p in r.problems if "crop_taxon" in p]) == 1


def test_review_refuses_what_the_save_route_refuses():
    r = review(chosen_from(carried_answers(make_protocol())), **{**KEYS, "version": 0}, **REVIEW)
    assert not r.ready and r.protocol is None and r.problems


def test_edited_fields_name_what_changed():
    p = make_protocol()
    assert edited_fields(p, p) == ()
    assert edited_fields(p, p.model_copy(update={"question": "other"})) == ("question",)
    changed = p.model_copy(
        update={"analysis": p.analysis.model_copy(update={"target_effect": 0.3})}
    )
    assert edited_fields(p, changed) == ("analysis.target_effect",)
