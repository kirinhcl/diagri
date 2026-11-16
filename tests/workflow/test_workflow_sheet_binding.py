"""A replacement run sheet keeps the stage's project, experiment and device.

Write rights are issued for the device the run sheet names, while every check that looks at the
stage reads the device on the stage row. A replacement that names another device would make the
two disagree, so it is refused like any other mismatched replacement.
"""

import pytest

from growbridge.ports import Denied


async def test_replacement_cannot_change_device(world):
    await world.pending("stage-1")

    with pytest.raises(Denied) as denied:
        world.svc.submit_run_sheet(
            world.round_id, world.sheet("stage-1", version=2, device_id="OTHER-DEVICE"), world.op
        )

    assert denied.value.code == "state"
    assert "keeps the stage's project, experiment and device" in str(denied.value)
    assert world.svc.stage("stage-1").run_sheet.version == 1


async def test_replacement_cannot_change_experiment(world):
    await world.pending("stage-1")

    with pytest.raises(Denied) as denied:
        world.svc.submit_run_sheet(
            world.round_id,
            world.sheet("stage-1", version=2, experiment_id="experiment-other"),
            world.op,
        )

    assert denied.value.code == "state"
    assert world.svc.stage("stage-1").run_sheet.version == 1


async def test_replacement_with_the_same_binding_is_still_accepted(world):
    await world.pending("stage-1")

    world.svc.submit_run_sheet(world.round_id, world.sheet("stage-1", version=2), world.op)

    assert world.svc.stage("stage-1").run_sheet.version == 2
