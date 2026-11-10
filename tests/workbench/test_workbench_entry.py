"""The entry follows the listener that accepted the connection, not just the Host header."""

import pytest
from fastapi.testclient import TestClient
from workbench_support import (
    LAN_HOST,
    LAN_PORT,
    MAIN_PORT,
    OVERLAY_HOST,
    ROLE_TOKENS,
    SECRET,
    Bench,
)

from growbridge.workbench.api import create_workbench


def detail(response) -> dict:
    return response.json()["detail"]


def manual_stage(bench, client) -> None:
    bench.pending()
    for action in ("approve", "start", "takeover"):
        assert bench.post(client, f"/wb/stages/stage-1/{action}").status_code == 200


def client_on(bench, host: str, port: int, scheme: str = "http") -> TestClient:
    return TestClient(bench.app, base_url=f"{scheme}://{host}:{port}")


def test_lan_host_on_the_lan_port_is_the_lan_entry(bench):
    assert bench.login(bench.lan).status_code == 200

    assert bench.lan.get("/wb/me").json()["entry"] == "lan"


def test_spoofed_lan_host_and_origin_on_the_main_port_is_no_entry(bench):
    spoof = client_on(bench, LAN_HOST, MAIN_PORT)

    response = bench.login(spoof)  # Host and Origin both name the LAN host

    assert response.status_code == 403 and detail(response)["code"] == "entry"


def test_overlay_session_replayed_with_a_spoofed_lan_host_cannot_irrigate(bench):
    assert bench.login(bench.overlay).status_code == 200
    manual_stage(bench, bench.overlay)
    spoof = client_on(bench, LAN_HOST, MAIN_PORT)
    spoof.cookies.set("growbridge_operator", bench.overlay.cookies.get("growbridge_operator"))
    body = {"stage_id": "stage-1", "request_id": "water-0001", "seconds": 2}

    response = bench.post(spoof, "/wb/irrigation", body)

    assert response.status_code == 403 and bench.control.irrigated == []


def test_lan_session_does_not_work_for_a_spoofed_host_on_the_main_port(bench, operator):
    spoof = client_on(bench, LAN_HOST, MAIN_PORT)
    spoof.cookies.update(operator.cookies)

    assert spoof.get("/wb/me").status_code == 403


def test_overlay_host_on_the_lan_port_is_not_the_overlay_entry(bench):
    response = bench.login(client_on(bench, OVERLAY_HOST, LAN_PORT, "https"))

    assert response.status_code == 403 and detail(response)["code"] == "entry"


def test_overlay_host_on_the_main_port_is_the_overlay_entry(bench):
    assert bench.login(bench.overlay).status_code == 200

    assert bench.overlay.get("/wb/me").json()["entry"] == "overlay"


def test_irrigation_is_refused_when_no_lan_port_is_configured(bench_without_lan):
    bench = bench_without_lan
    assert bench.login(bench.overlay).status_code == 200
    manual_stage(bench, bench.overlay)
    body = {"stage_id": "stage-1", "request_id": "water-0001", "seconds": 2}

    over_overlay = bench.post(bench.overlay, "/wb/irrigation", body)
    lan_attempt = bench.login(bench.lan)

    assert over_overlay.status_code == 403 and detail(over_overlay)["code"] == "entry"
    assert lan_attempt.status_code == 403 and detail(lan_attempt)["code"] == "entry"
    assert bench.control.irrigated == []


def test_an_unknown_listener_port_is_no_entry(bench):
    assert bench.login(client_on(bench, LAN_HOST, 1234)).status_code == 403


def test_origin_must_still_name_the_host_the_request_arrived_on(bench):
    headers = {"Origin": f"http://{OVERLAY_HOST}", "x-growbridge-ui": "1"}

    response = bench.lan.post(
        "/wb/login", json={"name": "alice", "secret": SECRET}, headers=headers
    )

    assert response.status_code == 403


# --- role token length -------------------------------------------------------------------------


def build(bench: Bench, tokens: dict[str, str]):
    return create_workbench(
        bench.workflow, bench.control, bench.archive, bench.operators, bench.settings, tokens
    )


@pytest.mark.parametrize("token", ["", "tiny-0123", "x" * 31])
def test_short_role_tokens_are_rejected_without_echoing_them(bench, token):
    with pytest.raises(ValueError) as error:
        build(bench, {"planner": token})

    assert "planner" in str(error.value) and "32" in str(error.value)
    assert not token or token not in str(error.value)


def test_role_token_of_32_characters_is_accepted(bench):
    assert build(bench, {**ROLE_TOKENS, "extra": "y" * 32}) is not None


def test_one_short_token_among_good_ones_is_still_rejected(bench):
    with pytest.raises(ValueError):
        build(bench, {**ROLE_TOKENS, "analyst": "z" * 8})
