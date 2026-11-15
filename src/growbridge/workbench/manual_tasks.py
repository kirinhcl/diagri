"""The manual tasks of a stage: what is due, what was done, and the planned irrigation.

- ``GET /wb/stages/{stage_id}/manual-tasks`` lists each daily occurrence the run sheet plans in
  the stage window, with its state and the record that counts.
- ``POST /wb/stages/{stage_id}/manual-tasks`` records that an occurrence was done (at a stated
  time, never in the future) or skipped. Records are appended; the latest one counts.
- ``POST /wb/stages/{stage_id}/manual-tasks/irrigate`` runs a planned irrigation (an irrigation
  task with ``seconds``) and records it as done. It is started by a person on the LAN entry,
  like every irrigation, but under the stage right: the stage keeps running and no takeover
  (an intervention) is needed. The control service applies all the irrigation checks: the pump
  time limit, the cooldown, the interlock, and the switch-off that always runs.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import Field

from growbridge.archive.clock import Clock
from growbridge.archive.ids import new_id
from growbridge.archive.models import ActionState, Channel, TaskRecord
from growbridge.archive.store import Archive
from growbridge.planning import manual_tasks
from growbridge.ports import ActionRequest, Actor, ControlPort, Denied, StageRuntime
from growbridge.workbench.common import REQUEST_ID, Body
from growbridge.workflow.service import WorkflowService
from growbridge.workflow.states import StageState


class TaskOutcome(Body):
    task_id: str = Field(min_length=1, max_length=100)
    due_at: float
    outcome: Literal["done", "skipped"]
    done_at: float | None = None  # when it was done; default now (only for "done")
    note: str = Field(default="", max_length=200)


class PlannedIrrigation(Body):
    task_id: str = Field(min_length=1, max_length=100)
    due_at: float
    request_id: str = Field(pattern=REQUEST_ID)
    note: str = Field(default="", max_length=200)


def _window(stage: StageRuntime) -> tuple[float, float]:
    if stage.started_at is None:
        raise Denied("state", "the stage has not started; no manual task is due yet")
    return stage.started_at, stage.started_at + stage.run_sheet.duration_seconds


def _occurrence(
    workflow: WorkflowService, stage_id: str, task_id: str, due_at: float
) -> tuple[StageRuntime, manual_tasks.Occurrence]:
    stage = workflow.stage(stage_id)
    start, end = _window(stage)
    wanted = manual_tasks.key(task_id, due_at)
    for item in manual_tasks.occurrences(stage.run_sheet, start, end):
        if manual_tasks.key(item.task_id, item.due_at) == wanted:
            return stage, item
    raise Denied("scope", f"the run sheet plans no task {task_id} due at that time")


def _due(item: manual_tasks.Occurrence, now: float) -> None:
    if now < item.due_at - manual_tasks.EARLY_SECONDS:
        raise Denied("state", "this task is not due yet")


def _check_irrigation(archive: Archive, stage: StageRuntime, item, now: float) -> None:
    """The pump runs at most once per occurrence (a later "skipped" record does not undo a run),
    never after the occurrence's deadline, and not for an occurrence already done."""
    start, end = _window(stage)
    if now > manual_tasks.deadline(item, end):
        raise Denied("state", "this irrigation is past its deadline")
    wanted = manual_tasks.key(item.task_id, item.due_at)
    records = archive.task_records(stage.experiment_id, start, end)
    mine = [r for r in records if manual_tasks.key(r.task_id, r.due_at) == wanted]
    if any(record.irrigation_request_id is not None for record in mine):
        raise Denied("state", "the pump already ran for this irrigation")
    if _current(archive, stage, item, now)["status"] in ("done", "late"):
        raise Denied("state", "this irrigation is already recorded as done")


def _row(item, record: TaskRecord | None, state: str) -> dict:
    return {
        **item.model_dump(mode="json"),
        "status": state,
        "record": None if record is None else record.model_dump(mode="json"),
    }


def _current(archive: Archive, stage: StageRuntime, item, now: float) -> dict:
    start, end = _window(stage)
    records = archive.task_records(stage.experiment_id, start, end)
    ((_, record, state),) = manual_tasks.statuses([item], records, now, end)
    return _row(item, record, state)


