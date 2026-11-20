from vocab_support import WITH_OLD

from growbridge.archive.models import ApplicabilityRange, EvidenceCard
from growbridge.vocab import packaged_catalog
from growbridge.vocab.card_checks import card_problems, with_catalog_unit

CATALOG = packaged_catalog()


def card(**fields) -> EvidenceCard:
    return EvidenceCard(id="ev-1", source_class="paper", citation="Doe 2024", claim="c", **fields)


def test_a_card_without_the_new_fields_has_no_problems():
    assert card_problems(card(value=200.0, unit="umol m-2 s-1"), CATALOG) == []


def test_an_alias_is_refused_with_the_standard_id():
    assert card_problems(card(variable="temp"), CATALOG) == [
        "variable temp is an alias: use the standard ID air_temperature"
    ]


def test_a_deprecated_variable_is_refused_with_its_replacement():
    assert card_problems(card(variable="canopy_growth_old"), WITH_OLD) == [
        "variable canopy_growth_old is deprecated: use canopy_area_growth"
    ]


def test_a_factor_variable_is_refused():
    assert card_problems(card(variable="light"), CATALOG) == [
        "variable light is a factor: its levels are not comparable across sources"
    ]


def test_a_value_with_a_variable_needs_the_catalog_unit():
    assert card_problems(card(variable="air_temperature", value=24.0, unit="C"), CATALOG) == []
    assert card_problems(card(variable="air_temperature", value=24.0, unit="K"), CATALOG) == [
        "unit K is not the catalog unit Cel of air_temperature"
    ]
    assert card_problems(card(variable="air_temperature", value=24.0), CATALOG) == [
        "a value of air_temperature needs its unit Cel"
    ]
    fixed = with_catalog_unit(card(variable="air_temperature", value=24.0, unit="C"), CATALOG)
    assert fixed.unit == "Cel"


def test_conditions_follow_the_catalog():
    rng = ApplicabilityRange
    assert card_problems(
        card(conditions=(rng(variable="air_relative_humidity", min=80, max=70),)), CATALOG
    ) == ["condition air_relative_humidity: min 80 is above max 70"]
    assert card_problems(
        card(conditions=(rng(variable="air_relative_humidity", max=120),)), CATALOG
    ) == ["condition air_relative_humidity: 120 is outside 0–100"]
    assert card_problems(card(conditions=(rng(variable="air_temperature"),)), CATALOG) == [
        "condition air_temperature: give min, max or both"
    ]
    two = (rng(variable="air_temperature", min=18), rng(variable="temp", max=26))
    problems = card_problems(card(conditions=two), CATALOG)
    assert (
        "condition temp: variable temp is an alias: use the standard ID air_temperature" in problems
    )
    nine = tuple(rng(variable="air_temperature", min=i) for i in range(9))
    assert "at most 8 conditions" in card_problems(card(conditions=nine), CATALOG)


def test_a_condition_variable_appears_only_once():
    rng = ApplicabilityRange
    twice = (rng(variable="air_temperature", min=18), rng(variable="air_temperature", max=26))
    assert card_problems(card(conditions=twice), CATALOG) == [
        "condition air_temperature: a condition variable appears only once"
    ]
    via_alias = (rng(variable="air_temperature", min=18), rng(variable="temp", max=26))
    assert "condition temp: a condition variable appears only once" in card_problems(
        card(conditions=via_alias), CATALOG
    )


def test_crop_and_free_text_limits():
    assert card_problems(card(crop_taxon="NCBITaxon:4236", cultivar="Grand Rapids"), CATALOG) == []
    assert card_problems(card(crop_taxon="lettuce"), CATALOG) == [
        "crop_taxon lettuce is not NCBITaxon:<number>"
    ]
    assert card_problems(card(growth_stage="x" * 101), CATALOG) == [
        "growth_stage is longer than 100 characters"
    ]
    assert card_problems(card(conditions_note="x" * 501), CATALOG) == [
        "conditions_note is longer than 500 characters"
    ]


def test_a_checked_card_is_returned_with_the_catalog_unit():
    from growbridge.vocab.card_checks import checked_card

    fixed = checked_card(card(variable="air_temperature", value=20.0, unit="C"), CATALOG)

    assert fixed.unit == "Cel"


def test_a_checked_card_with_problems_is_refused_with_all_of_them():
    import pytest

    from growbridge.ports import Denied
    from growbridge.vocab.card_checks import checked_card

    with pytest.raises(Denied) as caught:
        checked_card(
            card(variable="temp", conditions=(ApplicabilityRange(variable="temp"),)), CATALOG
        )

    assert caught.value.code == "param" and caught.value.reason == "evidence_card_invalid"
    assert "air_temperature" in str(caught.value) and "min, max or both" in str(caught.value)
