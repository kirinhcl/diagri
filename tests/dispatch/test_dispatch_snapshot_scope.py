"""A snapshot, round or task named by the model must belong to the project of its task."""

import json

import pytest
from dispatch_helpers import call, script_calls

from growbridge.archive import snapshot as snapshots
from growbridge.archive.models import ManualMeasurement, SampleRecord
from growbridge.research.holdout import HoldoutRegistry
from growbridge.research.sandbox import SandboxResult
from growbridge.sim.clock import START
from growbridge.sim.llm import ScriptedClient
from growbridge.workflow.states import RoundState

HOLDOUT_VALUE = 987.5


class RecordingSandbox:
    def __init__(self):
        self.calls = []

    def run(self, script, snapshot_dir, out_dir, timeout):
        self.calls.append(snapshot_dir)
        return SandboxResult(exit_code=0, stdout="ok", stderr="", timed_out=False)


def _measurement(experiment_id: str, value: float, ident: str, batch: str = "batch-1"):
    return ManualMeasurement(
        id=ident,
        experiment_id=experiment_id,
        batch=batch,
        plant_id="p1",
        layout_version="v1",
        measured_at=START + 1,
        position="tent-1",
        method="ruler",
        metric="canopy_area_growth",
        value=value,
        unit="cm2",
        operator="op-1",
    )


def _freeze(env, experiment_id: str, rows=(), keep=None) -> str:
    for second in range(11):
        env.archive.append_sample(
            SampleRecord(
                id=f"s-{experiment_id}-{second}",
                experiment_id=experiment_id,
                stage_id="stage-1",
                device_id="SIMULATED",
                captured_at=START + second,
                received_at=START + second,
                clock_synced=True,
                data={"temp": 21.0},
            )
        )
    for row in rows:
        env.archive.add_measurement(row)
    shot = snapshots.freeze(
        env.archive, experiment_id, env.clock, START, START + 10, 1, 120, measurement_filter=keep
    )
    return shot.id


def _own_snapshot(env, **kw) -> str:
    env.stage_for("exp-a")
    return _freeze(env, "exp-a", **kw)


def _foreign_snapshot(env) -> str:
    env.other_project()
    return _freeze(env, "exp-b")


async def _analyse(env, task_id: str, snapshot_id: str, deps):
    return await env.invoke(
        "researcher",
        "run_local_analysis",
        deps,
        task_id=task_id,
        snapshot_id=snapshot_id,
        script="print(1)",
    )


@pytest.fixture
def spy_verify(monkeypatch):
    """Records every snapshot verification: it is the first thing that reads snapshot files."""
    seen: list[str] = []
    real = snapshots.verify

    def spy(archive, snapshot_id):
        seen.append(snapshot_id)
        return real(archive, snapshot_id)

    monkeypatch.setattr(snapshots, "verify", spy)
    return seen


# --- run_local_analysis ----------------------------------------------------------------------


async def test_a_snapshot_of_another_project_is_refused_before_anything_is_read(env, spy_verify):
    task = env.task("researcher")
    sandbox = RecordingSandbox()

    outcome = await _analyse(env, task.id, _foreign_snapshot(env), env.make_deps(sandbox=sandbox))

    assert outcome.is_error and "denied (scope)" in outcome.content
    assert sandbox.calls == [] and spy_verify == []


async def test_an_unknown_snapshot_is_refused_before_the_sandbox_starts(env, spy_verify):
    task = env.task("researcher")
    sandbox = RecordingSandbox()

    outcome = await _analyse(env, task.id, "snap-none", env.make_deps(sandbox=sandbox))

    assert outcome.is_error and "denied (scope)" in outcome.content
    assert sandbox.calls == [] and spy_verify == []


async def test_a_snapshot_whose_experiment_has_no_stage_is_refused(env, spy_verify):
    task = env.task("researcher")
    sandbox = RecordingSandbox()
    orphan = _freeze(env, "exp-orphan")

    outcome = await _analyse(env, task.id, orphan, env.make_deps(sandbox=sandbox))

    assert outcome.is_error and "denied (scope)" in outcome.content
    assert sandbox.calls == [] and spy_verify == []


async def test_a_call_without_a_task_id_is_rejected_by_the_schema(env):
    sandbox = RecordingSandbox()
    snapshot_id = _own_snapshot(env)

    outcome = await env.invoke(
        "researcher",
        "run_local_analysis",
        env.make_deps(sandbox=sandbox),
        snapshot_id=snapshot_id,
        script="print(1)",
    )

    assert outcome.is_error and "invalid input" in outcome.content and sandbox.calls == []


