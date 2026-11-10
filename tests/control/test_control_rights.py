import asyncio

import pytest

from growbridge.archive.models import ActionState, Channel, RightKind, RuleAction
from growbridge.ports import Denied, RightScope

DEVICE = "SIMULATED"


def scope(**fields):
    return RightScope(**{"device_id": DEVICE, "channels": (Channel.LIGHT,), **fields})


async def wait_for(predicate, attempts=200):
    for _ in range(attempts):
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition not reached")


def state(rig, request_id):
    record = rig.service.receipt(request_id)
    return record.state if record else None


async def test_control_unregistered_host_cannot_grant_or_write(build):
    rig = await build(register=False)
    with pytest.raises(Denied) as error:
        rig.service.grant(RightKind.STAGE, scope())
    assert error.value.code == "host_unregistered"
    assert rig.service.host_registered() is False
    rig.service.register_host()
    assert rig.service.host_registered() is True
    number = rig.service.grant(RightKind.STAGE, scope())
    record = await rig.service.submit(rig.request(number, Channel.LIGHT, 20))
    assert record.state is ActionState.CONFIRMED


async def test_control_other_registered_host_is_refused(rig, restart):
    other = restart(host_id="host-b")
    with pytest.raises(Denied) as error:
        other.register_host()
    assert error.value.code == "host_unregistered"
    assert other.host_registered() is False
    number = rig.stage_right()
    rig.service.register_host()  # registering the same host again is harmless
    assert rig.service.right(number) is not None


async def test_control_write_stops_when_host_registration_is_lost(rig):
    number = rig.stage_right()
    rig.db.execute("UPDATE control_host SET host_id = 'host-b'")
    with pytest.raises(Denied) as error:
        await rig.service.submit(rig.request(number, Channel.LIGHT, 20))
    assert error.value.code == "host_unregistered"
    assert rig.writes() == []


async def test_control_only_one_stage_right_per_device(rig):
    first = rig.stage_right()
    with pytest.raises(Denied) as error:
        rig.stage_right(stage_id="stage-2")
    assert error.value.code == "right_held"
    await rig.service.handover(first, "stage ended")
    assert rig.stage_right(stage_id="stage-2") > first


async def test_control_manual_right_not_granted_while_stage_right_held(rig):
    stage = rig.stage_right()
    with pytest.raises(Denied) as error:
        rig.manual_right()
    assert error.value.code == "right_held"
    await rig.service.handover(stage, "takeover")
    assert rig.service.right(rig.manual_right()).kind is RightKind.MANUAL


@pytest.mark.parametrize("kind", [RightKind.CARE, RightKind.PROTECTION])
async def test_control_care_and_protection_rights_need_listed_levels(rig, kind):
    with pytest.raises(Denied) as error:
        rig.service.grant(kind, scope())
    assert error.value.code == "scope"
    levels = (RuleAction(channel=Channel.LIGHT, level=0),)
    number = rig.service.grant(kind, scope(levels=levels))
    assert rig.service.right(number).levels == levels


async def test_control_grant_for_other_device_or_manual_without_operator_is_denied(rig):
    with pytest.raises(Denied) as error:
        rig.service.grant(RightKind.STAGE, scope(device_id="OTHER"))
    assert error.value.code == "scope"
    with pytest.raises(Denied) as error:
        rig.service.grant(RightKind.MANUAL, scope())
    assert error.value.code == "right_invalid"


async def test_control_handover_voids_queued_actions_and_rejects_old_number(rig):
    number = rig.stage_right()
    release = asyncio.Event()
    original = rig.sim.send

    async def slow(command):
        if command["method"] == "setConfigField":
            await release.wait()
        await original(command)

    rig.sim.send = slow
    first = asyncio.create_task(rig.service.submit(rig.request(number, Channel.LIGHT, 50, "a")))
    await wait_for(lambda: state(rig, "a") is ActionState.MAYBE_SENT)
    second = asyncio.create_task(rig.service.submit(rig.request(number, Channel.EXHAUST, 40, "b")))
    await wait_for(lambda: state(rig, "b") is ActionState.PENDING)
    handover = asyncio.create_task(rig.service.handover(number, "stage ended"))
    await asyncio.sleep(0)
    assert rig.service.right(number).revoked_at is not None  # persisted before waiting
    assert state(rig, "b") is ActionState.VOID
    assert not handover.done()  # still waiting for the in-flight receipt
    release.set()
    await handover
    assert (await first).state is ActionState.CONFIRMED
    with pytest.raises(Denied) as error:
        await second
    assert error.value.code == "right_invalid"
    with pytest.raises(Denied) as error:
        await rig.service.submit(rig.request(number, Channel.LIGHT, 10))
    assert error.value.code == "right_invalid"
    assert len(rig.writes()) == 1


async def test_control_recovery_bump_voids_every_right(rig):
    stage = rig.stage_right()
    before = rig.service.recovery_number()
    assert rig.service.bump_recovery("restore") == before + 1
    assert rig.service.recovery_number() == before + 1
    assert rig.service.right(stage).revoked_at is not None
    with pytest.raises(Denied) as error:
        await rig.service.submit(rig.request(stage, Channel.LIGHT, 10))
    assert error.value.code == "right_invalid"
    assert rig.stage_right(stage_id="stage-2") > stage
    assert rig.service.protection_right() is None