def _record(
    archive: Archive, stage: StageRuntime, item, actor: Actor, now: float, **fields
) -> TaskRecord:
    record = TaskRecord(
        id=new_id("taskrec"),
        experiment_id=stage.experiment_id,
        stage_id=stage.stage_id,
        task_id=item.task_id,
        kind=item.kind,
        due_at=item.due_at,
        operator=actor.id,
        recorded_at=now,
        **fields,
    )
    archive.add_task_record(record)
    return record


def add_manual_task_routes(
    router: APIRouter,
    operator,
    on_site,
    workflow: WorkflowService,
    archive: Archive,
    control: ControlPort,
    clock: Clock,
) -> None:
    Operator = Annotated[Actor, Depends(operator)]  # noqa: N806
    OnSite = Annotated[Actor, Depends(on_site)]  # noqa: N806

    @router.get("/stages/{stage_id}/manual-tasks")
    async def list_tasks(stage_id: str, actor: Operator):
        stage = workflow.stage(stage_id)
        body = {
            "stage_id": stage.stage_id,
            "stage_state": stage.state.value,
            "timezone": stage.run_sheet.timezone,
            "on_time_seconds": manual_tasks.ON_TIME_SECONDS,
            "early_seconds": manual_tasks.EARLY_SECONDS,
            "now": clock.now(),
            "occurrences": [],
        }
        if stage.started_at is None:
            return body
        start, end = _window(stage)
        items = manual_tasks.occurrences(stage.run_sheet, start, end)
        records = archive.task_records(stage.experiment_id, start, end)
        rows = manual_tasks.statuses(items, records, body["now"], end)
        body["occurrences"] = [_row(item, record, state) for item, record, state in rows]
        return body

    @router.post("/stages/{stage_id}/manual-tasks")
    async def record_task(stage_id: str, body: TaskOutcome, actor: Operator):
        stage, item = _occurrence(workflow, stage_id, body.task_id, body.due_at)
        now = clock.now()
        _due(item, now)
        done_at = None
        if body.outcome == "done":
            done_at = now if body.done_at is None else body.done_at
            if done_at > now or done_at < item.due_at - manual_tasks.EARLY_SECONDS:
                raise Denied(
                    "param", "done_at must be in the past and at most an hour before the task"
                )
        elif body.done_at is not None:
            raise Denied("param", "a skipped task has no done_at")
        _record(
            archive,
            stage,
            item,
            actor,
            now,
            outcome=body.outcome,
            done_at=done_at,
            note=body.note.strip(),
        )
        return _current(archive, stage, item, now)

    @router.post("/stages/{stage_id}/manual-tasks/irrigate")
    async def irrigate(stage_id: str, body: PlannedIrrigation, actor: OnSite):
        stage, item = _occurrence(workflow, stage_id, body.task_id, body.due_at)
        if item.kind != "irrigation" or item.seconds is None:
            raise Denied("scope", "this task is not a planned irrigation (it has no seconds)")
        if stage.state is not StageState.RUNNING or stage.right_number is None:
            raise Denied("state", "a planned irrigation runs only while the stage is running")
        now = clock.now()
        _due(item, now)
        _check_irrigation(archive, stage, item, now)
        note = body.note.strip()
        request = ActionRequest(
            request_id=body.request_id,
            right_number=stage.right_number,
            channel=Channel.PUMP,
            level=1,
            trigger=f"planned irrigation {item.task_id}" + (f": {note}" if note else ""),
            experiment_id=stage.experiment_id,
            stage_id=stage.stage_id,
            operator=actor.id,
        )
        action = await control.irrigate(request, item.seconds, planned=True)
        task = None
        if action.state is ActionState.CONFIRMED:
            now = clock.now()
            _record(
                archive,
                stage,
                item,
                actor,
                now,
                outcome="done",
                done_at=now,
                note=note,
                irrigation_request_id=action.request_id,
            )
            task = _current(archive, stage, item, now)
        return {"action": action.model_dump(mode="json"), "task": task}
