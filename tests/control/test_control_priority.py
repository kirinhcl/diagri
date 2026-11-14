import asyncio

import pytest

from growbridge.archive.models import ActionState, Channel, RightKind, RuleAction
from growbridge.control.priority_gate import NORMAL, URGENT
from growbridge.ports import Denied, RightScope
from growbridge.sim.fixtures import make_safety

DEVICE = "SIMULATED"
ALL = (Channel.PUMP, Channel.LIGHT, Channel.EXHAUST, Channel.FAN)


async def wait_for(predicate, attempts=400):
    for _ in range(attempts):
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition not reached")


def hang_first_field_write(rig):
    """Hold the first non-pump setConfigField until the returned event is set."""
    release = asyncio.Event()
    original = rig.sim.send
    state = {"hung": False}

    async def slow(command):
        is_field = command["method"] == "setConfigField"
        if is_field and command["params"]["keyPath"][1] != "O4" and not state["hung"]:
            state["hung"] = True
            await release.wait()
        await original(command)

    rig.sim.send = slow
    return release


def sent_order(rig):
    return [r.request_id for r in rig.sink.actions if r.state is ActionState.MAYBE_SENT]


async def hold_a(rig, number, channel=Channel.LIGHT):
    task = asyncio.create_task(rig.service.submit(rig.request(number, channel, 50, "a")))
    await wait_for(lambda: "a" in sent_order(rig))
    return task


async def test_protection_write_overtakes_queued_ordinary_writes(rig):
    number = rig.stage_right()
    rig.service.approve_safety(make_safety(), "alice")
    protection = rig.service.protection_right()
    release = hang_first_field_write(rig)
    first = await hold_a(rig, number)
    queued = [
        asyncio.create_task(rig.service.submit(rig.request(number, channel, level, name)))
        for name, channel, level in (("b", Channel.EXHAUST, 40), ("c", Channel.FAN, 5))
    ]
    await wait_for(lambda: all(rig.service.receipt(n) is not None for n in "bc"))
    urgent = asyncio.create_task(rig.service.submit(rig.request(protection, Channel.LIGHT, 0, "p")))
    await wait_for(lambda: rig.service.receipt("p") is not None)
    release.set()
    await asyncio.gather(first, urgent, *queued)
    assert sent_order(rig) == ["a", "p", "b", "c"]


async def test_irrigation_pump_off_overtakes_queued_writes(rig):
    number = rig.manual_right(ALL)
    release = hang_first_field_write(rig)
    irrigation = asyncio.create_task(
        rig.service.irrigate(rig.request(number, Channel.PUMP, 1, "pump"), 0.5)
    )
    await wait_for(lambda: rig.sim.config["outlet"]["O4"]["mOnOff"] == 1)
    first = await hold_a(rig, number)
    queued = [
        asyncio.create_task(rig.service.submit(rig.request(number, channel, level, name)))
        for name, channel, level in (("b", Channel.EXHAUST, 40), ("c", Channel.FAN, 5))
    ]
    await wait_for(lambda: all(rig.service.receipt(n) is not None for n in "bc"))
    # b, c and the pump-off (once the irrigation timer ends) are all queued behind a
    await wait_for(lambda: len(rig.service.gate._waiters) == 3)
    release.set()
    await asyncio.gather(irrigation, first, *queued)
    keys = [c["params"]["keyPath"][1] for c in rig.writes()]
    after_a = keys[keys.index("O4") + 1 :]
    assert after_a[0] != "O4" and after_a[1] == "O4", keys
    assert after_a.index("O4") == 1 and len(after_a) == 4, keys


