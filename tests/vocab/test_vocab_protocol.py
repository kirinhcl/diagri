from vocab_support import WITH_OLD

from growbridge.archive.ids import content_digest
from growbridge.archive.models import ResearchProtocol, Treatment
from growbridge.sim.fixtures import make_protocol
from growbridge.vocab import packaged_catalog
from growbridge.vocab.checks import check_protocol

NONE = frozenset()


def test_protocol_without_variables_dumps_as_before():
    raw = make_protocol(variables=()).model_dump(mode="json")
    assert "variables" not in raw
    assert ResearchProtocol.model_validate(raw).digest() == content_digest(raw)


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


def test_endpoint_must_be_declared():
    problems = check_protocol(make_protocol(variables=("light",)), packaged_catalog(), NONE)
    assert any("canopy_area_growth" in p for p in problems)


def test_deprecated_variable_needs_an_earlier_declaration():
    protocol = make_protocol(variables=("canopy_area_growth", "canopy_growth_old"))
    refused = check_protocol(protocol, WITH_OLD, NONE)
    assert any("canopy_growth_old" in p and "canopy_area_growth" in p for p in refused)
    assert check_protocol(protocol, WITH_OLD, frozenset({"canopy_growth_old"})) == []
