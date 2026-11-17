import asyncio

import pytest

from growbridge.archive.models import (
    ActionState,
    Channel,
    ChannelPlan,
    FrozenCheck,
    Ownership,
    RightKind,
    RuleAction,
)
from growbridge.control.device import SENSORS
from growbridge.ports import Denied, RightScope
from growbridge.sim.fixtures import make_run_sheet, make_safety

DEVICE = "SIMULATED"
PUMP_SECONDS = 0.02


async def wait_for(predicate, attempts=200):
    for _ in range(attempts):
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition not reached")


def state_of(rig, request_id):
    record = rig.service.receipt(request_id)
    return record.state if record else None


def care_scope(channel, level):
    return RightScope(
        device_id=DEVICE,
        channels=(channel,),
        levels=(RuleAction(channel=channel, level=level),),
    )


async def irrigate(rig, request_id="irrigation-1", seconds=PUMP_SECONDS, operator="alice"):
    number = rig.manual_right(operator=operator)
    request = rig.request(number, Channel.PUMP, 1, request_id, operator=operator)
    return await rig.service.irrigate(request, seconds)


async def interlock(rig):
    """Leave the pump-off unconfirmed, as a failed irrigation does."""
    rig.sim.fail_off = True
    record = await irrigate(rig)
    assert record.state is ActionState.UNKNOWN and rig.service.interlocked()
    return record


async def test_control_irrigate_runs_pump_and_switches_it_off(rig):
    record = await irrigate(rig)
    assert record.state is ActionState.CONFIRMED
    assert record.channel is Channel.PUMP and record.operator == "alice"
    assert [c["params"]["O4"]["mOnOff"] for c in rig.writes()] == [1, 0]
    assert rig.sim.config["outlet"]["O4"]["mOnOff"] == 0
    assert rig.service.interlocked() is False


async def test_control_irrigate_needs_manual_right_and_limits(rig, settings):
    stage = rig.stage_right(channels=(Channel.PUMP,))
    with pytest.raises(Denied) as error:
        await rig.service.irrigate(rig.request(stage, Channel.PUMP, 1), PUMP_SECONDS)
    assert error.value.code == "right_invalid"
    await rig.service.handover(stage, "takeover")
    manual = rig.manual_right()
    for seconds in (0, -1, float("nan"), settings.max_pump_seconds + 1):
        with pytest.raises(Denied) as error:
            await rig.service.irrigate(rig.request(manual, Channel.PUMP, 1), seconds)
        assert error.value.code == "scope"
    with pytest.raises(Denied) as error:
        await rig.service.irrigate(rig.request(manual, Channel.LIGHT, 1), PUMP_SECONDS)
    assert error.value.code == "scope"
    assert rig.writes() == []


async def test_control_irrigate_respects_cooldown(rig, settings):
    rig.bridge.settings = settings.model_copy(update={"pump_cooldown_seconds": 60})
    number = rig.manual_right()
    await rig.service.irrigate(rig.request(number, Channel.PUMP, 1), PUMP_SECONDS)
    rig.clock.advance(10)
    await rig.refresh()
    with pytest.raises(Denied) as error:
        await rig.service.irrigate(rig.request(number, Channel.PUMP, 1), PUMP_SECONDS)
    assert error.value.code == "cooldown"
    rig.clock.advance(60)
    await rig.refresh()
    again = await rig.service.irrigate(rig.request(number, Channel.PUMP, 1), PUMP_SECONDS)
    assert again.state is ActionState.CONFIRMED


async def test_control_pump_off_failure_sets_interlock_until_pump_off_succeeds(rig):
    await interlock(rig)
    assert [item.channel for item in rig.service.unsettled_actions()] == [Channel.PUMP]
    assert await rig.service.pump_off() is False  # still failing
    assert rig.service.interlocked()
    rig.sim.fail_off = False
    assert await rig.service.pump_off() is True
    assert rig.service.interlocked() is False
    assert rig.service.unsettled_actions() == ()


