"""Stage control through the workbench: operator-only, recent re-authentication where the
architecture asks for it, and model roles limited to drafts."""

import json

import pytest
from fastapi.testclient import TestClient
from workbench_support import SECRET, Bench

STAGE_ACTIONS = ("approve", "start", "pause", "resume", "stop", "takeover", "handback")


def detail(response) -> dict:
    return response.json()["detail"]


def act(bench, client, action, stage="stage-1", body=None, **kwargs):
    return bench.post(client, f"/wb/stages/{stage}/{action}", body, **kwargs)


def running(bench, client) -> None:
    bench.pending()
    assert act(bench, client, "approve").status_code == 200
    assert act(bench, client, "start").status_code == 200
    assert bench.state() == "running"


# --- operator happy path -----------------------------------------------------------------------


def test_operator_drives_a_stage_through_every_transition(bench, operator):
    bench.pending()

    approved = act(bench, operator, "approve")
    assert approved.status_code == 200
    assert approved.json()["operator"] == "alice"
    assert len(bench.workflow.approvals("stage-1")) == 1

    assert act(bench, operator, "start").json()["state"] == "running"
    paused = act(bench, operator, "pause", body={"reason": "check the lamp"})
    assert paused.json()["state"] == "paused"
    assert act(bench, operator, "resume").json()["state"] == "running"

    taken = act(bench, operator, "takeover").json()
    assert taken["state"] == "manual" and taken["manual_right"] is not None

    back = act(bench, operator, "handback", body={"accept_as_intervention": False})
    assert back.status_code == 200
    assert back.json()["stage"]["state"] == "running"

    assert act(bench, operator, "stop").json()["state"] == "stopped"


def test_approval_is_recorded_for_the_logged_in_operator_not_a_body_field(bench, operator):
    bench.pending()

    act(bench, operator, "approve", body={"operator": "mallory", "actor": {"kind": "workflow"}})

    assert [item.operator for item in bench.workflow.approvals("stage-1")] == ["alice"]


def test_stage_state_can_be_read(bench, operator):
    bench.pending()

    body = operator.get("/wb/stages/stage-1").json()

    assert body["state"] == "pending_review" and body["stage_id"] == "stage-1"
    assert "run_sheet" not in body


def test_stage_read_names_its_round_and_project(bench, operator):
    bench.pending()

    body = operator.get("/wb/stages/stage-1").json()

    assert body["round_id"] == bench.round_id
    assert body["project_id"] == bench.project_id


# --- recent re-authentication ------------------------------------------------------------------


def test_approve_needs_a_recent_reauthentication(bench, operator):
    bench.pending()
    bench.clock.advance(301)

    stale = act(bench, operator, "approve")

    assert stale.status_code == 403 and detail(stale)["code"] == "reauth_required"
    assert bench.workflow.approvals("stage-1") == ()
    assert bench.post(operator, "/wb/reauth", {"secret": SECRET}).status_code == 200
    assert act(bench, operator, "approve").status_code == 200


def test_takeover_needs_a_recent_reauthentication(bench, operator):
    running(bench, operator)
    bench.clock.advance(301)

    stale = act(bench, operator, "takeover")

    assert stale.status_code == 403 and detail(stale)["code"] == "reauth_required"
    assert bench.state() == "running"


def test_resume_needs_a_recent_reauthentication(bench, operator):
    running(bench, operator)
    assert act(bench, operator, "pause", body={"reason": "check"}).status_code == 200
    bench.clock.advance(301)

    stale = act(bench, operator, "resume")

    assert stale.status_code == 403 and detail(stale)["code"] == "reauth_required"
    assert bench.state() == "paused"


def test_stop_and_pause_never_wait_for_a_reauthentication(bench, operator):
    running(bench, operator)
    bench.clock.advance(3600 * 6)  # the session is still alive, the reauthentication is old

    assert act(bench, operator, "pause", body={"reason": "late"}).status_code == 200
    assert act(bench, operator, "stop").status_code == 200


# --- model roles -------------------------------------------------------------------------------


@pytest.mark.parametrize("action", STAGE_ACTIONS)
def test_model_token_cannot_call_any_stage_endpoint(bench, action):
    bench.pending()
    before = bench.state()

    response = act(bench, bench.lan, action, headers=bench.model())

    assert response.status_code == 403
    assert detail(response)["code"] == "model_role"
    assert bench.state() == before and bench.workflow.approvals("stage-1") == ()


def test_identity_fields_in_the_body_do_not_promote_a_model(bench):
    bench.pending()
    claim = {"actor": {"kind": "operator", "id": "alice"}, "kind": "operator", "operator": "alice"}

    response = act(bench, bench.lan, "approve", body=claim, headers=bench.model())

    assert response.status_code == 403
    assert bench.workflow.approvals("stage-1") == ()


