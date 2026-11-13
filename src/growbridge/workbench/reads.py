"""Read-only workbench routes for the browser console, under ``/wb``.

Operators only: no login is refused with ``session`` and a model role with ``model_role``. None of
these routes writes. The inbox gathers what waits for a person, at most ``INBOX_LIMIT`` items of
each kind, oldest first (alerts: most urgent first); a kind whose service is not mounted is simply
empty. Rounds and tasks are fetched with that limit and the number cut comes from a COUNT query.
A stage's readings are reused for 15 s per (stage, points, stage state), so the page's refresh
does not scan the whole stage window every time.
"""

import copy
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from growbridge.archive.clock import Clock
from growbridge.archive.readings import DEFAULT_POINTS, MAX_POINTS, bucketed_samples
from growbridge.archive.store import Archive
from growbridge.compute.service import ComputeService
from growbridge.observer.alerts import AlertBook, awaits_reading
from growbridge.ports import Actor, ControlPort, Denied
from growbridge.workbench.rounds import PathId, ProjectBudget
from growbridge.workflow.listing import (
    count_rounds_awaiting_choice,
    project_detail,
    project_summaries,
    rounds_awaiting_choice,
)
from growbridge.workflow.service import WorkflowService
from growbridge.workflow.states import StageState, TaskState
from growbridge.workflow.store import StageRow
from growbridge.workflow.tasks import TaskBoard

INBOX_LIMIT = 50
READINGS_CACHE_SECONDS = 15.0  # the stage page's refresh interval
READINGS_CACHE_SIZE = 64  # (stage, points) answers kept at most
SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}
PROJECT_LIMIT = 200
TASK_LIMIT = 100
Dependency = Callable[..., Awaitable[Actor]]
STAGE_KINDS = {
    StageState.PENDING_REVIEW: "stage_review",
    StageState.MANUAL: "stage_manual",
    StageState.RECOVERY_CHECK: "stage_recovery",
    StageState.PAUSED: "stage_paused",
}
ATTENTION_TASKS = (TaskState.NEEDS_ATTENTION, TaskState.NEEDS_REVIEW)
FINISHED_STAGES = (StageState.ENDED, StageState.STOPPED)


def _item(kind, ident, project_id, round_id, since, detail) -> dict[str, Any]:
    return {
        "kind": kind,
        "id": ident,
        "project_id": project_id,
        "round_id": round_id,
        "since": since,
        "detail": detail,
    }


