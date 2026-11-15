"""The ``publish_research_report`` handler (architecture doc §9.1, §9.3).

Everything that decides the label or the numbers is computed here from frozen data and the
protocol, never taken from tool input. The model may pass flags only for facts the server cannot
see, and a flag can only make the result stricter. The estimate comes from the snapshots' own
``measurements.jsonl`` (after verification), not from the live archive, so the numbers cannot
change under the same snapshot id.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import Field, model_validator

from growbridge.agents.handlers_common import (
    Deps,
    ToolInput,
    require_bound,
    require_round,
    scoped_snapshot,
    unavailable,
)
from growbridge.archive import snapshot as snapshots
from growbridge.archive.ids import new_id
from growbridge.archive.models import (
    ManualMeasurement,
    ResearchProtocol,
    ResearchTask,
    Snapshot,
    TaskRecord,
)
from growbridge.planning import manual_tasks
from growbridge.planning.design import check_experimental_design
from growbridge.planning.treatment import allocated, delivered, unread
from growbridge.ports import Denied
from growbridge.research.analysis import (
    AnalysisDecision,
    AnalysisFacts,
    classify,
    conclusion,
    decided,
)
from growbridge.research.notes import Note, note
from growbridge.research.report import publish_research_report
from growbridge.research.stats import UnitTable, paired_block_estimate, unit_table
from growbridge.workflow.states import RoundState, TaskState

ROLE = "researcher"
NO_RUN_NOTE = note("no_confirmatory_run")
HOLDOUT_NOTE = note("holdout_read")


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
    """The running researcher task; ``task_id`` from the model must equal the server's binding."""
    task = require_bound(deps, task_id)
    if task.owner_role != ROLE:
        raise Denied("scope", "this run does not belong to the researcher")
    return task


def _verified(deps: Deps, task: ResearchTask, snapshot_id: str) -> Snapshot:
    snap = scoped_snapshot(deps, task, snapshot_id)  # project and holdout checks come first
    if deps.archive.is_invalid(snap.id):
        raise Denied("state", f"snapshot {snap.id} was invalidated by a later correction")
    if not snapshots.verify(deps.archive, snap.id):
        raise Denied("snapshot_incomplete", f"snapshot {snap.id} fails verification")
    return snap


def _read_rows(deps: Deps, snap: Snapshot) -> list[ManualMeasurement]:
    path = deps.archive.root / "snapshots" / snap.id / "measurements.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ManualMeasurement.model_validate_json(line) for line in lines if line]


def _freeze_inputs(deps: Deps, task: ResearchTask, data: PublishInput) -> Frozen:
    snaps: list[Snapshot] = []
    round_of: dict[str, int] = {}
    rows: list[ManualMeasurement] = []
    for item in data.snapshots:
        snap = _verified(deps, task, item.snapshot_id)
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


def _missing_fraction(
    protocol: ResearchProtocol, frozen: Frozen, metric: str, started: frozenset[int]
) -> float:
    """The share of planned units without an endpoint value, among the rounds that ran.

    A round counts when a cited snapshot belongs to it or when one of its stages has started:
    a protocol round nobody has run yet is not missing data (too few rounds lowers the label
    through the replicate and sample-size rules instead), while a round that ran and is left
    out of the report still counts as missing.
    """
    positions: dict[int, set[str]] = {}
    for m in frozen.rows:
        if m.metric == metric:
            positions.setdefault(frozen.round_of[m.experiment_id], set()).add(m.position)
    ran = set(frozen.round_of.values()) | started
    planned = {(a.round, a.unit) for a in protocol.allocations if a.round in ran}
    per_round = {r: sum(1 for a in protocol.allocations if a.round == r) for r, _ in planned}
    present = {
        (r, u) for r, u in planned if r in positions and (per_round[r] == 1 or u in positions[r])
    }
    return 1 - len(present) / len(planned) if planned else 1.0


def _complete_blocks(table: UnitTable, control: str, treatment: str) -> int:
    blocks = {b for b, t in table.values if t == control}
    return len({b for b in blocks if (b, treatment) in table.values})


@dataclass(frozen=True)
class TreatmentCheck:
    """Rounds whose recorded device levels do not show their allocated treatment."""

    failed: frozenset[str]  # experiment ids
    details: tuple[dict, ...]
    unverified: tuple[dict, ...] = ()  # rounds whose samples record no level to compare

    def notes(self) -> list[Note]:
        failed = [note("treatment_not_applied", **d) for d in self.details]
        unread = [
            note(
                "treatment_unverified",
                round=d["round"],
                treatment_id=d["treatment_id"],
                channels=", ".join(d["channels"]),
            )
            for d in self.unverified
        ]
        return failed + unread


def _samples(deps: Deps, snap: Snapshot) -> list[dict]:
    path = deps.archive.root / "snapshots" / snap.id / "samples.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line).get("data", {}) for line in lines if line]


