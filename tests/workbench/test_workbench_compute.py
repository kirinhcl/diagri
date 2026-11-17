"""The compute routes of the workbench: an operator enters the CSC balance and task budgets."""

import json
import math

import pytest
from fastapi.testclient import TestClient
from workbench_support import LAN_HOST, LAN_PORT, ROLE_TOKENS, SECRET, Bench

from growbridge.api import create_app
from growbridge.archive.models import Budget, ResearchTask
from growbridge.compute.backend import JobTemplate, ParamSpec
from growbridge.compute.service import ComputeService
from growbridge.sim.compute import FakeBackend
from growbridge.workbench.api import create_workbench

BALANCE = "/wb/compute/balance"
OVERVIEW = "/wb/compute"
TEMPLATE = JobTemplate(
    id="segment",
    version=1,
    script="#!/bin/bash\n",
    parameters={"epochs": ParamSpec(kind="int", minimum=1, maximum=100)},
    max_cpu_hours=10.0,
    max_storage_gb=5.0,
)


def budget_path(task_id="task-ev-1"):
    return f"/wb/compute/tasks/{task_id}/budget"


def settle_path(attempt_id):
    return f"/wb/compute/attempts/{attempt_id}/settle"


def post_raw(bench, client, path, body):
    """Like ``bench.post``, but the body may hold NaN or Infinity, which httpx will not encode."""
    headers = {**bench.ui(client), "content-type": "application/json"}
    return client.post(path, content=json.dumps(body), headers=headers)


def detail(response) -> dict:
    return response.json()["detail"]


def make_compute(bench):
    return ComputeService(
        bench.db,
        bench.clock,
        FakeBackend(),
        [TEMPLATE],
        {"researcher": "csc_robot"},
        service_cpu_cap=1000.0,
        service_storage_cap=100.0,
    )


@pytest.fixture
def bench(tmp_path):
    instance = Bench(tmp_path, compute_factory=make_compute)
    instance.operators.add("alice", SECRET)
    instance.tasks.create(
        ResearchTask(
            id="task-ev-1",
            project_id="project-x",
            question="does more light speed up canopy growth?",
            owner_role="researcher",
            budget=Budget(max_calls=10, max_cost=5.0),
            trigger_event_id="ev-1",
            correlation_id="corr-1",
        )
    )
    yield instance
    instance.db.close()


@pytest.fixture
def operator(bench):
    assert bench.login(bench.lan).status_code == 200
    return bench.lan


# --- the balance -------------------------------------------------------------------------------


def test_an_operator_records_the_balance_and_the_server_names_them(bench, operator):
    response = bench.post(
        operator, BALANCE, {"cpu_hours": 500.0, "note": "MyCSC 2026-11-12", "entered_by": "mallory"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "cpu_hours": 500.0,
        "entered_by": "alice",
        "note": "MyCSC 2026-11-12",
        "recorded_at": bench.clock.now(),
    }
    assert bench.compute.overview()["balance"]["entered_by"] == "alice"


def test_recording_a_balance_needs_a_recent_reauthentication(bench, operator):
    bench.clock.advance(301)

    stale = bench.post(operator, BALANCE, {"cpu_hours": 500.0})

    assert stale.status_code == 403 and detail(stale)["code"] == "reauth_required"
    assert bench.compute.overview()["balance"] is None
    assert bench.post(operator, "/wb/reauth", {"secret": SECRET}).status_code == 200
    assert bench.post(operator, BALANCE, {"cpu_hours": 500.0}).status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"cpu_hours": -1.0},
        {"cpu_hours": math.nan},
        {"cpu_hours": math.inf},
        {"cpu_hours": "500"},
        {"cpu_hours": True},
        {"cpu_hours": None},
        {"cpu_hours": 5.0, "note": "x" * 501},
    ],
    ids=["missing", "negative", "nan", "inf", "string", "bool", "null", "long-note"],
)
def test_a_balance_that_is_not_a_finite_non_negative_number_is_rejected(bench, operator, body):
    response = post_raw(bench, operator, BALANCE, body)

    assert response.status_code == 422
    assert bench.compute.overview()["balance"] is None


def test_a_zero_balance_is_a_real_zero_and_is_kept(bench, operator):
    assert bench.post(operator, BALANCE, {"cpu_hours": 0}).status_code == 200
    assert bench.compute.overview()["balance"]["cpu_hours"] == 0.0


# --- task budgets ------------------------------------------------------------------------------


