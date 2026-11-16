"""The console's reads name rounds and stages: the project's name, the round's number among the
project's rounds of its protocol, the stage's place in its round and the growth phase the protocol
gives that place. The names are added beside the ids; no key the reads had before changes."""

import pytest

from growbridge.archive import snapshot as snapshots
from growbridge.archive.models import Budget, ResearchTask
from growbridge.sim.clock import START
from growbridge.sim.fixtures import make_protocol
from growbridge.workbench.api import runtime_json
from growbridge.workflow.naming import STAGE_NAME_KEYS, stage_names
from growbridge.workflow.states import StageState, TaskState

PROJECT = "Lettuce light"
PHASES = ("vegetative", "flowering")
OLD_ROUND_KEYS = (
    "round_id",
    "project_id",
    "protocol_id",
    "protocol_version",
    "state",
    "stages_done",
    "awaiting_choice",
    "snapshot_id",
    "report_artifact_id",
    "stage_total",
)
OLD_PROJECT_ROUND_KEYS = (
    "round_id",
    "state",
    "protocol_id",
    "protocol_version",
    "awaiting_choice",
    "created_at",
)


def seed(bench, phases=PHASES) -> tuple[str, str]:
    """A project, a protocol with ``phases`` and two rounds of it (the first: bench.round_id)."""
    bench.project_id = bench.workflow.create_project(PROJECT, bench.designer)
    protocol = make_protocol(project_id=bench.project_id, stages=phases)
    bench.workflow.save_protocol(protocol, bench.designer)
    first = bench.workflow.create_round(bench.project_id, protocol.id, bench.designer)
    second = bench.workflow.create_round(bench.project_id, protocol.id, bench.designer)
    bench.round_id = first
    return first, second


def names(item: dict) -> dict:
    return {key: item[key] for key in STAGE_NAME_KEYS}


def task(ident: str, project_id: str) -> ResearchTask:
    return ResearchTask(
        id=ident,
        project_id=project_id,
        question="does more light help?",
        owner_role="researcher",
        budget=Budget(max_calls=5, max_cost=1.0),
        trigger_event_id=f"trigger-{ident}",
        correlation_id=f"corr-{ident}",
    )


def test_round_read_names_its_round_and_stages(bench, operator):
    first, second = seed(bench)
    bench.pending("stage-1")
    bench.pending("stage-2")

    body = operator.get(f"/wb/rounds/{first}").json()

    assert body["round_number"] == 1 and body["project_name"] == PROJECT
    assert body["stages"] == [
        {"stage_id": "stage-1", "state": "pending_review", "stage_index": 1, "phase": "vegetative"},
        {"stage_id": "stage-2", "state": "pending_review", "stage_index": 2, "phase": "flowering"},
    ]
    later = operator.get(f"/wb/rounds/{second}").json()
    assert (later["round_number"], later["project_name"], later["stages"]) == (2, PROJECT, [])


def test_stage_read_names_index_and_phase(bench, operator):
    seed(bench)
    bench.pending("stage-1")
    bench.pending("stage-2")

    body = operator.get("/wb/stages/stage-2").json()

    assert names(body) == {
        "project_name": PROJECT,
        "round_number": 1,
        "stage_index": 2,
        "phase": "flowering",
    }


def test_model_tokens_get_no_names_on_the_stage_read(bench):
    seed(bench)
    bench.pending("stage-1")

    body = bench.lan.get("/wb/stages/stage-1", headers=bench.model("analyst")).json()

    assert not set(STAGE_NAME_KEYS) & set(body)  # as before: no round, so no round number


def test_phase_is_none_beyond_the_protocol_stages(bench, operator):
    first, _ = seed(bench, phases=("vegetative",))
    bench.pending("stage-1")
    bench.pending("stage-2")

    stages = operator.get(f"/wb/rounds/{first}").json()["stages"]
    stage = operator.get("/wb/stages/stage-2").json()

    assert [(row["stage_index"], row["phase"]) for row in stages] == [(1, "vegetative"), (2, None)]
    assert (stage["stage_index"], stage["phase"]) == (2, None)


def test_phase_is_none_when_the_rounds_protocol_is_gone(bench, operator):
    first, _ = seed(bench)
    bench.pending("stage-1")
    bench.workflow.store.db.execute("DELETE FROM wf_protocols")

    stage = operator.get(f"/wb/rounds/{first}").json()["stages"][0]

    assert (stage["stage_index"], stage["phase"]) == (1, None)


def test_a_missing_project_or_round_is_named_none_not_refused(bench):
    seed(bench)
    bench.pending("stage-1")
    store = bench.workflow.store
    row = store.stage("stage-1")
    store.db.execute("DELETE FROM wf_rounds")

    assert stage_names(store, row) == {**dict.fromkeys(STAGE_NAME_KEYS), "project_name": PROJECT}

    store.db.execute("DELETE FROM wf_projects")

    assert stage_names(store, row) == dict.fromkeys(STAGE_NAME_KEYS)


