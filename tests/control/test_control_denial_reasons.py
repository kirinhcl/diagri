"""Every refusal in device control names a registered reason and carries its params."""

from pathlib import Path

import pytest
from test_control_interlock import PUMP_SECONDS

from growbridge.archive.models import Channel, RightKind, RuleAction
from growbridge.control import rights
from growbridge.control.ledger import META_LAST_IRRIGATION
from growbridge.ports import ActionRequest, Denied, RightScope
from growbridge.runtime import register_write_host

DEVICE = "SIMULATED"


def refusal(call):
    with pytest.raises(Denied) as error:
        call()
    return error.value


async def refusal_of(awaitable):
    with pytest.raises(Denied) as error:
        await awaitable
    return error.value


def check(exc, code, reason, params):
    assert (exc.code, exc.reason, exc.params) == (code, reason, params)


def stage_scope(**fields):
    return RightScope(device_id=DEVICE, channels=(Channel.LIGHT,), stage_id="stage-1", **fields)


def request(number, channel=Channel.LIGHT, level=20, **extra):
    return ActionRequest(
        request_id=extra.pop("request_id", "r-1"),
        right_number=number,
        channel=channel,
        level=level,
        trigger="test",
        **extra,
    )


# --- host ---------------------------------------------------------------------------------------


async def test_other_host_registered_carries_the_device(rig, restart):
    exc = refusal(restart(host_id="host-b").register_host)
    check(exc, "host_unregistered", "other_host_registered", {"device_id": DEVICE})


async def test_other_host_registered_at_startup_carries_the_device(rig, settings):
    rig.db.execute("UPDATE control_host SET host_id = 'host-b'")
    moved = settings.model_copy(update={"data_dir": Path(rig.db.path).parent})
    exc = refusal(lambda: register_write_host(moved))
    check(exc, "host_unregistered", "other_host_registered", {"device_id": settings.device})


async def test_not_write_host_carries_the_device(build):
    rig = await build(register=False)
    exc = refusal(lambda: rig.service.grant(RightKind.STAGE, stage_scope()))
    check(exc, "host_unregistered", "not_write_host", {"device_id": DEVICE})


async def test_controls_disabled_carries_nothing(rig, settings):
    number = rig.stage_right()
    rig.bridge.settings = settings.model_copy(update={"controls_enabled": False})
    exc = await refusal_of(rig.service.submit(rig.request(number, Channel.LIGHT, 20)))
    check(exc, "controls_disabled", "controls_disabled", {})


# --- rights -------------------------------------------------------------------------------------


async def test_right_incomplete_carries_the_right_id(rig):
    scope = RightScope(device_id=DEVICE)
    exc = refusal(lambda: rig.service.grant(RightKind.CARE, scope))
    check(exc, "scope", "right_incomplete", {"right_id": None})


async def test_right_needs_operator_carries_the_right_id(rig):
    exc = refusal(lambda: rig.service.grant(RightKind.MANUAL, RightScope(device_id=DEVICE)))
    check(exc, "right_invalid", "right_needs_operator", {"right_id": None})


async def test_right_unknown_carries_the_right_id(rig):
    exc = await refusal_of(rig.service.submit(rig.request(999, Channel.LIGHT, 20)))
    check(exc, "right_invalid", "right_unknown", {"right_id": 999})


async def test_right_revoked_carries_the_right_id(rig):
    number = rig.stage_right()
    rig.service.ledger.revoke(number, rig.clock.now())
    exc = await refusal_of(rig.service.submit(rig.request(number, Channel.LIGHT, 20)))
    check(exc, "right_invalid", "right_revoked", {"right_id": number})


async def test_right_from_old_recovery_carries_the_right_id(rig):
    number = rig.stage_right()
    right = rig.service.right(number)
    exc = refusal(lambda: rights.check_valid(right, DEVICE, right.recovery_number + 1, number))
    check(exc, "right_invalid", "right_from_old_recovery", {"right_id": number})


async def test_right_wrong_kind_carries_the_right_id(rig):
    number = rig.stage_right(channels=(Channel.PUMP,))
    req = rig.request(number, Channel.PUMP, 1)
    exc = await refusal_of(rig.service.irrigate(req, PUMP_SECONDS))
    check(exc, "right_invalid", "right_wrong_kind", {"right_id": number})