async def test_handover_waits_only_for_the_write_in_flight(rig):
    stage = rig.stage_right()
    scope = RightScope(
        device_id=DEVICE,
        channels=(Channel.EXHAUST,),
        levels=(RuleAction(channel=Channel.EXHAUST, level=40),),
    )
    care = rig.service.grant(RightKind.CARE, scope)
    release = hang_first_field_write(rig)
    first = await hold_a(rig, stage)
    second = asyncio.create_task(rig.service.submit(rig.request(care, Channel.EXHAUST, 40, "b")))
    await wait_for(lambda: rig.service.receipt("b") is not None)

    async def hand_over_and_look():
        await rig.service.handover(stage, "test")
        return sent_order(rig)  # no await in between: b has not had a turn yet

    handover = asyncio.create_task(hand_over_and_look())
    await asyncio.sleep(0.05)
    release.set()
    assert "b" not in await handover
    await asyncio.gather(first, second, return_exceptions=True)


async def test_protection_and_irrigation_off_use_urgent(rig):
    seen = []
    real = rig.service.gate.acquire

    def recording(priority):
        seen.append(priority)
        return real(priority)

    rig.service.gate.acquire = recording
    protection = rig.service.approve_safety(make_safety(), "alice")
    await rig.service.submit(rig.request(protection, Channel.LIGHT, 0, "p"))
    assert seen == [URGENT]
    seen.clear()
    number = rig.manual_right()
    await rig.service.irrigate(rig.request(number, Channel.PUMP, 1, "pump"), 0.02)
    assert seen == [NORMAL, URGENT]


async def test_protection_write_voids_queued_ordinary_writes_on_its_channel(rig):
    number = rig.stage_right()
    rig.service.approve_safety(make_safety(), "alice")
    protection = rig.service.protection_right()
    release = hang_first_field_write(rig)
    first = await hold_a(rig, number)
    b = asyncio.create_task(rig.service.submit(rig.request(number, Channel.LIGHT, 3, "b")))
    c = asyncio.create_task(rig.service.submit(rig.request(number, Channel.EXHAUST, 40, "c")))
    await wait_for(lambda: all(rig.service.receipt(n) is not None for n in "bc"))
    urgent = asyncio.create_task(rig.service.submit(rig.request(protection, Channel.LIGHT, 0, "p")))
    await wait_for(lambda: rig.service.receipt("p") is not None)
    release.set()
    with pytest.raises(Denied) as error:
        await b
    assert error.value.code == "right_invalid"
    await asyncio.gather(first, urgent, c)
    assert rig.service.receipt("b").state is ActionState.VOID
    assert "protection" in rig.service.receipt("b").error
    assert rig.service.receipt("c").state is ActionState.CONFIRMED
    assert sent_order(rig) == ["a", "p", "c"]
    light = rig.sim.config["device"]["light"]
    assert light["mOnOff"] == 0 or light["mLevel"] == 0


async def test_protection_on_the_pump_voids_a_queued_irrigation(rig):
    scope = RightScope(
        device_id=DEVICE,
        levels=(RuleAction(channel=Channel.PUMP, level=0),),
    )
    config = make_safety(
        rules=(make_safety().rules[0].model_copy(update={"action": scope.levels[0]}),)
    )
    rig.service.approve_safety(config, "alice")
    protection = rig.service.protection_right()
    number = rig.manual_right(ALL)
    release = hang_first_field_write(rig)
    first = await hold_a(rig, number)
    irrigation = asyncio.create_task(
        rig.service.irrigate(rig.request(number, Channel.PUMP, 1, "pump"), 0.05)
    )
    await wait_for(lambda: rig.service.receipt("pump") is not None)
    urgent = asyncio.create_task(rig.service.submit(rig.request(protection, Channel.PUMP, 0, "p")))
    await wait_for(lambda: rig.service.receipt("p") is not None)
    release.set()
    with pytest.raises(Denied):
        await irrigation
    await asyncio.gather(first, urgent)
    assert rig.service.receipt("pump").state is ActionState.VOID
    pump_writes = [
        c["params"]["O4"]["mOnOff"] for c in rig.writes() if c["params"]["keyPath"][1] == "O4"
    ]
    assert 1 not in pump_writes
