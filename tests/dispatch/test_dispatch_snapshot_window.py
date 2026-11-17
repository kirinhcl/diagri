"""The snapshot window of a stage: device data up to the moment the stage actually ended (the
executor ends it on the tick after its planned end), manual measurements up to two hours later
(a harvest weight is taken when the stage ends), and what is left out is listed, not hidden."""

import json

from test_dispatch_researcher import (
    HOLE,
    _inspect,
    _measurement,
    _payload,
    _running_stage,
    _samples,
    _task_id,
)

from growbridge.agents.handlers_common import local_time
from growbridge.archive import snapshot as snapshots
from growbridge.archive.models import SamplingPlan
from growbridge.sim.clock import START
from growbridge.workflow.states import StageState

PLANNED_END = START + 10  # _running_stage plans a 10 s stage
LATE_TICK = 128  # the stage ended this long after its planned end (one fast-forward step)
GRACE = 2 * 3600


def _ended(env) -> float:
    store = env.workflow.store
    end = PLANNED_END + LATE_TICK
    store.update_stage(store.find_stage("stage-1"), state=StageState.ENDED, state_at=end)
    return end


def _rows(env, snapshot_id: str, name: str) -> list[dict]:
    path = env.archive.root / "snapshots" / snapshot_id / name
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


async def _freeze(env) -> dict:
    fields = {"task_id": _task_id(env), "stage_id": "stage-1"}
    return _payload(await env.invoke("researcher", "freeze_dataset", None, **fields))


async def test_device_data_runs_to_the_actual_end_and_no_further(env):
    await _running_stage(env)
    end = _ended(env)
    _samples(env, "experiment-stage-1", seconds=(100, LATE_TICK + 10 + 60))  # before, after end

    shot = await _freeze(env)

    manifest = _rows(env, shot["snapshot_id"], snapshots.MANIFEST)[0]
    assert manifest["window"] == [START, end]
    kept = {row["id"] for row in _rows(env, shot["snapshot_id"], "samples.jsonl")}
    assert "s-experiment-stage-1-100" in kept
    assert f"s-experiment-stage-1-{LATE_TICK + 10 + 60}" not in kept


async def test_a_measurement_up_to_two_hours_after_the_end_belongs_to_the_stage(env):
    await _running_stage(env)
    end = _ended(env)
    for ident, at in (("m-at-end", end), ("m-harvest", end + GRACE), ("m-later", end + GRACE + 1)):
        env.archive.add_measurement(_measurement("experiment-stage-1", 3.0, ident, measured_at=at))

    shot = await _freeze(env)

    kept = {row["id"] for row in _rows(env, shot["snapshot_id"], "measurements.jsonl")}
    assert kept == {"m-at-end", "m-harvest"}
    manifest = _rows(env, shot["snapshot_id"], snapshots.MANIFEST)[0]
    assert manifest["measurement_grace_seconds"] == GRACE


async def test_inspect_lists_the_measurements_left_outside_the_window(env):
    await _running_stage(env)
    end = _ended(env)
    late = _measurement("experiment-stage-1", 3.0, "m-later", measured_at=end + GRACE + 60)
    env.archive.add_measurement(late)

    body = _payload(await _inspect(env))

    late_at = end + GRACE + 60
    assert body["measurements_outside_window"] == [
        {
            "id": "m-later",
            "metric": "canopy_area_growth",
            "measured_at": late_at,
            "measured_at_local": local_time(late_at, "UTC"),
        }
    ]


async def test_inspect_counts_measurements_before_the_stage_start_and_does_not_list_them(env):
    # every stage of a round shares one experiment: an earlier stage's measurement is not
    # this stage's to judge
    await _running_stage(env)
    end = _ended(env)
    earlier = _measurement("experiment-stage-1", 3.0, "m-earlier", measured_at=START - 60)
    late = _measurement("experiment-stage-1", 3.0, "m-later", measured_at=end + GRACE + 60)
    env.archive.add_measurement(earlier)
    env.archive.add_measurement(late)

    body = _payload(await _inspect(env))

    assert [m["id"] for m in body["measurements_outside_window"]] == ["m-later"]
    assert body["measurements_outside_count"] == 1
    assert body["measurements_before_stage"] == 1


async def test_inspect_writes_the_local_time_beside_every_epoch(env):
    # the model is shown times in the reporting time zone, as the auditor's records do (RND-18)
    zone = "Europe/Helsinki"
    sampling = SamplingPlan(interval_seconds=1, max_gap_seconds=2)
    await _running_stage(env, seconds=HOLE, sampling=sampling)
    end = _ended(env)
    late_at = end + GRACE + 60
    late = _measurement("experiment-stage-1", 3.0, "m-later", measured_at=late_at)
    env.archive.add_measurement(late)

    body = _payload(await _inspect(env, env.make_deps(timezone=zone)))

    assert body["window_local"] == [local_time(at, zone) for at in body["window"]]
    assert body["gaps"], "the silence in HOLE leaves a gap"
    gaps = [[local_time(a, zone), local_time(b, zone)] for a, b in body["gaps"]]
    assert body["gaps_local"] == gaps
    [listed] = body["measurements_outside_window"]
    assert listed["measured_at_local"] == local_time(late_at, zone)
