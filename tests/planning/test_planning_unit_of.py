from growbridge.archive.models import Allocation
from growbridge.planning.treatment import unit_of
from growbridge.sim.fixtures import make_protocol

TWO_UNITS = make_protocol(
    allocations=(
        Allocation(round=1, block=1, unit="tent-1", treatment_id="high"),
        Allocation(round=1, block=1, unit="tent-2", treatment_id="control"),
    )
)


def test_single_allocation_round_takes_any_position():
    allocation = unit_of(make_protocol().allocations, 1, "anywhere")
    assert allocation is not None and allocation.unit == "tent-1"


def test_multi_unit_round_matches_the_unit():
    allocation = unit_of(TWO_UNITS.allocations, 1, "tent-2")
    assert allocation is not None and allocation.treatment_id == "control"


def test_no_match_is_none():
    assert unit_of(TWO_UNITS.allocations, 1, "nowhere") is None
    assert unit_of(TWO_UNITS.allocations, 9, "tent-1") is None
