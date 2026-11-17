"""Two operators use the app ``serve`` builds in parallel, on twelve registered greenhouses.

Alice locks the local greenhouse and runs a stage on the simulated AC5 through HTTP only; Bob
locks three others meanwhile and sees none of Alice's work. When Alice's stage has ended she
releases the greenhouse and Bob can take it.
"""

import httpx
import pytest
import pytest_asyncio
from e2e_support import STAGE

from growbridge.api import create_app
from growbridge.config import Greenhouse
from growbridge.sim.fixtures import make_protocol, make_safety

LAN_HOST = "lan.test"
LAN_PORT = 9443
BASE = f"http://{LAN_HOST}:{LAN_PORT}"
PAGE = {"Origin": BASE, "x-growbridge-ui": "1"}
SECRET = "correct horse battery staple"  # obviously fake
HOUSES = [Greenhouse(id="gh-01", name="Greenhouse 1", device_id="SIMULATED")] + [
    Greenhouse(id=f"gh-{n:02d}", name=f"Greenhouse {n}", device_id=f"AC5-{n:02d}")
    for n in range(2, 13)
]


@pytest.fixture
def settings(settings):
    entry = {"lan_port": LAN_PORT, "lan_hosts": [LAN_HOST]}
    return settings.model_copy(update={**entry, "multi_user": True, "greenhouses": HOUSES})


@pytest_asyncio.fixture
async def site(world):
    runtime = await world.boot()
    for name, role in (("alice", "user"), ("bob", "user"), ("root", "admin")):
        runtime.operators.add(name, SECRET, role)
    app = create_app(world.settings, bridge=runtime.bridge, workbench=runtime.workbench())
    clients = {}
    for name in ("alice", "bob"):
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE)
        response = await client.post(
            "/wb/login", json={"name": name, "secret": SECRET}, headers=PAGE
        )
        assert response.status_code == 200
        clients[name] = client
    yield runtime, clients
    for client in clients.values():
        await client.aclose()


async def post(client, path: str, body: dict | None = None) -> dict:
    response = await client.post(path, json=body or {}, headers=PAGE)
    assert response.status_code == 200, f"{path}: {response.status_code} {response.text}"
    return response.json()


async def _alice_designs(world, runtime, alice) -> str:
    await post(alice, "/wb/greenhouses/lock", {"greenhouse_ids": ["gh-01"]})
    runtime.control.approve_safety(make_safety(), "alice")
    project = (await post(alice, "/wb/projects", {"name": "lettuce"}))["project_id"]
    protocol = make_protocol(project_id=project)
    await post(alice, "/wb/protocols", {"protocol": protocol.model_dump(mode="json")})
    round_id = (
        await post(alice, "/wb/rounds", {"project_id": project, "protocol_id": protocol.id})
    )["round_id"]
    sheet = world.sheet(project, protocol_id=protocol.id, protocol_version=protocol.version)
    body = {"round_id": round_id, "run_sheet": sheet.model_dump(mode="json")}
    await post(alice, "/wb/drafts/run-sheet", body)
    return project


async def test_two_users_in_parallel(world, site):
    runtime, clients = site
    alice, bob = clients["alice"], clients["bob"]

    project = await _alice_designs(world, runtime, alice)
    await post(bob, "/wb/greenhouses/lock", {"greenhouse_ids": ["gh-02", "gh-03", "gh-04"]})
    review = (await alice.get(f"/wb/stages/{STAGE}/run-sheet")).json()
    await post(
        alice, f"/wb/stages/{STAGE}/approve", {"expected_digest": review["run_sheet_digest"]}
    )
    await post(alice, f"/wb/stages/{STAGE}/start")
    await world.run_until_ended(runtime)

    assert (await bob.get("/wb/projects")).json()["projects"] == []
    assert (await bob.get(f"/wb/stages/{STAGE}")).status_code == 409
    assert (await bob.get(f"/wb/projects/{project}")).status_code == 409
    await post(bob, "/wb/reauth", {"secret": SECRET})  # the stage took simulated hours
    taken = await bob.post("/wb/greenhouses/lock", json={"greenhouse_ids": ["gh-01"]}, headers=PAGE)
    assert taken.status_code == 409 and taken.json()["detail"]["code"] == "lock_taken"

    await post(alice, "/wb/greenhouses/gh-01/release")

    assert (await post(bob, "/wb/greenhouses/lock", {"greenhouse_ids": ["gh-01"]})) == {
        "locked": ["gh-01"]
    }
    assert runtime.workflow.store.care_holder("SIMULATED") is None  # nothing writes for alice


async def test_multi_user_off_is_unchanged(world):
    world.settings = world.settings.model_copy(update={"multi_user": False})
    runtime = await world.boot()

    assert runtime.access_parts is None and runtime.workflow.access is None
    await world.approved_stage(runtime)  # the single-user flow, as before
    assert runtime.workflow.stage(STAGE).state.value == "running"
