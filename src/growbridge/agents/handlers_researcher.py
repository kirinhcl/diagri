"""Researcher tool handlers (architecture doc §9): inspect and freeze data, query evidence, run
exploratory analysis in the sandbox, use CSC compute, and publish a report (see
``handlers_report``).

The model can only produce exploratory analyses. Freezing takes the window and sampling limits
from the stage's run sheet, never from tool input, and leaves holdout outcomes out of the data.
"""

from __future__ import annotations

import asyncio

from pydantic import Field

from growbridge.agents.handlers_common import (
    MAX_ITEMS,
    Deps,
    ToolInput,
    clip,
    require_round,
    resolve,
    scoped_snapshot,
    unavailable,
)
from growbridge.agents.handlers_report import PublishInput, own_task, publish
from growbridge.agents.tools import Tool
from growbridge.archive import snapshot as snapshots
from growbridge.archive.ids import new_id
from growbridge.planning import manual_tasks
from growbridge.ports import Denied
from growbridge.workflow.states import RoundState

ROLE = "researcher"
DEFAULT_MIN_COVERAGE = 0.9  # the server's threshold for a complete snapshot
MAX_SCRIPT_CHARS = 20_000
MAX_TIMEOUT_SECONDS = 600.0
MAX_OUTPUT = 2000
ATTEMPT_ID = r"^[A-Za-z0-9_-][A-Za-z0-9_.-]*$"  # used as a directory name: no separators


class FreezeInput(ToolInput):
    task_id: str  # the researcher task this freeze belongs to; the stage must be its project's
    stage_id: str
    round_id: str | None = None  # advance this round (数据核验 -> 研究分析) when the data is whole


class InspectInput(ToolInput):
    task_id: str  # the researcher task; the stage must be its project's
    stage_id: str


class EvidenceInput(ToolInput):
    ids: tuple[str, ...] = ()
    text: str = ""
    limit: int = Field(default=MAX_ITEMS, ge=1, le=MAX_ITEMS)


class LocalAnalysisInput(ToolInput):
    task_id: str  # the researcher task this analysis belongs to; the snapshot must be its project's
    snapshot_id: str
    script: str = Field(max_length=MAX_SCRIPT_CHARS)
    timeout_seconds: float = Field(default=60.0, gt=0, le=MAX_TIMEOUT_SECONDS)


class ParamItem(ToolInput):
    name: str
    value: bool | int | float | str


class InputRef(ToolInput):
    name: str
    ref: str


class SubmitJobInput(ToolInput):
    task_id: str
    template_id: str
    params: tuple[ParamItem, ...] = ()
    inputs: tuple[InputRef, ...] = ()


class AttemptInput(ToolInput):
    attempt_id: str = Field(pattern=ATTEMPT_ID)


async def _local_analysis(deps: Deps, data: LocalAnalysisInput) -> dict:
    """Binding, scope and snapshot checks run on the event loop; only the sandbox is threaded.

    ``sandbox.run`` blocks for up to ``MAX_TIMEOUT_SECONDS``. ``serve`` runs the executor tick
    and the model roles in one event loop, so running it inline would stop the protection rules
    and the pump interlock: safety must never wait for a model.
    """
    task = own_task(deps, data.task_id)
    scoped_snapshot(deps, task, data.snapshot_id)  # before anything is mounted or read
    if deps.sandbox is None:
        unavailable("sandbox")
    if not snapshots.verify(deps.archive, data.snapshot_id):
        raise Denied("snapshot_incomplete", f"snapshot {data.snapshot_id} fails verification")
    run_id = new_id("local")
    out_dir = deps.work_root / "local" / run_id / "out"
    out_dir.mkdir(parents=True)
    script = deps.work_root / "local" / run_id / "analysis.py"
    script.write_text(data.script, encoding="utf-8")
    snapshot_dir = deps.archive.root / "snapshots" / data.snapshot_id
    result = await asyncio.to_thread(
        deps.sandbox.run, script, snapshot_dir, out_dir, data.timeout_seconds
    )
    return {
        "run_id": run_id,
        "label": "exploratory",
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
        "stdout": clip(result.stdout, MAX_OUTPUT),
        "stderr": clip(result.stderr, MAX_OUTPUT),
        "files": sorted(p.name for p in out_dir.iterdir()),
    }