def test_an_operator_sets_the_budget_of_an_existing_task(bench, operator):
    response = bench.post(operator, budget_path(), {"cpu_hours": 40.0, "storage_gb": 20.0})

    assert response.status_code == 200
    assert response.json()["task_id"] == "task-ev-1"
    assert response.json()["cpu_hours_budget"] == 40.0
    (task,) = bench.compute.overview()["tasks"]
    assert (task["cpu_hours_budget"], task["storage_gb_budget"]) == (40.0, 20.0)


def test_a_budget_for_a_task_that_does_not_exist_is_out_of_scope(bench, operator):
    response = bench.post(operator, budget_path("no-such-task"), {"cpu_hours": 1, "storage_gb": 1})

    assert response.status_code == 403 and detail(response)["code"] == "scope"
    assert bench.compute.overview()["tasks"] == []


def test_a_budget_needs_a_recent_reauthentication(bench, operator):
    bench.clock.advance(301)

    stale = bench.post(operator, budget_path(), {"cpu_hours": 40.0, "storage_gb": 20.0})

    assert stale.status_code == 403 and detail(stale)["code"] == "reauth_required"
    assert bench.compute.overview()["tasks"] == []


@pytest.mark.parametrize(
    "body",
    [
        {"cpu_hours": 1.0},
        {"storage_gb": 1.0},
        {"cpu_hours": -1.0, "storage_gb": 1.0},
        {"cpu_hours": 1.0, "storage_gb": math.nan},
        {"cpu_hours": 1.0, "storage_gb": "1"},
    ],
)
def test_an_invalid_budget_is_rejected(bench, operator, body):
    assert post_raw(bench, operator, budget_path(), body).status_code == 422
    assert bench.compute.overview()["tasks"] == []


def test_a_budget_can_be_raised_later(bench, operator):
    bench.post(operator, budget_path(), {"cpu_hours": 40.0, "storage_gb": 20.0})
    bench.post(operator, budget_path(), {"cpu_hours": 80.0, "storage_gb": 20.0})

    (task,) = bench.compute.overview()["tasks"]
    assert task["cpu_hours_budget"] == 80.0


# --- the overview ------------------------------------------------------------------------------


def test_the_overview_shows_the_balance_budgets_and_open_jobs_without_reauthentication(
    bench, operator
):
    bench.post(operator, BALANCE, {"cpu_hours": 500.0})
    bench.post(operator, budget_path(), {"cpu_hours": 40.0, "storage_gb": 20.0})
    attempt = bench.run(
        bench.compute.submit_compute_job("task-ev-1", "researcher", "segment", {"epochs": 3}, {})
    )
    bench.clock.advance(3600)  # the reauthentication is old; reading does not need it

    response = operator.get(OVERVIEW)

    assert response.status_code == 200
    view = response.json()
    assert view["balance"]["cpu_hours"] == 500.0 and view["balance"]["entered_by"] == "alice"
    assert view["tasks"][0]["cpu_hours_reserved"] == 10.0
    assert [job["attempt_id"] for job in view["jobs"]] == [attempt.id]
    assert view["service"]["cpu_hours_cap"] == 1000.0


def test_the_overview_without_any_record_says_there_is_no_balance(bench, operator):
    view = operator.get(OVERVIEW).json()
    assert view["balance"] is None and view["tasks"] == [] and view["jobs"] == []


# --- who may call ------------------------------------------------------------------------------


def send(bench, client, name, headers=None, ui=True):
    if name == "overview":
        return client.get(OVERVIEW, headers=headers)
    base = bench.ui(client) if ui else {}
    path, body = {
        "balance": (BALANCE, {"cpu_hours": 5.0}),
        "budget": (budget_path(), {"cpu_hours": 1.0, "storage_gb": 1.0}),
        "settle": (settle_path("att_x"), {"reason": "stuck"}),
    }[name]
    return client.post(path, json=body, headers={**base, **(headers or {})})


NAMES = ["balance", "budget", "settle", "overview"]


@pytest.mark.parametrize("name", NAMES)
def test_a_model_token_cannot_call_the_compute_routes(bench, name):
    response = send(bench, bench.lan, name, headers=bench.model())

    assert response.status_code == 403 and detail(response)["code"] == "model_role"
    assert bench.compute.overview()["balance"] is None


@pytest.mark.parametrize("name", NAMES)
def test_the_compute_routes_need_a_session(bench, name):
    visitor = TestClient(bench.app, base_url=f"http://{LAN_HOST}:{LAN_PORT}")  # no cookie

    response = send(bench, visitor, name)

    assert response.status_code == 401 and detail(response)["code"] == "session"


