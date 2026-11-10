"""The legacy write endpoints, mounting of the workbench, the MCP inventory, trusted hosts and
origin checks on both entry addresses."""

import pytest
from fastapi.testclient import TestClient
from workbench_support import LAN_HOST, OVERLAY_HOST, SECRET, Bench

from growbridge.api import create_app
from growbridge.dashboard import COOKIE
from growbridge.mcp_server import create_mcp

LEGACY_WRITES = (
    ("/control/light", {"request_id": "legacy-001", "level": 50}),
    ("/control/exhaust", {"request_id": "legacy-002", "level": 20}),
    ("/control/fan", {"request_id": "legacy-003", "level": 3}),
    ("/outlet", {"request_id": "legacy-004", "number": 1, "on": True}),
    ("/pump", {"request_id": "legacy-005", "seconds": 1}),
)


class StubBridge:
    """Stands in for the BLE bridge: any write that reaches it succeeds."""

    def __init__(self):
        self.calls = []

    async def operate(self, request_id, kind, params):
        self.calls.append((request_id, kind, params))
        return {"ok": True}


def shared(bench) -> dict[str, str]:
    return {"Authorization": f"Bearer {bench.settings.token}"}


def browser_session(bench, client: TestClient) -> None:
    """Exchange the shared token for a legacy browser session cookie, as the dashboard does."""
    code = client.post("/ui/session", headers=shared(bench)).json()["code"]
    response = client.post("/ui/session/redeem", json={"code": code}, headers=Bench.ui(client))
    assert response.status_code == 200
    assert client.cookies.get(COOKIE)


# --- legacy writes closed ----------------------------------------------------------------------


@pytest.mark.parametrize(("path", "body"), LEGACY_WRITES)
def test_shared_token_cannot_write_in_auto_research_mode(bench, path, body):
    response = bench.lan.post(path, json=body, headers=shared(bench))

    assert response.status_code == 403


@pytest.mark.parametrize(("path", "body"), LEGACY_WRITES)
def test_browser_session_from_shared_token_cannot_write_either(bench, path, body):
    client = TestClient(bench.app, base_url=f"http://{LAN_HOST}")
    browser_session(bench, client)

    response = client.post(path, json=body, headers=Bench.ui(client))

    assert response.status_code == 403


def test_closed_legacy_write_is_refused_before_body_validation(bench):
    response = bench.lan.post("/control/light", json={"level": 999}, headers=shared(bench))

    assert response.status_code == 403


@pytest.mark.parametrize(("path", "body"), LEGACY_WRITES)
def test_unauthenticated_legacy_write_is_still_401(bench, path, body):
    assert bench.lan.post(path, json=body).status_code == 401


def test_shared_token_is_not_a_workbench_credential(bench):
    response = bench.lan.get("/wb/me", headers=shared(bench))

    assert response.status_code == 401


def test_legacy_behaviour_is_unchanged_when_auto_research_is_off(bench):
    stub = StubBridge()
    off = bench.settings.model_copy(update={"auto_research": False})
    app = create_app(off, bridge=stub, workbench=bench.router)
    client = TestClient(app, base_url="http://localhost")

    response = client.post("/control/light", json=LEGACY_WRITES[0][1], headers=shared(bench))

    assert response.status_code == 200
    assert stub.calls == [("legacy-001", "light", {"level": 50})]


# --- mounting ----------------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["get", "post"])
def test_workbench_routes_do_not_exist_when_auto_research_is_off(bench, method):
    off = bench.settings.model_copy(update={"auto_research": False})
    client = TestClient(create_app(off, bridge=StubBridge(), workbench=bench.router))

    response = getattr(client, method)("/wb/login" if method == "post" else "/wb/me")

    assert response.status_code == 404


def test_workbench_is_absent_when_none_is_given(bench):
    app = create_app(bench.settings, bridge=StubBridge())
    client = TestClient(app, base_url=f"http://{LAN_HOST}")

    assert client.get("/wb/me").status_code == 404


# --- MCP ---------------------------------------------------------------------------------------


async def test_mcp_keeps_eight_tools_when_auto_research_is_off(bench):
    off = bench.settings.model_copy(update={"auto_research": False})

    tools = await create_mcp(off).list_tools()

    assert len(tools) == 8


async def test_mcp_exposes_only_the_read_tools_in_auto_research_mode(bench):
    tools = await create_mcp(bench.settings).list_tools()

    assert {tool.name for tool in tools} == {"get_health", "get_status", "get_history"}
    assert all(tool.annotations.readOnlyHint for tool in tools)


# --- trusted hosts and origins -----------------------------------------------------------------


@pytest.mark.parametrize("host", [LAN_HOST, OVERLAY_HOST])
def test_both_entry_addresses_are_trusted_hosts(bench, host):
    client = TestClient(bench.app, base_url=f"http://{host}")

    assert client.get("/wb/me").status_code == 401  # reached the app, not the host filter


def test_unregistered_host_is_rejected_before_any_route(bench):
    client = TestClient(bench.app, base_url="http://evil.test")

    assert client.get("/wb/me").status_code == 400
    assert client.post("/wb/login", json={}).status_code == 400


@pytest.mark.parametrize("client_name", ["lan", "overlay"])
def test_login_accepts_its_own_origin_on_each_entry(bench, client_name):
    client = getattr(bench, client_name)

    assert bench.login(client).status_code == 200


@pytest.mark.parametrize(
    "origin",
    [None, "http://evil.test", f"https://{OVERLAY_HOST}", "null", f"http://{LAN_HOST}.evil.test"],
)
def test_login_on_lan_rejects_other_origins(bench, origin):
    headers = {"x-growbridge-ui": "1"}
    if origin:
        headers["Origin"] = origin
    body = {"name": "alice", "secret": "x" * 20}

    response = bench.lan.post("/wb/login", json=body, headers=headers)

    assert response.status_code == 403


@pytest.mark.parametrize("origin", [f"http://{LAN_HOST}", "http://evil.test"])
def test_login_on_overlay_rejects_other_origins(bench, origin):
    response = bench.overlay.post(
        "/wb/login",
        json={"name": "alice", "secret": "x" * 20},
        headers={"Origin": origin, "x-growbridge-ui": "1"},
    )

    assert response.status_code == 403


def test_login_without_the_ui_header_is_rejected(bench):
    response = bench.lan.post(
        "/wb/login",
        json={"name": "alice", "secret": "x" * 20},
        headers={"Origin": f"http://{LAN_HOST}"},
    )

    assert response.status_code == 403


def test_lan_origin_without_a_port_is_allowed_on_the_lan_listener(bench):
    headers = {"Origin": f"http://{LAN_HOST}", "x-growbridge-ui": "1"}

    response = bench.lan.post(
        "/wb/login", json={"name": "alice", "secret": SECRET}, headers=headers
    )

    assert response.status_code == 200


def test_legacy_session_exchange_accepts_the_registered_origins(bench):
    client = TestClient(bench.app, base_url=f"https://{OVERLAY_HOST}")

    browser_session(bench, client)


def test_legacy_session_exchange_rejects_an_unknown_origin(bench):
    code = bench.lan.post("/ui/session", headers=shared(bench)).json()["code"]

    response = bench.lan.post(
        "/ui/session/redeem", json={"code": code}, headers={"Origin": "http://evil.test"}
    )

    assert response.status_code == 403
