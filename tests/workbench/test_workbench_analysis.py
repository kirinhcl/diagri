"""The workbench entry of the confirmatory analysis: an operator freezes the analysis script of the
latest protocol version before any stage has started, and later starts the one run of a frozen
data snapshot. Every refusal comes before the sandbox starts and leaves no run behind."""

import hashlib

import pytest
from fastapi.testclient import TestClient
from workbench_support import LAN_HOST, LAN_PORT, ROLE_TOKENS, SECRET

from growbridge.api import create_app
from growbridge.archive import snapshot as snapshots
from growbridge.archive.models import ManualMeasurement
from growbridge.ports import Actor
from growbridge.research.sandbox import RefusingSandbox, SandboxResult
from growbridge.sim.clock import START
from growbridge.sim.fixtures import make_protocol
from growbridge.workbench.api import create_workbench

SCRIPT = "print('analysis')\n"
PROTOCOL = "protocol-1"
FREEZE = f"/wb/protocols/{PROTOCOL}/analysis"
RUNS = "/wb/analysis/runs"
STDOUT_LIMIT = 4000


def detail(response) -> dict:
    return response.json()["detail"]


def freeze(bench, client, script: str = SCRIPT, **body):
    fields = {"project_id": bench.project_id, "script": script, **body}
    return bench.post(client, FREEZE, fields)


def status_of(bench, client, **params):
    query = {"project_id": bench.project_id, **params}
    return client.get(FREEZE, params=query)


def run(bench, client, snapshot_id: str, **body):
    fields = {
        "project_id": bench.project_id,
        "protocol_id": PROTOCOL,
        "snapshot_id": snapshot_id,
        **body,
    }
    return bench.post(client, RUNS, fields)


def measurement(metric="yield_g", batch="b1", number=1, experiment="experiment-stage-1"):
    return ManualMeasurement(
        id=f"m{number}",
        experiment_id=experiment,
        batch=batch,
        plant_id="p0",
        layout_version="v1",
        measured_at=START + 1,
        position="tent-1",
        method="ruler",
        metric=metric,
        value=1.0,
        unit="g",
        operator="alice",
    )


def snapshot_of(bench, rows=(), experiment="experiment-stage-1", complete=True, keep=None):
    for row in rows:
        bench.archive.add_measurement(row)
    return snapshots.freeze(
        bench.archive,
        experiment,
        bench.clock,
        START,
        START + 10,
        1,
        2,
        min_coverage=0.0 if complete else 1.0,
        measurement_filter=keep,
    )


@pytest.fixture
def seeded(bench, operator):
    bench.pending()  # project, protocol-1 and a round with a stage waiting for review
    return bench


def latest(bench):
    return bench.workflow.store.latest_protocol(PROTOCOL, bench.project_id)


def runner_state(bench, snapshot_id: str) -> str:
    return bench.runner.status(snapshot_id, latest(bench))


def nothing_ran(bench, snapshot_id: str) -> bool:
    return bench.sandbox.runs == [] and runner_state(bench, snapshot_id) == "none"


def start_the_stage(bench) -> None:
    actor = Actor(kind="operator", id="alice", reauth_at=bench.clock.now())
    bench.workflow.approve("stage-1", actor)
    bench.run(bench.workflow.start_stage("stage-1", actor))


# --- freezing ----------------------------------------------------------------------------------


def test_an_operator_freezes_the_script_of_the_latest_protocol_version(seeded, operator):
    response = freeze(seeded, operator)

    assert response.status_code == 200
    body = response.json()
    assert body["protocol_id"] == PROTOCOL and body["version"] == 1
    assert body["script_sha256"] == hashlib.sha256(SCRIPT.encode()).hexdigest()
    assert body["frozen_at"] == seeded.clock.now()
    assert seeded.runner.frozen_script(latest(seeded)) == (body["script_sha256"], SCRIPT.encode())
    assert seeded.runner.frozen_info(latest(seeded)).frozen_by == "alice"


def test_who_froze_comes_from_the_session_never_from_the_body(seeded, operator):
    freeze(seeded, operator, frozen_by="mallory", operator="mallory", actor={"id": "mallory"})

    assert seeded.runner.frozen_info(latest(seeded)).frozen_by == "alice"


def test_freezing_needs_a_recent_reauthentication(seeded, operator):
    seeded.clock.advance(301)

    stale = freeze(seeded, operator)

    assert stale.status_code == 403 and detail(stale)["code"] == "reauth_required"
    assert seeded.runner.frozen_info(latest(seeded)) is None
    assert seeded.post(operator, "/wb/reauth", {"secret": SECRET}).status_code == 200
    assert freeze(seeded, operator).status_code == 200


