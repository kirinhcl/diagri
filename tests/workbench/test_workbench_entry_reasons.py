"""The refusals of the workbench entry layer (sign-in, entry, session), manual writes, manual
measurements, receipts and manual tasks carry a registered reason and the params the console
builds its text from; the coarse code, the HTTP status and the English message stay as they were."""

import pytest
from fastapi.testclient import TestClient
from test_workbench_actions import manual_body, manual_stage, measurement
from test_workbench_manual_tasks import (
    PATH,
    PHOTO_DUE,
    STARTED,
    WATER_DUE,
    done,
    irrigate,
    run_id,
    running,
)
from workbench_support import LAN_HOST, LAN_PORT, MAIN_PORT, SECRET

from growbridge.archive.models import ActionRecord, ActionState, Channel, RightKind
from growbridge.planning.manual_tasks import ON_TIME_SECONDS
from growbridge.workbench.auth import SESSION_SECONDS
from growbridge.workbench.manual_tasks import MAX_ATTEMPTS
from growbridge.workflow.states import StageState

COOKIE = "growbridge_operator"


def refused(response, status: int, code: str, reason: str, params: dict) -> dict:
    assert response.status_code == status
    body = response.json()["detail"]
    assert (body["code"], body["reason"], body["params"]) == (code, reason, params)
    return body


def client_on(bench, host: str, port: int, scheme: str = "http") -> TestClient:
    return TestClient(bench.app, base_url=f"{scheme}://{host}:{port}")


# --- sign-in and session -----------------------------------------------------------------------


def test_not_signed_in_carries_no_params(bench):
    refused(bench.lan.get("/wb/me"), 401, "session", "not_signed_in", {})


def test_not_signed_in_also_covers_a_bearer_that_is_no_role_token(bench):
    response = bench.lan.get("/wb/me", headers={"Authorization": "Bearer nope"})
    refused(response, 401, "session", "not_signed_in", {})


def test_session_expired_carries_no_params_when_the_session_ran_out(bench, operator):
    bench.clock.advance(SESSION_SECONDS + 1)
    refused(operator.get("/wb/me"), 401, "session", "session_expired", {})


def test_session_expired_carries_no_params_after_logout(bench, operator):
    token = operator.cookies.get(COOKIE)
    assert bench.post(operator, "/wb/logout").status_code == 200
    stale = client_on(bench, LAN_HOST, LAN_PORT)
    stale.cookies.set(COOKIE, token)
    refused(stale.get("/wb/me"), 401, "session", "session_expired", {})


def test_session_expired_carries_no_params_when_recovery_changed(bench, operator):
    bench.control.bump_recovery("restore")
    refused(operator.get("/wb/me"), 401, "session", "session_expired", {})


def test_bad_credentials_carries_no_params(bench):
    response = bench.login(bench.lan, secret="definitely not the secret")
    refused(response, 401, "session", "bad_credentials", {})


def test_login_locked_carries_no_params_when_the_wait_is_not_known(bench):
    for _ in range(5):
        assert bench.login(bench.lan, secret="definitely not the secret").status_code == 401
    refused(bench.login(bench.lan, secret=SECRET), 429, "locked", "login_locked", {})


# --- entry -------------------------------------------------------------------------------------


def test_unknown_address_carries_no_params(bench):
    response = bench.login(client_on(bench, LAN_HOST, MAIN_PORT))
    refused(response, 403, "entry", "unknown_address", {})


def test_not_from_page_carries_no_params(operator):
    response = operator.post("/wb/logout", headers={"x-growbridge-ui": "1"})
    refused(response, 403, "entry", "not_from_page", {})


def test_session_other_entry_carries_no_params(bench):
    bench.login(bench.overlay)
    lan = client_on(bench, LAN_HOST, LAN_PORT)
    lan.cookies.set(COOKIE, bench.overlay.cookies.get(COOKIE))
    refused(lan.get("/wb/me"), 403, "entry", "session_other_entry", {})


def test_onsite_only_carries_no_params(bench):
    manual_stage_over_overlay(bench)
    body = {"stage_id": "stage-1", "request_id": "water-0001", "seconds": 2}
    response = bench.post(bench.overlay, "/wb/irrigation", body)
    refused(response, 403, "entry", "onsite_only", {})


def manual_stage_over_overlay(bench) -> None:
    assert bench.login(bench.overlay).status_code == 200
    manual_stage(bench, bench.overlay)


# --- manual writes, measurements, receipts -----------------------------------------------------


def test_stage_not_in_manual_carries_the_stage_and_its_state(bench, operator):
    bench.pending()
    response = bench.post(operator, "/wb/manual/light", manual_body())
    params = {"stage_id": "stage-1", "state": bench.state()}
    refused(response, 409, "state", "stage_not_in_manual", params)


def test_pump_on_forbidden_carries_no_params(bench, operator):
    manual_stage(bench, operator)
    response = bench.post(operator, "/wb/manual/pump", manual_body(level=1))
    refused(response, 403, "pump_on_forbidden", "pump_on_forbidden", {})


@pytest.mark.parametrize(
    ("channel", "level", "low", "high"), [("fan", 11, 0, 10), ("light", -1, 0, 100)]
)
def test_level_out_of_range_carries_the_channel_the_level_and_its_range(
    bench, operator, channel, level, low, high
):
    manual_stage(bench, operator)
    response = bench.post(operator, f"/wb/manual/{channel}", manual_body(level=level))
    params = {"channel": channel, "level": level, "min": low, "max": high}
    body = refused(response, 422, "param", "level_out_of_range", params)
    assert body["message"] == f"{channel} level {level} is outside {low}..{high}"