def _by_age(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items.sort(key=lambda item: (item["since"] is not None, item["since"] or 0.0))
    return items


def _urgency(item: dict[str, Any]) -> tuple[int, float]:
    """Alerts survive the cap by severity, then by how recently they were raised."""
    detail = item["detail"]
    return (SEVERITY_RANK.get(detail["severity"], len(SEVERITY_RANK)), -detail["last_at"])


def _cap(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """At most ``INBOX_LIMIT`` of each kind (oldest first; alerts most urgent first), the
    survivors oldest first, and how many items of each kind were cut."""
    kept: list[dict[str, Any]] = []
    truncated: dict[str, int] = {}
    for kind in sorted({item["kind"] for item in items}):
        of_kind = [item for item in items if item["kind"] == kind]
        ranked = sorted(of_kind, key=_urgency) if kind == "alert" else _by_age(list(of_kind))
        kept += ranked[:INBOX_LIMIT]
        if len(ranked) > INBOX_LIMIT:
            truncated[kind] = len(ranked) - INBOX_LIMIT
    return _by_age(kept), truncated


def _stage_items(workflow: WorkflowService) -> list[dict[str, Any]]:
    store = workflow.store
    found: list[dict[str, Any]] = []
    for state, kind in STAGE_KINDS.items():
        for row in store.stages_in((state,)):
            entered = store.entered(row.stage_id, state)
            since = entered["at"] if entered else row.state_at
            detail = {"state": state.value, "device_id": row.device_id}
            found.append(_item(kind, row.stage_id, row.project_id, row.round_id, since, detail))
    return found


def _choice_since(workflow: WorkflowService, row: dict[str, Any]) -> tuple[float, str]:
    """A round waits for a choice from when the stage named in ``awaiting_choice`` stopped. When
    that stage is gone or not stopped, the round's creation time is shown and labelled as such."""
    stage = workflow.store.find_stage(row["awaiting_choice"])
    if stage is not None and stage.state is StageState.STOPPED:
        return stage.state_at, "stage_stopped"
    return row["created_at"], "round_created"


def _round_items(workflow: WorkflowService) -> list[dict[str, Any]]:
    items = []
    for row in rounds_awaiting_choice(workflow.store, INBOX_LIMIT):
        since, since_from = _choice_since(workflow, row)
        detail = {"awaiting_choice": row["awaiting_choice"], "since_from": since_from}
        round_id = row["round_id"]
        items.append(_item("round_choice", round_id, row["project_id"], round_id, since, detail))
    return items


def _alert_items(alerts: AlertBook | None, now: float) -> list[dict[str, Any]]:
    if alerts is None:
        return []
    items = [
        _item(
            "alert",
            alert.event_id,
            None,
            None,
            alert.first_at,
            {
                "alert_kind": alert.kind,
                "severity": alert.severity,
                "message": alert.message,
                "count": alert.count,
                "last_at": alert.last_at,
            },
        )
        for alert in alerts.open()
        if awaits_reading(alert, now)  # unread, worse than when read, or read over a day ago
    ]
    return items


def _compute_items(compute: ComputeService | None) -> list[dict[str, Any]]:
    if compute is None:
        return []
    return [
        _item("compute_stuck", job["attempt_id"], None, None, job["since"], dict(job))
        for job in compute.overview()["stuck"]
    ]


def _task_items(tasks: TaskBoard | None) -> list[dict[str, Any]]:
    if tasks is None:
        return []
    found = tasks.in_states(ATTENTION_TASKS, INBOX_LIMIT)
    since = tasks.state_since([task.id for task in found])
    return [
        _item(
            "task",
            task.id,
            task.project_id,
            None,
            since.get(task.id),
            {"question": task.question, "state": task.state.value, "owner_role": task.owner_role},
        )
        for task in found
    ]


def _budget_view(budget: ProjectBudget | None, project_id: str) -> dict[str, Any] | None:
    if budget is None:
        return None
    try:
        calls, cost = budget.remaining(project_id)
    except Denied as refusal:
        if refusal.code == "budget":
            return None
        raise
    return {"calls_left": calls, "cost_left": cost}


def _stage(workflow: WorkflowService, stage_id: str) -> StageRow:
    row = workflow.store.find_stage(stage_id)
    if row is None:
        raise Denied("state", f"unknown stage {stage_id}")
    return row


class ReadingsCache:
    """A stage's readings per key (stage, points and the stage state the answer depends on), reused
    for ``seconds`` of the injected monotonic clock: the stage page asks every 15 s, and each answer
    scans the whole stage window. At most ``size`` answers are kept; the one used least recently
    goes first. Callers get a copy, so none can change the shared entry."""

    def __init__(
        self, clock: Clock, seconds: float = READINGS_CACHE_SECONDS, size: int = READINGS_CACHE_SIZE
    ):
        self.clock = clock
        self.seconds = seconds
        self.size = size
        self._entries: OrderedDict[tuple[Any, ...], tuple[float, dict[str, Any]]] = OrderedDict()

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, key: tuple[Any, ...], compute: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        now = self.clock.monotonic()
        kept = self._entries.get(key)
        if kept is not None and now - kept[0] < self.seconds:
            self._entries.move_to_end(key)
            return copy.deepcopy(kept[1])
        value = compute()
        self._entries[key] = (now, value)
        self._entries.move_to_end(key)
        while len(self._entries) > self.size:
            self._entries.popitem(last=False)
        return copy.deepcopy(value)


def _empty_readings() -> dict[str, Any]:
    return {
        "samples": [],
        "window": None,
        "total_samples": 0,
        "flagged_total": 0,
        "downsampled": False,
    }


def add_read_routes(
    router: APIRouter,
    operator: Dependency,
    workflow: WorkflowService,
    archive: Archive,
    control: ControlPort,
    clock: Clock,
    *,
    tasks: TaskBoard | None = None,
    budget: ProjectBudget | None = None,
    alerts: AlertBook | None = None,
    compute: ComputeService | None = None,
) -> None:
    _inbox_routes(router, operator, workflow, tasks, alerts, compute, clock)
    _project_routes(router, operator, workflow, tasks, budget)
    _stage_read_routes(router, operator, workflow, archive, clock)

    Operator = Annotated[Actor, Depends(operator)]  # noqa: N806

    @router.get("/safety")
    async def safety(actor: Operator):
        config = control.safety()
        return {"safety": None if config is None else config.model_dump(mode="json")}


def _inbox_routes(router, operator, workflow, tasks, alerts, compute, clock) -> None:
    Operator = Annotated[Actor, Depends(operator)]  # noqa: N806

    @router.get("/inbox")
    async def inbox(actor: Operator):
        kept, truncated = _cap(
            _stage_items(workflow) + _alert_items(alerts, clock.now()) + _compute_items(compute)
        )
        fetched = {"round_choice": _round_items(workflow), "task": _task_items(tasks)}
        counts = {
            "round_choice": count_rounds_awaiting_choice(workflow.store),
            "task": 0 if tasks is None else tasks.count_in_states(ATTENTION_TASKS),
        }
        for kind, items in fetched.items():
            kept += items
            if counts[kind] > INBOX_LIMIT:
                truncated[kind] = counts[kind] - INBOX_LIMIT
        return {"items": _by_age(kept), "truncated": truncated}


def _project_routes(router, operator, workflow, tasks, budget) -> None:
    Operator = Annotated[Actor, Depends(operator)]  # noqa: N806

    @router.get("/projects")
    async def projects(actor: Operator):
        return {"projects": project_summaries(workflow.store, PROJECT_LIMIT)}

    @router.get("/projects/{project_id}")
    async def project(project_id: PathId, actor: Operator):
        detail = project_detail(workflow.store, project_id)
        if detail is None:
            raise Denied("state", f"unknown project {project_id}")
        listed = () if tasks is None else tasks.list(project_id)[:TASK_LIMIT]
        return {
            **detail,
            "budget": _budget_view(budget, project_id),
            "tasks": [task.model_dump(mode="json") for task in listed],
        }


def _stage_read_routes(router, operator, workflow, archive, clock) -> None:
    Operator = Annotated[Actor, Depends(operator)]  # noqa: N806
    cache = ReadingsCache(clock)

    @router.get("/stages/{stage_id}/readings")
    async def readings(
        stage_id: PathId,
        actor: Operator,
        points: Annotated[int, Query(ge=2, le=MAX_POINTS)] = DEFAULT_POINTS,
    ):
        row = _stage(workflow, stage_id)
        if row.started_at is None:
            return _empty_readings()
        started_at = row.started_at
        end = row.state_at if row.state in FINISHED_STAGES else clock.now()

        def compute() -> dict[str, Any]:
            return bucketed_samples(archive.db, row.experiment_id, started_at, end, points)

        key = (stage_id, points, row.state, row.state_at, started_at, row.experiment_id)
        return cache.get(key, compute)

    @router.get("/stages/{stage_id}/measurements")
    async def measurements(stage_id: PathId, actor: Operator):
        row = _stage(workflow, stage_id)
        found = archive.measurements(row.experiment_id, include_corrected=True)
        return {"measurements": [record.model_dump(mode="json") for record in found]}

    @router.get("/stages/{stage_id}/history")
    async def history(stage_id: PathId, actor: Operator):
        row = _stage(workflow, stage_id)
        mine = [
            entry
            for entry in workflow.store.interventions(row.experiment_id)
            if entry["stage_id"] == stage_id
        ]
        return {"history": workflow.store.history(stage_id), "interventions": mine}