async def test_right_voided_carries_the_right_id(rig):
    number = rig.stage_right()
    req = rig.request(number, Channel.LIGHT, 20)
    record = rights.intent(req, rig.service.right(number), 20, rig.clock.now())
    exc = refusal(lambda: rig.service._recheck(record, req))
    check(exc, "right_invalid", "right_voided", {"right_id": number})


async def test_right_held_carries_device_and_the_stage_that_holds_it(rig):
    rig.stage_right()  # held by stage-1
    asking = RightScope(device_id=DEVICE, channels=(Channel.LIGHT,), stage_id="stage-2")
    exc = refusal(lambda: rig.service.grant(RightKind.STAGE, asking))
    check(exc, "right_held", "right_held", {"device_id": DEVICE, "stage_id": "stage-1"})


async def test_right_channel_carries_right_and_channel(rig):
    number = rig.stage_right(channels=(Channel.LIGHT,))
    exc = await refusal_of(rig.service.submit(rig.request(number, Channel.FAN, 20)))
    check(exc, "scope", "right_channel", {"right_id": number, "channel": "fan"})


async def test_right_value_carries_right_channel_and_level_when_out_of_range(rig):
    number = rig.stage_right()
    exc = await refusal_of(rig.service.submit(rig.request(number, Channel.LIGHT, 500)))
    check(exc, "scope", "right_value", {"right_id": number, "channel": "light", "level": 500})


async def test_right_value_carries_right_channel_and_level_when_not_listed(rig):
    scope = RightScope(device_id=DEVICE, levels=(RuleAction(channel=Channel.LIGHT, level=10),))
    number = rig.service.grant(RightKind.CARE, scope)
    exc = await refusal_of(rig.service.submit(rig.request(number, Channel.LIGHT, 20)))
    check(exc, "scope", "right_value", {"right_id": number, "channel": "light", "level": 20})


async def test_right_binding_carries_right_and_stage(rig):
    number = rig.stage_right()
    req = rig.request(number, Channel.LIGHT, 20, stage_id="stage-2")
    exc = await refusal_of(rig.service.submit(req))
    check(exc, "scope", "right_binding", {"right_id": number, "stage_id": "stage-1"})


async def test_unknown_device_carries_the_device(rig):
    exc = refusal(lambda: rig.service.grant(RightKind.STAGE, RightScope(device_id="OTHER")))
    check(exc, "scope", "unknown_device", {"device_id": "OTHER"})


async def test_pump_on_forbidden_carries_nothing(rig):
    number = rig.stage_right(channels=(Channel.PUMP,))
    exc = await refusal_of(rig.service.submit(rig.request(number, Channel.PUMP, 1)))
    check(exc, "pump_on_forbidden", "pump_on_forbidden", {})


# --- approval, operator -------------------------------------------------------------------------


async def test_safety_needs_approver_carries_nothing(rig):
    exc = refusal(lambda: rig.service.approve_safety(_config(), " "))
    check(exc, "approval_invalid", "safety_needs_approver", {})


async def test_safety_unknown_sensors_carries_the_names(rig):
    config = _config(frozen={"nope": 5})
    exc = refusal(lambda: rig.service.approve_safety(config, "alice"))
    check(exc, "approval_invalid", "safety_unknown_sensors", {"sensors": ["nope"]})


def _config(frozen=None):
    from growbridge.archive.models import FrozenCheck, SafetyConfig

    return SafetyConfig(version=1, rules=(), frozen=FrozenCheck(minutes=frozen or {}))


async def test_not_operator_needs_no_params(rig):
    exc = await refusal_of(rig.service.onsite_check(" ", "note"))
    check(exc, "not_operator", "not_operator", {})


# --- irrigation ---------------------------------------------------------------------------------


async def test_irrigation_seconds_range_carries_the_request_and_the_limit(rig, settings):
    number = rig.manual_right()
    req = rig.request(number, Channel.PUMP, 1)
    too_long = settings.max_pump_seconds + 1
    exc = await refusal_of(rig.service.irrigate(req, too_long))
    check(
        exc,
        "scope",
        "irrigation_seconds_range",
        {"seconds": too_long, "max_seconds": settings.max_pump_seconds},
    )


