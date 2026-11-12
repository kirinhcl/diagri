"""Manual writes, irrigation (LAN only), manual measurements, safety approval, receipts and
alerts through the workbench."""

import json

import pytest

from growbridge.archive.models import Channel
from growbridge.sim.fixtures import make_safety


def detail(response) -> dict:
    return response.json()["detail"]


def manual_stage(bench, client) -> int:
    """A running stage taken over by the logged-in operator; returns the manual right."""
    bench.pending()
    for action in ("approve", "start", "takeover"):
        assert bench.post(client, f"/wb/stages/stage-1/{action}").status_code == 200
    number = bench.workflow.stage("stage-1").manual_right
    assert number is not None
    return number


def manual_body(**fields) -> dict:
    return {"stage_id": "stage-1", "request_id": "manual-0001", "level": 40, **fields}


# --- manual writes -----------------------------------------------------------------------------


def test_manual_write_uses_the_stage_right_and_the_session_identity(bench, operator):
    number = manual_stage(bench, operator)
    body = manual_body(note="dim the lamp", operator="mallory", right_number=999)

    response = bench.post(operator, "/wb/manual/light", body)

    assert response.status_code == 200 and response.json()["state"] == "confirmed"
    (request,) = bench.control.submitted
    assert request.right_number == number
    assert (request.channel, request.level) == (Channel.LIGHT, 40)
    assert request.operator == "alice"
    assert request.experiment_id == "experiment-stage-1" and request.stage_id == "stage-1"
    assert "dim the lamp" in request.trigger


def test_manual_write_needs_a_stage_under_manual_control(bench, operator):
    bench.pending()

    response = bench.post(operator, "/wb/manual/light", manual_body())

    assert response.status_code == 409 and detail(response)["code"] == "state"
    assert bench.control.submitted == []


def test_manual_write_is_available_on_the_overlay_entry_too(bench, operator):
    manual_stage(bench, operator)
    assert bench.login(bench.overlay).status_code == 200

    response = bench.post(bench.overlay, "/wb/manual/light", manual_body())

    assert response.status_code == 200


def test_manual_write_by_a_model_is_refused(bench, operator):
    manual_stage(bench, operator)

    response = bench.post(bench.lan, "/wb/manual/light", manual_body(), headers=bench.model())

    assert response.status_code == 403 and detail(response)["code"] == "model_role"
    assert bench.control.submitted == []


@pytest.mark.parametrize(
    ("channel", "level"), [("heater", 1), ("fan", 11), ("light", 101), ("light", -1)]
)
def test_manual_write_rejects_unknown_channels_and_out_of_range_levels(
    bench, operator, channel, level
):
    manual_stage(bench, operator)

    response = bench.post(operator, f"/wb/manual/{channel}", manual_body(level=level))

    assert response.status_code == 422
    assert bench.control.submitted == []


def test_manual_route_cannot_switch_the_pump_on(bench, operator):
    manual_stage(bench, operator)

    on = bench.post(operator, "/wb/manual/pump", manual_body(level=1))
    off = bench.post(operator, "/wb/manual/pump", manual_body(request_id="manual-0002", level=0))

    assert on.status_code == 403 and detail(on)["code"] == "pump_on_forbidden"
    assert off.status_code == 200
    assert [request.level for request in bench.control.submitted] == [0]


def test_receipt_can_be_read_by_operators_and_models(bench, operator):
    manual_stage(bench, operator)
    bench.post(operator, "/wb/manual/light", manual_body())

    mine = operator.get("/wb/receipts/manual-0001")
    theirs = bench.lan.get("/wb/receipts/manual-0001", headers=bench.model("analyst"))

    assert mine.status_code == theirs.status_code == 200
    assert mine.json()["request_id"] == "manual-0001" and mine.json()["state"] == "confirmed"
    assert operator.get("/wb/receipts/never-sent").status_code == 404


# --- irrigation --------------------------------------------------------------------------------


