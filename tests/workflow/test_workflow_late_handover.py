"""A command that waited on the device must not hand over rights once its stage has changed.

``ControlService.handover`` ends the device's current irrigation cycle whatever right it is given,
so a late hand-over from a request that lost the race would cut short whatever now runs on the
device. The workflow re-reads the stage before every hand-over and refuses instead.
"""

import pytest

from growbridge.ports import Denied


async def _stop_while_waiting(world, method: str) -> None:
    """Make ``method`` of the fake control stop stage-1 the first time it is awaited."""
    original = getattr(world.control, method)

    async def racing(*args, **kwargs):
        setattr(world.control, method, original)
        await world.svc.stop_stage("stage-1", world.op)
        return await original(*args, **kwargs)

    setattr(world.control, method, racing)


async def test_late_handback_does_not_hand_over(world):
    await world.running("stage-1")
    await world.svc.takeover("stage-1", world.op)
    manual = world.svc.stage("stage-1").manual_right
    await _stop_while_waiting(world, "differences")

    with pytest.raises(Denied) as denied:
        await world.svc.handback("stage-1", world.op, False)

    assert denied.value.code == "state"
    assert (manual, "handback") not in world.control.handovers
    assert world.state("stage-1") == "stopped"


async def test_late_takeover_does_not_hand_over(world):
    await world.running("stage-1")
    stage_right = world.svc.stage("stage-1").right_number
    await _stop_while_waiting(world, "reconcile_unsettled")

    with pytest.raises(Denied) as denied:
        await world.svc.takeover("stage-1", world.op)

    assert denied.value.code == "state"
    assert (stage_right, "operator takeover") not in world.control.handovers
    assert world.state("stage-1") == "stopped"