async def test_control_interlock_blocks_ordinary_writes_but_not_protection_or_care(rig):
    care = rig.service.grant(RightKind.CARE, care_scope(Channel.EXHAUST, 30))
    pump_care = rig.service.grant(RightKind.CARE, care_scope(Channel.PUMP, 0))
    protection = rig.service.approve_safety(make_safety(), "alice")
    await interlock(rig)
    stage = rig.stage_right()
    with pytest.raises(Denied) as error:
        await rig.service.submit(rig.request(stage, Channel.LIGHT, 10))
    assert error.value.code == "interlock"
    dimmed = await rig.service.submit(rig.request(protection, Channel.LIGHT, 0))
    assert dimmed.state is ActionState.CONFIRMED and dimmed.right_kind is RightKind.PROTECTION
    exhaust = await rig.service.submit(rig.request(care, Channel.EXHAUST, 30))
    assert exhaust.state is ActionState.CONFIRMED
    with pytest.raises(Denied) as error:
        await rig.service.submit(rig.request(pump_care, Channel.PUMP, 0))
    assert error.value.code == "interlock"


async def test_control_care_is_blocked_during_interlock_when_transport_not_stopped(rig):
    care = rig.service.grant(RightKind.CARE, care_scope(Channel.EXHAUST, 30))
    await interlock(rig)
    rig.sim.halt_confirmed = False
    assert await rig.service.confirm_transport_stopped() is False
    assert rig.service.transport_stopped() is False
    with pytest.raises(Denied) as error:
        await rig.service.submit(rig.request(care, Channel.EXHAUST, 30))
    assert error.value.code == "interlock"
    rig.sim.halt_confirmed = True
    assert await rig.service.confirm_transport_stopped() is True
    record = await rig.service.submit(rig.request(care, Channel.EXHAUST, 30))
    assert record.state is ActionState.CONFIRMED


async def test_control_interlock_stays_while_old_transport_is_unconfirmed(rig):
    await interlock(rig)
    rig.sim.fail_off = False
    rig.sim.halt_confirmed = False
    await rig.service.confirm_transport_stopped()
    assert await rig.service.pump_off() is True  # the outlet reads back off ...
    assert rig.service.interlocked()  # ... but an old switch-on may still be queued
    rig.sim.halt_confirmed = True
    await rig.service.confirm_transport_stopped()
    assert await rig.service.pump_off() is True
    assert rig.service.interlocked() is False


async def test_control_onsite_check_settles_unknown_actions_and_interlock(rig):
    await interlock(rig)
    with pytest.raises(Denied) as error:
        await rig.service.onsite_check("", "note")
    assert error.value.code == "not_operator"
    await rig.service.onsite_check("alice", "pump physically off")
    assert rig.service.interlocked() is False
    assert rig.service.unsettled_actions() == ()
    settled = rig.service.receipt("irrigation-1")
    assert settled.state is ActionState.UNKNOWN and settled.settled_at == rig.clock.now()


async def test_control_pump_off_needs_registered_host(rig):
    rig.db.execute("UPDATE control_host SET host_id = 'host-b'")
    with pytest.raises(Denied) as error:
        await rig.service.pump_off()
    assert error.value.code == "host_unregistered"


# --- safety configuration ---------------------------------------------------------------------


async def test_control_approved_safety_issues_one_protection_right(rig):
    assert rig.service.safety() is None and rig.service.protection_right() is None
    first = rig.service.approve_safety(make_safety(), "alice")
    stored = rig.service.safety()
    assert stored.rules == make_safety().rules
    assert stored.approved_by == "alice" and stored.approved_at == rig.clock.now()
    assert rig.service.protection_right() == first
    second = rig.service.approve_safety(make_safety(version=2), "alice")
    assert second > first and rig.service.protection_right() == second
    assert rig.service.right(first).revoked_at is not None
    with pytest.raises(Denied) as error:
        rig.service.approve_safety(make_safety(version=3), " ")
    assert error.value.code == "approval_invalid"


async def test_control_safety_refuses_frozen_thresholds_for_sensors_the_device_lacks(rig):
    misspelt = FrozenCheck(minutes={"temp": 120.0, "tmep": 60.0})
    with pytest.raises(Denied) as error:
        rig.service.approve_safety(make_safety(frozen=misspelt), "alice")
    assert error.value.code == "approval_invalid" and "tmep" in str(error.value)
    assert rig.service.safety() is None and rig.service.protection_right() is None
    every = FrozenCheck(minutes=dict.fromkeys(SENSORS, 60.0))
    rig.service.approve_safety(make_safety(frozen=every), "alice")
    assert rig.service.safety().frozen == every