def test_freezing_the_same_script_again_is_idempotent_and_another_is_refused(seeded, operator):
    first = freeze(seeded, operator).json()

    again = freeze(seeded, operator).json()
    other = freeze(seeded, operator, script="print('other')\n")

    assert again == first
    assert other.status_code == 403 and detail(other)["code"] == "script_hash"


def test_freezing_after_a_stage_started_is_refused_and_says_why(seeded, operator):
    start_the_stage(seeded)

    late = freeze(seeded, operator)

    assert late.status_code == 409 and detail(late)["code"] == "state"
    assert "6.5" in detail(late)["message"]
    assert seeded.runner.frozen_info(latest(seeded)) is None


def test_a_frozen_script_cannot_be_frozen_again_once_a_stage_started(seeded, operator):
    freeze(seeded, operator)
    start_the_stage(seeded)

    late = freeze(seeded, operator)

    assert late.status_code == 409 and detail(late)["code"] == "state"


def test_freezing_for_an_unknown_protocol_or_another_project_is_a_state_conflict(seeded, operator):
    body = {"project_id": seeded.project_id, "script": SCRIPT}
    unknown = seeded.post(operator, "/wb/protocols/nope/analysis", body)
    elsewhere = seeded.post(operator, FREEZE, {**body, "project_id": "other-project"})

    for response in (unknown, elsewhere):
        assert response.status_code == 409 and detail(response)["code"] == "state"


@pytest.mark.parametrize("script", ["", "x" * 20_001], ids=["empty", "too-long"])
def test_a_script_that_is_empty_or_too_long_is_rejected(seeded, operator, script):
    response = freeze(seeded, operator, script=script)

    assert response.status_code == 422
    assert seeded.runner.frozen_info(latest(seeded)) is None


def test_a_script_with_a_lone_surrogate_is_a_422_not_a_server_error(seeded, operator):
    raw = '{"project_id": "' + seeded.project_id + '", "script": "print(1) \\ud800"}'
    headers = {**seeded.ui(operator), "content-type": "application/json"}

    response = operator.post(FREEZE, content=raw, headers=headers)

    assert response.status_code == 422
    assert seeded.runner.frozen_info(latest(seeded)) is None


def test_a_request_id_in_the_body_is_not_part_of_the_freeze_route(seeded, operator):
    """Freezing the same text again is harmless, so the route has no request id to check."""
    assert freeze(seeded, operator, request_id="short").status_code == 200


def test_a_script_that_cannot_compile_is_refused_and_nothing_is_frozen(seeded, operator):
    response = freeze(seeded, operator, script="def broken(:\n")

    assert response.status_code == 403 and detail(response)["code"] == "param"
    assert "syntax" in detail(response)["message"]
    assert seeded.runner.frozen_info(latest(seeded)) is None


def test_the_answer_says_plainly_that_a_frozen_script_cannot_be_corrected(seeded, operator):
    body = freeze(seeded, operator).json()

    assert "cannot be corrected" in body["note"]
    assert "new protocol version" in body["note"]


# --- reading the state -------------------------------------------------------------------------


def test_the_state_shows_the_freeze_and_each_snapshots_run_without_a_reauthentication(
    seeded, operator
):
    snap = snapshot_of(seeded)
    before = status_of(seeded, operator).json()
    freeze(seeded, operator)
    run(seeded, operator, snap.id)
    seeded.clock.advance(3600)  # the reauthentication is old; reading does not need it

    after = status_of(seeded, operator)

    assert before["frozen"] is None and before["started"] is False
    assert [item["run_status"] for item in before["snapshots"]] == ["none"]
    assert after.status_code == 200
    body = after.json()
    assert body["frozen"]["script_sha256"] == hashlib.sha256(SCRIPT.encode()).hexdigest()
    assert body["frozen"]["frozen_by"] == "alice"
    assert body["frozen"]["script"] == SCRIPT
    assert body["snapshots"] == [
        {
            "snapshot_id": snap.id,
            "experiment_id": "experiment-stage-1",
            "complete": True,
            "run_status": "succeeded",
        }
    ]


def test_the_state_says_when_a_stage_has_started(seeded, operator):
    start_the_stage(seeded)

    assert status_of(seeded, operator).json()["started"] is True


def test_the_state_of_an_unknown_project_is_a_state_conflict(seeded, operator):
    response = status_of(seeded, operator, project_id="other-project")

    assert response.status_code == 409 and detail(response)["code"] == "state"


# --- running -----------------------------------------------------------------------------------


def test_an_operator_runs_the_frozen_script_on_a_snapshot_once(seeded, operator):
    freeze(seeded, operator)
    snap = snapshot_of(seeded)

    response = run(seeded, operator, snap.id)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "succeeded" and body["exit_code"] == 0 and body["timed_out"] is False
    assert body["stdout"] == "analysis finished" and body["run_id"]
    assert seeded.sandbox.runs[0][0] == SCRIPT.encode()
    assert runner_state(seeded, snap.id) == "succeeded"


