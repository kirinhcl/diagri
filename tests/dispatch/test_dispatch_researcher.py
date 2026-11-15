import json

import pytest
from dispatch_helpers import call, result_blocks, script_calls

from growbridge.agents.tools import ROLE_TOOLS
from growbridge.archive import snapshot as snapshots
from growbridge.archive.models import (
    EvidenceCard,
    ManualMeasurement,
    SampleRecord,
    SamplingPlan,
)
from growbridge.research.analysis import ConfirmatoryRunner
from growbridge.research.holdout import HoldoutRegistry
from growbridge.research.sandbox import SandboxResult
from growbridge.sim.clock import START
from growbridge.sim.llm import ScriptedClient
from growbridge.workflow.states import RoundState, TaskState

VALUES = (5.0, 4.0, 4.2, 5.5)  # rounds 1-4: high, control, control, high
PUBLISH_FIELDS = {
    "treatment_id": "high",
    "evidence_chain": ["card-1"],
    "limitations": ["one cultivar"],
    "next_round": "repeat",
    "unresolved": [],
}


def _task_id(env) -> str:
    """The researcher task the freeze belongs to (created once per trigger event)."""
    return env.task("researcher").id


def _payload(outcome) -> dict:
    assert not outcome.is_error, outcome.content
    return json.loads(outcome.content)


class RecordingSandbox:
    def __init__(self):
        self.calls = []

    def run(self, script, snapshot_dir, out_dir, timeout):
        self.calls.append((script, snapshot_dir, out_dir, timeout))
        (out_dir / "result.txt").write_text("42")
        return SandboxResult(exit_code=0, stdout="ok", stderr="", timed_out=False)


class FakeCompute:
    def __init__(self):
        self.submitted = []

    async def submit_compute_job(self, task_id, submitter, template_id, params, inputs):
        self.submitted.append((task_id, submitter, template_id, dict(params), dict(inputs)))

        class Attempt:
            id, phase, task_state, error = "att-1", "queued", TaskState.REMOTE_QUEUED, ""

        return Attempt()


HOLE = (0, 1, 2, 3, 8, 9, 10)  # a 5 s silence: coverage 0.6 when the gap limit is 2 s


def _samples(env, experiment_id: str, seconds=range(11), light: int | None = None) -> None:
    for second in seconds:
        env.archive.append_sample(
            SampleRecord(
                id=f"s-{experiment_id}-{second}",
                experiment_id=experiment_id,
                stage_id="stage-1",
                device_id="SIMULATED",
                captured_at=START + second,
                received_at=START + second,
                clock_synced=True,
                data={"temp": 21.0} if light is None else {"light": {"level": light, "on": 1}},
            )
        )


def _measurement(experiment_id: str, value: float, ident: str, batch="batch-1", **fields):
    values = {
        "id": ident,
        "experiment_id": experiment_id,
        "batch": batch,
        "plant_id": "p1",
        "layout_version": "v1",
        "measured_at": START + 1,
        "position": "tent-1",
        "method": "ruler",
        "metric": "canopy_area_growth",
        "value": value,
        "unit": "cm2",
        "operator": "op-1",
        **fields,
    }
    return ManualMeasurement(**values)


def _experiment(
    env,
    number: int,
    value: float | None,
    batch="batch-1",
    holdout=None,
    seconds=range(11),
    lights: dict[int, int] | None = None,
) -> str:
    """Samples and one measurement for experiment e<number>, frozen; returns the snapshot id.
    ``lights`` gives the light level the device recorded in each round (default: none)."""
    name = f"e{number}"
    env.stage_for(name)  # a snapshot is only usable when its experiment has a stage of the project
    _samples(env, name, seconds, None if lights is None else lights[number])
    if value is not None:
        env.archive.add_measurement(_measurement(name, value, f"m{number}", batch))
    keep = None if holdout is None else holdout.development_filter(env.project_id)
    shot = snapshots.freeze(
        env.archive, name, env.clock, START, START + 10, 1, 2, measurement_filter=keep
    )
    return shot.id


def _rounds(env, values=VALUES, **kw) -> list[dict]:
    return [
        {"snapshot_id": _experiment(env, n, v, **kw), "round": n}
        for n, v in enumerate(values, 1)
        if v is not None
    ]


async def _publish(env, task_id: str, rounds: list[dict], deps=None, **extra):
    fields = {"task_id": task_id, "protocol_id": env.protocol.id, **PUBLISH_FIELDS}
    fields.update(extra)
    return await env.invoke(
        "researcher", "publish_research_report", deps, snapshots=rounds, **fields
    )


def _report(env, outcome) -> dict:
    artifact = env.archive.artifact(_payload(outcome)["artifact_id"])
    with open(artifact.path) as handle:
        return json.load(handle)


