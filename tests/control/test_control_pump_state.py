"""The control service's read-only pump accessors: read-back, irrigation state, pump-off trigger."""

import asyncio
from types import SimpleNamespace

import pytest

from growbridge.archive.models import Channel
from growbridge.control.device import DeviceIO


async def wait_until(predicate, attempts=200):
    for _ in range(attempts):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not reached")


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"outlet": {"O4": {"on": 1}}}, True),
        ({"outlet": {"O4": {"on": 0}}}, False),
        ({"outlet": {}}, None),
        ({"outlet": {"O4": "x"}}, None),
        ({}, None),
        ({"outlet": None}, None),
        ({"outlet": "x"}, None),
        ({"outlet": {"O4": {"on": "0"}}}, None),
        ({"outlet": {"O4": {"on": 2}}}, True),
        ({"outlet": {"O4": {"on": 1.0}}}, True),
        ({"outlet": {"O4": {"on": 0.0}}}, False),
        ({"outlet": {"O4": {"on": float("nan")}}}, None),
        ({"outlet": {"O4": {"on": float("inf")}}}, None),
        ({"outlet": {"O4": {"on": None}}}, None),
        ({"outlet": {"O4": {"on": True}}}, True),
        ({"outlet": {"O4": {"on": False}}}, False),
    ],
)
def test_pump_on_reads_the_pump_outlet(data, expected):
    bridge = SimpleNamespace(settings=SimpleNamespace(pump_outlet=4))
    assert DeviceIO(bridge).pump_on(data) is expected


@pytest.mark.parametrize(
    "data",
    [{"outlet": {"O4": {}}}, {"outlet": None}, {"outlet": {"O4": {"on": "x"}}}, {}],
)
def test_levels_from_leaves_a_malformed_pump_outlet_out(data):
    bridge = SimpleNamespace(settings=SimpleNamespace(pump_outlet=4))
    assert Channel.PUMP not in DeviceIO(bridge).levels_from(data)


def test_levels_from_reads_a_well_formed_pump_outlet():
    bridge = SimpleNamespace(settings=SimpleNamespace(pump_outlet=4))
    device = DeviceIO(bridge)
    assert device.levels_from({"outlet": {"O4": {"on": 1}}})[Channel.PUMP] == 1
    assert device.levels_from({"outlet": {"O4": {"on": 0}}})[Channel.PUMP] == 0


async def test_pump_reading_follows_the_panel(rig):
    rig.sim.external_change("outlet", "O4", mOnOff=1)
    await rig.refresh()
    reading = rig.service.pump_reading()
    assert reading.on is True
    assert reading.mono == rig.bridge.received_monotonic
    assert reading.at == rig.bridge.received_at


async def test_pump_reading_is_unknown_before_the_first_status(rig):
    rig.bridge.received_monotonic = 0.0
    reading = rig.service.pump_reading()
    assert (reading.on, reading.at, reading.mono) == (None, 0.0, 0.0)


async def test_irrigating_is_true_only_during_a_cycle(rig):
    number = rig.manual_right()
    assert rig.service.irrigating() is False
    task = asyncio.create_task(
        rig.service.irrigate(rig.request(number, Channel.PUMP, 1, "pump"), 0.3)
    )
    await wait_until(lambda: rig.service.irrigating())
    assert rig.service.irrigating() is True
    await task
    assert rig.service.irrigating() is False


async def test_last_cycle_end_is_set_once_the_pump_is_off(rig):
    number = rig.manual_right()
    assert rig.service.last_cycle_end() is None
    await rig.service.irrigate(rig.request(number, Channel.PUMP, 1, "pump"), 0.02)
    end = rig.service.last_cycle_end()
    assert end is not None
    assert end <= rig.clock.monotonic()


async def test_pump_off_records_its_trigger(rig):
    assert rig.service.last_pump_off_id() is None
    await rig.service.pump_off(trigger="watchdog")
    assert rig.service.receipt(rig.service.last_pump_off_id()).trigger == "watchdog"
    await rig.service.pump_off()
    assert rig.service.receipt(rig.service.last_pump_off_id()).trigger == "interlock"


async def test_cancelled_irrigation_does_not_latch_irrigating(rig):
    number = rig.manual_right((Channel.PUMP, Channel.LIGHT))
    release = asyncio.Event()
    original = rig.sim.send
    held = {"on": False}

    async def slow(command):
        is_field = command["method"] == "setConfigField"
        if is_field and command["params"]["keyPath"][1] != "O4" and held["on"]:
            await release.wait()
        await original(command)

    rig.sim.send = slow
    irrigation = asyncio.create_task(
        rig.service.irrigate(rig.request(number, Channel.PUMP, 1, "pump"), 0.05)
    )
    await wait_until(lambda: rig.service.irrigating())
    held["on"] = True
    blocker = asyncio.create_task(
        rig.service.submit(rig.request(number, Channel.LIGHT, 50, "light"))
    )
    await wait_until(lambda: rig.service.receipt("light") is not None)
    await asyncio.sleep(0.15)  # the timer ended; the pump-off now waits for the gate
    irrigation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await irrigation
    assert rig.service.irrigating() is False
    assert rig.service.interlocked() is True
    release.set()
    await asyncio.gather(blocker, return_exceptions=True)