def _treatment_check(deps: Deps, protocol: ResearchProtocol, frozen: Frozen) -> TreatmentCheck:
    """Compare each snapshot's recorded levels with its round's allocated treatment; a round
    that never ran its treatment counts as a protocol deviation, whatever the model says."""
    failed, details, unverified = set(), [], []
    for snap in frozen.snaps:
        number = frozen.round_of[snap.experiment_id]
        treatment = allocated(protocol, number)
        if treatment is None:
            continue
        rows = _samples(deps, snap)
        problems = delivered(rows, treatment)
        if problems:
            failed.add(snap.experiment_id)
            details.append({"round": number, "treatment_id": treatment.id, "problems": problems})
        channels = unread(rows, treatment)
        if channels:
            unverified.append({"round": number, "treatment_id": treatment.id, "channels": channels})
    return TreatmentCheck(frozenset(failed), tuple(details), tuple(unverified))


@dataclass(frozen=True)
class ManualCheck:
    """Per round: the planned manual tasks the snapshot holds and how many were not done in time."""

    deviated: frozenset[str]  # experiment ids whose share not done in time is over the limit
    details: tuple[dict, ...]

    def notes(self) -> list[Note]:
        return [
            note(
                "manual_tasks_missed",
                round=d["round"],
                missed=d["missed"],
                total=d["total"],
                detail=manual_tasks.by_kind_text(d["by_kind"]),
            )
            for d in self.details
            if d["missed"]
        ]


def _rows(deps: Deps, snap: Snapshot, name: str) -> list[str]:
    path = deps.archive.root / "snapshots" / snap.id / name
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line]


def _manual_check(deps: Deps, frozen: Frozen) -> ManualCheck:
    """Judge each snapshot's manual tasks from its own files, at the time it was frozen (its
    records are the ones present then); occurrences not yet settled then are left out.

    A snapshot frozen before manual tasks were frozen with it has neither file and is left out.
    """
    deviated, details = set(), []
    for snap in frozen.snaps:
        if "manual_tasks.jsonl" not in snap.files:
            continue
        items = [
            manual_tasks.Occurrence.model_validate_json(x)
            for x in _rows(deps, snap, "manual_tasks.jsonl")
        ]
        records = [
            TaskRecord.model_validate_json(x) for x in _rows(deps, snap, "task_records.jsonl")
        ]
        manifest = json.loads(_rows(deps, snap, snapshots.MANIFEST)[0])
        judged_at = manifest.get("manual_tasks_judged_at", manifest["created_at"])
        missed, total, by_kind = manual_tasks.missed(
            items, records, manifest["window"][1], judged_at
        )
        if not total:
            continue
        number = frozen.round_of[snap.experiment_id]
        details.append({"round": number, "missed": missed, "total": total, "by_kind": by_kind})
        if manual_tasks.deviates(missed, total):
            deviated.add(snap.experiment_id)
    return ManualCheck(frozenset(deviated), tuple(details))


def _deviation(deps: Deps, frozen: Frozen, check: TreatmentCheck, manual: ManualCheck) -> float:
    """The share of experiments with an intervention, a treatment not applied, or too many
    manual tasks not done in time."""
    experiments = set(frozen.round_of)
    hit = sum(
        1
        for e in experiments
        if deps.archive.interventions(e) or e in check.failed or e in manual.deviated
    )
    return hit / len(experiments)


def _facts(
    deps: Deps,
    protocol: ResearchProtocol,
    data: PublishInput,
    frozen: Frozen,
    table: UnitTable,
    check: TreatmentCheck,
    manual: ManualCheck,
) -> AnalysisFacts:
    metric = protocol.analysis.primary_endpoint
    rounds = _data_rounds(frozen, metric)
    control = protocol.control_treatment_id
    replicates = min(
        _unit_count(protocol, control, rounds), _unit_count(protocol, data.treatment_id, rounds)
    )
    worst_coverage = min(s.coverage for s in frozen.snaps)
    started = deps.workflow.store.started_round_numbers(protocol.project_id, protocol.id)
    missing = max(_missing_fraction(protocol, frozen, metric, started), 1 - worst_coverage)
    flags = data.flags
    return AnalysisFacts(
        independent_replicates=replicates,
        confounded_with_time=_confounded(protocol, rounds),
        missing_fraction=missing,
        changed_after_outcomes=flags.changed_after_outcomes,
        deviation_fraction=max(_deviation(deps, frozen, check, manual), flags.deviation_fraction),
        planned_sample_size=protocol.blocks,
        achieved_sample_size=_complete_blocks(table, control, data.treatment_id),
        early_terminated=flags.early_terminated,
    )


def _capped(decision: AnalysisDecision, why: Note) -> AnalysisDecision:
    if decision.label != "confirmatory":
        return decision
    return decided("exploratory", (*decision.notes, why))


