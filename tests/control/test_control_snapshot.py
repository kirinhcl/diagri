"""Snapshot of one AC5 channel's configuration block, and its whole-block restore."""

import pytest

from growbridge.archive.models import ActionState, Channel, RightKind
from growbridge.ports import Denied, RightScope

DEVICE = "SIMULATED"


def grant_test(rig, channel=Channel.LIGHT):
    scope = RightScope(device_id=DEVICE, channels=(channel,))
    return rig.service.grant(RightKind.TEST, scope, operator="alice")


def restore_request(rig, number, snapshot, request_id="restore-1"):
    return rig.request(number, snapshot.channel, snapshot.level or 0, request_id)


async def test_snapshot_copies_the_module_block(rig):
    rig.sim.external_change("device", "light", modeType=2)

    snapshot = await rig.service.snapshot(Channel.LIGHT)

    assert snapshot.channel is Channel.LIGHT
    assert snapshot.block == rig.sim.config["device"]["light"]
    assert snapshot.mode == 2 and snapshot.level == 20


async def test_restore_writes_back_a_non_manual_block(rig):
    rig.sim.external_change("device", "light", modeType=2)
    snapshot = await rig.service.snapshot(Channel.LIGHT)
    number = grant_test(rig)
    await rig.service.submit(rig.request(number, Channel.LIGHT, 100))
    assert rig.sim.config["device"]["light"]["modeType"] == 0

    record = await rig.service.restore(restore_request(rig, number, snapshot), snapshot)

    assert record.state is ActionState.CONFIRMED
    assert rig.sim.config["device"]["light"] == snapshot.block


async def test_restore_writes_back_the_pump_outlet_block(rig):
    rig.sim.external_change("outlet", "O4", modeType=1)
    snapshot = await rig.service.snapshot(Channel.PUMP)
    number = grant_test(rig, Channel.PUMP)
    await rig.service.irrigate(rig.request(number, Channel.PUMP, 1), 1)
    assert rig.sim.config["outlet"]["O4"]["modeType"] == 0

    record = await rig.service.restore(restore_request(rig, number, snapshot), snapshot)

    assert record.state is ActionState.CONFIRMED
    assert rig.sim.config["outlet"]["O4"] == snapshot.block


async def test_restore_refuses_a_tampered_snapshot(rig):
    snapshot = await rig.service.snapshot(Channel.LIGHT)
    number = grant_test(rig)
    forged = snapshot.model_copy(update={"block": {**snapshot.block, "mLevel": 100}})

    with pytest.raises(Denied) as refused:
        await rig.service.restore(restore_request(rig, number, forged), forged)

    assert refused.value.reason == "restore_invalid"
    assert rig.writes() == []


async def test_restore_refuses_a_non_test_right(rig):
    snapshot = await rig.service.snapshot(Channel.LIGHT)
    number = rig.manual_right((Channel.LIGHT,))

    with pytest.raises(Denied) as refused:
        await rig.service.restore(restore_request(rig, number, snapshot), snapshot)

    assert refused.value.reason == "restore_invalid"
    assert rig.writes() == []


async def test_restore_confirms_mode_not_every_field(rig):
    rig.sim.external_change("device", "light", modeType=2)
    snapshot = await rig.service.snapshot(Channel.LIGHT)
    number = grant_test(rig)
    original = rig.sim.send

    async def timer_moves(command):  # the AC5's own program edits the block right after a write
        await original(command)
        if command["method"] == "setConfigField":
            rig.sim.external_change("device", "light", timePeriod=[])

    rig.sim.send = timer_moves

    record = await rig.service.restore(restore_request(rig, number, snapshot), snapshot)

    assert record.state is ActionState.CONFIRMED


async def test_restore_reports_a_mode_the_device_did_not_take(rig):
    rig.sim.external_change("device", "light", modeType=2)
    snapshot = await rig.service.snapshot(Channel.LIGHT)
    number = grant_test(rig)
    rig.sim.ignore_writes = True
    rig.sim.external_change("device", "light", modeType=0)

    record = await rig.service.restore(restore_request(rig, number, snapshot), snapshot)

    assert record.state is ActionState.FAILED
    assert record.error_code == "readback_mode"