def test_project_reads_carry_round_numbers(bench, operator):
    first, second = seed(bench)
    other = make_protocol(id="protocol-2", project_id=bench.project_id)
    bench.workflow.save_protocol(other, bench.designer)
    third = bench.workflow.create_round(bench.project_id, other.id, bench.designer)

    detail = operator.get(f"/wb/projects/{bench.project_id}").json()
    summary = operator.get("/wb/projects").json()["projects"][0]

    numbers = [(row["round_id"], row["round_number"]) for row in detail["rounds"]]
    assert numbers == [(third, 1), (second, 2), (first, 1)]  # newest first, counted per protocol
    assert summary["latest_round"]["round_number"] == 1  # the newest round, of protocol-2


def test_inbox_items_carry_names(bench, operator):
    _, second = seed(bench)
    bench.pending("stage-1")
    bench.workflow.store.update_round(second, awaiting_choice="stage-gone")
    bench.tasks.create(task("task-1", bench.project_id))
    bench.tasks.create(task("task-2", "project-gone"))
    for ident in ("task-1", "task-2"):
        bench.tasks.transition(ident, TaskState.NEEDS_ATTENTION, f"ev-{ident}", "stuck")
    bench.alerts.raise_alert("threshold", "too_hot", "critical", "31 C")

    items = {item["id"]: item for item in operator.get("/wb/inbox").json()["items"]}

    assert names(items["stage-1"]) == {
        "project_name": PROJECT,
        "round_number": 1,
        "stage_index": 1,
        "phase": "vegetative",
    }
    assert names(items[second]) == {
        "project_name": PROJECT,
        "round_number": 2,
        "stage_index": None,
        "phase": None,
    }
    assert items["task-1"]["project_name"] == PROJECT
    assert items["task-2"]["project_name"] is None
    assert not {"round_number", "stage_index", "phase"} & set(items["task-1"])
    alert = next(item for item in items.values() if item["kind"] == "alert")
    assert not set(STAGE_NAME_KEYS) & set(alert)


def test_environment_stage_carries_names(bench, operator):
    seed(bench)
    bench.pending("stage-1")
    store = bench.workflow.store
    store.update_stage(store.find_stage("stage-1"), state=StageState.RUNNING, started_at=0.0)

    stage = operator.get("/wb/environment").json()["stage"]

    assert stage["stage_id"] == "stage-1"
    assert names(stage) == {
        "project_name": PROJECT,
        "round_number": 1,
        "stage_index": 1,
        "phase": "vegetative",
    }


def test_analysis_snapshots_carry_created_at(bench, operator):
    seed(bench)
    bench.pending("stage-1")
    bench.clock.advance(3600)
    snap = snapshots.freeze(
        bench.archive, "experiment-stage-1", bench.clock, START, START + 10, 1, 2, min_coverage=0.0
    )

    body = operator.get(
        "/wb/protocols/protocol-1/analysis", params={"project_id": bench.project_id}
    ).json()

    assert [(row["snapshot_id"], row["created_at"]) for row in body["snapshots"]] == [
        (snap.id, snap.created_at)
    ]
    assert snap.created_at == pytest.approx(START + 3600)


def test_existing_keys_are_unchanged(bench, operator):
    first, _ = seed(bench)
    bench.pending("stage-1")
    store = bench.workflow.store
    rnd = store.round(first)
    row = store.stage("stage-1")
    now = bench.clock.now()

    body = operator.get(f"/wb/rounds/{first}").json()
    stage = operator.get("/wb/stages/stage-1").json()
    detail = operator.get(f"/wb/projects/{bench.project_id}").json()

    old_round = {"round_id": first, **rnd.model_dump(mode="json", exclude={"id"}), "stage_total": 2}
    assert {key: body[key] for key in OLD_ROUND_KEYS} == old_round
    assert [{k: s[k] for k in ("stage_id", "state")} for s in body["stages"]] == [
        {"stage_id": "stage-1", "state": "pending_review"}
    ]
    old_stage = {
        **runtime_json(bench.workflow.stage("stage-1")),
        "round_id": first,
        "state_at": row.state_at,
        "project_id": bench.project_id,
    }
    assert {key: stage[key] for key in old_stage} == old_stage
    old_detail = {key: detail[key] for key in ("project_id", "name", "created_at")}
    assert old_detail == {"project_id": bench.project_id, "name": PROJECT, "created_at": now}
    oldest = {key: detail["rounds"][-1][key] for key in OLD_PROJECT_ROUND_KEYS}
    assert oldest == {
        "round_id": first,
        "state": "stage_review",
        "protocol_id": "protocol-1",
        "protocol_version": 1,
        "awaiting_choice": None,
        "created_at": now,
    }
