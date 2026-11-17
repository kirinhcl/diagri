"""The choice an operator makes after a stage stops, and who aborted a round, are recorded."""

import pytest

from growbridge.ports import Denied

TWO = ("vegetative", "flowering")


async def stopped_round(world):
    await world.design(TWO)
    await world.running()
    await world.svc.stop_stage("stage-1", world.op)


async def choose(world, choice):
    return await world.svc.choose_after_stop(world.round_id, choice, world.op)


@pytest.mark.parametrize("choice", ["redo", "next", "verify"])
async def test_choice_is_recorded_with_its_operator(world, choice):
    await stopped_round(world)
    await choose(world, choice)

    (row,) = world.svc.store.choices(world.round_id)
    assert (row["choice"], row["by"], row["stage_id"]) == (choice, world.op.id, "stage-1")


async def test_abort_through_the_choice_is_recorded_once(world):
    await stopped_round(world)
    await choose(world, "abort")

    assert [r["choice"] for r in world.svc.store.choices(world.round_id)] == ["abort"]


async def test_direct_abort_is_recorded(world):
    await world.design(TWO)
    await world.svc.abort_round(world.round_id, world.op)

    (row,) = world.svc.store.choices(world.round_id)
    assert (row["choice"], row["by"], row["stage_id"]) == ("abort", world.op.id, None)


async def test_a_refused_choice_records_nothing(world):
    await world.design(TWO)
    with pytest.raises(Denied):
        await choose(world, "redo")

    assert world.svc.store.choices(world.round_id) == ()
