"""The input guard keeps a model from sending another project's or held-out data to CSC."""

from types import SimpleNamespace

import pytest

from growbridge.archive import snapshot as snapshots
from growbridge.archive.db import Database
from growbridge.archive.models import ManualMeasurement, SampleRecord
from growbridge.archive.store import Archive
from growbridge.ports import Denied
from growbridge.runtime_compute import install_input_guard
from growbridge.sim.clock import START, FakeClock


def sample(experiment, second):
    return SampleRecord(
        id=f"s-{experiment}-{second}",
        experiment_id=experiment,
        stage_id="stage-1",
        device_id="SIMULATED",
        captured_at=START + second,
        received_at=START + second,
        clock_synced=True,
        data={"temp": 21.0},
    )


def measurement(experiment, batch):
    return ManualMeasurement(
        id=f"m-{experiment}-{batch}",
        experiment_id=experiment,
        batch=batch,
        plant_id="p1",
        layout_version="v1",
        measured_at=START + 1,
        position="tent-1",
        method="ruler",
        metric="yield_g",
        value=1.0,
        unit="g",
        operator="op-1",
    )


class Holdout:
    """Only what ``refuse_holdout_rows`` asks of a registry."""

    @staticmethod
    def development_filter(project_id):
        return lambda row: row.batch != "held"


@pytest.fixture
def world(tmp_path):
    clock = FakeClock()
    db = Database(tmp_path / "archive.sqlite3")
    archive = Archive(db, tmp_path / "archive", clock)
    stages = [
        SimpleNamespace(project_id="p1", experiment_id="exp-a"),
        SimpleNamespace(project_id="p2", experiment_id="exp-b"),
    ]
    runtime = SimpleNamespace(
        workflow=SimpleNamespace(
            store=SimpleNamespace(stages_in=lambda states: tuple(stages)),
            clock=clock,
        ),
        control=None,
        archive=archive,
        tasks=SimpleNamespace(get=lambda task_id: SimpleNamespace(id=task_id, project_id="p1")),
        clock=clock,
        holdout=Holdout(),
        compute=SimpleNamespace(input_guard=None),
    )

    def freeze(experiment, rows=()):
        for second in range(11):
            archive.append_sample(sample(experiment, second))
        for row in rows:
            archive.add_measurement(row)
        shot = snapshots.freeze(archive, experiment, clock, START, START + 10, 1, 120)
        return shot.id

    yield SimpleNamespace(runtime=runtime, freeze=freeze, archive=archive)
    db.close()


def guard_of(world):
    install_input_guard(world.runtime)
    return world.runtime.compute.input_guard


def test_guard_accepts_a_verified_snapshot_of_the_tasks_project(world):
    snapshot = world.freeze("exp-a")
    guard_of(world)("task-1", f"{snapshot}/samples.jsonl")  # no error


def test_guard_accepts_the_snapshot_directory_itself(world):
    snapshot = world.freeze("exp-a")
    guard_of(world)("task-1", snapshot)


def test_guard_refuses_another_projects_snapshot(world):
    snapshot = world.freeze("exp-b")
    with pytest.raises(Denied) as info:
        guard_of(world)("task-1", f"{snapshot}/samples.jsonl")
    assert info.value.code == "scope"


def test_guard_refuses_an_unknown_snapshot_the_same_way(world):
    with pytest.raises(Denied) as info:
        guard_of(world)("task-1", "snap-nope/samples.jsonl")
    assert info.value.code == "scope"


def test_guard_refuses_a_snapshot_holding_held_out_outcomes(world):
    snapshot = world.freeze("exp-a", rows=[measurement("exp-a", "held")])
    with pytest.raises(Denied) as info:
        guard_of(world)("task-1", f"{snapshot}/measurements.jsonl")
    assert info.value.code == "scope"
    assert "held-out" in str(info.value)


def test_guard_refuses_a_snapshot_that_fails_verification(world):
    snapshot = world.freeze("exp-a")
    path = world.archive.root / "snapshots" / snapshot / "samples.jsonl"
    path.write_text(path.read_text() + "tampered\n")
    with pytest.raises(Denied) as info:
        guard_of(world)("task-1", f"{snapshot}/samples.jsonl")
    assert info.value.code == "snapshot_incomplete"
    assert info.value.reason == "snapshot_fails_verification"
    assert info.value.params == {"snapshot_id": snapshot}


def test_guard_without_a_compute_service_is_a_no_op(world):
    world.runtime.compute = None
    install_input_guard(world.runtime)  # nothing to guard, nothing raised


def test_snapshot_invalidated_carries_the_snapshot_through_the_guard(world):
    snapshot = world.freeze("exp-a")
    world.archive.is_invalid = lambda snapshot_id: True
    with pytest.raises(Denied) as info:
        guard_of(world)("task-1", f"{snapshot}/samples.jsonl")
    assert (info.value.code, info.value.reason) == ("state", "snapshot_invalidated")
    assert info.value.params == {"snapshot_id": snapshot}