async def test_control_safety_needs_reapproval_after_recovery_bump(rig):
    rig.service.approve_safety(make_safety(), "alice")
    rig.service.bump_recovery("restore")
    assert rig.service.safety() is None
    assert rig.service.protection_right() is None
    number = rig.service.approve_safety(make_safety(version=2), "alice")  # versions only go up
    record = await rig.service.submit(rig.request(number, Channel.LIGHT, 0))
    assert record.state is ActionState.CONFIRMED


async def test_control_safety_conflicts_list_rules_on_device_managed_channels(rig):
    assert rig.service.safety_conflicts(make_run_sheet()) == ()
    plans = tuple(
        ChannelPlan(channel=plan.channel, ownership=Ownership.DEVICE)
        if plan.channel is Channel.LIGHT
        else plan
        for plan in make_run_sheet().channels
    )
    rig.service.approve_safety(make_safety(), "alice")
    conflicts = rig.service.safety_conflicts(make_run_sheet(channels=plans))
    assert len(conflicts) == 1 and "overheat-light-off" in conflicts[0]
    without_light = tuple(plan for plan in plans if plan.channel is not Channel.LIGHT)
    assert len(rig.service.safety_conflicts(make_run_sheet(channels=without_light))) == 1


# --- restart ----------------------------------------------------------------------------------


async def test_control_restart_marks_in_flight_action_unknown_and_blocks_writes(rig, restart):
    old = rig.stage_right()
    release = asyncio.Event()
    original = rig.sim.send

    async def hang(command):
        if command["method"] == "setConfigField":
            await release.wait()
        await original(command)

    rig.sim.send = hang
    sent = asyncio.create_task(rig.service.submit(rig.request(old, Channel.LIGHT, 50, "sent")))
    await wait_for(lambda: state_of(rig, "sent") is ActionState.MAYBE_SENT)
    queued = asyncio.create_task(
        rig.service.submit(rig.request(old, Channel.EXHAUST, 40, "queued"))
    )
    await wait_for(lambda: state_of(rig, "queued") is ActionState.PENDING)
    for task in (sent, queued):  # the process dies: intent persisted, no receipt
        task.cancel()
    await asyncio.gather(sent, queued, return_exceptions=True)
    rig.sim.send = original
    writes = len(rig.writes())

    fresh = restart()
    await fresh.startup()
    assert fresh.receipt("sent").state is ActionState.UNKNOWN
    assert fresh.receipt("queued").state is ActionState.VOID
    assert [item.request_id for item in fresh.unsettled_actions()] == ["sent"]
    assert fresh.right(old).revoked_at is not None
    with pytest.raises(Denied) as error:
        await fresh.submit(rig.request(old, Channel.LIGHT, 10))
    assert error.value.code == "right_invalid"
    scope = RightScope(device_id=DEVICE, channels=(Channel.LIGHT,), stage_id="stage-2")
    new = fresh.grant(RightKind.STAGE, scope)
    with pytest.raises(Denied) as error:
        await fresh.submit(rig.request(new, Channel.LIGHT, 10))
    assert error.value.code == "unsettled"
    assert len(rig.writes()) == writes  # nothing was replayed
    await fresh.onsite_check("alice", "light verified by hand")
    record = await fresh.submit(rig.request(new, Channel.LIGHT, 10))
    assert record.state is ActionState.CONFIRMED


async def test_control_restart_reissues_protection_right_and_keeps_interlock(rig, restart):
    old = rig.service.approve_safety(make_safety(), "alice")
    await interlock(rig)
    fresh = restart()
    rig.sim.halt_confirmed = False
    await fresh.startup()
    assert fresh.recovery_number() == rig.service.recovery_number()
    assert fresh.protection_right() not in (None, old)
    assert fresh.interlocked() is True
    assert fresh.transport_stopped() is False


async def test_control_writes_wait_for_startup(build):
    rig = await build(start=False)
    number = rig.stage_right()
    with pytest.raises(Denied) as error:
        await rig.service.submit(rig.request(number, Channel.LIGHT, 10))
    assert error.value.code == "unsettled"
    assert rig.writes() == []
