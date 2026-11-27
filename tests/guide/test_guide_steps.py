import pytest
from vocab_support import TEST_CATALOG, WITH_OLD

from growbridge.guide.steps import (
    ANSWER_MODELS,
    ANSWERED,
    DEPENDS_ON,
    MAX_BLOCKS,
    MAX_ROUNDS,
    MAX_STAGES,
    MAX_TREATMENTS,
    MAX_UNITS,
    STEPS,
    answer_problems,
    parse_answer,
)


def t(id, factors):
    return {"id": id, "name": id, "factors": factors}


def treatments(*items, control="a"):
    return parse_answer("treatments", {"treatments": list(items), "control_treatment_id": control})


def test_steps_are_in_order_and_six_have_answers():
    assert STEPS[-2:] == ("review", "round")
    assert ANSWERED == STEPS[:6] and set(ANSWER_MODELS) == set(ANSWERED)
    assert DEPENDS_ON["scale"] == {"treatments", "analysis"}


def test_a_treatment_factor_must_be_a_catalog_factor():
    answer = treatments(t("a", {"light": 40}), t("b", {"nutrient": 2}))
    assert any("nutrient" in p for p in answer_problems("treatments", answer, TEST_CATALOG))


def test_valid_treatments_have_no_problems():
    answer = treatments(t("a", {"light": 40}), t("b", {"light": 70}))
    assert answer_problems("treatments", answer, TEST_CATALOG) == ()


def test_the_control_must_be_one_of_the_treatments():
    answer = treatments(t("a", {"light": 40}), t("b", {"light": 70}), control="z")
    assert any("z" in p for p in answer_problems("treatments", answer, TEST_CATALOG))


def test_treatment_ids_are_not_repeated():
    answer = treatments(t("a", {"light": 40}), t("a", {"light": 70}))
    assert any("twice" in p for p in answer_problems("treatments", answer, TEST_CATALOG))


def test_at_least_two_treatments_are_needed():
    with pytest.raises(ValueError):
        treatments(t("a", {"light": 40}))


def test_the_primary_endpoint_must_be_a_listed_manual_variable():
    sensor = parse_answer(
        "measures", {"variables": ["air_temperature"], "primary_endpoint": "air_temperature"}
    )
    assert any("manual" in p for p in answer_problems("measures", sensor, TEST_CATALOG))
    unlisted = parse_answer(
        "measures", {"variables": ["height"], "primary_endpoint": "canopy_area_growth"}
    )
    assert any("listed" in p for p in answer_problems("measures", unlisted, TEST_CATALOG))
    fine = parse_answer(
        "measures", {"variables": ["canopy_area_growth"], "primary_endpoint": "canopy_area_growth"}
    )
    assert answer_problems("measures", fine, TEST_CATALOG) == ()


def test_variables_are_unique_and_in_the_catalog():
    answer = parse_answer(
        "measures", {"variables": ["height", "height", "nope"], "primary_endpoint": "height"}
    )
    problems = answer_problems("measures", answer, TEST_CATALOG)
    assert any("twice" in p for p in problems) and any("nope" in p for p in problems)


def test_a_deprecated_variable_an_earlier_version_declared_may_be_kept():
    raw = {
        "variables": ["canopy_growth_old", "canopy_area_growth"],
        "primary_endpoint": "canopy_area_growth",
    }
    answer = parse_answer("measures", raw)

    refused = answer_problems("measures", answer, WITH_OLD)
    kept = answer_problems("measures", answer, WITH_OLD, frozenset({"canopy_growth_old"}))

    assert any("deprecated" in p for p in refused)
    assert kept == ()


def test_a_malformed_species_is_a_problem():
    answer = parse_answer("crop", {"crop": "lettuce", "crop_taxon": "4236"})
    assert any("crop_taxon" in p for p in answer_problems("crop", answer, TEST_CATALOG))
    ok = parse_answer("crop", {"crop": "lettuce", "crop_taxon": "NCBITaxon:4236"})
    assert answer_problems("crop", ok, TEST_CATALOG) == ()


def test_steps_without_catalog_rules_have_no_problems():
    q = parse_answer("question", {"question": "Does light matter?"})
    assert answer_problems("question", q, TEST_CATALOG) == ()