def test_output_is_cut_to_the_limit(seeded, operator):
    seeded.sandbox.result = SandboxResult(0, "o" * 9000, "e" * 9000, False)
    freeze(seeded, operator)

    body = run(seeded, operator, snapshot_of(seeded).id).json()

    assert len(body["stdout"]) <= STDOUT_LIMIT + 20 and len(body["stderr"]) <= STDOUT_LIMIT + 20
    assert body["stdout"].startswith("o" * STDOUT_LIMIT)


def test_a_failed_run_is_reported_and_uses_up_the_attempt(seeded, operator):
    seeded.sandbox.result = SandboxResult(1, "", "boom", False)
    freeze(seeded, operator)
    snap = snapshot_of(seeded)

    first = run(seeded, operator, snap.id)
    again = run(seeded, operator, snap.id)

    assert first.status_code == 200 and first.json()["status"] == "failed"
    assert again.status_code == 403 and detail(again)["code"] == "already_run"
    assert len(seeded.sandbox.runs) == 1


def test_a_snapshot_runs_only_once(seeded, operator):
    freeze(seeded, operator)
    snap = snapshot_of(seeded)
    run(seeded, operator, snap.id)

    again = run(seeded, operator, snap.id)

    assert again.status_code == 403 and detail(again)["code"] == "already_run"
    assert len(seeded.sandbox.runs) == 1


def test_running_needs_a_recent_reauthentication(seeded, operator):
    freeze(seeded, operator)
    snap = snapshot_of(seeded)
    seeded.clock.advance(301)

    stale = run(seeded, operator, snap.id)

    assert stale.status_code == 403 and detail(stale)["code"] == "reauth_required"
    assert nothing_ran(seeded, snap.id)


def test_who_started_the_run_comes_from_the_session(seeded, operator):
    freeze(seeded, operator)
    snap = snapshot_of(seeded)

    run(seeded, operator, snap.id, started_by="mallory", operator="mallory")

    row = seeded.db.one("SELECT started_by FROM research_runs WHERE snapshot_id = ?", (snap.id,))
    assert row["started_by"] == "alice"


def test_a_protocol_without_a_frozen_script_is_refused(seeded, operator):
    snap = snapshot_of(seeded)

    response = run(seeded, operator, snap.id)

    assert response.status_code == 409 and detail(response)["code"] == "state"
    assert nothing_ran(seeded, snap.id)


def test_an_unknown_protocol_or_another_project_is_refused(seeded, operator):
    freeze(seeded, operator)
    snap = snapshot_of(seeded)

    unknown = run(seeded, operator, snap.id, protocol_id="nope")
    elsewhere = run(seeded, operator, snap.id, project_id="other-project")

    for response in (unknown, elsewhere):
        assert response.status_code == 409 and detail(response)["code"] == "state"
    assert nothing_ran(seeded, snap.id)


def other_project_snapshot(bench):
    """A snapshot of an experiment that belongs to a different project and protocol."""
    designer = bench.designer
    project = bench.workflow.create_project("other series", designer)
    protocol = make_protocol(project_id=project, id="protocol-2", stages=("vegetative",))
    bench.workflow.save_protocol(protocol, designer)
    round_id = bench.workflow.create_round(project, protocol.id, designer)
    change = {"project_id": project, "protocol_id": "protocol-2", "experiment_id": "experiment-p2"}
    bench.workflow.submit_run_sheet(
        round_id, bench.sheet("stage-2").model_copy(update=change), designer
    )
    return snapshot_of(bench, experiment="experiment-p2")


@pytest.mark.parametrize("which", ["unknown", "other-protocol", "no-stage"])
def test_a_snapshot_outside_the_protocols_rounds_is_refused(seeded, operator, which):
    freeze(seeded, operator)
    if which == "unknown":
        snapshot_id = "snap_nope"
    elif which == "other-protocol":
        snapshot_id = other_project_snapshot(seeded).id
    else:
        snapshot_id = snapshot_of(seeded, experiment="experiment-without-stage").id

    response = run(seeded, operator, snapshot_id)

    assert response.status_code == 403 and detail(response)["code"] == "scope"
    assert seeded.sandbox.runs == []


def test_an_incomplete_snapshot_is_refused(seeded, operator):
    freeze(seeded, operator)
    snap = snapshot_of(seeded, complete=False)

    response = run(seeded, operator, snap.id)

    assert response.status_code == 403 and detail(response)["code"] == "snapshot_incomplete"
    assert nothing_ran(seeded, snap.id)


def test_a_snapshot_whose_files_changed_is_refused(seeded, operator):
    freeze(seeded, operator)
    snap = snapshot_of(seeded, rows=[measurement()])
    path = seeded.archive.root / "snapshots" / snap.id / "measurements.jsonl"
    path.write_text(path.read_text() + "\n")

    response = run(seeded, operator, snap.id)

    assert response.status_code == 403 and detail(response)["code"] == "snapshot_incomplete"
    assert nothing_ran(seeded, snap.id)


