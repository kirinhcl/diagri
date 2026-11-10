"""The ``publish_research_report`` handler (architecture doc §9.1, §9.3).

Everything that decides the label or the numbers is computed here from frozen data and the
protocol, never taken from tool input. The model may pass flags only for facts the server cannot
see, and a flag can only make the result stricter. The estimate comes from the snapshots' own
``measurements.jsonl`` (after verification), not from the live archive, so the numbers cannot
change under the same snapshot id.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import Field, model_validator

from growbridge.agents.handlers_common import (
    Deps,
    ToolInput,
    load_snapshot,
    require_round,
    unavailable,
)
from growbridge.archive import snapshot as snapshots
from growbridge.archive.ids import new_id
from growbridge.archive.models import ManualMeasurement, ResearchProtocol, ResearchTask, Snapshot
from growbridge.planning.design import check_experimental_design
from growbridge.ports import Denied
from growbridge.research.analysis import AnalysisDecision, AnalysisFacts, classify, conclusion
from growbridge.research.report import publish_research_report
from growbridge.research.stats import UnitTable, paired_block_estimate, unit_table
from growbridge.workflow.states import RoundState, TaskState

ROLE = "researcher"
NO_RUN_NOTE = "没有该数据快照上已冻结的确认性分析记录：不能作为确认性结果"
HOLDOUT_NOTE = "留出集已被读取过：本次读取只能作为探索性结果"


class SnapshotRound(ToolInput):
    snapshot_id: str
    round: int = Field(ge=1)


class Flags(ToolInput):
    """Facts only the model can know; each one can only make the result stricter."""

    changed_after_outcomes: bool = False
    early_terminated: bool = False
    deviation_fraction: float = Field(default=0.0, ge=0, le=1)


class PublishInput(ToolInput):
    task_id: str
    protocol_id: str
    treatment_id: str
    snapshots: tuple[SnapshotRound, ...] = Field(min_length=1)
    flags: Flags = Flags()
    evidence_chain: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    next_round: str = ""
    unresolved: tuple[str, ...] = ()
    round_id: str | None = None  # deliver this round when the report is final
    holdout_id: str | None = None  # read this holdout with a registered model ...
    model_sha: str | None = None  # ... identified by this digest

    @model_validator(mode="after")
    def _holdout_pair(self) -> PublishInput:
        if (self.holdout_id is None) != (self.model_sha is None):
            raise ValueError("holdout_id and model_sha go together")
        return self


@dataclass(frozen=True)
class Frozen:
    """The verified snapshots behind a report and the measurements read from them."""

    snaps: tuple[Snapshot, ...]
    round_of: dict[str, int]
    rows: tuple[ManualMeasurement, ...]


def own_task(deps: Deps, task_id: str) -> ResearchTask:
    task = deps.tasks.get(task_id)
    if task.owner_role != ROLE:
        raise Denied("scope", f"task {task_id} does not belong to the researcher")
    return task


def _verified(deps: Deps, snapshot_id: str) -> Snapshot:
    snap = load_snapshot(deps, snapshot_id)
    if deps.archive.is_invalid(snap.id):
        raise Denied("state", f"snapshot {snap.id} was invalidated by a later correction")
    if not snapshots.verify(deps.archive, snap.id):
        raise Denied("snapshot_incomplete", f"snapshot {snap.id} fails verification")
    return snap


def _read_rows(deps: Deps, snap: Snapshot) -> list[ManualMeasurement]:
    path = deps.archive.root / "snapshots" / snap.id / "measurements.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ManualMeasurement.model_validate_json(line) for line in lines if line]


def _freeze_inputs(deps: Deps, data: PublishInput) -> Frozen:
    snaps: list[Snapshot] = []
    round_of: dict[str, int] = {}
    rows: list[ManualMeasurement] = []
    for item in data.snapshots:
        snap = _verified(deps, item.snapshot_id)
        if round_of.setdefault(snap.experiment_id, item.round) != item.round:
            raise Denied("param", f"experiment {snap.experiment_id} listed in two rounds")
        snaps.append(snap)
        rows.extend(_read_rows(deps, snap))
    return Frozen(tuple(snaps), round_of, tuple(rows))


def _data_rounds(frozen: Frozen, metric: str) -> set[int]:
    return {frozen.round_of[m.experiment_id] for m in frozen.rows if m.metric == metric}


def _unit_count(protocol: ResearchProtocol, treatment: str, rounds: set[int]) -> int:
    units = {(a.round, a.unit) for a in protocol.allocations if a.treatment_id == treatment}
    return len({key for key in units if key[0] in rounds})


def _confounded(protocol: ResearchProtocol, rounds: set[int]) -> bool:
    kept = tuple(a for a in protocol.allocations if a.round in rounds)
    restricted = protocol.model_copy(update={"allocations": kept})
    return any(f.code == "confounded_with_time" for f in check_experimental_design(restricted))


def _missing_fraction(protocol: ResearchProtocol, frozen: Frozen, metric: str) -> float:
    positions: dict[int, set[str]] = {}
    for m in frozen.rows:
        if m.metric == metric:
            positions.setdefault(frozen.round_of[m.experiment_id], set()).add(m.position)
    planned = {(a.round, a.unit) for a in protocol.allocations}
    per_round = {r: sum(1 for a in protocol.allocations if a.round == r) for r, _ in planned}
    present = {
        (r, u) for r, u in planned if r in positions and (per_round[r] == 1 or u in positions[r])
    }
    return 1 - len(present) / len(planned) if planned else 1.0


def _complete_blocks(table: UnitTable, control: str, treatment: str) -> int:
    blocks = {b for b, t in table.values if t == control}
    return len({b for b in blocks if (b, treatment) in table.values})


def _deviation(deps: Deps, frozen: Frozen) -> float:
    experiments = set(frozen.round_of)
    hit = sum(1 for e in experiments if deps.archive.interventions(e))
    return hit / len(experiments)


def _facts(
    deps: Deps, protocol: ResearchProtocol, data: PublishInput, frozen: Frozen, table: UnitTable
) -> AnalysisFacts:
    metric = protocol.analysis.primary_endpoint
    rounds = _data_rounds(frozen, metric)
    control = protocol.control_treatment_id
    replicates = min(
        _unit_count(protocol, control, rounds), _unit_count(protocol, data.treatment_id, rounds)
    )
    worst_coverage = min(s.coverage for s in frozen.snaps)
    missing = max(_missing_fraction(protocol, frozen, metric), 1 - worst_coverage)
    flags = data.flags
    return AnalysisFacts(
        independent_replicates=replicates,
        confounded_with_time=_confounded(protocol, rounds),
        missing_fraction=missing,
        changed_after_outcomes=flags.changed_after_outcomes,
        deviation_fraction=max(_deviation(deps, frozen), flags.deviation_fraction),
        planned_sample_size=protocol.blocks,
        achieved_sample_size=_complete_blocks(table, control, data.treatment_id),
        early_terminated=flags.early_terminated,
    )


def _capped(decision: AnalysisDecision, note: str) -> AnalysisDecision:
    if decision.label != "confirmatory":
        return decision
    return AnalysisDecision(label="exploratory", reasons=(*decision.reasons, note))


def _decide(
    deps: Deps, protocol: ResearchProtocol, frozen: Frozen, facts: AnalysisFacts
) -> AnalysisDecision:
    decision = classify(protocol, facts)
    runner = deps.runner
    if runner is None or not all(runner.completed(s.id, protocol) for s in frozen.snaps):
        return _capped(decision, NO_RUN_NOTE)
    return decision


def _table(protocol: ResearchProtocol, data: PublishInput, frozen: Frozen) -> UnitTable:
    if data.treatment_id not in {t.id for t in protocol.treatments}:
        raise Denied("param", f"unknown treatment {data.treatment_id}")
    metric = protocol.analysis.primary_endpoint
    try:
        return unit_table(frozen.rows, protocol.allocations, metric, frozen.round_of)
    except ValueError as exc:
        raise Denied("param", str(exc)) from None


def _deliver(deps: Deps, round_id: str, artifact_id: str, state: TaskState) -> str:
    """Only a final report delivers the round; one that needs review leaves it in analysis."""
    if state is not TaskState.DONE:
        return deps.workflow.round_state(round_id).value
    event = f"report_published:{round_id}:{artifact_id}"
    return deps.workflow.mark_report_published(round_id, artifact_id, event).value


def _precheck(deps: Deps, data: PublishInput) -> tuple[ResearchTask, ResearchProtocol]:
    task = own_task(deps, data.task_id)
    if task.state is not TaskState.IN_PROGRESS:
        raise Denied("state", f"task {task.id} is {task.state.value}; nothing can be published")
    if data.holdout_id is not None and deps.holdout is None:
        unavailable("holdout registry")
    if data.round_id is not None:
        require_round(deps, data.round_id, RoundState.ANALYSIS)
    protocol = deps.workflow.store.latest_protocol(data.protocol_id, task.project_id)
    if protocol is None:
        raise Denied("state", f"no protocol {data.protocol_id} in project {task.project_id}")
    return task, protocol


def publish(deps: Deps, data: PublishInput) -> dict:
    task, protocol = _precheck(deps, data)
    frozen = _freeze_inputs(deps, data)
    table = _table(protocol, data, frozen)
    facts = _facts(deps, protocol, data, frozen, table)
    decision = _decide(deps, protocol, frozen, facts)
    if data.holdout_id is not None and data.model_sha is not None:
        read = deps.holdout.evaluate(data.holdout_id, ROLE, data.model_sha)
        decision = decision if read == "confirmatory" else _capped(decision, HOLDOUT_NOTE)
    estimate = paired_block_estimate(table.values, protocol.control_treatment_id, data.treatment_id)
    notes = [f"{len(table.dropped)} 条测量没有对应的分配，未计入"] if table.dropped else []
    weakest = min(frozen.snaps, key=lambda s: (s.complete, s.coverage))
    artifact, state = publish_research_report(
        deps.archive,
        task.id,
        weakest,
        decision,
        estimate,
        conclusion(estimate, facts),
        (*data.evidence_chain, *(f"snapshot:{s.id}" for s in frozen.snaps)),
        (*data.limitations, *notes),
        data.next_round,
        data.unresolved,
        deps.work_root / "reports" / task.id / new_id("report"),
    )
    body = {
        "artifact_id": artifact.id,
        "label": artifact.label,
        "needs_review": state is TaskState.NEEDS_REVIEW,
        "task_state": state.value,
    }
    if data.round_id is not None:
        body["round_state"] = _deliver(deps, data.round_id, artifact.id, state)
    return body
