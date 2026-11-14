"""The watchdog inside the executor: a pump found on by the panel is switched off and recorded."""

import asyncio

from executor_helpers import STAGE

from growbridge.archive.models import Channel
from growbridge.ports import ActionRequest, RightKind, RightScope


def panel_pump_on(rig):
    rig.sim.external_change("outlet", "O4", mOnOff=1)


async def let_it_see(rig):
    await rig.pass_time(5)
    await rig.tick()


def watering(rig):
    experiment = rig.svc.stage(STAGE).experiment_id
    return [i for i in rig.svc.interventions(experiment) if i["kind"] == "unexpected_watering"]


async def test_panel_pump_on_is_switched_off_and_recorded(rig):
    await rig.start()
    panel_pump_on(rig)
    await let_it_see(rig)
    assert (await rig.levels())[Channel.PUMP] == 0
    assert rig.control.receipt(rig.control.last_pump_off_id()).trigger == "watchdog"
    [item] = watering(rig)
    assert item["operator"] is None
    assert rig.state() == "running"


async def test_panel_pump_on_during_manual_takeover_is_switched_off(rig):
    await rig.start()
    await rig.svc.takeover(STAGE, rig.op)
    panel_pump_on(rig)
    await let_it_see(rig)
    assert (await rig.levels())[Channel.PUMP] == 0
    assert len(watering(rig)) == 1


async def test_panel_pump_on_while_paused_is_switched_off(rig):
    await rig.start()
    await rig.svc.pause_stage(STAGE, rig.op, "test")
    panel_pump_on(rig)
    await let_it_see(rig)
    assert (await rig.levels())[Channel.PUMP] == 0
    assert len(watering(rig)) == 1
    assert rig.state() == "paused"


async def test_disconnected_device_is_left_alone(rig):
    await rig.start()
    panel_pump_on(rig)
    await rig.pass_time(5)
    before = rig.control.last_pump_off_id()
    rig.sim.drop()
    await rig.tick()
    assert rig.control.last_pump_off_id() == before


async def test_unconfirmed_switch_off_hands_over_to_the_interlock(rig):
    await rig.start()
    rig.sim.fail_off = True
    panel_pump_on(rig)
    await let_it_see(rig)
    assert rig.control.interlocked()
    first = rig.control.last_pump_off_id()
    await rig.tick()
    assert rig.control.last_pump_off_id() != first
    assert rig.control.receipt(rig.control.last_pump_off_id()).trigger == "interlock"


async def test_watchdog_runs_without_a_stage(rig):
    panel_pump_on(rig)
    await let_it_see(rig)
    assert (await rig.levels())[Channel.PUMP] == 0
    assert rig.control.receipt(rig.control.last_pump_off_id()).trigger == "watchdog"


async def test_own_irrigation_is_left_alone_then_a_later_panel_on_is_caught(rig):
    await rig.start()
    await rig.svc.pause_stage(STAGE, rig.op, "test")
    scope = RightScope(device_id="SIMULATED", channels=(Channel.PUMP,))
    number = rig.control.grant(RightKind.MANUAL, scope, operator="alice")
    request = ActionRequest(
        request_id="irrigation-1",
        right_number=number,
        channel=Channel.PUMP,
        level=1,
        trigger="test",
        operator="alice",
    )
    task = asyncio.create_task(rig.control.irrigate(request, 0.4))
    await asyncio.sleep(0.1)
    await rig.pass_time(1)
    assert rig.control.irrigating() and rig.control.pump_reading().on is True
    await rig.tick()  # quiet during the operator's irrigation
    assert rig.control.last_pump_off_id() is None
    await task
    await rig.tick()  # quiet just after, before a fresh status
    assert rig.control.last_pump_off_id() is None
    await rig.pass_time(1)
    await rig.tick()
    assert rig.control.last_pump_off_id() is None and watering(rig) == []
    panel_pump_on(rig)  # a later panel switch-on is still caught
    await let_it_see(rig)
    assert rig.control.receipt(rig.control.last_pump_off_id()).trigger == "watchdog"
    assert len(watering(rig)) == 1


async def test_a_failing_pump_reading_does_not_stop_protection(rig, monkeypatch):
    await rig.start()
    reached = []
    real = rig.engine._protect

    async def protect(*args):
        reached.append(True)
        await real(*args)

    def broken():
        raise RuntimeError("bad status")

    monkeypatch.setattr(rig.engine, "_protect", protect)
    monkeypatch.setattr(rig.control, "pump_reading", broken)
    alerts = []
    rig.engine.watchdog.alert = lambda *args: alerts.append(args[:2] + args[3:])
    await rig.tick()
    assert reached
    assert ("pump_watchdog", "step", "critical") in alerts