def _deps_with_confirmatory_runs(env, rounds, tmp_path, **more):
    script = tmp_path / "analysis.py"
    script.write_text("print('frozen')\n")
    runner = ConfirmatoryRunner(env.db, env.clock, RecordingSandbox(), tmp_path / "runs")
    runner.freeze_analysis(env.protocol, script)
    for item in rounds:
        snap = env.archive.snapshot(item["snapshot_id"])
        runner.run(env.protocol, snap, env.archive.root / "snapshots" / snap.id, script)
    return env.make_deps(runner=runner, **more)


async def _running_stage(env, seconds=range(11), **fields) -> None:
    sheet = env.sheet(duration_seconds=10, **fields)
    env.workflow.submit_run_sheet(env.round_id, sheet, env.operator)
    env.workflow.approve("stage-1", env.operator)
    await env.workflow.start_stage("stage-1", env.operator)
    _samples(env, "experiment-stage-1", seconds)


# --- freeze_dataset --------------------------------------------------------------------------


async def test_freeze_dataset_snapshots_the_stage_window_and_returns_only_a_summary(env):
    await _running_stage(env)

    body = _payload(
        await env.invoke("researcher", "freeze_dataset", task_id=_task_id(env), stage_id="stage-1")
    )

    assert body["complete"] is True and body["verified"] is True
    snap = env.archive.snapshot(body["snapshot_id"])
    assert snap.experiment_id == "experiment-stage-1"
    assert "samples" not in body


async def test_freeze_takes_the_gap_limit_from_the_run_sheet_sampling(env):
    sampling = SamplingPlan(interval_seconds=1, max_gap_seconds=2)
    await _running_stage(env, seconds=HOLE, sampling=sampling)

    body = _payload(
        await env.invoke("researcher", "freeze_dataset", task_id=_task_id(env), stage_id="stage-1")
    )

    assert body["complete"] is False  # the default 120 s limit would have called this whole


@pytest.mark.parametrize(
    "extra", [{"min_coverage": 0.0}, {"max_gap": 9999}, {"expected_interval": 9999}, {"start": 0}]
)
async def test_freeze_rejects_limits_supplied_by_the_model(env, extra):
    await _running_stage(env)

    outcome = await env.invoke(
        "researcher", "freeze_dataset", task_id=_task_id(env), stage_id="stage-1", **extra
    )

    assert outcome.is_error and env.archive.snapshots("experiment-stage-1") == ()


async def test_freeze_of_a_stage_that_never_started_is_an_error(env):
    env.workflow.submit_run_sheet(env.round_id, env.sheet(), env.operator)

    outcome = await env.invoke(
        "researcher", "freeze_dataset", task_id=_task_id(env), stage_id="stage-1"
    )

    assert outcome.is_error


async def test_freeze_dataset_with_an_unsynced_clock_is_an_error_result(env):
    await _running_stage(env)
    env.clock.synced = False

    outcome = await env.invoke(
        "researcher", "freeze_dataset", task_id=_task_id(env), stage_id="stage-1"
    )

    assert outcome.is_error and "clock_unsynced" in outcome.content


# --- inspect_stage_data ----------------------------------------------------------------------


async def _inspect(env, deps=None, **fields):
    fields = {"task_id": _task_id(env), "stage_id": "stage-1", **fields}
    return await env.invoke("researcher", "inspect_stage_data", deps, **fields)


async def test_inspect_predicts_the_freeze_and_writes_nothing(env):
    sampling = SamplingPlan(interval_seconds=1, max_gap_seconds=2)
    await _running_stage(env, seconds=HOLE, sampling=sampling)
    untrusted = SampleRecord(
        id="s-late",
        experiment_id="experiment-stage-1",
        stage_id="stage-1",
        device_id="SIMULATED",
        captured_at=START + 5,
        received_at=START + 5,
        clock_synced=False,
        data={"temp": 99.0},
    )
    env.archive.append_sample(untrusted)

    body = _payload(await _inspect(env))

    assert env.archive.snapshots("experiment-stage-1") == ()
    frozen = _payload(
        await env.invoke("researcher", "freeze_dataset", task_id=_task_id(env), stage_id="stage-1")
    )
    assert body["coverage"] == pytest.approx(frozen["coverage"])
    assert body["would_be_complete"] is frozen["complete"] is False
    assert body["gap_count"] == frozen["gap_count"] == 1
    assert body["longest_gap_seconds"] == pytest.approx(4.0)
    samples = body["samples"]
    assert (samples["trusted"], samples["untrusted"]) == (len(HOLE), 1)
    assert samples["untrusted_reasons"]["clock_unsynced"] == 1
    assert samples["channels"]["temp"] == {"n": len(HOLE), "min": 21.0, "max": 21.0, "mean": 21.0}
    assert body["stage_state"] == "running" and body["snapshots"] == []