async def test_a_task_of_another_role_cannot_mount_a_snapshot(env, spy_verify):
    task = env.task("planner")
    sandbox = RecordingSandbox()

    outcome = await _analyse(env, task.id, _own_snapshot(env), env.make_deps(sandbox=sandbox))

    assert outcome.is_error and "denied (scope)" in outcome.content
    assert sandbox.calls == [] and spy_verify == []


async def test_an_unknown_task_cannot_mount_a_snapshot(env, spy_verify):
    sandbox = RecordingSandbox()

    outcome = await _analyse(env, "task-none", _own_snapshot(env), env.make_deps(sandbox=sandbox))

    assert outcome.is_error and sandbox.calls == [] and spy_verify == []


async def test_a_snapshot_of_the_tasks_own_project_still_runs(env):
    task = env.task("researcher")
    sandbox = RecordingSandbox()
    snapshot_id = _own_snapshot(env)

    outcome = await _analyse(env, task.id, snapshot_id, env.make_deps(sandbox=sandbox))

    assert not outcome.is_error and json.loads(outcome.content)["exit_code"] == 0
    assert sandbox.calls == [env.archive.root / "snapshots" / snapshot_id]


async def test_a_scripted_run_cannot_reach_a_foreign_snapshot(env):
    task = env.task("researcher")
    sandbox = RecordingSandbox()
    request = call(
        "run_local_analysis",
        task_id=task.id,
        snapshot_id=_foreign_snapshot(env),
        script="print(open('/etc/passwd').read())",
    )
    client = ScriptedClient(script_calls(request))

    run = await env.dispatcher(client, env.make_deps(sandbox=sandbox)).run_task(task.id)

    assert run is not None and run.tool_calls[0].is_error and sandbox.calls == []


# --- holdout data on the data path -----------------------------------------------------------


def _holdout(env) -> HoldoutRegistry:
    registry = HoldoutRegistry(env.db, env.clock)
    registry.register(env.project_id, "hold-1", ["batch-h"], ["canopy_area_growth"], 3)
    return registry


def _held_rows():
    return (_measurement("exp-a", HOLDOUT_VALUE, "m-hold", batch="batch-h"),)


async def test_an_unfiltered_snapshot_with_holdout_outcomes_is_refused(env):
    registry = _holdout(env)
    task = env.task("researcher")
    sandbox = RecordingSandbox()
    snapshot_id = _own_snapshot(env, rows=_held_rows())  # frozen without the development filter

    outcome = await _analyse(
        env, task.id, snapshot_id, env.make_deps(sandbox=sandbox, holdout=registry)
    )

    assert outcome.is_error and "denied (scope)" in outcome.content
    assert "987.5" not in outcome.content and sandbox.calls == []


async def test_a_snapshot_frozen_with_the_development_filter_is_allowed(env):
    registry = _holdout(env)
    task = env.task("researcher")
    sandbox = RecordingSandbox()
    keep = registry.development_filter(env.project_id)
    snapshot_id = _own_snapshot(env, rows=_held_rows(), keep=keep)

    outcome = await _analyse(
        env, task.id, snapshot_id, env.make_deps(sandbox=sandbox, holdout=registry)
    )

    assert not outcome.is_error and len(sandbox.calls) == 1


# --- publish_research_report -----------------------------------------------------------------

PUBLISH = {"treatment_id": "high", "next_round": "repeat"}


async def _publish(env, task_id: str, snapshot_id: str, deps=None, **extra):
    return await env.invoke(
        "researcher",
        "publish_research_report",
        deps,
        task_id=task_id,
        protocol_id=env.protocol.id,
        snapshots=[{"snapshot_id": snapshot_id, "round": 1}],
        **PUBLISH,
        **extra,
    )


async def test_publish_refuses_a_snapshot_of_another_project(env, spy_verify):
    task = env.task("researcher")

    outcome = await _publish(env, task.id, _foreign_snapshot(env))

    assert outcome.is_error and "denied (scope)" in outcome.content
    assert env.archive.artifacts(task.id) == () and spy_verify == []


async def test_publish_refuses_an_unfiltered_snapshot_with_holdout_outcomes(env):
    registry = _holdout(env)
    task = env.task("researcher")
    snapshot_id = _own_snapshot(env, rows=_held_rows())

    outcome = await _publish(env, task.id, snapshot_id, env.make_deps(holdout=registry))

    assert outcome.is_error and "denied (scope)" in outcome.content
    assert env.archive.artifacts(task.id) == ()


