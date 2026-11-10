"""Operator login over HTTP: cookie attributes, the entry bound to the arrival address, session
invalidation, CSRF headers and the login lock."""

from fastapi.testclient import TestClient
from workbench_support import LAN_HOST, LAN_PORT, SECRET

OPERATOR_COOKIE = "growbridge_operator"


def detail(response) -> dict:
    return response.json()["detail"]


def test_login_sets_a_strict_http_only_cookie_without_secure_on_lan(bench):
    response = bench.login(bench.lan)

    cookie = response.headers["set-cookie"].lower()
    assert response.status_code == 200
    assert cookie.startswith(OPERATOR_COOKIE)
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert "secure" not in cookie


def test_login_cookie_is_secure_on_the_overlay_entry(bench):
    response = bench.login(bench.overlay)

    cookie = response.headers["set-cookie"].lower()
    assert "secure" in cookie and "httponly" in cookie and "samesite=strict" in cookie


def test_login_response_never_contains_the_token_or_the_secret(bench):
    response = bench.login(bench.lan)

    token = bench.lan.cookies.get(OPERATOR_COOKIE)
    assert token and token not in response.text and SECRET not in response.text


def test_session_reports_the_operator_and_the_entry(operator):
    body = operator.get("/wb/me").json()

    assert body["operator"] == "alice"
    assert body["entry"] == "lan"
    assert body["kind"] == "operator"


def test_entry_comes_from_the_host_not_from_the_body(bench):
    body = {"name": "alice", "secret": SECRET, "entry": "lan"}

    bench.post(bench.overlay, "/wb/login", body)

    assert bench.overlay.get("/wb/me").json()["entry"] == "overlay"


def test_cookie_from_the_overlay_does_not_work_on_the_lan_address(bench):
    bench.login(bench.overlay)
    stolen = bench.overlay.cookies.get(OPERATOR_COOKIE)
    lan = TestClient(bench.app, base_url=f"http://{LAN_HOST}:{LAN_PORT}")
    lan.cookies.set(OPERATOR_COOKIE, stolen)

    response = lan.get("/wb/me")

    assert response.status_code == 403
    assert detail(response)["code"] == "entry"


def test_an_address_that_is_not_a_registered_entry_cannot_log_in(bench):
    client = TestClient(bench.app, base_url=f"http://localhost:{bench.settings.port}")

    response = bench.login(client)

    assert response.status_code == 403
    assert detail(response)["code"] == "entry"


def test_wrong_secret_is_401_with_a_generic_message(bench):
    response = bench.login(bench.lan, secret="definitely not the secret")

    assert response.status_code == 401
    assert detail(response)["code"] == "session"
    assert "scrypt" not in response.text and "alice" not in response.text


def test_repeated_failures_lock_the_account_with_429(bench):
    for _ in range(5):
        assert bench.login(bench.lan, secret="definitely not the secret").status_code == 401

    response = bench.login(bench.lan)

    assert response.status_code == 429
    assert detail(response)["code"] == "locked"


def test_changed_recovery_number_voids_the_session(bench, operator):
    assert operator.get("/wb/me").status_code == 200

    bench.control.bump_recovery("restore")

    response = operator.get("/wb/me")
    assert response.status_code == 401
    assert detail(response)["code"] == "session"


def test_session_expires(bench, operator):
    bench.clock.advance(13 * 3600)

    assert operator.get("/wb/me").status_code == 401


def test_logout_ends_the_session(bench, operator):
    token = operator.cookies.get(OPERATOR_COOKIE)

    assert bench.post(operator, "/wb/logout").status_code == 200

    stale = TestClient(bench.app, base_url=f"http://{LAN_HOST}:{LAN_PORT}")
    stale.cookies.set(OPERATOR_COOKIE, token)
    assert stale.get("/wb/me").status_code == 401


def test_state_changing_request_needs_origin_and_ui_header(operator):
    no_origin = operator.post("/wb/logout", headers={"x-growbridge-ui": "1"})
    no_header = operator.post("/wb/logout", headers={"Origin": f"http://{LAN_HOST}"})
    wrong_origin = operator.post(
        "/wb/logout", headers={"Origin": "http://evil.test", "x-growbridge-ui": "1"}
    )

    assert (no_origin.status_code, no_header.status_code, wrong_origin.status_code) == (403,) * 3
    assert operator.get("/wb/me").status_code == 200  # still logged in; reads need no headers


def test_reauthentication_endpoint_refreshes_and_rejects_a_wrong_secret(bench, operator):
    bench.clock.advance(600)

    bad = bench.post(operator, "/wb/reauth", {"secret": "definitely not the secret"})
    good = bench.post(operator, "/wb/reauth", {"secret": SECRET})

    assert bad.status_code == 401
    assert good.status_code == 200
    assert operator.get("/wb/me").json()["reauth_at"] == bench.clock.now()


def test_unauthenticated_requests_are_401(bench):
    assert bench.lan.get("/wb/me").status_code == 401
    assert bench.post(bench.lan, "/wb/stages/stage-1/approve").status_code == 401
    assert bench.lan.get("/wb/alerts").status_code == 401


def test_bearer_with_an_unknown_token_is_401(bench):
    response = bench.lan.get("/wb/me", headers={"Authorization": "Bearer not-a-role-token"})

    assert response.status_code == 401


def test_failures_from_one_client_address_do_not_lock_other_addresses(bench):
    attacker = TestClient(bench.app, base_url=bench.lan.base_url, client=("198.51.100.7", 4000))
    friend = TestClient(bench.app, base_url=bench.lan.base_url, client=("192.0.2.10", 4000))
    for _ in range(5):
        assert bench.login(attacker, secret="definitely not the secret").status_code == 401

    assert bench.login(attacker).status_code == 429
    assert bench.login(friend).status_code == 200
