"""A model task starts with its project's history (memory design 2026-11-17)."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from test_e2e_agents import design, task

from growbridge.agents.dispatch import INTRO
from growbridge.archive.ids import file_digest
from growbridge.archive.models import (
    ActionRecord,
    ActionState,
    Artifact,
    Channel,
    RightKind,
    Snapshot,
)
from growbridge.ports import Actor
from growbridge.sim.llm import ScriptedClient, text_reply
from growbridge.workflow.states import RoundState, StageState
from growbridge.workflow.store import StageRow

DAY, HOUR = 86400.0, 3600.0
STAGE = "stage-memory"
EXPERIMENT = "experiment-memory"


def task_record(client) -> dict:
    """The record of the first request's task message, as the model received it."""
    first = client.requests[0]["messages"][0]["content"]
    return json.loads(first[len(INTRO) :])


async def test_a_task_message_carries_the_history(world):
    runtime = await world.boot()
    project, _, _ = await design(world, runtime)
    runtime.notes.add(runtime.settings.device, "alice", "changed the CO2 probe")
    runtime.tasks.create(task(project, "planner", "ev-plan"))

    client = ScriptedClient([text_reply("ok")])
    await runtime.run_agents(client)

    history = task_record(client)["context"]["history"]
    assert set(history) == {"rounds", "patterns", "episodes", "notes"}
    assert [n["text"] for n in history["notes"]] == ["changed the CO2 probe"]


def delivered_round(world, runtime, project: str, round_id: str) -> None:
    """Round 1 ran for four days and was delivered with a report on snapshot ``snap-1``."""
    store, archive, now = runtime.workflow.store, runtime.archive, world.clock.now()
    sheet = world.sheet(project, id="sheet-memory", stage_id=STAGE, experiment_id=EXPERIMENT)
    store.put_run_sheet(sheet, round_id, now)
    store.add_stage(
        StageRow(
            stage_id=STAGE,
            round_id=round_id,
            project_id=project,
            experiment_id=EXPERIMENT,
            device_id=str(runtime.settings.device),
            run_sheet_id=sheet.id,
            run_sheet_version=sheet.version,
            state=StageState.ENDED,
            started_at=now - 5 * DAY,
            state_at=now - HOUR,
            recovery_number=0,
        )
    )
    snap = Snapshot(
        id="snap-1",
        experiment_id=EXPERIMENT,
        version=1,
        created_at=now,
        manifest_sha256="0" * 64,
        complete=True,
        coverage=1.0,
    )
    archive.save_snapshot(snap, ["m-1"])
    path = world.settings.data_dir / "report-memory.json"
    body = {"label": "confirmatory", "conclusion": "supported", "estimate": {"effect": 2.5}}
    path.write_text(json.dumps({**body, "evidence_chain": ["snapshot:snap-1"], "holdout_id": None}))
    report = Artifact(
        id="art-memory",
        task_id="task-memory",
        kind="research_report",
        path=str(path),
        sha256=file_digest(path),
        label="confirmatory",
        snapshot_id="snap-1",
    )
    archive.add_artifact(report)
    store.update_round(round_id, state=RoundState.DELIVERED, report_artifact_id=report.id)


def protect(runtime, at: float, n: int) -> None:
    runtime.archive.append_action(
        ActionRecord(
            request_id=f"req-memory-{n}",
            state=ActionState.CONFIRMED,
            channel=Channel.EXHAUST,
            planned_level=100,
            right_number=1,
            right_kind=RightKind.PROTECTION,
            trigger="protect:hot",
            created_at=at,
            experiment_id=EXPERIMENT,
            stage_id=STAGE,
        )
    )


async def test_a_planner_task_sees_the_earlier_round_and_the_device_history(world):
    runtime = await world.boot()
    project, _, round_id = await design(world, runtime)
    delivered_round(world, runtime, project, round_id)
    runtime.archive.mark_dependents_invalid("m-1")  # a correction of a measurement behind it
    now = world.clock.now()
    for day in (1, 2, 3):  # the day before, and the two before that, at about the same hour
        protect(runtime, now - day * DAY + 4 * HOUR, day)
    period = runtime.archive.open_frozen("co2", 400.0, now - 2 * DAY)
    alert = runtime.book.raise_alert("frozen_reading", "co2", "warning", "flat")
    runtime.book.mark_read(alert.event_id, Actor(kind="operator", id="alice"), note="wire loose")
    world.clock.advance(60)
    runtime.archive.close_frozen(period, "co2", now - 2 * DAY + 3 * HOUR, "value_changed")
    runtime.book.resolve("frozen_reading", "co2")
    runtime.tasks.create(task(project, "planner", "ev-memory"))

    client = ScriptedClient([text_reply("ok")])
    await runtime.run_agents(client)

    history = task_record(client)["context"]["history"]
    (earlier,) = history["rounds"]
    assert earlier["round_id"] == round_id
    assert earlier["report"] == {"invalid": True, "label": "confirmatory"}
    assert "2.5" not in json.dumps(history)
    hot = [p for p in history["patterns"] if p["kind"] == "protection" and p["subject"] == "hot"]
    assert hot and hot[0]["recurring"] is True and hot[0]["days"] == 3
    assert any("wire loose" in line for line in history["episodes"])

    # the daily report of the day before lists the same problem
    zone = ZoneInfo(runtime.settings.report_timezone)
    day = datetime.fromtimestamp(now - DAY, zone).date()
    text = runtime._report_text(runtime.workflow.stage(STAGE), day)
    assert "Recurring:\n- protect:hot on 3 of the last 7 days" in text