async def test_irrigation_wrong_request_carries_nothing(rig):
    number = rig.manual_right()
    exc = await refusal_of(rig.service.irrigate(rig.request(number, Channel.FAN, 1), PUMP_SECONDS))
    check(exc, "scope", "irrigation_wrong_request", {})


async def test_irrigation_running_carries_the_device(rig):
    import asyncio

    rig.service._cycle = asyncio.Event()
    exc = refusal(rig.service._check_cooldown)
    check(exc, "cooldown", "irrigation_running", {"device_id": DEVICE})


async def test_irrigation_too_soon_carries_the_wait_and_the_ready_time(rig, settings):
    rig.bridge.settings = settings.model_copy(update={"pump_cooldown_seconds": 600})
    last = rig.clock.now()
    rig.service.ledger.set_meta(META_LAST_IRRIGATION, str(last))
    rig.clock.advance(120)
    exc = refusal(rig.service._check_cooldown)
    check(exc, "cooldown", "irrigation_too_soon", {"wait_seconds": 480, "ready_at": last + 600})


async def test_request_id_reused_carries_the_request_id(rig):
    number = rig.manual_right()
    first = rig.request(number, Channel.PUMP, 1, request_id="same")
    await rig.service.irrigate(first, PUMP_SECONDS)
    again = rig.request(number, Channel.PUMP, 1, request_id="same")
    exc = await refusal_of(rig.service.irrigate(again, PUMP_SECONDS * 2))
    check(exc, "request_id_reused", "request_id_reused", {"request_id": "same"})


# --- state of the service and the link ----------------------------------------------------------


async def test_still_starting_carries_nothing(build):
    rig = await build(start=False)
    number = rig.stage_right()
    exc = await refusal_of(rig.service.submit(rig.request(number, Channel.LIGHT, 20)))
    check(exc, "unsettled", "still_starting", {})


async def test_pump_unconfirmed_carries_the_device(rig):
    from growbridge.control.ledger import FLAG_INTERLOCK

    number = rig.stage_right()
    rig.service.ledger.set_flag(FLAG_INTERLOCK, True)
    exc = await refusal_of(rig.service.submit(rig.request(number, Channel.LIGHT, 20)))
    check(exc, "interlock", "pump_unconfirmed", {"device_id": DEVICE})


async def test_old_path_running_carries_nothing(rig):
    from growbridge.control.ledger import FLAG_TRANSPORT_STOPPED

    number = rig.stage_right()
    rig.service.ledger.set_flag(FLAG_TRANSPORT_STOPPED, False)
    exc = await refusal_of(rig.service.submit(rig.request(number, Channel.LIGHT, 20)))
    check(exc, "unsettled", "old_path_running", {})


async def test_unknown_result_carries_the_count(rig, monkeypatch):
    number = rig.stage_right()
    pending = [object(), object()]
    monkeypatch.setattr(rig.service.ledger, "unsettled", lambda: pending)
    exc = await refusal_of(rig.service.submit(rig.request(number, Channel.LIGHT, 20)))
    check(exc, "unsettled", "unknown_result", {"count": 2})


async def test_no_live_link_carries_the_device(rig, monkeypatch):
    number = rig.stage_right()
    monkeypatch.setattr(type(rig.bridge), "connected", property(lambda _self: False))
    exc = await refusal_of(rig.service.submit(rig.request(number, Channel.LIGHT, 20)))
    check(exc, "not_connected", "no_live_link", {"device_id": DEVICE})


async def test_stale_carries_the_device_and_the_age(rig):
    number = rig.stage_right()
    rig.clock.advance(1000)
    exc = await refusal_of(rig.service.submit(rig.request(number, Channel.LIGHT, 20)))
    assert (exc.code, exc.reason) == ("stale", "stale")
    assert exc.params["device_id"] == DEVICE and exc.params["age_seconds"] > 900


async def test_state_unreadable_carries_the_device_and_the_cause(rig, monkeypatch):
    async def broken(_now):
        raise ConnectionError("link lost")

    monkeypatch.setattr(rig.service.device, "read_state", broken)
    exc = await refusal_of(rig.service.read_state())
    check(exc, "not_connected", "state_unreadable", {"device_id": DEVICE, "detail": "link lost"})