def irrigation_body(**fields) -> dict:
    return {"stage_id": "stage-1", "request_id": "water-0001", "seconds": 2, **fields}


def test_irrigation_runs_on_the_lan_entry(bench, operator):
    number = manual_stage(bench, operator)

    response = bench.post(operator, "/wb/irrigation", irrigation_body(note="tray 3"))

    assert response.status_code == 200
    ((request, seconds),) = bench.control.irrigated
    assert (request.channel, request.level, seconds) == (Channel.PUMP, 1, 2)
    assert request.right_number == number and request.operator == "alice"


def test_irrigation_is_refused_on_the_overlay_entry(bench, operator):
    manual_stage(bench, operator)
    assert bench.login(bench.overlay).status_code == 200

    response = bench.post(bench.overlay, "/wb/irrigation", irrigation_body())

    assert response.status_code == 403 and detail(response)["code"] == "entry"
    assert bench.control.irrigated == []


def test_irrigation_by_a_model_is_refused(bench, operator):
    manual_stage(bench, operator)

    response = bench.post(bench.lan, "/wb/irrigation", irrigation_body(), headers=bench.model())

    assert response.status_code == 403 and detail(response)["code"] == "model_role"
    assert bench.control.irrigated == []


@pytest.mark.parametrize("seconds", [0, -1, 61, "soon"])
def test_irrigation_duration_is_bounded(bench, operator, seconds):
    manual_stage(bench, operator)

    response = bench.post(operator, "/wb/irrigation", irrigation_body(seconds=seconds))

    assert response.status_code == 422 and bench.control.irrigated == []


def test_entry_claim_in_the_body_does_not_unlock_irrigation_on_the_overlay(bench, operator):
    manual_stage(bench, operator)
    assert bench.login(bench.overlay).status_code == 200

    response = bench.post(bench.overlay, "/wb/irrigation", irrigation_body(entry="lan"))

    assert response.status_code == 403 and bench.control.irrigated == []


# --- manual measurements -----------------------------------------------------------------------


def measurement(**fields) -> dict:
    return {
        "experiment_id": "experiment-stage-1",
        "batch": "batch-a",
        "plant_id": "plant-01",
        "layout_version": "layout-1",
        "measured_at": 1_799_999_000.0,
        "position": "tray-1",
        "method": "ruler",
        "metric": "height",
        "value": 12.5,
        "unit": "cm",
        **fields,
    }


def stored(bench, include_corrected=False):
    return bench.archive.measurements("experiment-stage-1", include_corrected)


def test_measurement_is_archived_under_the_session_operator(bench, operator):
    response = bench.post(operator, "/wb/measurements", measurement(operator="mallory"))

    assert response.status_code == 200
    (record,) = stored(bench)
    assert record.operator == "alice" and record.value == 12.5 and record.id
    assert response.json()["id"] == record.id


def test_measurement_retry_with_the_same_id_is_stored_once(bench, operator):
    body = measurement(id="measure-0001")

    assert bench.post(operator, "/wb/measurements", body).status_code == 200
    assert bench.post(operator, "/wb/measurements", body).status_code == 200

    assert len(stored(bench)) == 1


def test_measurement_correction_keeps_the_raw_record(bench, operator):
    first = bench.post(operator, "/wb/measurements", measurement(id="measure-0001")).json()
    fix = measurement(id="measure-0002", value=13.0, corrects=first["id"])

    assert bench.post(operator, "/wb/measurements", fix).status_code == 200

    assert [record.id for record in stored(bench)] == ["measure-0002"]
    assert len(stored(bench, include_corrected=True)) == 2


def test_correcting_an_unknown_measurement_is_rejected_without_detail(bench, operator):
    response = bench.post(operator, "/wb/measurements", measurement(corrects="measure-nope"))

    assert response.status_code == 422
    assert stored(bench) == ()


def test_measurement_by_a_model_is_refused(bench):
    response = bench.post(bench.lan, "/wb/measurements", measurement(), headers=bench.model())

    assert response.status_code == 403 and stored(bench) == ()