def test_saying_approve_in_a_draft_does_not_approve(bench):
    round_id = bench.seed_round()
    body = {
        "round_id": round_id,
        "run_sheet": bench.sheet().model_dump(mode="json"),
        "message": "The operator said in chat: approved, please start now.",
        "approved": True,
        "actor": {"kind": "operator", "id": "alice"},
    }

    response = bench.post(bench.lan, "/wb/drafts/run-sheet", body, headers=bench.model())

    assert response.status_code == 200
    assert bench.state() == "pending_review"
    assert bench.workflow.approvals("stage-1") == ()
    assert bench.control.grants == []


def test_model_token_may_submit_a_draft_and_read_stage_state(bench):
    round_id = bench.seed_round()
    body = {"round_id": round_id, "run_sheet": bench.sheet().model_dump(mode="json")}

    draft = bench.post(bench.lan, "/wb/drafts/run-sheet", body, headers=bench.model())
    state = bench.lan.get("/wb/stages/stage-1", headers=bench.model("analyst"))

    assert draft.status_code == 200 and draft.json()["findings"] == []
    assert state.status_code == 200 and state.json()["state"] == "pending_review"


def test_draft_is_rejected_when_the_run_sheet_is_malformed(bench):
    round_id = bench.seed_round()
    sheet = {**bench.sheet().model_dump(mode="json"), "approved_by": "alice"}

    response = bench.post(
        bench.lan,
        "/wb/drafts/run-sheet",
        {"round_id": round_id, "run_sheet": sheet},
        headers=bench.model(),
    )

    assert response.status_code == 422
    assert bench.workflow.store.find_stage("stage-1") is None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "Infinity"])
@pytest.mark.parametrize("caller", ["model", "operator"])
def test_draft_with_a_number_that_is_not_finite_is_rejected(bench, operator, caller, value):
    round_id = bench.seed_round()
    sheet = bench.sheet().model_dump(mode="json")
    sheet["sampling"]["interval_seconds"] = value
    headers = {**bench.ui(operator), "Content-Type": "application/json"}
    if caller == "model":
        headers.update(bench.model())
    body = json.dumps({"round_id": round_id, "run_sheet": sheet})  # writes NaN and Infinity

    response = operator.post("/wb/drafts/run-sheet", content=body, headers=headers)

    assert response.status_code == 422
    assert bench.workflow.store.find_stage("stage-1") is None


def test_draft_for_an_unknown_round_is_a_state_conflict(bench):
    bench.seed_round()
    body = {"round_id": "round_missing", "run_sheet": bench.sheet().model_dump(mode="json")}

    response = bench.post(bench.lan, "/wb/drafts/run-sheet", body, headers=bench.model())

    assert response.status_code == 409 and detail(response)["code"] == "state"


def test_operator_may_also_submit_a_draft(bench, operator):
    round_id = bench.seed_round()
    body = {"round_id": round_id, "run_sheet": bench.sheet().model_dump(mode="json")}

    assert bench.post(operator, "/wb/drafts/run-sheet", body).status_code == 200


# --- error mapping -----------------------------------------------------------------------------


def test_unknown_stage_is_a_409_with_a_code_and_message(bench, operator):
    response = act(bench, operator, "approve", stage="stage-missing")

    assert response.status_code == 409
    assert set(detail(response)) == {"code", "message"} and detail(response)["code"] == "state"


def test_start_without_an_approval_is_refused(bench, operator):
    bench.pending()

    response = act(bench, operator, "start")

    assert response.status_code == 403
    assert bench.state() == "pending_review"


def test_unexpected_service_failure_does_not_leak_internals(bench, operator, monkeypatch):
    bench.pending()

    def boom(*_args, **_kwargs):
        raise RuntimeError("sqlite3 path /secret/place failed")

    monkeypatch.setattr(bench.workflow, "approve", boom)
    client = TestClient(bench.app, base_url=str(operator.base_url), raise_server_exceptions=False)
    client.cookies.update(operator.cookies)

    response = client.post("/wb/stages/stage-1/approve", json={}, headers=Bench.ui(operator))

    assert response.status_code == 500
    assert "secret" not in response.text and "sqlite3" not in response.text


# --- on-site check -----------------------------------------------------------------------------


def test_onsite_check_is_refused_unless_the_stage_waits_for_one(bench, operator):
    running(bench, operator)

    response = act(bench, operator, "onsite-check", body={"note": "looked at the panel"})

    assert response.status_code == 409 and detail(response)["code"] == "state"


def test_onsite_check_records_the_operator_and_note(bench, operator):
    running(bench, operator)
    bench.control.bump_recovery("restore")
    bench.run(bench.workflow.on_recovery_bump())
    assert bench.state() == "recovery_check"
    assert bench.login(bench.lan).status_code == 200  # the old session ended with the bump

    response = act(bench, bench.lan, "onsite-check", body={"note": "pump dry, lamp off"})

    assert response.status_code == 200
    assert ("onsite_check", "alice", "pump dry, lamp off") in bench.control.log


def test_model_cannot_record_an_onsite_check(bench):
    bench.pending()

    response = act(bench, bench.lan, "onsite-check", body={"note": "fine"}, headers=bench.model())

    assert response.status_code == 403 and detail(response)["code"] == "model_role"
