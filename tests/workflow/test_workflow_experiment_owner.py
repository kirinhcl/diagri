"""An experiment id belongs to one project: another project's run sheet may not reuse it."""

import pytest

from growbridge.ports import Denied
from growbridge.sim.fixtures import make_protocol, make_run_sheet


def _second_project(world) -> tuple[str, str]:
    project = world.svc.create_project("other", world.op)
    protocol = make_protocol(project_id=project, id="protocol-2")
    world.svc.save_protocol(protocol, world.op)
    return project, world.svc.create_round(project, protocol.id, world.op)


def _sheet(project: str, stage_id: str, experiment_id: str):
    return make_run_sheet(
        id=f"sheet-{stage_id}",
        project_id=project,
        protocol_id="protocol-2",
        stage_id=stage_id,
        experiment_id=experiment_id,
    )


async def test_a_run_sheet_reusing_another_projects_experiment_id_is_denied(world):
    await world.pending("stage-1")  # project 1 owns experiment-stage-1
    project, round_id = _second_project(world)

    with pytest.raises(Denied) as denied:
        world.svc.submit_run_sheet(
            round_id, _sheet(project, "stage-x", "experiment-stage-1"), world.op
        )

    assert denied.value.code == "scope"
    assert world.svc.store.find_stage("stage-x") is None


async def test_the_owner_is_checked_for_a_replacement_sheet_too(world):
    await world.pending("stage-1")
    project, round_id = _second_project(world)
    world.svc.submit_run_sheet(round_id, _sheet(project, "stage-y", "experiment-y"), world.op)
    swapped = _sheet(project, "stage-y", "experiment-stage-1").model_copy(update={"version": 2})

    with pytest.raises(Denied) as denied:
        world.svc.submit_run_sheet(round_id, swapped, world.op)

    assert denied.value.code == "scope"


async def test_one_project_may_reuse_its_own_experiment_id(world):
    await world.pending("stage-1")

    world.svc.submit_run_sheet(
        world.round_id, world.sheet("stage-2", experiment_id="experiment-stage-1"), world.op
    )

    assert world.svc.store.find_stage("stage-2") is not None


async def test_a_fresh_experiment_id_in_another_project_is_accepted(world):
    await world.pending("stage-1")
    project, round_id = _second_project(world)

    world.svc.submit_run_sheet(round_id, _sheet(project, "stage-z", "experiment-z"), world.op)

    assert world.svc.store.find_stage("stage-z") is not None
