"""The runtime's holdout registry is wired to the project's real data: the register-before-
outcomes rule holds on the assembled daemon, not only on a registry built by a test."""

import pytest
from e2e_support import STAGE

from growbridge.archive.models import ManualMeasurement
from growbridge.ports import Denied

DEV = ("dev-1", "dev-2")


def outcome(batch: str, metric: str = "yield_g") -> ManualMeasurement:
    return ManualMeasurement(
        id="m-1",
        experiment_id=f"experiment-{STAGE}",
        batch=batch,
        plant_id="plant-1",
        layout_version="layout-1",
        measured_at=1.0,
        position="tent-1",
        method="ruler",
        metric=metric,
        value=1.0,
        unit="g",
        operator="op-1",
    )


async def test_the_assembled_runtime_refuses_a_holdout_whose_outcomes_exist(world):
    runtime = await world.boot()
    project, _round = world.designed_stage(runtime)
    runtime.archive.add_measurement(outcome("b3"))

    with pytest.raises(Denied) as caught:
        runtime.holdout.register(project, "h1", ("b3",), ("yield_g",), DEV)

    assert caught.value.code == "state"
    assert runtime.holdout.holdouts(project) == ()


async def test_the_assembled_runtime_registers_a_holdout_before_its_outcomes(world):
    runtime = await world.boot()
    project, _round = world.designed_stage(runtime)
    runtime.archive.add_measurement(outcome("b1"))  # a development batch: not in the way

    runtime.holdout.register(project, "h1", ("b3",), ("yield_g",), DEV)

    assert [h.holdout_id for h in runtime.holdout.holdouts(project)] == ["h1"]