def test_nested_device_readings_are_summarised_by_dotted_key():
    reading = {"light": {"level": 70, "on": 1}, "sensor": {"temp": 22.5}, "ok": True}
    sample = SampleRecord(
        id="s",
        experiment_id="e",
        stage_id="st",
        device_id="SIMULATED",
        captured_at=START,
        received_at=START,
        clock_synced=True,
        data=reading,
    )

    channels = snapshots._channels([sample, sample.model_copy(update={"id": "t"})])

    assert set(channels) == {"light.level", "light.on", "sensor.temp"}
    assert channels["light.level"] == {"n": 2, "min": 70.0, "max": 70.0, "mean": 70.0}


async def test_inspect_summarises_measurements_and_only_counts_held_out_ones(env):
    registry = _registry(env)
    await _running_stage(env)
    for n, value in enumerate((1.0, 3.0)):
        env.archive.add_measurement(
            _measurement("experiment-stage-1", value, f"m{n}", plant_id=f"p{n}")
        )
    env.archive.add_measurement(
        _measurement("experiment-stage-1", 987.5, "m-hold", batch="batch-h")
    )

    outcome = await _inspect(env, env.make_deps(holdout=registry))

    body = _payload(outcome)
    growth = body["measurements"]["canopy_area_growth"]
    assert (growth["n"], growth["min"], growth["max"], growth["mean"]) == (2, 1.0, 3.0, 2.0)
    assert growth["plants"] == 2 and growth["units"] == ["cm2"]
    assert body["measurements_withheld"] == 1 and "987.5" not in outcome.content


async def test_inspect_refuses_a_stage_of_another_project_or_one_never_started(env):
    env.other_project()
    env.workflow.submit_run_sheet(env.round_id, env.sheet(), env.operator)

    foreign = await _inspect(env, stage_id="stage-b")
    unstarted = await _inspect(env)

    assert foreign.is_error and "denied (scope)" in foreign.content
    assert unstarted.is_error and "never started" in unstarted.content


def test_inspect_is_a_read_only_tool_of_the_researcher(env):
    (tool,) = [t for t in env.tools()["researcher"] if t.name == "inspect_stage_data"]

    assert not tool.writes and not tool.sandbox
    assert "inspect_stage_data" in ROLE_TOOLS["researcher"]


# --- evidence and local analysis -------------------------------------------------------------


async def test_query_evidence_filters_cards_from_the_archive(env):
    for number, claim in enumerate(("lettuce likes 200 umol light", "basil likes warmth")):
        env.archive.add_evidence(
            EvidenceCard(id=f"card-{number}", source_class="handbook", citation="H", claim=claim)
        )

    body = _payload(await env.invoke("researcher", "query_evidence", text="lettuce"))

    assert [card["id"] for card in body["cards"]] == ["card-0"]


async def test_local_analysis_runs_only_through_the_sandbox_and_is_exploratory(env):
    task = env.task("researcher")
    snapshot_id = _experiment(env, 1, 5.0)
    sandbox = RecordingSandbox()
    deps = env.make_deps(sandbox=sandbox)

    outcome = await env.invoke(
        "researcher",
        "run_local_analysis",
        deps,
        task_id=task.id,
        snapshot_id=snapshot_id,
        script="print(1)",
    )

    body = _payload(outcome)
    assert body["label"] == "exploratory" and body["exit_code"] == 0
    script, snapshot_dir, _out, _timeout = sandbox.calls[0]
    assert snapshot_dir == env.archive.root / "snapshots" / snapshot_id
    assert script.read_text() == "print(1)" and script.is_relative_to(env.work_root)
    assert body["files"] == ["result.txt"]


async def test_local_analysis_without_a_sandbox_is_an_error_result(env):
    task = env.task("researcher")
    snapshot_id = _experiment(env, 1, 5.0)

    outcome = await env.invoke(
        "researcher",
        "run_local_analysis",
        task_id=task.id,
        snapshot_id=snapshot_id,
        script="print(1)",
    )

    assert outcome.is_error and "sandbox" in outcome.content


async def test_local_analysis_refuses_an_unknown_snapshot(env):
    task = env.task("researcher")
    sandbox = RecordingSandbox()
    deps = env.make_deps(sandbox=sandbox)

    outcome = await env.invoke(
        "researcher",
        "run_local_analysis",
        deps,
        task_id=task.id,
        snapshot_id="snap-none",
        script="print(1)",
    )

    assert outcome.is_error and not sandbox.calls