async def test_publish_refuses_a_round_of_another_project(env):
    task = env.task("researcher")
    _project_b, round_b = env.other_project()
    env.workflow.store.update_round(round_b, state=RoundState.ANALYSIS)
    snapshot_id = _own_snapshot(env)

    outcome = await _publish(env, task.id, snapshot_id, round_id=round_b)

    assert outcome.is_error and "denied (scope)" in outcome.content
    assert env.workflow.round_state(round_b) is RoundState.ANALYSIS
    assert env.archive.artifacts(task.id) == ()


# --- freeze_dataset --------------------------------------------------------------------------


async def _start_own_stage(env) -> None:
    """Stage-1 of the main project, started, with samples over its 10 s window."""
    env.workflow.submit_run_sheet(env.round_id, env.sheet(duration_seconds=10), env.operator)
    env.workflow.approve("stage-1", env.operator)
    await env.workflow.start_stage("stage-1", env.operator)
    for second in range(11):
        env.archive.append_sample(
            SampleRecord(
                id=f"s-own-{second}",
                experiment_id="experiment-stage-1",
                stage_id="stage-1",
                device_id="SIMULATED",
                captured_at=START + second,
                received_at=START + second,
                clock_synced=True,
                data={"temp": 21.0},
            )
        )


@pytest.mark.parametrize("with_round", [True, False])
async def test_freeze_of_a_stage_of_another_project_is_refused_and_writes_nothing(env, with_round):
    task = env.task("researcher")
    _project_b, round_b = env.other_project()
    env.workflow.store.update_round(round_b, state=RoundState.DATA_VERIFICATION)
    extra = {"round_id": round_b} if with_round else {}

    outcome = await env.invoke(
        "researcher", "freeze_dataset", task_id=task.id, stage_id="stage-b", **extra
    )

    assert outcome.is_error and "denied (scope)" in outcome.content
    assert env.archive.snapshots("exp-b") == ()
    assert env.workflow.round_state(round_b) is RoundState.DATA_VERIFICATION


async def test_freeze_with_a_round_of_another_project_is_refused(env):
    task = env.task("researcher")
    await _start_own_stage(env)
    _project_b, round_b = env.other_project()
    env.workflow.store.update_round(round_b, state=RoundState.DATA_VERIFICATION)

    outcome = await env.invoke(
        "researcher", "freeze_dataset", task_id=task.id, stage_id="stage-1", round_id=round_b
    )

    assert outcome.is_error and "denied (scope)" in outcome.content
    assert env.archive.snapshots("experiment-stage-1") == ()
    assert env.workflow.round_state(round_b) is RoundState.DATA_VERIFICATION


@pytest.mark.parametrize("owner", ["planner", "orchestrator"])
async def test_freeze_for_a_task_of_another_role_is_refused(env, owner):
    task = env.task(owner)
    await _start_own_stage(env)

    outcome = await env.invoke("researcher", "freeze_dataset", task_id=task.id, stage_id="stage-1")

    assert outcome.is_error and env.archive.snapshots("experiment-stage-1") == ()


async def test_freeze_for_an_unknown_task_is_refused(env):
    await _start_own_stage(env)

    outcome = await env.invoke(
        "researcher", "freeze_dataset", task_id="task-none", stage_id="stage-1"
    )

    assert outcome.is_error and env.archive.snapshots("experiment-stage-1") == ()


async def test_freeze_without_a_task_id_is_rejected_by_the_schema(env):
    await _start_own_stage(env)

    outcome = await env.invoke("researcher", "freeze_dataset", stage_id="stage-1")

    assert outcome.is_error and "invalid input" in outcome.content
    assert env.archive.snapshots("experiment-stage-1") == ()


async def test_freeze_of_an_own_stage_still_works_and_advances_the_round(env):
    task = env.task("researcher")
    await _start_own_stage(env)
    env.workflow.store.update_round(env.round_id, state=RoundState.DATA_VERIFICATION)

    outcome = await env.invoke(
        "researcher", "freeze_dataset", task_id=task.id, stage_id="stage-1", round_id=env.round_id
    )

    body = json.loads(outcome.content)
    assert not outcome.is_error and body["complete"] is True
    assert env.workflow.round_state(env.round_id) is RoundState.ANALYSIS
