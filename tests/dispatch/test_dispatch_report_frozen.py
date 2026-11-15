"""Publishing a report when the protocol's analysis script is frozen: the pre-registered run of
every cited snapshot must have happened first, so a round is never delivered with an exploratory
conclusion by accident."""

import json

from growbridge.archive import snapshot as snapshots
from growbridge.archive.models import ManualMeasurement, SampleRecord
from growbridge.research.analysis import ConfirmatoryRunner
from growbridge.research.holdout import HoldoutRegistry
from growbridge.research.sandbox import SandboxResult
from growbridge.sim.clock import START
from growbridge.sim.fixtures import make_protocol

VALUES = (5.0, 4.0, 4.2, 5.5)  # rounds 1-4: high, control, control, high
FIELDS = {
    "treatment_id": "high",
    "evidence_chain": ["card-1"],
    "limitations": [],
    "next_round": "repeat",
    "unresolved": [],
}
SCRIPT = b"print('frozen analysis')\n"


class ScriptedSandbox:
    def __init__(self, exit_code: int = 0):
        self.exit_code = exit_code
        self.calls = 0

    def run(self, script, snapshot_dir, out_dir, timeout):
        self.calls += 1
        return SandboxResult(self.exit_code, "", "", False)


def _stage(env, name: str, version: int) -> None:
    """A stage of this project for experiment ``name``, in a round under ``version``."""
    if version == 1:
        env.stage_for(name)
        return
    round_id = env.workflow.create_round(env.project_id, env.protocol.id, env.operator)
    sheet = env.sheet(f"stage-of-{name}", experiment_id=name, protocol_version=version)
    env.workflow.submit_run_sheet(round_id, sheet, env.operator)


def _snapshot(env, number: int, value: float, holdout=None, version: int = 1) -> str:
    name = f"e{number}"
    _stage(env, name, version)
    for second in range(11):
        env.archive.append_sample(
            SampleRecord(
                id=f"s-{name}-{second}",
                experiment_id=name,
                stage_id="stage-1",
                device_id="SIMULATED",
                captured_at=START + second,
                received_at=START + second,
                clock_synced=True,
                data={"temp": 21.0},
            )
        )
    env.archive.add_measurement(
        ManualMeasurement(
            id=f"m{number}",
            experiment_id=name,
            batch="batch-1",
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
    )
    keep = None if holdout is None else holdout.development_filter(env.project_id)
    shot = snapshots.freeze(
        env.archive, name, env.clock, START, START + 10, 1, 2, measurement_filter=keep
    )
    return shot.id


def _rounds(env, holdout=None, versions=(1, 1, 1, 1)) -> list[dict]:
    return [
        {"snapshot_id": _snapshot(env, n, v, holdout, versions[n - 1]), "round": n}
        for n, v in enumerate(VALUES, 1)
    ]


def _save_v2(env):
    protocol = make_protocol(project_id=env.project_id, version=2)
    env.workflow.save_protocol(protocol, env.operator)
    return protocol


def _runner(env, tmp_path, exit_code: int = 0, freeze: bool = True) -> ConfirmatoryRunner:
    runner = ConfirmatoryRunner(env.db, env.clock, ScriptedSandbox(exit_code), tmp_path / "runs")
    if freeze:
        runner.freeze_analysis(env.protocol, SCRIPT, "alice")
    return runner


async def _run(env, runner, rounds, only=None) -> None:
    for item in rounds if only is None else rounds[:only]:
        snap = env.archive.snapshot(item["snapshot_id"])
        directory = env.archive.root / "snapshots" / snap.id
        await runner.run_frozen(env.protocol, snap, directory, "op-1")


async def _publish(env, task_id: str, rounds: list[dict], deps, **extra):
    fields = {"task_id": task_id, "protocol_id": env.protocol.id, **FIELDS, **extra}
    return await env.invoke(
        "researcher", "publish_research_report", deps, snapshots=rounds, **fields
    )


def _report(env, outcome) -> dict:
    artifact = env.archive.artifact(json.loads(outcome.content)["artifact_id"])
    with open(artifact.path) as handle:
        return json.load(handle)


async def test_publish_is_refused_while_no_frozen_run_has_happened(env, tmp_path):
    task = env.task("researcher")
    rounds = _rounds(env)
    deps = env.make_deps(runner=_runner(env, tmp_path))

    outcome = await _publish(env, task.id, rounds, deps)

    assert outcome.is_error
    assert rounds[0]["snapshot_id"] in outcome.content
    assert "POST /wb/analysis/runs" in outcome.content
    assert env.archive.artifacts(task.id) == ()


async def test_one_snapshot_without_its_run_is_enough_to_refuse(env, tmp_path):
    runner = _runner(env, tmp_path)
    task = env.task("researcher")
    rounds = _rounds(env)
    await _run(env, runner, rounds, only=3)
    deps = env.make_deps(runner=runner)

    outcome = await _publish(env, task.id, rounds, deps)

    assert outcome.is_error and rounds[3]["snapshot_id"] in outcome.content
    assert env.archive.artifacts(task.id) == ()


async def test_a_run_that_is_still_going_also_refuses(env, tmp_path):
    runner = _runner(env, tmp_path)
    task = env.task("researcher")
    rounds = _rounds(env)
    await _run(env, runner, rounds, only=3)
    env.db.execute(  # the fourth run is claimed and has not finished
        "INSERT INTO research_runs(id, protocol_id, protocol_version, snapshot_id, "
        "script_sha256, started_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            "run-live",
            env.protocol.id,
            env.protocol.version,
            rounds[3]["snapshot_id"],
            runner.frozen_script(env.protocol)[0],
            env.clock.now(),
        ),
    )
    assert runner.status(rounds[3]["snapshot_id"], env.protocol) == "running"

    outcome = await _publish(env, task.id, rounds, env.make_deps(runner=runner))

    assert outcome.is_error and "has not finished" in outcome.content
    assert env.archive.artifacts(task.id) == ()