def test_malformed_measurement_is_422(bench, operator):
    response = bench.post(operator, "/wb/measurements", {"value": "tall"})

    assert response.status_code == 422


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_a_measurement_that_is_not_finite_is_422_and_its_input_is_echoed_as_text(
    bench, operator, value
):
    headers = {**bench.ui(operator), "Content-Type": "application/json"}
    body = json.dumps(measurement(value=value))  # writes the NaN and Infinity tokens

    response = operator.post("/wb/measurements", content=body, headers=headers)

    assert response.status_code == 422 and stored(bench) == ()
    (error,) = response.json()["detail"]
    assert error["loc"] == ["body", "value"] and error["input"] == str(value)


# --- safety configuration ----------------------------------------------------------------------


def safety_body(**fields) -> dict:
    config = make_safety(version=2).model_dump(mode="json")
    return {"config": {**config, **fields}}


def test_safety_approval_is_stamped_with_the_session_operator(bench, operator):
    body = safety_body(approved_by="mallory", approved_at=5.0)

    response = bench.post(operator, "/wb/safety/approve", body)

    assert response.status_code == 200 and isinstance(response.json()["protection_right"], int)
    assert bench.control.safety_config.version == 2
    assert bench.control.safety_config.approved_by == "alice"
    assert bench.control.safety_config.approved_at == bench.clock.now()


def test_safety_approval_needs_a_recent_reauthentication(bench, operator):
    bench.clock.advance(301)

    response = bench.post(operator, "/wb/safety/approve", safety_body())

    assert response.status_code == 403 and detail(response)["code"] == "reauth_required"
    assert bench.control.safety_config.version == 1


def test_safety_approval_by_a_model_is_refused(bench):
    response = bench.post(bench.lan, "/wb/safety/approve", safety_body(), headers=bench.model())

    assert response.status_code == 403 and bench.control.safety_config.version == 1


def test_safety_config_with_a_wrong_shape_is_422(bench, operator):
    response = bench.post(operator, "/wb/safety/approve", {"config": {"version": "two"}})

    assert response.status_code == 422


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "Infinity"])
def test_safety_config_with_a_number_that_is_not_finite_is_422_and_nothing_changes(
    bench, operator, value
):
    body = safety_body()
    body["config"]["rules"][0]["trigger"]["value"] = value
    headers = {**bench.ui(operator), "Content-Type": "application/json"}

    response = operator.post("/wb/safety/approve", content=json.dumps(body), headers=headers)

    assert response.status_code == 422
    assert bench.control.safety_config.version == 1  # the approved configuration is unchanged


# --- alerts ------------------------------------------------------------------------------------


def test_alerts_are_listed_and_marked_read_by_the_operator(bench, operator):
    alert = bench.alerts.raise_alert("threshold", "too_hot", "critical", "31 C")

    listed = operator.get("/wb/alerts").json()["alerts"]
    marked = bench.post(operator, f"/wb/alerts/{alert.event_id}/read")

    assert [item["event_id"] for item in listed] == [alert.event_id]
    assert marked.status_code == 200
    assert bench.alerts.get(alert.event_id).read_by == "alice"


def test_models_may_list_alerts_but_not_mark_them_read(bench):
    alert = bench.alerts.raise_alert("threshold", "too_hot", "critical", "31 C")

    listed = bench.lan.get("/wb/alerts", headers=bench.model())
    marked = bench.post(bench.lan, f"/wb/alerts/{alert.event_id}/read", headers=bench.model())

    assert listed.status_code == 200 and len(listed.json()["alerts"]) == 1
    assert marked.status_code == 403
    assert bench.alerts.get(alert.event_id).read_by is None


def test_marking_an_unknown_alert_read_is_a_state_conflict(bench, operator):
    response = bench.post(operator, "/wb/alerts/alert_missing/read")

    assert response.status_code == 409 and detail(response)["code"] == "state"
