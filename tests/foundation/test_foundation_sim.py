import pytest

from growbridge.archive.models import Channel, Entry
from growbridge.ports import ActionRequest, Actor, Denied, RightScope
from growbridge.sim.device import SimulatedTransport


def collect():
    frames = []
    return frames, frames.append


async def test_sensor_values_can_be_changed_and_removed():
    simulator = SimulatedTransport()
    simulator.set_sensor("temp", 31.5)
    simulator.set_sensor("co2", None)

    assert simulator.status()["sensor"] == {"temp": 31.5, "humi": 55}


async def test_external_change_edits_the_device_like_the_panel_would():
    simulator = SimulatedTransport()

    simulator.external_change("device", "light", modeType=1, mLevel=80)

    assert simulator.config["device"]["light"]["modeType"] == 1
    assert simulator.status()["light"]["level"] == 80


async def test_drop_disconnects_and_refuses_reconnect_until_restored():
    simulator = SimulatedTransport()
    _, callback = collect()
    await simulator.connect(callback)

    simulator.drop(refuse_connect=True)

    assert simulator.connected is False
    with pytest.raises(ConnectionError):
        await simulator.connect(callback)
    simulator.restore()
    await simulator.connect(callback)
    assert simulator.connected is True


async def test_lost_reply_still_applies_the_write():
    simulator = SimulatedTransport()
    frames, callback = collect()
    await simulator.connect(callback)
    seen = len(frames)
    simulator.lose_replies = True
    block = {"modeType": 0, "mOnOff": 1, "mLevel": 70}

    await simulator.send(
        {
            "method": "setConfigField",
            "msgId": "m1",
            "params": {"keyPath": ["device", "light"], "light": block},
        }
    )

    assert simulator.config["device"]["light"]["mLevel"] == 70
    assert len(frames) == seen


async def test_halt_reports_whether_old_writes_are_confirmed_stopped():
    simulator = SimulatedTransport()

    assert await simulator.halt() is True
    simulator.halt_confirmed = False
    assert await simulator.halt() is False


def test_ports_models_carry_authorization_inputs_only_as_data():
    actor = Actor(kind="model", id="planner", entry=Entry.OVERLAY)
    scope = RightScope(device_id="SIM", channels=(Channel.LIGHT,))
    request = ActionRequest(
        request_id="req-00000001", right_number=1, channel=Channel.LIGHT, level=40, trigger="t"
    )
    denied = Denied("scope", "channel outside the granted scope")

    assert actor.reauth_at is None and scope.levels == ()
    assert request.operator is None
    assert (denied.code, str(denied)) == ("scope", "channel outside the granted scope")
    assert str(Denied("right_invalid")) == "right_invalid"