def _decide(
    deps: Deps, protocol: ResearchProtocol, frozen: Frozen, facts: AnalysisFacts
) -> AnalysisDecision:
    decision = classify(protocol, facts)
    runner = deps.runner
    if runner is None or not all(runner.completed(s.id, protocol) for s in frozen.snaps):
        return _capped(decision, NO_RUN_NOTE)
    return decision


def _require_registered_runs(deps: Deps, protocol: ResearchProtocol, frozen: Frozen) -> None:
    """With a frozen analysis script, every cited snapshot's pre-registered run must be over.

    A run that failed still counts as over: the report is then published and capped at
    exploratory. Refusing here, before anything is read from the holdout or written, keeps a
    round from being delivered with an exploratory conclusion before the operator has run the
    analysis it froze.
    """
    runner = deps.runner
    if runner is None or runner.frozen_info(protocol) is None:
        return
    for snap in frozen.snaps:
        if runner.status(snap.id, protocol) in ("none", "running"):
            raise Denied(
                "state",
                f"the pre-registered confirmatory run of snapshot {snap.id} has not finished;"
                " the operator starts it with POST /wb/analysis/runs",
            )


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


def _precheck(deps: Deps, data: PublishInput) -> ResearchTask:
    task = own_task(deps, data.task_id)
    if task.state is not TaskState.IN_PROGRESS:
        raise Denied("state", f"task {task.id} is {task.state.value}; nothing can be published")
    if data.holdout_id is not None and deps.holdout is None:
        unavailable("holdout registry")
    if data.round_id is not None:
        require_round(deps, data.round_id, RoundState.ANALYSIS, task.project_id)
    if deps.workflow.store.latest_protocol(data.protocol_id, task.project_id) is None:
        raise Denied("state", f"no protocol {data.protocol_id} in project {task.project_id}")
    return task


def _data_protocol(
    deps: Deps, task: ResearchTask, data: PublishInput, frozen: Frozen
) -> ResearchProtocol:
    """The protocol version the cited snapshots were collected under.

    It is read from the rounds that have a stage for each snapshot's experiment, never from
    the latest saved version: a later version has its own script and runs, and asking for them
    would refuse a report of earlier data for good. Snapshots of more than one version, or of
    another protocol, cannot be analysed together.
    """
    store = deps.workflow.store
    found = {
        pair for snap in frozen.snaps for pair in store.protocol_versions_of(snap.experiment_id)
    }
    if len(found) > 1:
        raise Denied("param", "the cited snapshots come from more than one protocol version")
    if not found or next(iter(found))[0] != data.protocol_id:
        raise Denied("param", f"the cited snapshots were not collected under {data.protocol_id}")
    protocol = store.protocol(*next(iter(found)))
    if protocol is None or protocol.project_id != task.project_id:
        raise Denied("scope", "that protocol is not available to this run")
    return protocol


def _written_notes(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)["notes"]


def publish(deps: Deps, data: PublishInput) -> dict:
    task = _precheck(deps, data)
    frozen = _freeze_inputs(deps, task, data)
    protocol = _data_protocol(deps, task, data, frozen)
    _require_registered_runs(deps, protocol, frozen)
    table = _table(protocol, data, frozen)
    check = _treatment_check(deps, protocol, frozen)
    manual = _manual_check(deps, frozen)
    facts = _facts(deps, protocol, data, frozen, table, check, manual)
    decision = _decide(deps, protocol, frozen, facts)
    if data.holdout_id is not None and data.model_sha is not None:
        read = deps.holdout.evaluate(data.holdout_id, ROLE, data.model_sha)
        decision = decision if read == "confirmatory" else _capped(decision, HOLDOUT_NOTE)
    estimate = paired_block_estimate(table.values, protocol.control_treatment_id, data.treatment_id)
    notes = [note("unallocated_measurements", count=len(table.dropped))] if table.dropped else []
    notes += check.notes() + manual.notes()
    weakest = min(frozen.snaps, key=lambda s: (s.complete, s.coverage))
    artifact, state = publish_research_report(
        deps.archive,
        task.id,
        weakest,
        decision,
        estimate,
        conclusion(estimate, facts),
        (*data.evidence_chain, *(f"snapshot:{s.id}" for s in frozen.snaps)),
        data.limitations,
        data.next_round,
        data.unresolved,
        deps.work_root / "reports" / task.id / new_id("report"),
        notes,
    )
    body = {
        "artifact_id": artifact.id,
        "label": artifact.label,
        "needs_review": state is TaskState.NEEDS_REVIEW,
        "task_state": state.value,
        "treatment_check": {"failed": list(check.details), "unverified": list(check.unverified)},
        "manual_task_check": list(manual.details),
        "server_notes": [n["text"] for n in _written_notes(artifact.path)],
    }
    if data.round_id is not None:
        body["round_state"] = _deliver(deps, data.round_id, artifact.id, state)
    return body