# --- compute ---------------------------------------------------------------------------------


async def test_missing_compute_yields_error_results_and_the_loop_continues(env):
    env.task("researcher")
    client = ScriptedClient(
        script_calls(
            call("submit_compute_job", task_id="task-ev-1", template_id="t1", params=[], inputs=[]),
            call("get_compute_job", call_id="c2", attempt_id="att-1"),
            call("fetch_compute_artifacts", call_id="c3", attempt_id="att-1"),
        )
    )

    run = await env.dispatcher(client).run_task("task-ev-1")

    assert run is not None and run.stop_reason == "end_turn"
    assert all(block["is_error"] for block in result_blocks(client))
    assert env.tasks.get("task-ev-1").state is TaskState.NEEDS_ATTENTION  # nothing published


async def test_compute_submission_for_another_roles_task_is_refused(env):
    task = env.task("planner")
    compute = FakeCompute()
    deps = env.make_deps(compute=compute)

    outcome = await env.invoke(
        "researcher",
        "submit_compute_job",
        deps,
        task_id=task.id,
        template_id="phenotype",
        params=[],
        inputs=[],
    )

    assert outcome.is_error and not compute.submitted


async def test_compute_submission_is_made_as_the_researcher_role(env):
    env.task("researcher")
    compute = FakeCompute()
    deps = env.make_deps(compute=compute)

    body = _payload(
        await env.invoke(
            "researcher",
            "submit_compute_job",
            deps,
            task_id="task-ev-1",
            template_id="phenotype",
            params=[{"name": "threads", "value": 4}, {"name": "mode", "value": "fast"}],
            inputs=[{"name": "snapshot", "ref": "snap-1"}],
        )
    )

    assert body["attempt_id"] == "att-1"
    expected = ("task-ev-1", "researcher", "phenotype", {"threads": 4, "mode": "fast"})
    assert compute.submitted == [(*expected, {"snapshot": "snap-1"})]


async def test_compute_input_claiming_another_submitter_is_rejected(env):
    compute = FakeCompute()
    deps = env.make_deps(compute=compute)

    outcome = await env.invoke(
        "researcher",
        "submit_compute_job",
        deps,
        task_id="t",
        template_id="x",
        params=[],
        inputs=[],
        submitter="operator",
    )

    assert outcome.is_error and not compute.submitted


# --- the report: server-computed label and numbers -------------------------------------------


async def test_report_without_a_recorded_confirmatory_run_is_never_confirmatory(env):
    task = env.task("researcher")
    rounds = _rounds(env)

    body = _payload(await _publish(env, task.id, rounds))

    assert body["label"] == "exploratory" and body["needs_review"] is False
    assert [a.id for a in env.archive.artifacts(task.id)] == [body["artifact_id"]]


async def test_confirmatory_report_with_open_questions_needs_review(env, tmp_path):
    task = env.task("researcher")
    rounds = _rounds(env)
    deps = _deps_with_confirmatory_runs(env, rounds, tmp_path)

    outcome = await _publish(env, task.id, rounds, deps, unresolved=["outlier"])

    body = _payload(outcome)
    assert body["label"] == "confirmatory" and body["needs_review"] is True


ALLOCATED_LIGHT = {1: 70, 2: 40, 3: 40, 4: 70}  # make_protocol: high, control, control, high


async def test_rounds_that_ran_their_treatment_stay_confirmatory(env, tmp_path):
    task = env.task("researcher")
    rounds = _rounds(env, lights=ALLOCATED_LIGHT)
    deps = _deps_with_confirmatory_runs(env, rounds, tmp_path)

    body = _payload(await _publish(env, task.id, rounds, deps))

    assert body["label"] == "confirmatory"
    assert body["treatment_check"] == {"failed": [], "unverified": []}


async def test_a_round_the_device_never_ran_at_its_level_is_a_deviation(env, tmp_path):
    """qwen3.6's round: the light stayed at 20 % while the report called it the 70 % round."""
    task = env.task("researcher")
    rounds = _rounds(env, lights={**ALLOCATED_LIGHT, 1: 20})
    deps = _deps_with_confirmatory_runs(env, rounds, tmp_path)

    outcome = await _publish(env, task.id, rounds, deps)

    body = _payload(outcome)
    assert body["label"] != "confirmatory"
    (failed,) = body["treatment_check"]["failed"]
    assert failed == {
        "round": 1,
        "treatment_id": "high",
        "problems": ["light was never at 70 (recorded [20])"],
    }
    assert any("第 1 轮没有按分配的处理 high" in x for x in _report(env, outcome)["limitations"])


