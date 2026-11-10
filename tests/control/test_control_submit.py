import re

import pytest

from growbridge.archive.models import LEVEL_RANGES, ActionState, Channel, RightKind, RuleAction
from growbridge.ports import Denied, Difference, RightScope

DEVICE = "SIMULATED"


async def test_control_write_reads_back_level_and_manual_mode(rig):
    rig.sim.external_change("device", "light", modeType=1)  # the panel put it on a timer
    number = rig.stage_right()
    record = await rig.service.submit(rig.request(number, Channel.LIGHT, 40, "w1"))
    assert record.state is ActionState.CONFIRMED
    assert record.confirmed_level == 40
    assert record.right_kind is RightKind.STAGE and record.right_number == number
    assert record.sent_at is not None and record.confirmed_at is not None
    assert rig.sim.config["device"]["light"]["modeType"] == 0
    assert rig.sim.config["device"]["light"]["mLevel"] == 40
    assert rig.writes()[-1]["params"]["keyPath"] == ["device", "light"]
    assert rig.sink.actions[-1] == record


@pytest.mark.parametrize(
    "channel,key,level",
    [(Channel.EXHAUST, "blower", 35), (Channel.FAN, "fan", 4)],
)
async def test_control_channel_maps_to_module(rig, channel, key, level):
    number = rig.stage_right()
    record = await rig.service.submit(rig.request(number, channel, level))
    assert record.state is ActionState.CONFIRMED
    assert rig.sim.config["device"][key]["mLevel"] == level
    assert rig.writes()[-1]["params"]["keyPath"] == ["device", key]


async def test_control_device_acknowledges_but_state_unchanged_is_failed(rig):
    rig.sim.ignore_writes = True
    number = rig.stage_right()
    record = await rig.service.submit(rig.request(number, Channel.LIGHT, 40))
    assert record.state is ActionState.FAILED
    assert record.error
    assert rig.service.unsettled_actions() == ()


async def test_control_device_rejection_is_failed(rig):
    original = rig.sim.send

    async def reject(command):
        if command["method"] == "setConfigField":
            rig.sim.emit({"method": "setConfigField", "msgId": command["msgId"], "code": 500})
            return
        await original(command)

    rig.sim.send = reject
    number = rig.stage_right()
    record = await rig.service.submit(rig.request(number, Channel.LIGHT, 40))
    assert record.state is ActionState.FAILED


async def test_control_lost_reply_is_unknown_and_unsettled(rig):
    rig.sim.lose_replies = True
    number = rig.stage_right()
    record = await rig.service.submit(rig.request(number, Channel.LIGHT, 40, "lost"))
    assert record.state is ActionState.UNKNOWN
    assert [item.request_id for item in rig.service.unsettled_actions()] == ["lost"]
    again = await rig.service.submit(rig.request(number, Channel.LIGHT, 40, "lost"))
    assert again == record and len(rig.writes()) == 1


async def test_control_retry_returns_original_receipt(rig):
    number = rig.stage_right()
    request = rig.request(number, Channel.LIGHT, 40, "same")
    first = await rig.service.submit(request)
    commands = len(rig.sim.commands)
    second = await rig.service.submit(request)
    assert second == first
    assert len(rig.sim.commands) == commands  # nothing was sent again
    assert rig.service.receipt("same") == first
    assert rig.service.receipt("missing") is None


async def test_control_reused_request_id_with_other_arguments_is_denied(rig):
    number = rig.stage_right()
    await rig.service.submit(rig.request(number, Channel.LIGHT, 40, "same"))
    commands = len(rig.sim.commands)
    with pytest.raises(Denied) as error:
        await rig.service.submit(rig.request(number, Channel.LIGHT, 41, "same"))
    assert error.value.code == "request_id_reused"
    assert len(rig.sim.commands) == commands


async def test_control_write_outside_scope_is_denied(rig):
    number = rig.stage_right(channels=(Channel.LIGHT,))
    cases = [
        rig.request(number, Channel.EXHAUST, 30),  # channel not in the right
        rig.request(number, Channel.FAN, 11),  # above the channel range
        rig.request(number, Channel.LIGHT, -1),
        rig.request(number, Channel.LIGHT, 10, stage_id="stage-9"),  # another stage
    ]
    for request in cases:
        with pytest.raises(Denied) as error:
            await rig.service.submit(request)
        assert error.value.code == "scope"
        assert rig.service.receipt(request.request_id) is None
    assert rig.writes() == []