def test_series_needs_blocks_and_one_unit():
    with pytest.raises(ValueError):
        parse_answer(
            "scale",
            {"layout": "series", "units": ["tent-1", "tent-2"], "blocks": 2, "stages": ["veg"]},
        )
    with pytest.raises(ValueError):
        parse_answer("scale", {"layout": "series", "units": ["tent-1"], "stages": ["veg"]})


def test_tents_need_rounds():
    with pytest.raises(ValueError):
        parse_answer("scale", {"layout": "tents", "units": ["a", "b"], "stages": ["veg"]})
    ok = parse_answer(
        "scale", {"layout": "tents", "units": ["a", "b"], "rounds": 3, "stages": ["veg"]}
    )
    assert ok.rounds == 3 and ok.experimental_unit == "tent"


def test_analysis_defaults_and_bounds():
    a = parse_answer("analysis", {"target_effect": 0.15, "method": "paired_block"})
    assert a.max_missing_fraction == 0.2 and a.max_deviation_fraction == 0.1
    assert a.script_sha256 is None
    with pytest.raises(ValueError):
        parse_answer(
            "analysis", {"target_effect": 0.1, "method": "paired_block", "max_missing_fraction": 2}
        )
    with pytest.raises(ValueError):
        parse_answer("analysis", {"target_effect": 0.1, "method": "anova"})


def test_parse_answer_rejects_unknown_fields_and_steps():
    with pytest.raises(ValueError):
        parse_answer("question", {"question": "Q", "extra": 1})
    with pytest.raises(ValueError):
        parse_answer("review", {})
    with pytest.raises(ValueError):
        parse_answer("question", {"question": ""})


# --- the caps that keep one answer from stalling the controller --------------------------------


def series(**changes):
    return {"layout": "series", "units": ["tent-1"], "blocks": 2, "stages": ["veg"], **changes}


def tents(**changes):
    return {"layout": "tents", "units": ["a", "b"], "rounds": 2, "stages": ["veg"], **changes}


def test_the_count_a_layout_asks_for_is_capped():
    assert parse_answer("scale", series(blocks=MAX_BLOCKS)).blocks == MAX_BLOCKS
    assert parse_answer("scale", tents(rounds=MAX_ROUNDS)).rounds == MAX_ROUNDS
    with pytest.raises(ValueError, match="at most"):
        parse_answer("scale", series(blocks=MAX_BLOCKS + 1))
    with pytest.raises(ValueError, match="at most"):
        parse_answer("scale", tents(rounds=MAX_ROUNDS + 1))


def test_the_count_only_a_carried_version_brings_is_capped_too():
    most = MAX_BLOCKS * MAX_TREATMENTS
    assert parse_answer("scale", series(rounds=most)).rounds == most
    with pytest.raises(ValueError, match="at most"):
        parse_answer("scale", series(rounds=most + 1))
    with pytest.raises(ValueError, match="at most"):
        parse_answer("scale", tents(blocks=MAX_ROUNDS + 1))
    with pytest.raises(ValueError):
        parse_answer("scale", tents(blocks=0))


@pytest.mark.parametrize(
    "scale",
    [
        tents(units=["a", "a"]),
        tents(units=["a", " "]),
        series(units=[""]),
        series(stages=["veg", "veg"]),
        series(stages=["veg", ""]),
    ],
)
def test_unit_and_stage_names_are_filled_in_and_distinct(scale):
    with pytest.raises(ValueError):
        parse_answer("scale", scale)


def test_units_stages_and_treatments_are_capped():
    many = [f"u{i}" for i in range(MAX_UNITS + 1)]
    with pytest.raises(ValueError):
        parse_answer("scale", tents(units=many))
    with pytest.raises(ValueError):
        parse_answer("scale", series(stages=[f"s{i}" for i in range(MAX_STAGES + 1)]))
    rows = [t(f"t{i}", {"light": i}) for i in range(MAX_TREATMENTS + 1)]
    with pytest.raises(ValueError):
        parse_answer("treatments", {"treatments": rows, "control_treatment_id": "t0"})