async def test_rounds_without_recorded_levels_are_reported_as_unverified(env):
    task = env.task("researcher")

    outcome = await _publish(env, task.id, _rounds(env))

    unverified = _payload(outcome)["treatment_check"]["unverified"]
    assert [u["round"] for u in unverified] == [1, 2, 3, 4]
    assert any("无法核对处理" in x for x in _report(env, outcome)["limitations"])


async def test_the_report_carries_the_computed_conclusion(env):
    task = env.task("researcher")
    rounds = _rounds(env)

    outcome = await _publish(env, task.id, rounds)

    assert _report(env, outcome)["conclusion"] == "uncertain"  # two blocks cannot reach alpha


async def test_the_estimate_comes_from_the_frozen_snapshots_not_the_live_archive(env):
    task = env.task("researcher")
    rounds = _rounds(env)
    env.archive.add_measurement(_measurement("e1", 100.0, "m-late", measured_at=START + 2))

    outcome = await _publish(env, task.id, rounds)

    assert _report(env, outcome)["estimate"]["effect"] == pytest.approx(1.15)


async def test_an_edited_snapshot_file_is_refused_and_nothing_is_published(env):
    task = env.task("researcher")
    rounds = _rounds(env)
    path = env.archive.root / "snapshots" / rounds[0]["snapshot_id"] / "measurements.jsonl"
    path.write_text(path.read_text().replace("5.0", "50.0"))

    outcome = await _publish(env, task.id, rounds)

    assert outcome.is_error and env.archive.artifacts(task.id) == ()


async def test_an_invalidated_snapshot_is_refused_and_nothing_is_published(env):
    task = env.task("researcher")
    rounds = _rounds(env)
    env.archive.mark_dependents_invalid("m1")

    outcome = await _publish(env, task.id, rounds)

    assert outcome.is_error and env.archive.artifacts(task.id) == ()


@pytest.mark.parametrize("field", ["label", "task_state", "approved", "snapshot_id", "facts"])
async def test_publish_cannot_be_told_its_own_label_or_facts(env, field):
    task = env.task("researcher")
    rounds = _rounds(env)

    outcome = await _publish(env, task.id, rounds, **{field: "confirmatory"})

    assert outcome.is_error and env.archive.artifacts(task.id) == ()


async def test_a_server_found_deviation_cannot_be_cleared_by_the_model(env, tmp_path):
    task = env.task("researcher")
    rounds = _rounds(env)
    env.archive.record_intervention("e1", "stage-1", "takeover", {}, "op-1")
    deps = _deps_with_confirmatory_runs(env, rounds, tmp_path)

    outcome = await _publish(env, task.id, rounds, deps, flags={"deviation_fraction": 0})

    assert _payload(outcome)["label"] == "exploratory"  # 1 of 4 experiments deviated


async def test_a_model_flag_can_only_make_the_result_stricter(env, tmp_path):
    first, second = env.task("researcher"), env.task("researcher", "ev-2")
    rounds = _rounds(env)
    deps = _deps_with_confirmatory_runs(env, rounds, tmp_path)

    strict = await _publish(env, first.id, rounds, deps, flags={"changed_after_outcomes": True})
    clean = await _publish(env, second.id, rounds, deps, flags={"changed_after_outcomes": False})

    assert _payload(strict)["label"] == "exploratory"
    assert _payload(clean)["label"] == "confirmatory"


async def test_early_termination_flag_makes_the_conclusion_uncertain(env):
    task = env.task("researcher")
    rounds = _rounds(env)

    outcome = await _publish(env, task.id, rounds, flags={"early_terminated": True})

    assert _report(env, outcome)["conclusion"] == "uncertain"


async def test_thin_snapshot_coverage_counts_as_missing_data(env):
    task = env.task("researcher")
    rounds = _rounds(env, seconds=HOLE)

    outcome = await _publish(env, task.id, rounds)

    assert any("缺失" in reason for reason in _report(env, outcome)["reasons"])


async def test_a_single_unit_per_treatment_is_only_descriptive(env, tmp_path):
    task = env.task("researcher")
    rounds = _rounds(env, (5.0, 4.0, None, None))  # one control unit, one high unit
    deps = _deps_with_confirmatory_runs(env, rounds, tmp_path)

    body = _payload(await _publish(env, task.id, rounds, deps))

    assert body["label"] == "descriptive"


async def test_publish_refuses_a_task_the_researcher_does_not_own(env):
    task = env.task("planner")
    rounds = _rounds(env)

    outcome = await _publish(env, task.id, rounds)

    assert outcome.is_error and env.archive.artifacts(task.id) == ()