def test_not_this_stage_carries_the_experiment(bench, operator):
    response = bench.post(operator, "/wb/measurements", measurement())
    params = {"experiment_id": "experiment-stage-1"}
    refused(response, 403, "scope", "not_this_stage", params)


def test_measurement_rejected_carries_the_reason_the_archive_gave_as_detail(bench, operator):
    bench.pending()
    response = bench.post(operator, "/wb/measurements", measurement(corrects="measure-nope"))
    body = refused(
        response, 422, "param", "measurement_rejected", {"detail": response_detail(bench)}
    )
    assert body["message"] == "the measurement was not accepted"


def response_detail(bench) -> str:
    with pytest.raises(ValueError) as raised:
        from growbridge.archive.models import ManualMeasurement

        record = ManualMeasurement(id="m", operator="alice", **measurement(corrects="measure-nope"))
        bench.archive.add_measurement(record)
    return str(raised.value)


def test_unknown_request_is_a_404_with_the_full_body(operator):
    response = operator.get("/wb/receipts/never-sent")
    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "state",
        "reason": "unknown_request",
        "params": {"request_id": "never-sent"},
        "message": "Unknown request id",
    }


# --- manual tasks ------------------------------------------------------------------------------


def test_stage_not_started_carries_the_stage(bench, operator):
    bench.pending()
    refused(done(bench, operator), 409, "state", "stage_not_started", {"stage_id": "stage-1"})


def test_no_such_occurrence_carries_the_task_and_the_time(bench, operator):
    running(bench)
    response = done(bench, operator, due_at=WATER_DUE + 60)
    refused(
        response, 403, "scope", "no_such_occurrence", {"task_id": "water", "due_at": WATER_DUE + 60}
    )


def test_manual_task_not_due_carries_when_it_opens(bench, operator):
    running(bench)
    bench.clock.wall = STARTED
    response = done(bench, operator, "photo", PHOTO_DUE)
    params = {"task_id": "photo", "due_at": PHOTO_DUE, "opens_at": PHOTO_DUE - 3600.0}
    refused(response, 409, "state", "manual_task_not_due", params)


def test_done_at_window_carries_the_window_length(bench, operator):
    running(bench)
    bench.clock.wall = WATER_DUE + 600
    response = done(bench, operator, done_at=WATER_DUE + 7200)
    refused(response, 403, "param", "done_at_window", {"window_seconds": 3600.0})


def test_skipped_has_time_carries_no_params(bench, operator):
    running(bench)
    bench.clock.wall = WATER_DUE + 600
    body = {"task_id": "water", "due_at": WATER_DUE, "outcome": "skipped", "done_at": WATER_DUE}
    refused(bench.post(operator, PATH, body), 403, "param", "skipped_has_time", {})


def test_not_irrigation_carries_the_task(bench, operator):
    running(bench)
    bench.clock.wall = PHOTO_DUE
    body = {"task_id": "photo", "due_at": PHOTO_DUE}
    response = bench.post(operator, f"{PATH}/irrigate", body)
    refused(response, 403, "scope", "not_irrigation", {"task_id": "photo"})


def test_irrigation_stage_not_running_carries_the_stage_and_its_state(bench, operator):
    running(bench, state=StageState.PAUSED, right_number=None)
    bench.clock.wall = WATER_DUE
    params = {"stage_id": "stage-1", "state": "paused"}
    refused(irrigate(bench, operator), 409, "state", "irrigation_stage_not_running", params)


def test_irrigation_past_deadline_carries_the_deadline(bench, operator):
    running(bench)
    bench.clock.wall = WATER_DUE + ON_TIME_SECONDS + 1
    response = irrigate(bench, operator)
    body = response.json()["detail"]
    assert response.status_code == 409 and body["reason"] == "irrigation_past_deadline"
    assert set(body["params"]) == {"task_id", "due_at", "deadline_at"}
    assert body["params"]["task_id"] == "water" and body["params"]["due_at"] == WATER_DUE
    assert body["params"]["deadline_at"] > WATER_DUE


def test_irrigation_already_ran_carries_the_task_and_the_time(bench, operator):
    running(bench)
    bench.clock.wall = WATER_DUE + 60
    assert irrigate(bench, operator).status_code == 200
    skipped = {"task_id": "water", "due_at": WATER_DUE, "outcome": "skipped"}
    assert bench.post(operator, PATH, skipped).status_code == 200
    params = {"task_id": "water", "due_at": WATER_DUE}
    refused(irrigate(bench, operator), 409, "state", "irrigation_already_ran", params)


def test_irrigation_already_done_carries_the_task_and_the_time(bench, operator):
    running(bench)
    bench.clock.wall = WATER_DUE + 60
    assert done(bench, operator).status_code == 200
    params = {"task_id": "water", "due_at": WATER_DUE}
    refused(irrigate(bench, operator), 409, "state", "irrigation_already_done", params)


def test_irrigation_attempts_exhausted_carries_the_task_the_stage_and_the_attempts(bench, operator):
    running(bench)
    bench.clock.wall = WATER_DUE + 60
    for attempt in range(1, MAX_ATTEMPTS + 1):
        bench.control.receipts[run_id(attempt)] = ActionRecord(
            request_id=run_id(attempt),
            state=ActionState.VOID,
            channel=Channel.PUMP,
            planned_level=1,
            right_number=7,
            right_kind=RightKind.STAGE,
            trigger="planned irrigation water",
            created_at=WATER_DUE,
            sent_at=WATER_DUE,
        )
    params = {"task_id": "water", "stage_id": "stage-1", "attempts": MAX_ATTEMPTS}
    body = refused(irrigate(bench, operator), 409, "state", "irrigation_attempts_exhausted", params)
    assert body["message"] == f"{MAX_ATTEMPTS} attempts of this irrigation never reached the device"