@pytest.mark.parametrize("name", ["balance", "budget", "settle"])
def test_writing_needs_the_workbench_origin_and_header(bench, operator, name):
    no_header = send(bench, operator, name, ui=False)
    foreign = send(bench, operator, name, headers={"Origin": "http://evil.test"})

    for response in (no_header, foreign):
        assert response.status_code == 403 and detail(response)["code"] == "entry"
    assert bench.compute.overview()["balance"] is None


@pytest.mark.parametrize("name", NAMES)
def test_a_session_of_the_other_entry_is_refused(bench, operator, name):
    bench.overlay.cookies.set("growbridge_operator", operator.cookies.get("growbridge_operator"))

    response = send(bench, bench.overlay, name)

    assert response.status_code == 403 and detail(response)["code"] == "entry"


@pytest.mark.parametrize("name", NAMES)
def test_the_routes_are_absent_without_a_compute_service(bench, name):
    args = (bench.workflow, bench.control, bench.archive, bench.operators, bench.settings)
    router = create_workbench(*args, ROLE_TOKENS, tasks=bench.tasks)
    bare = TestClient(
        create_app(bench.settings, bridge=object(), workbench=router),
        base_url=f"http://{LAN_HOST}:{LAN_PORT}",
    )
    assert bench.login(bare).status_code == 200

    assert send(bench, bare, name).status_code == 404


# --- settling a stuck attempt ------------------------------------------------------------------


@pytest.fixture
def stuck(bench, operator):
    """An attempt whose submit receipt was lost, long ago: nothing has recovered it."""
    bench.compute.set_task_budget("task-ev-1", 40.0, 20.0)
    bench.compute.record_balance(500.0, "alice")
    bench.compute.backend.lose_receipt = True
    attempt = bench.run(
        bench.compute.submit_compute_job("task-ev-1", "researcher", "segment", {"epochs": 3}, {})
    )
    bench.clock.advance(600)
    bench.post(operator, "/wb/reauth", {"secret": SECRET})
    return attempt


def test_an_operator_settles_a_stuck_attempt_and_the_server_names_them(bench, operator, stuck):
    response = bench.post(
        operator,
        settle_path(stuck.id),
        {"reason": "the job is not on CSC", "settled_by": "mallory"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["attempt_id"] == stuck.id
    assert body["phase"] == "failed" and body["task_state"] == "needs_attention"
    assert (body["used_cpu"], body["used_storage"]) == (10.0, 5.0)  # unknown: the full reservation
    assert body["settled_by"] == "alice" and body["settle_reason"] == "the job is not on CSC"
    assert bench.compute.overview()["tasks"][0]["cpu_hours_reserved"] == 0.0


def test_settling_needs_a_recent_reauthentication(bench, operator, stuck):
    bench.clock.advance(301)

    stale = bench.post(operator, settle_path(stuck.id), {"reason": "stuck"})

    assert stale.status_code == 403 and detail(stale)["code"] == "reauth_required"
    assert bench.compute.overview()["tasks"][0]["cpu_hours_reserved"] == 10.0


@pytest.mark.parametrize("body", [{}, {"reason": ""}, {"reason": "   "}, {"reason": "x" * 501}])
def test_settling_needs_a_reason(bench, operator, stuck, body):
    response = bench.post(operator, settle_path(stuck.id), body)

    assert response.status_code == 422
    assert bench.compute.overview()["tasks"][0]["cpu_hours_reserved"] == 10.0


def test_settling_an_unknown_attempt_is_a_state_error(bench, operator):
    response = bench.post(operator, settle_path("att_nope"), {"reason": "stuck"})

    assert response.status_code == 409 and detail(response)["code"] == "state"


def test_settling_twice_is_refused_the_second_time(bench, operator, stuck):
    assert bench.post(operator, settle_path(stuck.id), {"reason": "first"}).status_code == 200

    again = bench.post(operator, settle_path(stuck.id), {"reason": "second"})

    assert again.status_code == 409 and detail(again)["code"] == "state"


def test_the_overview_lists_the_stuck_attempt_until_it_is_settled(bench, operator, stuck):
    (item,) = operator.get(OVERVIEW).json()["stuck"]
    assert item["attempt_id"] == stuck.id and item["phase"] == "reconcile"

    bench.post(operator, settle_path(stuck.id), {"reason": "gone"})

    assert operator.get(OVERVIEW).json()["stuck"] == []


def test_compute_task_unknown_carries_the_task(bench, operator):
    response = bench.post(operator, budget_path("no-such-task"), {"cpu_hours": 1, "storage_gb": 1})

    body = detail(response)
    assert response.status_code == 403 and body["code"] == "scope"
    assert body["reason"] == "compute_task_unknown" and body["params"] == {
        "task_id": "no-such-task"
    }
