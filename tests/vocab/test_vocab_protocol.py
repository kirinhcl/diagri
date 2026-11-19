import pytest
from vocab_support import WITH_OLD

from growbridge.archive.ids import content_digest
from growbridge.archive.models import ResearchProtocol, Treatment
from growbridge.sim.fixtures import make_protocol
from growbridge.vocab import load_catalog, packaged_catalog, packaged_text
from growbridge.vocab.checks import check_protocol

NONE = frozenset()
# make_protocol().digest() before protocols had `variables` (base d7d479a, spec §13).
PRE_CHANGE_DIGEST = "43a1b3295e64a74f2e948c38755068627abd79b2bc54de64c89ab26e84cc0ce1"

RETIRED_ENTRY = """
[[variable]]
id = "canopy_retired"
kind = "manual"
label_en = "Canopy (retired)"
label_zh = "冠层（停用）"
quantity = "area_growth_rate"
unit = "cm2/d"
method = "retired method"
deprecated = true
refs = []
"""
WITH_RETIRED = load_catalog(packaged_text() + RETIRED_ENTRY)  # deprecated, no replacement


def test_protocol_without_variables_dumps_as_before():
    raw = make_protocol(variables=()).model_dump(mode="json")
    assert "variables" not in raw
    assert ResearchProtocol.model_validate(raw).digest() == content_digest(raw)


def test_protocol_without_variables_keeps_its_pre_change_digest():
    assert make_protocol(variables=(), crop_taxon="").digest() == PRE_CHANGE_DIGEST


def test_protocol_without_crop_fields_dumps_as_before():
    raw = make_protocol(variables=(), crop_taxon="", cultivar="").model_dump(mode="json")
    assert "crop_taxon" not in raw and "cultivar" not in raw


def test_crop_fields_are_dumped_when_set():
    raw = make_protocol(crop_taxon="NCBITaxon:4236", cultivar="Grand Rapids").model_dump(
        mode="json"
    )
    assert raw["crop_taxon"] == "NCBITaxon:4236" and raw["cultivar"] == "Grand Rapids"


def test_declared_variables_are_dumped():
    assert make_protocol().model_dump(mode="json")["variables"] == ["canopy_area_growth"]


def test_fixture_protocol_passes():
    assert check_protocol(make_protocol(), packaged_catalog(), NONE) == []


def test_every_problem_is_reported_at_once():
    protocol = make_protocol(
        variables=("canopy_area_growth", "canopy_area_growth", "temp", "heigth"),
        treatments=(
            Treatment(id="control", name="c", factors={"lux": 40}),
            Treatment(id="high", name="h", factors={"light": 70}),
        ),
    )
    problems = " | ".join(check_protocol(protocol, packaged_catalog(), NONE))
    assert "twice" in problems
    assert "air_temperature" in problems  # an alias names the ID to use
    assert "heigth" in problems
    assert "lux" in problems


def test_empty_variables_are_refused():
    problems = check_protocol(make_protocol(variables=()), packaged_catalog(), NONE)
    assert any("variables" in p for p in problems)


def test_empty_variables_do_not_hide_the_other_problems():
    protocol = make_protocol(
        variables=(), treatments=(Treatment(id="control", name="c", factors={"lux": 40}),)
    )
    problems = check_protocol(protocol, packaged_catalog(), NONE)
    assert any("`variables` list is empty" in p for p in problems)
    assert any("lux" in p for p in problems)  # a factor key that is no catalog factor
    assert any("primary endpoint canopy_area_growth" in p for p in problems)  # not declared


@pytest.mark.parametrize(("endpoint", "kind"), [("light", "factor"), ("air_temperature", "sensor")])
def test_primary_endpoint_must_be_a_manual_variable(endpoint, kind):
    analysis = make_protocol().analysis.model_copy(update={"primary_endpoint": endpoint})
    protocol = make_protocol(variables=(endpoint,), analysis=analysis)
    problems = check_protocol(protocol, packaged_catalog(), NONE)
    assert any(endpoint in p and kind in p and "manual" in p for p in problems), problems


def test_endpoint_must_be_declared():
    problems = check_protocol(make_protocol(variables=("light",)), packaged_catalog(), NONE)
    assert any("canopy_area_growth" in p for p in problems)


def test_deprecated_variable_needs_an_earlier_declaration():
    protocol = make_protocol(variables=("canopy_area_growth", "canopy_growth_old"))
    refused = check_protocol(protocol, WITH_OLD, NONE)
    assert any("canopy_growth_old" in p and "canopy_area_growth" in p for p in refused)
    assert check_protocol(protocol, WITH_OLD, frozenset({"canopy_growth_old"})) == []


def test_deprecated_variable_without_replacement_names_no_replacement():
    protocol = make_protocol(variables=("canopy_area_growth", "canopy_retired"))
    refused = check_protocol(protocol, WITH_RETIRED, NONE)
    assert refused == ["variable canopy_retired is deprecated"]
