import httpx

from growbridge.api import create_app
from growbridge.mcp_server import create_mcp


async def test_api_authentication_and_bounds(bridge, settings):
    core, device = bridge
    app = create_app(settings, core)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        assert (await client.get("/status")).status_code == 401
        client.headers["Authorization"] = f"Bearer {settings.token}"
        assert (await client.get("/status")).json()["data"]["sensor"]["temp"] == 22.5
        assert (
            await client.post("/control/light", json={"request_id": "bounds-001", "level": 101})
        ).status_code == 422
        assert (
            await client.post("/pump", json={"request_id": "pump-001", "seconds": 6})
        ).status_code == 409
        assert not device.commands


async def test_mcp_tool_inventory_and_annotations(settings):
    tools = await create_mcp(settings).list_tools()
    assert len(tools) == 8
    by_name = {tool.name: tool for tool in tools}
    assert by_name["get_status"].annotations.readOnlyHint
    assert by_name["run_pump"].annotations.destructiveHint
    assert "request_id" in by_name["run_pump"].inputSchema["required"]


async def test_a_lone_surrogate_in_a_bridge_body_is_a_readable_422(bridge, settings):
    core, device = bridge
    app = create_app(settings, core)
    raw = '{"request_id": "\\ud800bad-id", "seconds": 1}'  # JSON text: a lone surrogate escape
    headers = {"Authorization": f"Bearer {settings.token}", "content-type": "application/json"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/pump", content=raw, headers=headers)

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][-1] == "request_id"
    assert not device.commands


def coded(response, status, detail, code, reason, params=None):
    assert response.status_code == status
    body = response.json()
    assert body["detail"] == detail and isinstance(body["detail"], str)
    assert (body["code"], body["reason"], body["params"]) == (code, reason, params or {})


async def test_a_missing_bearer_is_not_signed_in(bridge, settings):
    app = create_app(settings, bridge[0])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/status", headers={"Authorization": "Bearer wrong"})
    coded(response, 401, "Authentication required", "session", "not_signed_in")


async def test_an_unknown_device_is_record_not_found(bridge, settings):
    app = create_app(settings, bridge[0])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/control/heater",
            json={"request_id": "unknown-001", "level": 5},
            headers={"Authorization": f"Bearer {settings.token}"},
        )
    coded(
        response,
        404,
        "Unknown device",
        "state",
        "record_not_found",
        {"record_kind": "device", "record_id": "heater"},
    )


async def test_an_unconfirmed_pump_is_pump_unconfirmed(bridge, settings):
    core, _ = bridge
    core.interlock = True
    app = create_app(settings, core)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/pump",
            json={"request_id": "pump-9001", "seconds": 1},
            headers={"Authorization": f"Bearer {settings.token}"},
        )
    # a plain BridgeError (the interlock refusal): no code, reason null
    coded(
        response,
        409,
        "Pump off is unconfirmed; resolve before further controls",
        None,
        None,
    )


async def test_the_pump_off_unconfirmed_error_is_interlock_pump_unconfirmed(settings, bridge):
    from growbridge.service import PumpOffUnconfirmed

    app = create_app(settings, bridge[0])

    @app.get("/boom")
    async def boom():
        raise PumpOffUnconfirmed("Pump off unconfirmed; check the pump physically")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/boom")
    coded(
        response,
        409,
        "Pump off unconfirmed; check the pump physically",
        "interlock",
        "pump_unconfirmed",
        {"device_id": None},
    )


async def test_old_clients_still_read_a_string_detail(bridge, settings):
    app = create_app(settings, bridge[0])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        auth = {"Authorization": f"Bearer {settings.token}"}
        bodies = [
            (await client.get("/status")).json(),
            (await client.get("/status", headers={"Authorization": "Bearer no"})).json(),
            (
                await client.post(
                    "/control/heater", json={"request_id": "old-client-1", "level": 5}, headers=auth
                )
            ).json(),
            (
                await client.post(
                    "/pump", json={"request_id": "old-client-2", "seconds": 6}, headers=auth
                )
            ).json(),
        ]
    assert all(isinstance(body["detail"], str) for body in bodies)
