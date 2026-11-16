"""The live environment view (GET /wb/environment): what the device reads and does now.

It answers from the archive, never by asking the device: the newest sample gives the current
readings and channel levels, and recent samples, across stages and outside them, give the trends.
A running stage adds what its run sheet expects each channel to be at now, so a channel that is
not where the sheet wants it shows at a glance (a treatment that was never applied, a device that
ignored a write). A stage in any other state expects nothing: the run sheet is not in force.
"""

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from growbridge.archive.clock import Clock
from growbridge.archive.models import Channel, Ownership
from growbridge.archive.readings import bucketed_samples
from growbridge.archive.store import Archive
from growbridge.observer.alerts import AlertBook
from growbridge.ports import Actor, ControlPort
from growbridge.workbench.planned import planned_series
from growbridge.workflow.naming import STAGE_NAME_KEYS, stage_names
from growbridge.workflow.service import WorkflowService
from growbridge.workflow.states import StageState

DEFAULT_WINDOW = 6 * 3600
MIN_WINDOW, MAX_WINDOW = 300, 7 * 86400
DEFAULT_POINTS, MAX_POINTS = 360, 1000  # MAX_POINTS within archive/readings.MAX_POINTS
# the reading block of each level channel in a device sample (as control/device.MODULES)
MODULES = {Channel.LIGHT: "light", Channel.EXHAUST: "blower", Channel.FAN: "fan"}

_NEWEST = "SELECT at, body FROM samples ORDER BY at DESC, rowid DESC LIMIT 1"


def _number(value: Any) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


def _channels(data: dict, outlets: dict[Channel, int]) -> dict[str, dict]:
    """Each channel's recorded level and on/off state; None where the sample does not say."""
    found = {}
    for channel in Channel:
        if channel in MODULES:
            block = data.get(MODULES[channel])
            block = block if isinstance(block, dict) else {}
            level, on = _number(block.get("level")), _number(block.get("on"))
        else:  # the pump is an outlet: only on or off
            outlet = (data.get("outlet") or {}).get(f"O{outlets.get(channel)}")
            on = _number(outlet.get("on")) if isinstance(outlet, dict) else None
            level = on
        found[channel.value] = {"level": level, "on": None if on is None else bool(on)}
    return found


def latest_reading(archive: Archive, outlets: dict[Channel, int], now: float) -> dict | None:
    row = archive.db.one(_NEWEST)
    if row is None:
        return None
    body = json.loads(row["body"])
    data = body.get("data") or {}
    sensors = data.get("sensor") if isinstance(data.get("sensor"), dict) else {}
    return {
        "timestamp": row["at"],
        "age_seconds": max(0.0, now - row["at"]),
        "quality": body.get("quality", "ok"),
        "clock_synced": bool(body.get("clock_synced", True)),
        "experiment_id": body.get("experiment_id"),
        "sensors": {k: v for k, v in sensors.items() if _number(v) is not None},
        "channels": _channels(data, outlets),
    }


def active_stage(workflow: WorkflowService, now: float, window: float) -> dict | None:
    """The active stage, and what its run sheet expects of each channel now. Only a running stage
    follows the run sheet; paused, under takeover, in recovery check or ended, it expects
    nothing, so the page shows no difference from the run sheet. ``planned`` is the plan over the
    window, from the stage start. The stage is named as the stage read names it (project name,
    round number, stage index, phase)."""
    stage = workflow.active_stage()
    if stage is None:
        return None
    sheet = stage.run_sheet
    running = stage.state is StageState.RUNNING
    expected = sheet.expected_levels(now) if running else {}
    planned: dict[str, list[tuple[float, int]]] = {}
    if running and stage.started_at is not None:
        planned = planned_series(sheet, max(now - window, stage.started_at), now)
    row = workflow.store.find_stage(stage.stage_id)
    return {
        "stage_id": stage.stage_id,
        "state": stage.state.value,
        "experiment_id": stage.experiment_id,
        "project_id": stage.project_id,
        **(stage_names(workflow.store, row) if row else dict.fromkeys(STAGE_NAME_KEYS)),
        "started_at": stage.started_at,
        "ends_at": None if stage.started_at is None else stage.started_at + sheet.duration_seconds,
        "sampling_seconds": sheet.sampling.interval_seconds,
        "timezone": sheet.timezone,
        "planned": planned,
        "channels": {
            plan.channel.value: {
                "ownership": plan.ownership.value,
                "expected": expected.get(plan.channel)
                if plan.ownership is Ownership.HOST
                else None,
            }
            for plan in sheet.channels
        },
    }


def add_environment_routes(
    router: APIRouter,
    operator,
    workflow: WorkflowService,
    archive: Archive,
    control: ControlPort,
    clock: Clock,
    alerts: AlertBook | None = None,
) -> None:
    Operator = Annotated[Actor, Depends(operator)]  # noqa: N806

    @router.get("/environment")
    async def environment(
        actor: Operator,
        window: Annotated[int, Query(ge=MIN_WINDOW, le=MAX_WINDOW)] = DEFAULT_WINDOW,
        points: Annotated[int, Query(ge=2, le=MAX_POINTS)] = DEFAULT_POINTS,
    ):
        now = clock.now()
        caps = control.capabilities()
        open_alerts = () if alerts is None else alerts.open()
        severities: dict[str, int] = {}
        for alert in open_alerts:
            severities[alert.severity] = severities.get(alert.severity, 0) + 1
        return {
            "now": now,
            "clock_synced": clock.synced,
            "latest": latest_reading(archive, caps.outlets, now),
            "stage": active_stage(workflow, now, window),
            "sensors": caps.sensors,
            "level_ranges": {c.value: list(r) for c, r in caps.level_ranges.items()},
            "alerts": severities,
            "readings": bucketed_samples(archive.db, None, now - window, now, points),
        }
