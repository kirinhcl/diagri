"""A planned irrigation runs while the stage keeps running: the executor must not take the pump
it switched on for an external change, and must see a real change afterwards."""

import asyncio

from executor_helpers import STAGE

from growbridge.archive.models import Channel, TimedAction
from growbridge.ports import ActionRequest, StageEventKind
from growbridge.sim.fixtures import make_run_sheet

KIND = StageEventKind
TIMED = (
    *make_run_sheet().timed_actions,
    TimedAction(id="pump-off", channel=Channel.PUMP, at="00:00", level=0),  # pump is "applied"
)


async def test_a_planned_irrigation_is_not_an_external_change(rig):
    await rig.at("10:00")
    await rig.start(timed_actions=TIMED)
    await rig.tick()
    stage = rig.svc.stage(STAGE)
    request = ActionRequest(
        request_id="planned-0001",
        right_number=stage.right_number,
        channel=Channel.PUMP,
        level=1,
        trigger="planned irrigation water",
        experiment_id=stage.experiment_id,
        stage_id=STAGE,
        operator="op-1",
    )

    run = asyncio.create_task(rig.control.irrigate(request, 0.3, planned=True))
    for _ in range(100):
        await asyncio.sleep(0.005)
        if rig.control.irrigating():
            break
    await rig.refresh()
    during = await rig.tick()
    record = await run

    assert record.state.value == "confirmed"
    assert KIND.EXTERNAL_CHANGE not in during.reported and rig.state() == "running"
    await rig.refresh()
    assert KIND.EXTERNAL_CHANGE not in (await rig.tick()).reported
    rig.sim.external_change("device", "light", mLevel=10)  # a real panel change still counts
    assert KIND.EXTERNAL_CHANGE in (await rig.tick()).reported


def _planned(stage) -> ActionRequest:
    return ActionRequest(
        request_id="planned-0002",
        right_number=stage.right_number,
        channel=Channel.PUMP,
        level=1,
        trigger="planned irrigation water",
        experiment_id=stage.experiment_id,
        stage_id=STAGE,
        operator="op-1",
    )


async def test_a_pump_switched_on_at_the_panel_without_an_irrigation_is_an_external_change(
    rig, monkeypatch
):
    """The pump is left out of the comparison only while an irrigation runs. The watchdog would
    switch the pump off before the comparison (its own tests cover that), so it is silenced here
    to see the comparison alone."""
    await rig.at("10:00")
    await rig.start(timed_actions=TIMED)
    await rig.tick()
    assert not rig.control.irrigating()

    async def silent(stage):
        return None

    monkeypatch.setattr(rig.engine.watchdog, "step", silent)
    rig.sim.external_change("outlet", "O4", mOnOff=1)
    await rig.refresh()

    assert KIND.EXTERNAL_CHANGE in (await rig.tick()).reported


async def test_another_channel_changed_during_an_irrigation_is_an_external_change(rig):
    await rig.at("10:00")
    await rig.start(timed_actions=TIMED)
    await rig.tick()

    run = asyncio.create_task(rig.control.irrigate(_planned(rig.svc.stage(STAGE)), 0.3, True))
    for _ in range(100):
        await asyncio.sleep(0.005)
        if rig.control.irrigating():
            break
    rig.sim.external_change("device", "light", mLevel=10)
    await rig.refresh()
    during = await rig.tick()
    await run

    assert KIND.EXTERNAL_CHANGE in during.reported
