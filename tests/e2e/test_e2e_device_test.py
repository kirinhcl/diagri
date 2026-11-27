"""A device test through the app ``serve`` builds, on the simulated AC5 (design 2026-11-27).

The light runs on the AC5's own program (a non-manual mode) before the test; afterwards the
whole block, mode included, is back.
"""

import copy

import httpx
import pytest
import pytest_asyncio

from growbridge.api import create_app
from growbridge.config import Greenhouse

LAN_HOST = "lan.test"
LAN_PORT = 9443
BASE = f"http://{LAN_HOST}:{LAN_PORT}"
PAGE = {"Origin": BASE, "x-growbridge-ui": "1"}
SECRET = "correct horse battery staple"  # obviously fake
HOUSES = [
    Greenhouse(id="gh-01", name="Greenhouse 1", device_id="SIMULATED"),
    Greenhouse(id="gh-02", name="Greenhouse 2", device_id="AC5-02"),
]


@pytest.fixture
def settings(settings):
    entry = {"lan_port": LAN_PORT, "lan_hosts": [LAN_HOST]}
    return settings.model_copy(update={**entry, "multi_user": True, "greenhouses": HOUSES})


async def no_wait(_seconds: float) -> None:
    return None


@pytest_asyncio.fixture
async def site(world):
    runtime = await world.boot()
    runtime.operators.add("alice", SECRET, "user")
    app = create_app(world.settings, bridge=runtime.bridge, workbench=runtime.workbench())
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE)
    login = await client.post("/wb/login", json={"name": "alice", "secret": SECRET}, headers=PAGE)
    assert login.status_code == 200
    await world.beat(runtime)
    yield runtime, client
    await client.aclose()


async def test_light_test_restores_the_controller_program(world, site):
    runtime, alice = site
    tests = runtime.access_parts.tests
    tests.sleep = no_wait
    assert tests.protected == runtime.executor.protected_channels
    assert tests.alert == runtime.alert
    world.sim.external_change("device", "light", modeType=2)
    before = copy.deepcopy(world.sim.config["device"]["light"])
    lock = await alice.post(
        "/wb/greenhouses/lock", json={"greenhouse_ids": ["gh-01"]}, headers=PAGE
    )
    assert lock.status_code == 200, lock.text

    reply = await alice.post("/wb/greenhouses/gh-01/test/light", headers=PAGE)

    assert reply.status_code == 200, reply.text
    assert reply.json()["result"] == "restored"
    assert world.sim.config["device"]["light"] == before
    levels = [
        c["params"]["light"]["mLevel"]
        for c in world.sim.commands
        if c["method"] == "setConfigField" and c["params"]["keyPath"] == ["device", "light"]
    ]
    assert levels == [100, before["mLevel"]]