@pytest.mark.parametrize(
    ("unresolved", "expected"),
    [(["outlier"], TaskState.NEEDS_REVIEW), ([], TaskState.DONE)],
)
async def test_dispatch_moves_the_task_by_the_report_outcome(env, tmp_path, unresolved, expected):
    task = env.task("researcher")
    rounds = _rounds(env)
    deps = _deps_with_confirmatory_runs(env, rounds, tmp_path)
    fields = {**PUBLISH_FIELDS, "unresolved": unresolved}
    request = call(
        "publish_research_report",
        task_id=task.id,
        protocol_id=env.protocol.id,
        snapshots=rounds,
        **fields,
    )
    client = ScriptedClient(script_calls(request))

    run = await env.dispatcher(client, deps).run_task(task.id)

    assert run is not None and not run.tool_calls[0].is_error
    assert env.tasks.get(task.id).state is expected


# --- round progression -----------------------------------------------------------------------


def _to_data_verification(env) -> None:
    env.workflow.store.update_round(env.round_id, state=RoundState.DATA_VERIFICATION)


async def test_freeze_with_a_round_moves_it_to_analysis(env):
    await _running_stage(env)
    _to_data_verification(env)

    body = _payload(
        await env.invoke(
            "researcher",
            "freeze_dataset",
            task_id=_task_id(env),
            stage_id="stage-1",
            round_id=env.round_id,
        )
    )

    assert env.workflow.round_state(env.round_id) is RoundState.ANALYSIS
    assert body["round_state"] == "analysis"


async def test_freeze_with_a_round_in_the_wrong_state_is_an_error_and_freezes_nothing(env):
    await _running_stage(env)  # the round is stage_running

    outcome = await env.invoke(
        "researcher",
        "freeze_dataset",
        task_id=_task_id(env),
        stage_id="stage-1",
        round_id=env.round_id,
    )

    assert outcome.is_error and env.archive.snapshots("experiment-stage-1") == ()


async def test_an_incomplete_snapshot_does_not_advance_the_round(env):
    sampling = SamplingPlan(interval_seconds=1, max_gap_seconds=2)
    await _running_stage(env, seconds=HOLE, sampling=sampling)
    _to_data_verification(env)

    body = _payload(
        await env.invoke(
            "researcher",
            "freeze_dataset",
            task_id=_task_id(env),
            stage_id="stage-1",
            round_id=env.round_id,
        )
    )

    assert body["complete"] is False
    assert env.workflow.round_state(env.round_id) is RoundState.DATA_VERIFICATION


def _to_analysis(env) -> None:
    env.workflow.store.update_round(env.round_id, state=RoundState.ANALYSIS)


async def test_a_final_report_with_a_round_delivers_it(env):
    task = env.task("researcher")
    rounds = _rounds(env)
    _to_analysis(env)

    body = _payload(await _publish(env, task.id, rounds, round_id=env.round_id))

    assert env.workflow.round_state(env.round_id) is RoundState.DELIVERED
    assert body["round_state"] == "delivered"


async def test_a_report_needing_review_does_not_deliver_the_round(env, tmp_path):
    task = env.task("researcher")
    rounds = _rounds(env)
    _to_analysis(env)
    deps = _deps_with_confirmatory_runs(env, rounds, tmp_path)

    body = _payload(
        await _publish(env, task.id, rounds, deps, round_id=env.round_id, unresolved=["x"])
    )

    assert body["needs_review"] is True
    assert env.workflow.round_state(env.round_id) is RoundState.ANALYSIS


async def test_publish_with_a_round_in_the_wrong_state_is_an_error_and_publishes_nothing(env):
    task = env.task("researcher")
    rounds = _rounds(env)  # the round is still designing

    outcome = await _publish(env, task.id, rounds, round_id=env.round_id)

    assert outcome.is_error and env.archive.artifacts(task.id) == ()


# --- holdout ---------------------------------------------------------------------------------


def _registry(env) -> HoldoutRegistry:
    registry = HoldoutRegistry(env.db, env.clock)
    registry.register(
        env.project_id, "hold-1", ["batch-h"], ["canopy_area_growth"], ["d-1", "d-2", "d-3"]
    )
    registry.register_model("hold-1", "model-sha", "features-sha", "prep-sha")
    return registry


async def test_holdout_outcomes_never_reach_a_snapshot_or_a_tool_result(env):
    registry = _registry(env)
    await _running_stage(env)
    held = _measurement("experiment-stage-1", 987.5, "m-hold", batch="batch-h")
    env.archive.add_measurement(held)
    deps = env.make_deps(holdout=registry, sandbox=RecordingSandbox())

    outcome = await env.invoke(
        "researcher", "freeze_dataset", deps, task_id=_task_id(env), stage_id="stage-1"
    )

    body = _payload(outcome)
    assert "987.5" not in outcome.content
    snap_dir = env.archive.root / "snapshots" / body["snapshot_id"]
    assert "987.5" not in (snap_dir / "measurements.jsonl").read_text()
    task = env.task("researcher")
    run = await env.invoke(
        "researcher",
        "run_local_analysis",
        deps,
        task_id=task.id,
        snapshot_id=body["snapshot_id"],
        script="x",
    )
    assert "987.5" not in run.content