def _started_stage(deps: Deps, task_id: str, stage_id: str):
    """The stage, when it belongs to the task's project and has started."""
    task = own_task(deps, task_id)
    stage = deps.workflow.stage(stage_id)
    if stage.project_id != task.project_id:  # before anything is read, written or touched
        raise Denied("scope", f"stage {stage_id} is not available to task {task.id}")
    if stage.started_at is None:
        raise Denied("state", f"stage {stage_id} never started; there is no data yet")
    return task, stage


def _window(deps: Deps, stage) -> tuple:
    """The arguments ``freeze`` and ``preview`` share: all from the run sheet, none from input."""
    sheet = stage.run_sheet
    keep = None if deps.holdout is None else deps.holdout.development_filter(stage.project_id)
    args = (
        deps.archive,
        stage.experiment_id,
        stage.started_at,
        stage.started_at + sheet.duration_seconds,
        sheet.sampling.interval_seconds,
        sheet.sampling.max_gap_seconds,
    )
    return args, keep


def _schedule(stage) -> tuple[manual_tasks.Occurrence, ...]:
    """The manual task occurrences the run sheet plans in the stage window."""
    start = stage.started_at
    return manual_tasks.occurrences(
        stage.run_sheet, start, start + stage.run_sheet.duration_seconds
    )


def _manual_summary(deps: Deps, stage) -> dict:
    items = _schedule(stage)
    end = stage.started_at + stage.run_sheet.duration_seconds
    records = deps.archive.task_records(stage.experiment_id, stage.started_at, end)
    rows = manual_tasks.statuses(items, records, deps.clock.now(), end)
    counts: dict[str, dict[str, int]] = {}
    for item, _, state in rows:
        kind = counts.setdefault(item.kind, {})
        kind[state] = kind.get(state, 0) + 1
    missed, total, _ = manual_tasks.missed(items, records, end)
    return {"planned": total, "by_kind": counts, "not_done_in_time": missed}


def _inspect(deps: Deps, data: InspectInput) -> dict:
    _, stage = _started_stage(deps, data.task_id, data.stage_id)
    (archive, experiment_id, *limits), keep = _window(deps, stage)
    summary = snapshots.preview(
        archive, experiment_id, *limits, DEFAULT_MIN_COVERAGE, measurement_filter=keep
    )
    summary["manual_tasks"] = _manual_summary(deps, stage)
    frozen = archive.snapshots(experiment_id)
    return {
        "stage_id": stage.stage_id,
        "stage_state": stage.state.value,
        "experiment_id": experiment_id,
        "clock_synced": deps.clock.synced,
        **summary,
        "snapshots": [{"snapshot_id": s.id, "version": s.version} for s in frozen],
    }


def _freeze(deps: Deps, data: FreezeInput) -> dict:
    task, stage = _started_stage(deps, data.task_id, data.stage_id)
    if data.round_id is not None:
        require_round(deps, data.round_id, RoundState.DATA_VERIFICATION, task.project_id)
    (archive, experiment_id, *limits), keep = _window(deps, stage)
    shot = snapshots.freeze(
        archive,
        experiment_id,
        deps.clock,
        *limits,
        DEFAULT_MIN_COVERAGE,
        measurement_filter=keep,
        schedule=_schedule(stage),
    )
    verified = snapshots.verify(deps.archive, shot.id)
    body = {
        "snapshot_id": shot.id,
        "experiment_id": shot.experiment_id,
        "version": shot.version,
        "complete": shot.complete,
        "coverage": shot.coverage,
        "gap_count": len(shot.gaps),
        "verified": verified,
    }
    if data.round_id is not None:
        body["round_state"] = _advance(deps, data.round_id, shot.id, shot.complete and verified)
    return body


def _advance(deps: Deps, round_id: str, snapshot_id: str, whole: bool) -> str:
    if not whole:
        return deps.workflow.round_state(round_id).value
    event = f"snapshot_frozen:{round_id}:{snapshot_id}"
    return deps.workflow.mark_snapshot_frozen(round_id, snapshot_id, event).value