async def test_control_care_right_writes_only_listed_values(rig):
    levels = (RuleAction(channel=Channel.EXHAUST, level=30),)
    scope = RightScope(device_id=DEVICE, levels=levels, channels=(Channel.EXHAUST,))
    number = rig.service.grant(RightKind.CARE, scope)
    ok = await rig.service.submit(rig.request(number, Channel.EXHAUST, 30))
    assert ok.state is ActionState.CONFIRMED and ok.right_kind is RightKind.CARE
    for channel, level in [(Channel.EXHAUST, 31), (Channel.LIGHT, 30)]:
        with pytest.raises(Denied) as error:
            await rig.service.submit(rig.request(number, channel, level))
        assert error.value.code == "scope"


async def test_control_manual_right_is_bound_to_its_operator(rig):
    number = rig.manual_right(channels=(Channel.LIGHT,), operator="alice")
    with pytest.raises(Denied) as error:
        await rig.service.submit(rig.request(number, Channel.LIGHT, 10, operator="mallory"))
    assert error.value.code == "scope"
    record = await rig.service.submit(rig.request(number, Channel.LIGHT, 10, operator="alice"))
    assert record.operator == "alice"


async def test_control_submit_never_switches_pump_on(rig):
    stage = rig.stage_right(channels=(Channel.PUMP,))
    with pytest.raises(Denied) as error:
        await rig.service.submit(rig.request(stage, Channel.PUMP, 1))
    assert error.value.code == "pump_on_forbidden"
    assert rig.writes() == []
    off = await rig.service.submit(rig.request(stage, Channel.PUMP, 0))
    assert off.state is ActionState.CONFIRMED
    assert rig.writes()[-1]["params"]["keyPath"] == ["outlet", "O4"]


async def test_control_refuses_without_connection_fresh_data_or_permission(rig, settings):
    number = rig.stage_right()
    rig.clock.advance(100)
    with pytest.raises(Denied) as error:
        await rig.service.submit(rig.request(number, Channel.LIGHT, 10))
    assert error.value.code == "stale"
    await rig.refresh()
    rig.bridge.settings = settings.model_copy(update={"controls_enabled": False})
    with pytest.raises(Denied) as error:
        await rig.service.submit(rig.request(number, Channel.LIGHT, 10))
    assert error.value.code == "controls_disabled"
    rig.bridge.settings = settings
    rig.sim.drop(refuse_connect=True)
    assert rig.service.connected() is False
    with pytest.raises(Denied) as error:
        await rig.service.submit(rig.request(number, Channel.LIGHT, 10))
    assert error.value.code == "not_connected"
    assert rig.writes() == []


async def test_control_differences_find_panel_changes(rig):
    number = rig.stage_right()
    await rig.service.submit(rig.request(number, Channel.LIGHT, 60))
    expected = {Channel.LIGHT: 60, Channel.FAN: 1}
    assert await rig.service.differences(expected) == ()
    rig.sim.external_change("device", "light", modeType=1)
    rig.sim.external_change("device", "fan", mLevel=5)
    found = await rig.service.differences(expected)
    assert set(found) == {
        Difference(channel=Channel.LIGHT, field="mode", expected=0, actual=1),
        Difference(channel=Channel.FAN, field="level", expected=1, actual=5),
    }
    rig.sim.external_change("device", "light", modeType=0, mLevel=20)
    levels = await rig.service.differences({Channel.LIGHT: 60})
    assert levels == (Difference(channel=Channel.LIGHT, field="level", expected=60, actual=20),)


async def test_control_read_state_reports_levels_and_modes(rig):
    state = await rig.service.read_state()
    assert state.levels[Channel.LIGHT] == 20 and state.levels[Channel.PUMP] == 0
    assert state.modes[Channel.LIGHT] == 0 and state.modes[Channel.PUMP] == 0
    assert state.at == rig.clock.now()


async def test_control_capabilities_version_follows_wiring(rig, settings):
    caps = rig.service.capabilities()
    assert re.fullmatch(r"[0-9a-f]{16}", caps.version)
    assert caps.level_ranges == LEVEL_RANGES
    assert caps.outlets == {
        Channel.LIGHT: 1,
        Channel.EXHAUST: 2,
        Channel.FAN: 3,
        Channel.PUMP: 4,
    }
    assert caps.sensors["humi"] == "%"
    rig.bridge.settings = settings.model_copy(update={"pump_outlet": 5})
    assert rig.service.capabilities().version != caps.version


async def test_control_readings_carry_receive_times(rig):
    readings = {item.sensor: item for item in rig.service.readings()}
    assert readings["temp"].value == 22.5 and readings["temp"].unit == "C"
    assert readings["temp"].at == rig.clock.now() and readings["temp"].mono == rig.clock.mono
    rig.clock.advance(30)
    rig.sim.set_sensor("humi", None)
    await rig.refresh()
    later = {item.sensor: item for item in rig.service.readings()}
    assert "humi" not in later
    assert later["temp"].mono == rig.clock.mono
