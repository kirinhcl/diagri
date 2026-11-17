"""Safety configuration versions only go up on a device, also across a recovery (the batch 3
follow-up): a repeated number would make two approved sets indistinguishable in the ledger and
the event log. A configuration an earlier version stored keeps loading."""

import pytest

from growbridge.archive.models import STORED, SafetyConfig
from growbridge.ports import Denied
from growbridge.sim.fixtures import make_safety


def refused(call) -> Denied:
    with pytest.raises(Denied) as caught:
        call()
    return caught.value


def stored_versions(rig) -> list[int]:
    rows = rig.db.query("SELECT config FROM control_safety ORDER BY id")
    return [SafetyConfig.model_validate_json(row["config"], context=STORED).version for row in rows]


async def test_the_first_approval_needs_a_version_of_at_least_one(rig):
    error = refused(lambda: rig.service.approve_safety(make_safety(version=0), "alice"))

    assert (error.code, error.reason) == ("state", "safety_version_not_above")
    assert error.params == {"version": 0, "current_version": 0}
    assert rig.service.safety() is None


async def test_approving_the_same_version_again_is_refused_and_nothing_is_stored(rig):
    rig.service.approve_safety(make_safety(version=1), "alice")

    error = refused(lambda: rig.service.approve_safety(make_safety(version=1), "bob"))

    assert (error.code, error.reason) == ("state", "safety_version_not_above")
    assert error.params == {"version": 1, "current_version": 1}
    assert stored_versions(rig) == [1]
    assert rig.service.safety().approved_by == "alice"


async def test_a_lower_version_is_refused_and_a_higher_one_accepted(rig):
    rig.service.approve_safety(make_safety(version=3), "alice")

    error = refused(lambda: rig.service.approve_safety(make_safety(version=2), "alice"))
    rig.service.approve_safety(make_safety(version=5), "alice")

    assert error.params == {"version": 2, "current_version": 3}
    assert stored_versions(rig) == [3, 5]
    assert rig.service.safety().version == 5


async def test_after_a_recovery_nothing_is_in_force_but_the_count_goes_on(rig):
    rig.service.approve_safety(make_safety(version=2), "alice")
    rig.service.bump_recovery("restore")
    assert rig.service.safety() is None

    error = refused(lambda: rig.service.approve_safety(make_safety(version=1), "alice"))
    rig.service.approve_safety(make_safety(version=3), "alice")

    assert error.params == {"version": 1, "current_version": 2}
    assert rig.service.safety().version == 3


async def test_the_highest_version_counts_even_when_an_older_version_stored_a_lower_one_last(rig):
    """Before this check versions could go down; the highest one ever approved is the bar."""
    ledger, recovery = rig.service.ledger, rig.service.recovery_number()
    ledger.save_safety(make_safety(version=5), recovery, "alice", 1.0)
    ledger.save_safety(make_safety(version=3), recovery, "alice", 2.0)

    error = refused(lambda: rig.service.approve_safety(make_safety(version=4), "alice"))

    assert error.params == {"version": 4, "current_version": 5}
    assert rig.service.highest_safety_version() == 5


async def test_the_highest_version_is_none_until_something_is_approved(rig):
    assert rig.service.highest_safety_version() is None

    rig.service.approve_safety(make_safety(version=1), "alice")

    assert rig.service.highest_safety_version() == 1


async def test_a_stored_config_that_breaks_the_input_checks_still_loads_and_protects(rig, restart):
    """Stored before the checks: a repeated rule id and a negative time. It is read back as
    stored, and a restart still issues its protection right."""
    data = make_safety(version=1).model_dump(mode="json")
    rule = {**data["rules"][0], "validity_seconds": -5}
    stored = SafetyConfig.model_validate({**data, "rules": [rule, rule]}, context=STORED)
    rig.service.ledger.save_safety(stored, rig.service.recovery_number(), "alice", 1.0)

    assert rig.service.safety() == stored
    again = restart()
    await again.startup()
    assert again.safety() == stored
    assert again.protection_right() is not None
