"""One open question through a whole round on the simulated device (appendix C, end to end)."""

from e2e_support import OPERATOR, STAGE, STAGE_SECONDS

from growbridge.archive import snapshot as snapshots
from growbridge.archive.models import Channel, ManualMeasurement
from growbridge.ports import ActionRequest, Actor
from growbridge.research.analysis import AnalysisFacts, classify, conclusion
from growbridge.research.report import publish_research_report
from growbridge.research.stats import paired_block_estimate, unit_means
from growbridge.sim.fixtures import make_protocol, make_safety
from growbridge.workflow.states import RoundState, StageState

QUESTION = "提高光照后，冠层增长是否加快？"
METRIC = "canopy_area_growth"
# (round, treatment, canopy area growth per day): two blocks, treatment order randomized per block
OUTCOMES = ((1, "high", 1.30), (2, "control", 1.10), (3, "control", 1.00), (4, "high", 1.25))
# keyed by (block, treatment)
EXPECTED_MEANS = {(1, "high"): 1.30, (1, "control"): 1.10, (2, "control"): 1.00, (2, "high"): 1.25}


def measurements() -> list[ManualMeasurement]:
    return [
        ManualMeasurement(
            id=f"m-{number}",
            experiment_id=f"experiment-r{number}",
            batch="batch-1",
            plant_id="plant-1",
            layout_version="layout-1",
            measured_at=1_800_000_000.0 + number,
            position="tent-1",
            method="image",
            metric=METRIC,
            value=value,
            unit="cm2/day",
            operator=OPERATOR,
        )
        for number, _treatment, value in OUTCOMES
    ]


def analysis_facts() -> AnalysisFacts:
    return AnalysisFacts(
        independent_replicates=2,
        confounded_with_time=False,
        missing_fraction=0.0,
        changed_after_outcomes=False,
        deviation_fraction=0.0,
        planned_sample_size=4,
        achieved_sample_size=4,
        early_terminated=False,
    )


async def run_stage_with_takeover(world, runtime, project, round_id, protocol):
    """Approve and start, align, take over, write by hand, hand back, run to the end."""
    flow, operator = runtime.workflow, world.operator
    sheet = world.sheet(project, protocol_id=protocol.id, protocol_version=protocol.version)
    findings = flow.submit_run_sheet(round_id, sheet, Actor(kind="model", id="planner"))
    assert not [item for item in findings if item.blocking]
    assert flow.round_state(round_id) is RoundState.STAGE_REVIEW
    assert flow.stage(STAGE).state is StageState.PENDING_REVIEW
    flow.approve(STAGE, operator)
    await flow.start_stage(STAGE, operator)
    assert flow.round_state(round_id) is RoundState.STAGE_RUNNING

    await world.beat(runtime, 30)  # the executor aligns the light (60 % from 06:00)
    assert (await runtime.control.read_state()).levels[Channel.LIGHT] == 60

    taken = await flow.takeover(STAGE, operator)
    assert taken.state is StageState.MANUAL
    manual = ActionRequest(
        request_id="manual-1",
        right_number=taken.manual_right,
        channel=Channel.EXHAUST,
        level=55,
        trigger="operator note: stuffy air",
        experiment_id=sheet.experiment_id,
        stage_id=STAGE,
        operator=OPERATOR,
    )
    assert (await runtime.control.submit(manual)).state.value == "confirmed"
    back, differences = await flow.handback(STAGE, operator, accept_as_intervention=True)
    assert back.state is StageState.RUNNING
    assert [diff.channel for diff in differences] == [Channel.EXHAUST]
    kinds = [item["kind"] for item in runtime.workflow.interventions(sheet.experiment_id)]
    assert kinds == ["takeover", "accepted"]

    await world.run_until_ended(runtime)
    return sheet


async def test_open_question_goes_through_a_whole_round(world, tmp_path):
    runtime = await world.boot()
    flow, operator = runtime.workflow, world.operator

    runtime.control.approve_safety(make_safety(), OPERATOR)
    project = flow.create_project(QUESTION, operator)
    protocol = make_protocol(project_id=project)
    assert protocol.question == QUESTION
    flow.save_protocol(protocol, operator)
    round_id = flow.create_round(project, protocol.id, operator)
    assert flow.round_state(round_id) is RoundState.DESIGNING

    sheet = await run_stage_with_takeover(world, runtime, project, round_id, protocol)

    assert flow.stage(STAGE).state is StageState.ENDED
    assert flow.round_state(round_id) is RoundState.DATA_VERIFICATION
    assert len(runtime.archive.samples(sheet.experiment_id)) >= STAGE_SECONDS // 60
    assert any(a.channel is Channel.LIGHT for a in runtime.archive.actions(sheet.experiment_id))

    started = flow.stage(STAGE).started_at
    snapshot = snapshots.freeze(
        runtime.archive, sheet.experiment_id, world.clock, started, world.clock.now(), 60, 120
    )
    assert snapshots.verify(runtime.archive, snapshot.id)
    state = flow.mark_snapshot_frozen(round_id, snapshot.id, "snapshot-event-1")
    assert state is RoundState.ANALYSIS

    round_of = {f"experiment-r{item.round}": item.round for item in protocol.allocations}
    means = unit_means(measurements(), protocol.allocations, METRIC, round_of)
    assert means == EXPECTED_MEANS
    estimate = paired_block_estimate(means, "control", "high")
    assert estimate.estimable and estimate.blocks == 2
    assert round(estimate.effect, 3) == 0.225
    decision = classify(protocol, analysis_facts())
    assert decision.label == "confirmatory"
    # two blocks cannot reach alpha = 0.05: the result is never "supported" or "no effect"
    verdict = conclusion(estimate, analysis_facts())
    assert verdict == "uncertain"

    artifact, _task_state = publish_research_report(
        runtime.archive,
        "task-analysis-1",
        snapshot,
        decision,
        estimate,
        verdict,
        evidence_chain=("measurements m-1..m-4", f"snapshot {snapshot.id}"),
        limitations=("two blocks only",),
        next_round="add a third block",
        unresolved=(),
        out_dir=tmp_path / "report",
    )
    assert runtime.archive.artifact(artifact.id) is not None
    final = flow.mark_report_published(round_id, artifact.id, "report-event-1")
    assert final is RoundState.DELIVERED
