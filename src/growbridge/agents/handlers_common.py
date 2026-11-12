"""Shared parts of the model-role tool handlers (architecture doc §4, §5.2, §11.6).

Every handler acts as ``Actor(kind="model", id=<role>)`` built here, never from tool input. No
handler in this package approves, starts, pauses, resumes or stops a stage, or writes to the device.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from pydantic import BaseModel, ConfigDict

from growbridge.archive.models import ManualMeasurement, ResearchTask, RunSheet, Snapshot
from growbridge.planning.validate import validate_run_sheet
from growbridge.ports import Actor, Denied, Finding
from growbridge.workflow.states import RoundState, StageState

MAX_ITEMS = 20
MAX_TEXT = 4000


@dataclass(frozen=True)
class Deps:
    """The real services the handlers call; ``compute``, ``runner``, ``sandbox``, ``search`` are
    optional and their tools return an error result while they are ``None``."""

    workflow: Any
    control: Any
    archive: Any
    tasks: Any
    clock: Any
    work_root: Path
    compute: Any = None
    runner: Any = None
    sandbox: Any = None
    search: Any = None
    holdout: Any = None


class ToolInput(BaseModel):
    """Base of every tool input: unknown fields (``role``, ``approved``, ...) fail validation."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class DraftInput(ToolInput):
    round_id: str
    run_sheet: RunSheet


def actor_for(role: str) -> Actor:
    return Actor(kind="model", id=role)


def unavailable(what: str) -> NoReturn:
    raise Denied("unavailable", f"no {what} configured")


async def resolve(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def findings_json(findings: Iterable[Finding]) -> list[dict]:
    """Findings as plain dicts, without repeats (the workflow runs the same checks)."""
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for finding in findings:
        key = (finding.code, finding.message)
        if key not in seen:
            seen.add(key)
            out.append(finding.model_dump(mode="json"))
    return out


def check_sheet(deps: Deps, sheet: RunSheet) -> tuple[Finding, ...]:
    return validate_run_sheet(sheet, deps.control.capabilities(), deps.control.safety())


def submit_draft(deps: Deps, role: str, data: DraftInput) -> dict:
    """File a run-sheet draft for operator review; approval is never part of this."""
    sheet = data.run_sheet
    own = check_sheet(deps, sheet)
    if any(finding.blocking for finding in own):
        return {"saved": False, "stage_id": sheet.stage_id, "findings": findings_json(own)}
    returned = deps.workflow.submit_run_sheet(data.round_id, sheet, actor_for(role))
    findings = findings_json([*own, *returned])
    if any(finding["blocking"] for finding in findings):
        return {"saved": False, "stage_id": sheet.stage_id, "findings": findings}
    state = deps.workflow.stage(sheet.stage_id).state.value
    return {"saved": True, "stage_id": sheet.stage_id, "state": state, "findings": findings}


def clip(text: str, limit: int = MAX_TEXT) -> str:
    return text if len(text) <= limit else text[:limit] + "...[truncated]"


def require_round(deps: Deps, round_id: str, expected: RoundState, project_id: str) -> None:
    """The round must belong to the project and be in the expected state.

    Checked before anything is created, so a refusal leaves no orphan snapshot or report.
    """
    if deps.workflow.store.round(round_id).project_id != project_id:
        raise Denied("scope", f"round {round_id} does not belong to this project")
    state = deps.workflow.round_state(round_id)
    if state is not expected:
        raise Denied("state", f"round {round_id} is {state.value}; this needs {expected.value}")


def experiment_project(deps: Deps, experiment_id: str) -> str | None:
    """The project that owns an experiment, known from the stage that runs it."""
    for stage in deps.workflow.store.stages_in(StageState):
        if stage.experiment_id == experiment_id:
            return stage.project_id
    return None


def _refuse_holdout_rows(deps: Deps, snap: Snapshot, project_id: str) -> None:
    """A snapshot frozen without the development filter may hold outcomes of a holdout batch.

    ``Snapshot`` carries no marker for that (the manifest only counts excluded rows), so the rows
    are checked against the registry's own predicate. The message never quotes a value.
    """
    if deps.holdout is None:
        return
    keep = deps.holdout.development_filter(project_id)
    path = deps.archive.root / "snapshots" / snap.id / "measurements.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not keep(ManualMeasurement.model_validate_json(line)):
            raise Denied("scope", f"snapshot {snap.id} holds outcomes of a held-out batch")


def scoped_snapshot(deps: Deps, task: ResearchTask, snapshot_id: str) -> Snapshot:
    """The snapshot a model names, if it belongs to the task's project and is fit for development.

    Unknown ids and other projects' snapshots look the same to the caller. Nothing of the
    snapshot is mounted or read before this passes.
    """
    snap = deps.archive.snapshot(snapshot_id)
    if snap is None or experiment_project(deps, snap.experiment_id) != task.project_id:
        raise Denied("scope", f"snapshot {snapshot_id} is not available to task {task.id}")
    _refuse_holdout_rows(deps, snap, task.project_id)
    return snap