async def test_the_first_holdout_evaluation_may_be_confirmatory_the_second_never(env, tmp_path):
    registry = _registry(env)
    first, second = env.task("researcher"), env.task("researcher", "ev-2")
    rounds = _rounds(env, holdout=registry)
    deps = _deps_with_confirmatory_runs(env, rounds, tmp_path, holdout=registry)
    read = {"holdout_id": "hold-1", "model_sha": "model-sha"}

    one = await _publish(env, first.id, rounds, deps, **read)
    two = await _publish(env, second.id, rounds, deps, **read)

    assert _payload(one)["label"] == "confirmatory"
    assert _payload(two)["label"] == "exploratory"
    assert [r.label for r in registry.reads("hold-1")] == ["confirmatory", "exploratory"]


async def test_holdout_inputs_come_as_a_pair_and_need_a_registered_model(env):
    registry = _registry(env)
    task = env.task("researcher")
    rounds = _rounds(env, holdout=registry)
    deps = env.make_deps(holdout=registry)

    half = await _publish(env, task.id, rounds, deps, holdout_id="hold-1")
    unknown = await _publish(env, task.id, rounds, deps, holdout_id="hold-1", model_sha="other")

    assert half.is_error and unknown.is_error and env.archive.artifacts(task.id) == ()
    assert registry.reads("hold-1") == []


async def test_a_holdout_evaluation_without_a_registry_is_an_error(env):
    task = env.task("researcher")
    rounds = _rounds(env)

    outcome = await _publish(env, task.id, rounds, holdout_id="hold-1", model_sha="m")

    assert outcome.is_error and env.archive.artifacts(task.id) == ()


async def test_protocol_rounds_nobody_has_run_are_not_missing_data(env):
    """Round 1 of a four-round protocol: rounds 2 to 4 are still to come, nothing is missing."""
    task = env.task("researcher")
    rounds = _rounds(env, (5.0, None, None, None))

    outcome = await _publish(env, task.id, rounds)

    reasons = _report(env, outcome)["reasons"]
    assert not any("缺失" in reason for reason in reasons), reasons


def test_a_started_round_left_out_of_the_report_still_counts_as_missing(env):
    from growbridge.agents.handlers_report import Frozen, _missing_fraction

    rows = (_measurement("e1", 5.0, "m1"), _measurement("e2", 4.0, "m2"))
    frozen = Frozen((), {"e1": 1, "e2": 2}, rows)
    metric = env.protocol.analysis.primary_endpoint

    assert _missing_fraction(env.protocol, frozen, metric, frozenset()) == 0
    assert _missing_fraction(env.protocol, frozen, metric, frozenset({3})) == pytest.approx(1 / 3)


async def test_started_round_numbers_lists_the_rounds_with_a_started_stage(env):
    store = env.workflow.store
    assert store.started_round_numbers(env.project_id, env.protocol.id) == frozenset()

    await _running_stage(env)  # stage-1 belongs to env.round_id, the project's first round
    env.workflow.create_round(env.project_id, env.protocol.id, env.operator)

    assert store.started_round_numbers(env.project_id, env.protocol.id) == {1}
    assert store.started_round_numbers(env.project_id, "another-protocol") == frozenset()


async def test_server_notes_are_stored_with_their_code_in_both_languages(env):
    task = env.task("researcher")

    outcome = await _publish(env, task.id, _rounds(env))

    report = _report(env, outcome)
    assert report["model_limitations"] == ["one cultivar"]
    unverified = [n for n in report["notes"] if n["code"] == "treatment_unverified"]
    assert [n["params"]["round"] for n in unverified] == [1, 2, 3, 4]
    assert unverified[0]["kind"] == "limitation"
    assert unverified[0]["text"]["en"].startswith("The samples of round 1 record no level")
    assert unverified[0]["text"]["zh"] in report["limitations"]  # the plain text is unchanged
    reasons = [n for n in report["notes"] if n["kind"] == "reason"]
    assert [n["text"]["zh"] for n in reasons] == report["reasons"]
    assert report["conclusion_texts"] == {"en": "uncertain", "zh": "不确定"}
    assert _payload(outcome)["server_notes"][0].keys() == {"en", "zh"}


