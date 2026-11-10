"""Operator interventions reach the archive and the frozen snapshot, exactly once."""

import json

from e2e_support import STAGE

from growbridge.archive import snapshot as snapshots


async def takeover_then_end(world, runtime):
    await world.approved_stage(runtime)
    await world.beat(runtime, 30)
    await runtime.workflow.takeover(STAGE, world.operator)
    await world.beat(runtime, 5)
    await runtime.workflow.handback(STAGE, world.operator, accept_as_intervention=False)
    await world.run_until_ended(runtime)
    return f"experiment-{STAGE}"


async def test_takeover_is_in_the_archive_and_in_the_frozen_snapshot(world):
    runtime = await world.boot()
    experiment = await takeover_then_end(world, runtime)

    archived = runtime.archive.interventions(experiment)
    assert [item["kind"] for item in archived] == ["takeover"]
    assert archived[0]["operator"] == "op-1" and archived[0]["stage_id"] == STAGE

    started = runtime.workflow.stage(STAGE).started_at
    snapshot = snapshots.freeze(
        runtime.archive, experiment, world.clock, started, world.clock.now(), 60, 120
    )
    assert "interventions.jsonl" in snapshot.files
    path = runtime.archive.root / "snapshots" / snapshot.id / "interventions.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [row["kind"] for row in rows] == ["takeover"]


async def test_mirroring_the_same_intervention_twice_leaves_one_archive_record(world):
    runtime = await world.boot()
    experiment = await takeover_then_end(world, runtime)
    item = runtime.workflow.interventions(experiment)[0]
    names = ("stage_id", "at", "kind", "operator")
    payload = {"experiment_id": experiment, **{name: item[name] for name in names}, "detail": {}}

    runtime.workflow.on_intervention(payload)
    runtime.workflow.on_intervention(payload)

    assert len(runtime.archive.interventions(experiment)) == 1


async def test_a_failing_mirror_raises_an_alert_and_keeps_the_stage_moving(world, monkeypatch):
    runtime = await world.boot()

    def broken(*_args, **_kwargs):
        raise RuntimeError("archive unavailable")

    monkeypatch.setattr(runtime.archive, "record_intervention", broken)
    await world.approved_stage(runtime)
    await runtime.workflow.takeover(STAGE, world.operator)

    assert runtime.workflow.stage(STAGE).state.value == "manual"
    alerts = [a for a in runtime.book.open() if a.kind == "intervention_mirror"]
    assert len(alerts) == 1 and "archive unavailable" in alerts[0].message
    assert runtime.archive.interventions(f"experiment-{STAGE}") == ()
