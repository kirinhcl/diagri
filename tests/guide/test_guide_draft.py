from growbridge.archive.models import Allocation, AnalysisPlan
from growbridge.guide import draft
from growbridge.guide.draft import carried_answers, latest_chosen, step_states
from growbridge.guide.steps import MAX_BLOCKS
from growbridge.guide.store import GuideEvent
from growbridge.planning.design import randomize_series
from growbridge.sim.fixtures import make_protocol

ANSWERS = {
    "question": {"question": "Q"},
    "crop": {"crop": "lettuce", "crop_taxon": "NCBITaxon:4236"},
    "treatments": {"treatments": [], "control_treatment_id": "a"},
    "measures": {"variables": ["height"], "primary_endpoint": "height"},
    "analysis": {"target_effect": 0.1, "method": "paired_block"},
    "scale": {"layout": "series", "units": ["tent-1"], "blocks": 2, "stages": ["veg"]},
}


def events_choosing(*steps):
    return tuple(
        GuideEvent(
            session_id="s",
            seq=seq,
            step=step,
            kind="chosen",
            payload={"answer": {**ANSWERS[step], "n": seq}, "source": "own", "option_ids": []},
            actor="alice",
            at=float(seq),
        )
        for seq, step in enumerate(steps, start=1)
    )


def states(*steps):
    return {s.step: s.status for s in step_states(events_choosing(*steps))}


def test_the_latest_choice_of_a_step_wins():
    chosen = latest_chosen(events_choosing("question", "crop", "question"))
    assert chosen["question"].seq == 3 and chosen["question"].answer["n"] == 3
    assert chosen["crop"].seq == 2 and chosen["crop"].source == "own"


def test_other_event_kinds_are_not_choices():
    event = GuideEvent(
        session_id="s", seq=1, step="question", kind="offered", payload={}, actor="a", at=1.0
    )
    assert latest_chosen((event,)) == {}


def test_a_step_without_a_choice_is_pending():
    result = step_states(events_choosing("question"))
    assert [s.step for s in result] == [
        "question",
        "crop",
        "treatments",
        "measures",
        "analysis",
        "scale",
    ]
    assert result[0].status == "done" and result[0].chosen.seq == 1
    assert result[1].status == "pending" and result[1].chosen is None


def test_changing_treatments_after_analysis_marks_analysis_and_scale_for_review():
    result = states("treatments", "measures", "analysis", "scale", "treatments")
    assert result["analysis"] == "needs_review" and result["scale"] == "needs_review"
    assert result["measures"] == "done" and result["treatments"] == "done"


def test_review_is_transitive_through_a_reviewed_step():
    result = states("treatments", "measures", "analysis", "scale", "measures")
    assert result["analysis"] == "needs_review" and result["scale"] == "needs_review"


def test_rechoosing_a_dependent_step_clears_its_review():
    result = states("treatments", "measures", "analysis", "scale", "treatments", "analysis")
    assert result["analysis"] == "done" and result["scale"] == "needs_review"
    result = states(
        "treatments", "measures", "analysis", "scale", "treatments", "analysis", "scale"
    )
    assert result["scale"] == "done"


def test_reopening_does_not_change_status():
    reopened = GuideEvent(
        session_id="s", seq=9, step="treatments", kind="reopened", payload={}, actor="a", at=9.0
    )
    events = (*events_choosing("treatments", "measures", "analysis"), reopened)
    assert all(s.status != "needs_review" for s in step_states(events))


def test_carried_answers_reproduce_the_example_protocol_as_a_series():
    p = make_protocol()
    carried = carried_answers(p)
    scale = carried["scale"]
    assert scale["layout"] == "series" and scale["blocks"] == 2 and scale["rounds"] == 4
    assert scale["units"] == ["tent-1"] and scale["randomization_seed"] == 20261118
    assert scale["allocations"] is None  # the seed reproduces these allocations
    assert carried["question"] == {"question": p.question, "hypothesis": p.hypothesis}
    assert carried["crop"]["crop_taxon"] == "NCBITaxon:4236"
    assert carried["treatments"]["control_treatment_id"] == "control"
    assert carried["treatments"]["treatments"][0]["factors"] == {"light": 40}
    assert carried["measures"] == {
        "variables": ["canopy_area_growth"],
        "primary_endpoint": "canopy_area_growth",
    }
    assert carried["analysis"]["method"] == "paired_block"
    assert carried["analysis"]["script_sha256"] is None


def test_carried_scale_keeps_hand_written_allocations():
    hand = tuple(
        Allocation(round=r, block=b, unit="tent-1", treatment_id=tid)
        for r, b, tid in [(1, 1, "control"), (2, 1, "high"), (3, 2, "control"), (4, 2, "high")]
    )
    p = make_protocol(allocations=hand)
    carried = carried_answers(p)
    assert carried["scale"]["allocations"] == [a.model_dump(mode="json") for a in p.allocations]


def test_carried_tents_layout_lists_units_by_first_appearance():
    allocations = tuple(
        Allocation(round=1, block=1, unit=u, treatment_id=tid)
        for u, tid in [("tent-b", "control"), ("tent-a", "high")]
    )
    p = make_protocol(allocations=allocations, rounds=1, blocks=1)
    scale = carried_answers(p)["scale"]
    assert scale["layout"] == "tents" and scale["blocks"] == 1 and scale["rounds"] == 1
    assert scale["units"] == ["tent-b", "tent-a"]


def test_a_carried_scale_keeps_both_counts_exactly():
    scale = carried_answers(make_protocol(rounds=6))["scale"]
    assert (scale["blocks"], scale["rounds"]) == (2, 6)
    assert scale["allocations"] is None  # the seed still reproduces the allocations


def test_carried_analysis_keeps_the_script_hash():
    plan = AnalysisPlan(
        primary_endpoint="canopy_area_growth",
        target_effect=0.2,
        method="two_group",
        script_sha256="ab" * 32,
    )
    assert carried_answers(make_protocol(analysis=plan))["analysis"]["script_sha256"] == "ab" * 32


def test_a_carried_version_above_the_caps_is_not_randomized_again(monkeypatch):
    blocks = MAX_BLOCKS + 1
    made = randomize_series(["control", "high"], blocks, 7, "tent-1")
    p = make_protocol(allocations=made, randomization_seed=7, blocks=blocks, rounds=2 * blocks)

    def refuse(*args, **kwargs):
        raise AssertionError("randomized a carried version above the caps")

    monkeypatch.setattr(draft, "randomize_series", refuse)
    monkeypatch.setattr(draft, "randomize_tents", refuse)
    scale = carried_answers(p)["scale"]
    assert scale["allocations"] == [a.model_dump(mode="json") for a in made]