def _with_tasks(env, number: int, done: int, planned: int = 4, frozen_at=None) -> dict:
    """A frozen round whose snapshot holds ``planned`` watering occurrences, ``done`` recorded.
    It is frozen at ``frozen_at``, by default once every occurrence is past its deadline."""
    from growbridge.archive.models import TaskRecord
    from growbridge.planning.manual_tasks import ON_TIME_SECONDS, Occurrence

    name = f"e{number}"
    env.stage_for(name)
    _samples(env, name, light=ALLOCATED_LIGHT[number])
    env.archive.add_measurement(_measurement(name, VALUES[number - 1], f"m{number}"))
    items = [
        Occurrence(task_id="water", kind="irrigation", due_at=START + 1 + i) for i in range(planned)
    ]
    for item in items[:done]:
        env.archive.add_task_record(
            TaskRecord(
                id=f"rec-{name}-{item.due_at}",
                experiment_id=name,
                stage_id="stage-1",
                task_id="water",
                kind="irrigation",
                due_at=item.due_at,
                outcome="done",
                done_at=item.due_at,
                operator="op-1",
                recorded_at=item.due_at,
            )
        )
    env.clock.wall = START + 10 + ON_TIME_SECONDS + 1 if frozen_at is None else frozen_at
    shot = snapshots.freeze(env.archive, name, env.clock, START, START + 10, 1, 2, schedule=items)
    return {"snapshot_id": shot.id, "round": number}


async def test_manual_tasks_not_done_in_time_are_a_deviation(env, tmp_path):
    task = env.task("researcher")
    rounds = [_with_tasks(env, n, done=4 if n != 2 else 1) for n in (1, 2, 3, 4)]
    deps = _deps_with_confirmatory_runs(env, rounds, tmp_path)

    outcome = await _publish(env, task.id, rounds, deps)

    body = _payload(outcome)
    assert body["label"] == "exploratory"  # 1 of 4 experiments deviated, over the 0.1 limit
    check = {d["round"]: (d["missed"], d["total"]) for d in body["manual_task_check"]}
    assert check == {1: (0, 4), 2: (3, 4), 3: (0, 4), 4: (0, 4)}
    (missed,) = [n for n in _report(env, outcome)["notes"] if n["code"] == "manual_tasks_missed"]
    assert missed["text"]["en"] == (
        "Round 2: 3 of 4 planned manual tasks were not done on time (irrigation 3)"
    )


async def test_tasks_still_in_their_window_when_frozen_are_no_deviation(env, tmp_path):
    """Frozen at the window end, round 2's three unrecorded tasks may still be done on time."""
    task = env.task("researcher")
    end = START + 10
    rounds = [_with_tasks(env, n, done=4 if n != 2 else 1, frozen_at=end) for n in (1, 2, 3, 4)]
    deps = _deps_with_confirmatory_runs(env, rounds, tmp_path)

    body = _payload(await _publish(env, task.id, rounds, deps))

    assert body["label"] == "confirmatory"
    check = {d["round"]: (d["missed"], d["total"]) for d in body["manual_task_check"]}
    assert check == {1: (0, 4), 2: (0, 1), 3: (0, 4), 4: (0, 4)}
    manifest = env.archive.root / "snapshots" / rounds[1]["snapshot_id"] / snapshots.MANIFEST
    assert json.loads(manifest.read_text())["manual_tasks_judged_at"] == end


async def test_manual_tasks_all_done_keep_the_result_confirmatory(env, tmp_path):
    task = env.task("researcher")
    rounds = [_with_tasks(env, n, done=4) for n in (1, 2, 3, 4)]
    deps = _deps_with_confirmatory_runs(env, rounds, tmp_path)

    body = _payload(await _publish(env, task.id, rounds, deps))

    assert body["label"] == "confirmatory"
    assert all(d["missed"] == 0 for d in body["manual_task_check"])


async def test_the_freeze_tool_holds_the_planned_tasks_and_their_records(env):
    from growbridge.archive.models import ManualTask

    tasks = (ManualTask(id="water", kind="irrigation", at="10:00", seconds=5),)  # due at START
    await _running_stage(env, manual_tasks=tasks)
    env.clock.advance(20)

    body = _payload(await _inspect(env, stage_id="stage-1"))
    shot = _payload(
        await env.invoke(
            "researcher", "freeze_dataset", None, task_id=_task_id(env), stage_id="stage-1"
        )
    )

    assert body["manual_tasks"] == {
        "planned": 1,
        "by_kind": {"irrigation": {"open": 1}},
        "judged": 0,  # still within its two hours: not yet missed
        "not_done_in_time": 0,
    }
    files = env.archive.snapshot(shot["snapshot_id"]).files
    assert {"manual_tasks.jsonl", "task_records.jsonl"} <= set(files)
