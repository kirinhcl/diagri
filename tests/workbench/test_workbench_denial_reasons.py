"""The refusals of the workbench routes for rounds, reads, evidence, holdouts and compute carry
a registered reason and the params the console builds its text from; the coarse code, the HTTP
status and the English message stay as they were."""

import json

from fastapi.testclient import TestClient
from test_workbench_rounds import (
    GOAL,
    _published,
    designed,
    detail,
    funded,
    protocol_json,
    raw_post,
    set_budget,
)
from workbench_support import LAN_HOST, LAN_PORT, ROLE_TOKENS

from growbridge.api import create_app
from growbridge.workbench.api import create_workbench
from growbridge.workbench.rounds import MAX_ID_CHARS, MAX_PROTOCOL_VERSION


def refused(response, status: int, code: str, reason: str, params: dict) -> None:
    assert response.status_code == status
    body = detail(response)
    assert (body["code"], body["reason"], body["params"]) == (code, reason, params)


# --- rounds -----------------------------------------------------------------------------------


def test_report_not_published_carries_the_round(bench, operator):
    round_id = bench.seed_round()
    response = operator.get(f"/wb/rounds/{round_id}/report")
    refused(response, 409, "state", "report_not_published", {"round_id": round_id})


def test_report_file_missing_carries_the_round(bench, operator):
    round_id, path = _published(bench, {"conclusion": "uncertain"})
    path.unlink()
    response = operator.get(f"/wb/rounds/{round_id}/report")
    refused(response, 409, "state", "report_file_missing", {"round_id": round_id})


def test_artifact_digest_mismatch_carries_the_round_and_the_artifact(bench, operator):
    round_id, path = _published(bench, {"conclusion": "uncertain"})
    path.write_text(json.dumps({"conclusion": "supported"}), encoding="utf-8")
    response = operator.get(f"/wb/rounds/{round_id}/report")
    params = {"round_id": round_id, "artifact_id": "artifact-1"}
    refused(response, 409, "state", "artifact_digest_mismatch", params)


def test_archive_not_mounted_carries_no_params(bench):
    args = (bench.workflow, bench.control, None, bench.operators, bench.settings, ROLE_TOKENS)
    router = create_workbench(*args)
    app = create_app(bench.settings, bridge=object(), workbench=router)
    client = TestClient(app, base_url=f"http://{LAN_HOST}:{LAN_PORT}")
    assert bench.login(client).status_code == 200
    round_id = bench.seed_round()
    refused(client.get(f"/wb/rounds/{round_id}/report"), 409, "state", "archive_not_mounted", {})


def test_record_not_found_carries_the_project_of_a_budget_for_an_unknown_project(bench, operator):
    response = set_budget(bench, operator, "project-none")
    params = {"record_kind": "project", "record_id": "project-none"}
    refused(response, 409, "state", "record_not_found", params)


def test_round_not_in_project_carries_the_round_and_the_project(bench, operator):
    project_id, _round = funded(bench, operator)
    _other, foreign_round = designed(bench, operator, protocol_id="protocol-2")
    body = {"project_id": project_id, "round_id": foreign_round, "goal": GOAL}
    response = bench.post(operator, "/wb/goals", body)
    params = {"round_id": foreign_round, "project_id": project_id}
    refused(response, 409, "state", "round_not_in_project", params)


def test_budget_calls_exhausted_carries_the_project(bench, operator):
    project_id, _round = designed(bench, operator)
    assert set_budget(bench, operator, project_id, calls=0).status_code == 200
    response = bench.post(operator, "/wb/goals", {"project_id": project_id, "goal": GOAL})
    refused(response, 403, "budget", "budget_calls_exhausted", {"project_id": project_id})


def test_budget_cost_exhausted_carries_the_project(bench, operator):
    project_id, _round = designed(bench, operator)
    assert set_budget(bench, operator, project_id, cost=0.0).status_code == 200
    response = bench.post(operator, "/wb/goals", {"project_id": project_id, "goal": GOAL})
    refused(response, 403, "budget", "budget_cost_exhausted", {"project_id": project_id})


def test_request_id_reused_for_other_goal_carries_the_task_and_request(bench, operator):
    project_id, _round = funded(bench, operator)
    body = {"project_id": project_id, "goal": GOAL, "request_id": "goal-0001"}
    first = bench.post(operator, "/wb/goals", body).json()
    response = bench.post(operator, "/wb/goals", {**body, "goal": "something else"})
    params = {"task_id": first["task_id"], "request_id": "goal-0001"}
    refused(response, 409, "state", "request_id_reused_for_other_goal", params)


def spoiled(bench, client, change) -> dict:
    project_id, _round = funded(bench, client)
    protocol = protocol_json(project_id)
    change(protocol)
    response = raw_post(bench, client, "/wb/protocols", {"protocol": protocol})
    assert response.status_code == 422
    return detail(response)


def test_id_length_carries_the_longest_id_allowed(bench, operator):
    body = spoiled(bench, operator, lambda p: p.update(id="p" * (MAX_ID_CHARS + 1)))
    assert body["reason"] == "id_length" and body["params"] == {"max_length": MAX_ID_CHARS}


def test_protocol_version_range_carries_the_highest_version_allowed(bench, operator):
    body = spoiled(bench, operator, lambda p: p.update(version=MAX_PROTOCOL_VERSION + 1))
    assert body["reason"] == "protocol_version_range"
    assert body["params"] == {"max_version": MAX_PROTOCOL_VERSION}


def test_numbers_not_finite_carries_the_paths_of_the_spoiled_numbers(bench, operator):
    body = spoiled(bench, operator, lambda p: p["analysis"].update(target_effect=float("nan")))
    assert body["reason"] == "numbers_not_finite"
    assert body["params"] == {"paths": ["analysis.target_effect"]}


# --- reads, evidence, holdouts, compute -------------------------------------------------------


def test_record_not_found_carries_the_project_of_a_project_read(operator):
    response = operator.get("/wb/projects/nope")
    params = {"record_kind": "project", "record_id": "nope"}
    refused(response, 409, "state", "record_not_found", params)


def test_record_not_found_carries_the_stage_of_a_run_sheet_read(bench, operator):
    response = operator.get("/wb/stages/stage-none/run-sheet")
    assert response.status_code == 409
    body = detail(response)
    assert body["reason"] == "record_not_found" and body["params"]["record_kind"] == "stage"


def test_record_not_found_carries_the_evidence_card_of_a_verification(bench, operator):
    response = bench.post(operator, "/wb/evidence/card-none/verify", {})
    params = {"record_kind": "evidence_card", "record_id": "card-none"}
    refused(response, 409, "state", "record_not_found", params)


def test_not_this_project_carries_the_unknown_project_of_a_holdout(bench, operator):
    bench.pending()
    body = {
        "project_id": "no-such-project",
        "batch_ids": ["b3"],
        "development_batch_ids": ["dev-1", "dev-2"],
        "outcome_fields": ["yield_g", "canopy_score"],
    }
    response = bench.post(operator, "/wb/holdouts", body)
    refused(response, 403, "scope", "not_this_project", {"project_id": "no-such-project"})