async def test_after_every_run_succeeded_the_report_is_confirmatory(env, tmp_path):
    runner = _runner(env, tmp_path)
    task = env.task("researcher")
    rounds = _rounds(env)
    await _run(env, runner, rounds)

    outcome = await _publish(env, task.id, rounds, env.make_deps(runner=runner))

    assert not outcome.is_error
    assert _report(env, outcome)["label"] == "confirmatory"


async def test_a_failed_run_does_not_block_and_the_report_is_exploratory(env, tmp_path):
    runner = _runner(env, tmp_path, exit_code=1)
    task = env.task("researcher")
    rounds = _rounds(env)
    await _run(env, runner, rounds)

    outcome = await _publish(env, task.id, rounds, env.make_deps(runner=runner))

    assert not outcome.is_error
    assert _report(env, outcome)["label"] == "exploratory"


async def test_without_a_frozen_script_the_behaviour_is_unchanged(env, tmp_path):
    task = env.task("researcher")
    rounds = _rounds(env)
    deps = env.make_deps(runner=_runner(env, tmp_path, freeze=False))

    outcome = await _publish(env, task.id, rounds, deps)

    assert not outcome.is_error
    assert _report(env, outcome)["label"] == "exploratory"


async def test_a_refusal_does_not_use_up_the_holdout_read(env, tmp_path):
    registry = HoldoutRegistry(env.db, env.clock)
    registry.register(env.project_id, "hold-1", ("batch-9",), ("yield_g",), ("d-1", "d-2"))
    registry.register_model("hold-1", "model-sha", "features", "prep")
    task = env.task("researcher")
    rounds = _rounds(env, registry)
    deps = env.make_deps(runner=_runner(env, tmp_path), holdout=registry)

    outcome = await _publish(env, task.id, rounds, deps, holdout_id="hold-1", model_sha="model-sha")

    assert outcome.is_error
    assert registry.reads("hold-1") == []


async def test_after_an_interrupted_run_is_settled_the_report_is_published_as_exploratory(
    env, tmp_path
):
    runner = _runner(env, tmp_path)
    task = env.task("researcher")
    rounds = _rounds(env)
    await _run(env, runner, rounds, only=3)
    env.db.execute(  # the process died during the fourth run
        "INSERT INTO research_runs(id, protocol_id, protocol_version, snapshot_id, "
        "script_sha256, started_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            "run-live",
            env.protocol.id,
            env.protocol.version,
            rounds[3]["snapshot_id"],
            runner.frozen_script(env.protocol)[0],
            env.clock.now(),
        ),
    )
    deps = env.make_deps(runner=runner)
    assert (await _publish(env, task.id, rounds, deps)).is_error  # locked while "running"

    runner.settle_interrupted()
    outcome = await _publish(env, task.id, rounds, deps)

    assert not outcome.is_error
    assert _report(env, outcome)["label"] == "exploratory"


# --- a report is analysed under the protocol version its data was collected under --------------


async def test_a_report_of_v1_data_publishes_although_v2_froze_a_script_later(env, tmp_path):
    task = env.task("researcher")
    rounds = _rounds(env)  # collected under version 1, which never froze a script
    v2 = _save_v2(env)
    runner = _runner(env, tmp_path, freeze=False)
    runner.freeze_analysis(v2, b"print('version 2')\n", "alice")

    outcome = await _publish(env, task.id, rounds, env.make_deps(runner=runner))

    assert not outcome.is_error  # v2's missing runs say nothing about v1's data
    assert _report(env, outcome)["label"] == "exploratory"


async def test_a_v1_script_with_v1_runs_is_still_confirmatory_once_v2_exists(env, tmp_path):
    runner = _runner(env, tmp_path)  # freezes version 1
    task = env.task("researcher")
    rounds = _rounds(env)
    await _run(env, runner, rounds)
    v2 = _save_v2(env)
    runner.freeze_analysis(v2, b"print('version 2')\n", "alice")  # no run of version 2

    outcome = await _publish(env, task.id, rounds, env.make_deps(runner=runner))

    assert not outcome.is_error
    assert _report(env, outcome)["label"] == "confirmatory"


async def test_snapshots_from_two_protocol_versions_are_refused(env, tmp_path):
    task = env.task("researcher")
    first = _snapshot(env, 1, VALUES[0])  # collected under version 1
    _save_v2(env)  # rounds made from now on run version 2
    later = [_snapshot(env, n, v, version=2) for n, v in enumerate(VALUES[1:], 2)]
    rounds = [{"snapshot_id": first, "round": 1}]
    rounds += [{"snapshot_id": s, "round": n} for n, s in enumerate(later, 2)]
    deps = env.make_deps(runner=_runner(env, tmp_path, freeze=False))

    outcome = await _publish(env, task.id, rounds, deps)

    assert outcome.is_error and "more than one protocol version" in outcome.content
    assert env.archive.artifacts(task.id) == ()


async def test_snapshots_of_experiments_outside_the_named_protocol_are_refused(env, tmp_path):
    task = env.task("researcher")
    rounds = _rounds(env)
    deps = env.make_deps(runner=_runner(env, tmp_path, freeze=False))

    outcome = await _publish(env, task.id, rounds, deps, protocol_id="protocol-other")

    assert outcome.is_error
    assert env.archive.artifacts(task.id) == ()
