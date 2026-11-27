from datetime import date

from vocab_support import TEST_CATALOG

from growbridge.guide.crops import CHECKED_ON, CROPS
from growbridge.guide.options import option_in_answer, options_for
from growbridge.guide.steps import STEPS
from growbridge.vocab.curie import taxon_problems


def test_every_crop_has_a_well_formed_species_and_a_unique_key():
    assert all(taxon_problems(c.taxon, "") == [] for c in CROPS)
    assert len({c.key for c in CROPS}) == len(CROPS)
    assert date.fromisoformat(CHECKED_ON)


def test_crop_options_carry_the_species_the_protocol_needs():
    o = options_for("crop", TEST_CATALOG, 7)
    assert [x.id for x in o.options] == [c.key for c in CROPS]
    lettuce = next(x for x in o.options if x.id == "lettuce")
    assert lettuce.value == {"crop": "Lettuce", "crop_taxon": "NCBITaxon:4236"}
    assert lettuce.label_zh == "生菜"
    assert o.defaults == {}


def test_treatment_options_are_the_catalog_factors_that_are_not_deprecated():
    o = options_for("treatments", TEST_CATALOG, 7)
    ids = {x.id for x in o.options}
    assert ids == {v.id for v in TEST_CATALOG.variables if v.kind == "factor" and not v.deprecated}
    assert ids
    first = o.options[0]
    variable = TEST_CATALOG.get(first.id)
    assert first.value == {"factor": first.id, "unit": variable.unit}
    assert (first.label_en, first.label_zh) == (variable.label_en, variable.label_zh)


def test_measure_options_leave_out_factors():
    o = options_for("measures", TEST_CATALOG, 7)
    expected = [
        v.id for v in TEST_CATALOG.variables if v.kind in ("sensor", "manual") and not v.deprecated
    ]
    assert [x.id for x in o.options] == expected
    assert all(x.value["kind"] in ("sensor", "manual") for x in o.options)
    first = o.options[0]
    variable = TEST_CATALOG.get(first.id)
    assert first.value == {"variable": first.id, "kind": variable.kind, "unit": variable.unit}


def test_analysis_offers_two_methods_and_the_default_thresholds():
    o = options_for("analysis", TEST_CATALOG, 7)
    assert [x.id for x in o.options] == ["paired_block", "two_group"]
    assert [x.value for x in o.options] == [{"method": "paired_block"}, {"method": "two_group"}]
    assert o.defaults == {"max_missing_fraction": 0.2, "max_deviation_fraction": 0.1}


def test_scale_offers_the_session_seed():
    o = options_for("scale", TEST_CATALOG, 42)
    assert [x.id for x in o.options] == ["series", "tents"]
    assert [x.value for x in o.options] == [{"layout": "series"}, {"layout": "tents"}]
    assert o.defaults == {"randomization_seed": 42, "experimental_unit": "tent"}


def test_steps_without_choices_offer_nothing():
    for step in ("question", "review", "round"):
        o = options_for(step, TEST_CATALOG, 7)
        assert (o.step, o.options, o.defaults) == (step, (), {})


def offered(step, option_id):
    return next(o for o in options_for(step, TEST_CATALOG, 7).options if o.id == option_id)


def rows(*factors):
    return {"treatments": [{"id": f"t{i}", "factors": f} for i, f in enumerate(factors)]}


def test_a_picked_option_is_in_the_answer_only_with_its_value():
    lettuce = offered("crop", "lettuce")
    assert option_in_answer("crop", lettuce, {"crop": "Lettuce", "crop_taxon": "NCBITaxon:4236"})
    assert not option_in_answer("crop", lettuce, {"crop": "Lettuce", "crop_taxon": "NCBITaxon:1"})
    assert not option_in_answer("crop", lettuce, {"crop": "Rocket", "crop_taxon": "NCBITaxon:4236"})
    light = offered("treatments", "light")
    assert option_in_answer("treatments", light, rows({"light": 40}, {"light": 70, "co2": 1}))
    assert not option_in_answer("treatments", light, rows({"light": 40}, {"co2": 1}))
    endpoint = offered("measures", "canopy_area_growth")
    assert option_in_answer("measures", endpoint, {"variables": ["canopy_area_growth"]})
    assert not option_in_answer("measures", endpoint, {"variables": ["air_temperature"]})
    assert option_in_answer("analysis", offered("analysis", "two_group"), {"method": "two_group"})
    assert not option_in_answer("analysis", offered("analysis", "two_group"), {"method": "x"})
    assert option_in_answer("scale", offered("scale", "tents"), {"layout": "tents"})
    assert not option_in_answer("scale", offered("scale", "tents"), {"layout": "series"})
    assert not option_in_answer("question", lettuce, {"question": "Q"})


def test_options_are_a_pure_function_and_never_mention_ai():
    for step in STEPS:
        assert options_for(step, TEST_CATALOG, 3) == options_for(step, TEST_CATALOG, 3)
        assert "AI" not in options_for(step, TEST_CATALOG, 3).model_dump_json()