def test_a_snapshot_invalidated_by_a_correction_is_refused(seeded, operator):
    freeze(seeded, operator)
    snap = snapshot_of(seeded, rows=[measurement()])
    assert seeded.archive.mark_dependents_invalid("m1") == (snap.id,)

    response = run(seeded, operator, snap.id)

    assert response.status_code == 409 and detail(response)["code"] == "state"
    assert nothing_ran(seeded, snap.id)


def test_a_snapshot_holding_outcomes_of_a_held_out_batch_is_refused(seeded, operator):
    seeded.holdout.register(seeded.project_id, "hold-1", ("b3",), ("yield_g",), 2)
    freeze(seeded, operator)
    leaky = snapshot_of(seeded, rows=[measurement("yield_g", "b3")])

    response = run(seeded, operator, leaky.id)

    assert response.status_code == 403 and detail(response)["code"] == "scope"
    assert "1.0" not in detail(response)["message"]
    assert nothing_ran(seeded, leaky.id)


def test_a_snapshot_frozen_with_the_development_filter_is_analysed(seeded, operator):
    seeded.holdout.register(seeded.project_id, "hold-1", ("b3",), ("yield_g",), 2)
    freeze(seeded, operator)
    keep = seeded.holdout.development_filter(seeded.project_id)
    clean = snapshot_of(seeded, rows=[measurement("yield_g", "b3")], keep=keep)

    response = run(seeded, operator, clean.id)

    assert response.status_code == 200 and response.json()["status"] == "succeeded"


def test_a_platform_without_a_sandbox_refuses_and_leaves_the_attempt_unused(seeded, operator):
    seeded.runner.sandbox = RefusingSandbox()
    freeze(seeded, operator)
    snap = snapshot_of(seeded)

    response = run(seeded, operator, snap.id)

    assert response.status_code == 403 and detail(response)["code"] == "sandbox_unavailable"
    assert runner_state(seeded, snap.id) == "none"


# --- who may call ------------------------------------------------------------------------------

ROUTES = ("freeze", "state", "run")


def send(bench, client, name, headers=None, ui=True):
    if name == "state":
        return client.get(FREEZE, params={"project_id": bench.project_id}, headers=headers)
    if name == "freeze":
        path, body = FREEZE, {"project_id": bench.project_id, "script": SCRIPT}
    else:
        path = RUNS
        body = {"project_id": bench.project_id, "protocol_id": PROTOCOL, "snapshot_id": "x"}
    base = bench.ui(client) if ui else {}
    return client.post(path, json=body, headers={**base, **(headers or {})})


@pytest.mark.parametrize("name", ROUTES)
def test_a_model_token_cannot_call_any_analysis_route(seeded, name):
    response = send(seeded, seeded.lan, name, headers=seeded.model())

    assert response.status_code == 403 and detail(response)["code"] == "model_role"
    assert seeded.sandbox.runs == []


@pytest.mark.parametrize("name", ROUTES)
def test_analysis_routes_need_a_session(seeded, name):
    visitor = TestClient(seeded.app, base_url=f"http://{LAN_HOST}:{LAN_PORT}")  # no cookie

    response = send(seeded, visitor, name)

    assert response.status_code == 401 and detail(response)["code"] == "session"


@pytest.mark.parametrize("name", ["freeze", "run"])
def test_analysis_writes_need_the_workbench_origin_and_header(seeded, operator, name):
    no_header = send(seeded, operator, name, ui=False)
    foreign = send(seeded, operator, name, headers={"Origin": "http://evil.test"})

    for response in (no_header, foreign):
        assert response.status_code == 403 and detail(response)["code"] == "entry"


@pytest.mark.parametrize("name", ROUTES)
def test_a_session_of_the_other_entry_is_refused(seeded, operator, name):
    seeded.overlay.cookies.set("growbridge_operator", operator.cookies.get("growbridge_operator"))

    response = send(seeded, seeded.overlay, name)

    assert response.status_code == 403 and detail(response)["code"] == "entry"


def test_the_routes_are_absent_without_a_runner(seeded):
    args = (seeded.workflow, seeded.control, seeded.archive, seeded.operators, seeded.settings)
    app = create_app(
        seeded.settings, bridge=object(), workbench=create_workbench(*args, ROLE_TOKENS)
    )
    bare = TestClient(app, base_url=f"http://{LAN_HOST}:{LAN_PORT}")
    assert seeded.login(bare).status_code == 200

    assert freeze(seeded, bare).status_code == 404
    assert status_of(seeded, bare).status_code == 404
    assert run(seeded, bare, "snap_x").status_code == 404
