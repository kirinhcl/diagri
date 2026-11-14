"""The watchdog's alerts through the real runtime: raised, notified, closed and raised anew."""

import json

from e2e_support import STAGE, RecordingChannel

from growbridge.archive import snapshot as snapshots
from growbridge.archive.models import Channel

KIND = "pump_unexpected"
KIND_WATERING = "unexpected_watering"


def pump_alerts(runtime):
    return [a for a in runtime.book.open() if a.kind == KIND]


def panel_on(world):
    world.sim.external_change("outlet", "O4", mOnOff=1)


async def test_panel_pump_on_raises_one_critical_alert_and_one_notification(world):
    channel = RecordingChannel()
    runtime = await world.boot(channels={"rec": channel})
    panel_on(world)
    await world.beat(runtime, 5)

    [alert] = pump_alerts(runtime)
    assert alert.severity == "critical" and alert.key == "pump"
    assert runtime.outbox.status(alert.event_id, "rec") is not None
    assert (await runtime.control.read_state()).levels[Channel.PUMP] == 0


async def test_an_off_status_closes_the_alert_and_a_later_pump_on_is_a_new_event(world):
    runtime = await world.boot(channels={"rec": RecordingChannel()})
    panel_on(world)
    await world.beat(runtime, 5)
    [first] = pump_alerts(runtime)

    await world.beat(runtime, 5)  # the status now reads off (the watchdog switched it off)
    assert pump_alerts(runtime) == []
    assert runtime.book.get(first.event_id).resolved_at is not None

    panel_on(world)
    await world.beat(runtime, 5)
    [second] = pump_alerts(runtime)
    assert second.event_id != first.event_id
    assert runtime.outbox.status(second.event_id, "rec") is not None


async def test_an_unexpected_watering_reaches_the_archive_and_a_snapshot(world):
    runtime = await world.boot()
    await world.approved_stage(runtime)
    await world.beat(runtime, 30)
    panel_on(world)
    await world.beat(runtime, 5)

    experiment = f"experiment-{STAGE}"
    archived = [i for i in runtime.archive.interventions(experiment) if i["kind"] == KIND_WATERING]
    assert len(archived) == 1
    assert archived[0]["operator"] is None and archived[0]["stage_id"] == STAGE

    started = runtime.workflow.stage(STAGE).started_at
    snapshot = snapshots.freeze(
        runtime.archive, experiment, world.clock, started, world.clock.now(), 60, 120
    )
    path = runtime.archive.root / "snapshots" / snapshot.id / "interventions.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [row["kind"] for row in rows] == [KIND_WATERING]


async def test_a_watchdog_alert_whose_first_write_failed_is_written_on_the_next_tick(
    world, monkeypatch
):
    runtime = await world.boot()

    def unreadable():
        raise RuntimeError("bad status")

    monkeypatch.setattr(runtime.control, "pump_reading", unreadable)
    real = runtime.book.raise_alert
    refused: list[str] = []

    def locked_once(kind, key, severity, message):
        if kind == "pump_watchdog" and not refused:
            refused.append(kind)
            raise RuntimeError("database is locked")
        return real(kind, key, severity, message)

    monkeypatch.setattr(runtime.book, "raise_alert", locked_once)
    await world.beat(runtime, 5)
    assert refused and not [a for a in runtime.book.open() if a.kind == "pump_watchdog"]

    await world.beat(runtime, 5)  # far less than the 300 s re-raise interval

    assert [a.key for a in runtime.book.open() if a.kind == "pump_watchdog"] == ["step"]
