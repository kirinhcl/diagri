"""The auditor's tools: read one stage's records, raise an advisory finding, change nothing.

The auditor never reports a stage event: its finding is an alert for a person, and a stage
keeps running whatever it says.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Annotated, Literal

from pydantic import Field

from growbridge.agents.handlers_common import (
    Deps,
    ToolInput,
    clip,
    require_bound,
    require_stage_project,
)
from growbridge.agents.handlers_orchestrator import build_orchestrator_tools
from growbridge.agents.handlers_researcher import InspectInput, stage_preview
from growbridge.agents.tools import Tool
from growbridge.observer.stage_checks import AUDIT_FINDING, OUTSIDE_WINDOW
from growbridge.planning import manual_tasks
from growbridge.planning.window import MEASUREMENT_GRACE_SECONDS, data_window
from growbridge.ports import Denied

MAX_LISTED = 200
MAX_EVIDENCE = 10
MAX_LINE = 300
SHARED_TOOLS = ("get_project_state", "get_run_status")


class StageInput(ToolInput):
    task_id: str  # the auditor task; the stage must be its project's
    stage_id: str


class FindingInput(ToolInput):
    task_id: str
    stage_id: str
    severity: Literal["info", "warning"]
    summary: str = Field(
        min_length=1,
        max_length=MAX_LINE,
        description=(
            "One sentence for the operator under the writing rules: the problem "
            "and what to do about it, with no ids or field names."
        ),
    )
    evidence: tuple[Annotated[str, Field(max_length=MAX_LINE)], ...] = Field(
        default=(),
        max_length=MAX_EVIDENCE,
        description=(
            "One fact per item, written for the operator under the "
            "writing rules: plain words, local times, no ids or field names."
        ),
    )


def _started_stage(deps: Deps, task_id: str, stage_id: str):
    require_bound(deps, task_id)
    require_stage_project(deps, stage_id)
    stage = deps.workflow.stage(stage_id)
    if stage.started_at is None:
        raise Denied(
            "state",
            f"stage {stage_id} never started; there is no data yet",
            reason="stage_not_started",
            params={"stage_id": stage_id},
        )
    return stage


def _inspect(deps: Deps, data: InspectInput) -> dict:
    return stage_preview(deps, _started_stage(deps, data.task_id, data.stage_id))


def _run_sheet(stage) -> dict:
    sheet = stage.run_sheet
    dump = lambda items: [item.model_dump(mode="json") for item in items]  # noqa: E731
    return {
        "channels": dump(sheet.channels),
        "timed_actions": dump(sheet.timed_actions),
        "manual_tasks": dump(sheet.manual_tasks),
    }


def _task_rows(deps: Deps, stage, start: float, end: float) -> tuple[list[dict], int]:
    now = deps.clock.now()
    items = manual_tasks.occurrences(stage.run_sheet, start, end)
    records = deps.archive.task_records(stage.experiment_id, start, end)
    due = [row for row in manual_tasks.statuses(items, records, now, end) if row[0].due_at <= now]
    rows = [
        {
            "task_id": item.task_id,
            "kind": item.kind,
            "due_at": item.due_at,
            "status": state,
            "record": None if record is None else record.model_dump(mode="json"),
        }
        for item, record, state in due[-MAX_LISTED:]
    ]
    return rows, len(due) - len(rows)


def _kept_measurements(deps: Deps, stage) -> list:
    """The experiment's current measurements, without the held-out outcomes."""
    keep = None if deps.holdout is None else deps.holdout.development_filter(stage.project_id)
    return [m for m in deps.archive.measurements(stage.experiment_id) if keep is None or keep(m)]


