"""The TEST write right: an operator's short on-site device test on an idle greenhouse."""

import pytest

from growbridge.archive.models import ActionState, Channel, RightKind
from growbridge.ports import Denied, RightScope
from growbridge.sim.fixtures import make_safety

DEVICE = "SIMULATED"


def grant_test(rig, channels=(Channel.LIGHT,), operator="alice"):
    scope = RightScope(device_id=DEVICE, channels=tuple(channels))
    return rig.service.grant(RightKind.TEST, scope, operator=operator)


async def test_test_right_writes_its_channel(rig):
    number = grant_test(rig)

    record = await rig.service.submit(rig.request(number, Channel.LIGHT, 100))

    assert record.state is ActionState.CONFIRMED
    assert record.right_number == number
    assert rig.service.right(number).kind is RightKind.TEST


async def test_test_right_refuses_other_channels(rig):
    number = grant_test(rig)

    with pytest.raises(Denied):
        await rig.service.submit(rig.request(number, Channel.FAN, 5))
    assert rig.writes() == []


def test_test_right_needs_an_operator(rig):
    with pytest.raises(Denied) as refused:
        grant_test(rig, operator=None)

    assert refused.value.reason == "right_needs_operator"


async def test_test_right_may_irrigate(rig):
    number = grant_test(rig, channels=(Channel.PUMP,))

    record = await rig.service.irrigate(rig.request(number, Channel.PUMP, 1), 1)

    assert record.state is ActionState.CONFIRMED
    assert rig.sim.config["outlet"]["O4"]["mOnOff"] == 0


def test_test_right_refused_while_a_stage_right_is_held(rig):
    rig.stage_right()

    with pytest.raises(Denied) as refused:
        grant_test(rig)

    assert refused.value.reason == "right_held"


async def test_protection_still_writes_while_a_test_right_is_held(rig):
    grant_test(rig)
    rig.service.approve_safety(make_safety(), "alice")
    protection = rig.service.protection_right()

    record = await rig.service.submit(rig.request(protection, Channel.LIGHT, 0))

    assert record.state is ActionState.CONFIRMED