def query_cards(deps: Deps, data: EvidenceInput) -> dict:
    """Search the evidence cards (shared by the researcher and the planner)."""
    cards = deps.archive.evidence(data.ids or None)
    needle = data.text.casefold()
    hits = [c for c in cards if not needle or needle in f"{c.claim} {c.citation}".casefold()]
    return {
        "cards": [
            {
                "id": c.id,
                "source_class": c.source_class,
                "citation": clip(c.citation, 300),
                "claim": clip(c.claim, 300),
                "value": c.value,
                "unit": c.unit,
                "verified": c.verified,
                "calibrated": c.calibrated,
            }
            for c in hits[: data.limit]
        ]
    }


def _compute(deps: Deps):
    if deps.compute is None:
        unavailable("compute service")
    return deps.compute


def build_researcher_tools(deps: Deps) -> list[Tool]:
    async def submit_job(data: SubmitJobInput) -> dict:
        compute = _compute(deps)
        own_task(deps, data.task_id)
        params = {p.name: p.value for p in data.params}
        inputs = {i.name: i.ref for i in data.inputs}
        attempt = await resolve(
            compute.submit_compute_job(data.task_id, ROLE, data.template_id, params, inputs)
        )
        return {
            "attempt_id": attempt.id,
            "phase": attempt.phase,
            "task_state": attempt.task_state.value,
        }

    async def get_job(data: AttemptInput) -> dict:
        attempt = await resolve(_compute(deps).get_compute_job(data.attempt_id, ROLE))
        return {
            "attempt_id": attempt.id,
            "phase": attempt.phase,
            "task_state": attempt.task_state.value,
            "error": clip(attempt.error, MAX_OUTPUT),
        }

    async def fetch(data: AttemptInput) -> dict:
        compute = _compute(deps)
        out_dir = deps.work_root / "compute" / data.attempt_id
        out_dir.mkdir(parents=True, exist_ok=True)
        files = await resolve(compute.fetch_compute_artifacts(data.attempt_id, ROLE, out_dir))
        return {"attempt_id": data.attempt_id, "files": sorted(files)}

    return [
        Tool(
            "inspect_stage_data",
            "Read-only summary of a started stage's data over the window freeze_dataset would "
            "use: coverage and gaps, trusted and untrusted sample counts with reasons, ranges "
            "per sensor channel, manual measurements per metric, actions and interventions, "
            "the planned manual tasks and how many were done in time, "
            "and the snapshots already frozen. Writes nothing; use it to check the data before "
            "freezing. Pass the researcher task_id you are working on.",
            InspectInput,
            lambda d: _inspect(deps, d),
        ),
        Tool(
            "freeze_dataset",
            "Freeze a stage's data into a snapshot and verify it (window and limits come from "
            "its run sheet; the snapshot also holds the manual task records). The freeze "
            "itself checks coverage, gaps and file digests and "
            "returns complete/verified; it never fails because the data is poor, and freezing "
            "again later writes a new version. Pass round_id to advance a round in "
            "data_verification when the snapshot is complete and verified. Pass the researcher "
            "task_id you are working on; a stage or round of another project is refused.",
            FreezeInput,
            lambda d: _freeze(deps, d),
            writes=True,
        ),
        Tool(
            "query_evidence",
            "Search evidence cards already in the archive.",
            EvidenceInput,
            lambda d: query_cards(deps, d),
        ),
        Tool(
            "run_local_analysis",
            "Run an exploratory script in the sandbox on a snapshot of your task's project. "
            "Pass the researcher task_id you are working on; a snapshot of another project, "
            "an unknown snapshot or one holding held-out outcomes is refused.",
            LocalAnalysisInput,
            lambda d: _local_analysis(deps, d),
            sandbox=True,
        ),
        Tool(
            "submit_compute_job",
            "Submit a compute job from an approved template.",
            SubmitJobInput,
            submit_job,
            writes=True,
        ),
        Tool("get_compute_job", "Read the state of a compute job.", AttemptInput, get_job),
        Tool(
            "fetch_compute_artifacts",
            "Fetch and verify the outputs of a compute job.",
            AttemptInput,
            fetch,
            writes=True,
        ),
        Tool(
            "publish_research_report",
            "Publish the round's report; label and numbers are computed from frozen data.",
            PublishInput,
            lambda d: publish(deps, d),
            writes=True,
        ),
    ]