def _measurement_rows(kept: list, start: float, end: float) -> tuple[list[dict], int, int]:
    """``(rows, left out by the list limit, timed before the stage)``. Every stage of a round
    shares one experiment, so a measurement timed before this stage started is an earlier
    stage's: it is counted, not listed."""
    found = sorted((m for m in kept if m.measured_at >= start), key=lambda m: m.measured_at)
    rows = [
        {
            "id": m.id,
            "metric": m.metric,
            "value": m.value,
            "measured_at": m.measured_at,
            "in_window": m.measured_at <= end + MEASUREMENT_GRACE_SECONDS,
        }
        for m in found[-MAX_LISTED:]
    ]
    return rows, len(found) - len(rows), len(kept) - len(found)


def _open_alerts(deps: Deps, stage_id: str, kept_ids: set[str]) -> list[dict]:
    """The stage's open alerts. An outside-window alert names its measurement and metric, so
    one about a measurement that is not in ``kept_ids`` (a held-out outcome) is left out."""
    if deps.alerts is None:
        return []
    prefix = f"{stage_id}:"
    return [
        {"kind": a.kind, "key": a.key, "severity": a.severity, "message": clip(a.message, 600)}
        for a in deps.alerts.open()
        if (a.key == stage_id or a.key.startswith(prefix))
        and (a.kind != OUTSIDE_WINDOW or a.key[len(prefix) :] in kept_ids)
    ]


def stage_records(deps: Deps, data: StageInput) -> dict:
    stage = _started_stage(deps, data.task_id, data.stage_id)
    start, end = data_window(stage)
    tasks, tasks_left_out = _task_rows(deps, stage, start, end)
    kept = _kept_measurements(deps, stage)
    measurements, measurements_left_out, before = _measurement_rows(kept, start, end)
    return {
        "stage": {
            "id": stage.stage_id,
            "state": stage.state.value,
            "started_at": stage.started_at,
            "ended_at": stage.ended_at,
        },
        "window": [start, end],
        "run_sheet": _run_sheet(stage),
        "manual_tasks": tasks,
        "manual_tasks_left_out": tasks_left_out,
        "measurements": measurements,
        "measurements_left_out": measurements_left_out,
        "measurements_before_stage": before,
        "open_alerts": _open_alerts(deps, stage.stage_id, {m.id for m in kept}),
    }


def raise_finding(deps: Deps, data: FindingInput) -> dict:
    require_bound(deps, data.task_id)
    require_stage_project(deps, data.stage_id)
    if deps.alerts is None:
        raise Denied(
            "state",
            "no alert book is available; the finding cannot be recorded",
            reason="alert_book_unavailable",
            params={},
        )
    key = f"{data.stage_id}:{sha256(data.summary.encode()).hexdigest()[:12]}"
    message = "\n".join((data.summary, *data.evidence))
    params = {
        "stage_id": data.stage_id,
        "summary": data.summary,
        "evidence": list(data.evidence),
    }
    alert = deps.alerts.raise_alert(
        AUDIT_FINDING, key, data.severity, message, code="audit_finding", params=params
    )
    return {"raised": True, "kind": AUDIT_FINDING, "key": key, "event_id": alert.event_id}


def build_auditor_tools(deps: Deps) -> list[Tool]:
    shared = [t for t in build_orchestrator_tools(deps) if t.name in SHARED_TOOLS]
    return [
        *shared,
        Tool(
            "inspect_stage_data",
            "Preview the data of a started stage of your project: coverage, gaps, samples, "
            "measurements and manual task counts. Read only.",
            InspectInput,
            lambda data: _inspect(deps, data),
        ),
        Tool(
            "get_stage_records",
            "Read a started stage's plan and records: run sheet, manual tasks with their "
            "status and record, measurements, and the open alerts of that stage.",
            StageInput,
            lambda data: stage_records(deps, data),
        ),
        Tool(
            "raise_audit_finding",
            "Raise an advisory alert (info or warning) for something a person should act on "
            "now. It pauses nothing and changes nothing.",
            FindingInput,
            lambda data: raise_finding(deps, data),
            writes=True,
        ),
    ]
