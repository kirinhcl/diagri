"""A research round driven the way ``growbridge serve`` offers it, on the simulated AC5.

Every operator step is an HTTP request to ``/wb`` on the app ``serve`` builds. Every model step is
one pass of the model-role loop (``Runtime.run_agents``, what ``serve`` runs every 30 seconds) with
a scripted client that learns ids the way a model does: from its handoff and its tool results.
Time passes through ``World.beat`` (the tick ``serve`` runs every second). The test never calls a
workflow, task, budget or archive service to move the round or to look at it.
"""

import json

import httpx
import pytest
import pytest_asyncio
from e2e_support import STAGE

from growbridge.agents.dispatch import INTRO
from growbridge.agents.llm import ToolCall
from growbridge.api import create_app
from growbridge.sim.fixtures import make_protocol, make_safety
from growbridge.sim.llm import ScriptedClient, text_reply, tool_reply

LAN_HOST = "lan.test"
LAN_PORT = 9443
BASE = f"http://{LAN_HOST}:{LAN_PORT}"
PAGE = {"Origin": BASE, "x-growbridge-ui": "1"}
OPERATOR = "alice"
SECRET = "correct horse battery staple"  # obviously fake
EXPERIMENT = f"experiment-{STAGE}"
BEAT_SECONDS = 60.0
MAX_BEATS = 40


@pytest.fixture
def settings(settings):
    """The e2e settings plus an on-site entry, so the workbench has an address to log in on."""
    return settings.model_copy(update={"lan_port": LAN_PORT, "lan_hosts": [LAN_HOST]})


@pytest_asyncio.fixture
async def site(world):
    """The runtime and an HTTP client on the app ``serve`` builds from it, on the on-site entry."""
    runtime = await world.boot()
    runtime.operators.add(OPERATOR, SECRET)  # what ``growbridge operator add`` does
    app = create_app(world.settings, bridge=runtime.bridge, workbench=runtime.workbench())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
        yield runtime, client


async def post(client, path: str, body: dict | None = None) -> dict:
    response = await client.post(path, json=body or {}, headers=PAGE)
    assert response.status_code == 200, f"{path}: {response.status_code} {response.text}"
    return response.json()


async def get(client, path: str) -> dict:
    response = await client.get(path)
    assert response.status_code == 200, f"{path}: {response.status_code} {response.text}"
    return response.json()


def call(name: str, **fields) -> ToolCall:
    return ToolCall(id="c1", name=name, input=fields)


def handoff(request: dict) -> dict:
    """The task record a model role is given as its first message."""
    return json.loads(request["messages"][0]["content"].removeprefix(INTRO))


def tool_output(request: dict) -> dict:
    """What the last tool call returned, as the model reads it: JSON inside a data fence."""
    block = request["messages"][-1]["content"][-1]
    assert not block.get("is_error"), block
    fenced = block["content"].split("\n", 2)[2]  # after the opening tag and the notice
    return json.loads(fenced.rsplit("\n", 1)[0])


class ReadingClient(ScriptedClient):
    """A scripted model whose replies may be built from the request it is answering."""

    async def create(self, **request):
        if self._replies and callable(self._replies[0]):
            self._replies[0] = self._replies[0](request)
        return await super().create(**request)


def delegating(to_role: str, goal: str, project_id: str) -> ReadingClient:
    """The orchestrator hands its goal to another role, naming its own task as the parent."""

    def delegate(request: dict):
        task = handoff(request)
        return tool_reply(
            call(
                "delegate_task",
                project_id=project_id,
                to_role=to_role,
                goal=goal,
                budget={"max_calls": 8, "max_cost": 2.5},
                trigger_event_id=f"{task['task_id']}:{to_role}",
                correlation_id=task["correlation_id"],
                evidence_refs=task["evidence_refs"],
                parent_task_id=task["task_id"],
            )
        )

    return ReadingClient([delegate, text_reply("handed on")])


def device_writes(world) -> list:
    return [c for c in world.sim.commands if c["method"] == "setConfigField"]


async def designed(client) -> tuple[str, object, str]:
    """Log in, approve the safety configuration, then project, protocol and round."""
    await post(client, "/wb/login", {"name": OPERATOR, "secret": SECRET})
    await post(client, "/wb/safety/approve", {"config": make_safety().model_dump(mode="json")})
    project = (await post(client, "/wb/projects", {"name": "lettuce light series"}))["project_id"]
    protocol = make_protocol(project_id=project)
    await post(client, "/wb/protocols", {"protocol": protocol.model_dump(mode="json")})
    made = await post(client, "/wb/rounds", {"project_id": project, "protocol_id": protocol.id})
    assert made["state"] == "designing"
    return project, protocol, made["round_id"]


def sheet_json(world, project: str, protocol, **fields) -> dict:
    owner = {"protocol_id": protocol.id, "protocol_version": protocol.version}
    return world.sheet(project, **owner, **fields).model_dump(mode="json")


async def run_stage_to_its_end(world, runtime, client) -> dict:
    for _ in range(MAX_BEATS):
        await world.beat(runtime, BEAT_SECONDS)
        stage = await get(client, f"/wb/stages/{STAGE}")
        if stage["state"] == "ended":
            return stage
    raise AssertionError("the stage did not end")


async def test_round_from_goal_to_delivered_through_http_routes_only(world, site):
    runtime, client = site
    project, protocol, round_id = await designed(client)
    await post(client, f"/wb/projects/{project}/budget", {"max_calls": 50, "max_cost": 100.0})

    # the goal becomes the first orchestrator task, and the orchestrator hands it to the planner
    goal = {"project_id": project, "round_id": round_id, "goal": "does more light speed growth?"}
    assert (await post(client, "/wb/goals", goal))["state"] == "in_progress"
    orchestrator = delegating("planner", "draft a 60 % light run sheet", project)
    assert await runtime.run_agents(orchestrator) == 1

    # the planner validates and files a run sheet: it waits for review, nothing is written
    sheet = sheet_json(world, project, protocol)
    planner = ScriptedClient(
        [
            tool_reply(call("validate_run_sheet", run_sheet=sheet)),
            tool_reply(call("save_plan_draft", round_id=round_id, run_sheet=sheet)),
            text_reply("drafted"),
        ]
    )
    assert await runtime.run_agents(planner) == 1
    view = await get(client, f"/wb/rounds/{round_id}")
    assert view["state"] == "stage_review"
    assert view["stages"] == [{"stage_id": STAGE, "state": "pending_review"}]
    assert device_writes(world) == []

    # the operator reads what is to be approved, approves exactly that, and starts the stage
    review = await get(client, f"/wb/stages/{STAGE}/run-sheet")
    assert review["run_sheet"] == sheet and review["blocking"] is False
    approval = await post(client, f"/wb/stages/{STAGE}/approve")
    assert approval["operator"] == OPERATOR
    assert approval["run_sheet_digest"] == review["run_sheet_digest"]
    assert (await post(client, f"/wb/stages/{STAGE}/start"))["state"] == "running"
    assert (await get(client, f"/wb/rounds/{round_id}"))["state"] == "stage_running"

    # ticks run the stage to its end; no model is called on the way
    stage = await run_stage_to_its_end(world, runtime, client)
    assert (await get(client, f"/wb/rounds/{round_id}"))["state"] == "data_verification"
    assert device_writes(world)

    # the operator records a measurement and asks for the analysis
    measurement = {
        "id": "m-1",
        "experiment_id": EXPERIMENT,
        "batch": "batch-1",
        "plant_id": "plant-1",
        "layout_version": "layout-1",
        "measured_at": stage["started_at"] + 10,
        "position": "tent-1",
        "method": "image",
        "metric": "canopy_area_growth",
        "value": 1.30,
        "unit": "cm2/day",
    }
    assert await post(client, "/wb/measurements", measurement) == {"id": "m-1"}
    analysis = {"project_id": project, "round_id": round_id, "goal": "verify the data and report"}
    await post(client, "/wb/goals", analysis)
    orchestrator = delegating("researcher", "freeze the data and publish the report", project)
    assert await runtime.run_agents(orchestrator) == 1

    # the researcher freezes the data and publishes the report; the round is delivered
    def freeze(request: dict):
        task_id = handoff(request)["task_id"]
        return tool_reply(
            call("freeze_dataset", task_id=task_id, stage_id=STAGE, round_id=round_id)
        )

    def publish(request: dict):
        frozen = tool_output(request)
        assert frozen["complete"] and frozen["round_state"] == "analysis"
        return tool_reply(
            call(
                "publish_research_report",
                task_id=handoff(request)["task_id"],
                protocol_id=protocol.id,
                treatment_id="high",
                snapshots=[{"snapshot_id": frozen["snapshot_id"], "round": 1}],
                evidence_chain=["measurement m-1"],
                limitations=["one round only"],
                next_round="collect the other rounds",
                unresolved=[],
                round_id=round_id,
            )
        )

    researcher = ReadingClient([freeze, publish, text_reply("published")])
    assert await runtime.run_agents(researcher) == 1
    delivered = await get(client, f"/wb/rounds/{round_id}")
    assert delivered["state"] == "delivered"
    assert delivered["snapshot_id"] and delivered["report_artifact_id"]
    alerts = (await get(client, "/wb/alerts"))["alerts"]
    assert [
        alert for alert in alerts if alert["kind"] == "agent_task"
    ] == []  # no model task failed


async def test_operator_steers_a_stopped_round_through_http_routes_only(world, site):
    runtime, client = site
    project, protocol, round_id = await designed(client)
    draft = {"round_id": round_id, "run_sheet": sheet_json(world, project, protocol)}
    await post(client, "/wb/drafts/run-sheet", draft)
    await post(client, f"/wb/stages/{STAGE}/approve")
    await post(client, f"/wb/stages/{STAGE}/start")
    await world.beat(runtime, BEAT_SECONDS)

    # a stopped stage leaves the round waiting, and no new run sheet is taken meanwhile
    assert (await post(client, f"/wb/stages/{STAGE}/stop"))["state"] == "stopped"
    assert (await get(client, f"/wb/rounds/{round_id}"))["awaiting_choice"] == STAGE
    redo = sheet_json(
        world, project, protocol, id="sheet-redo", stage_id="stage-redo", experiment_id="exp-redo"
    )
    blocked = await client.post(
        "/wb/drafts/run-sheet", json={"round_id": round_id, "run_sheet": redo}, headers=PAGE
    )
    assert blocked.status_code == 409

    # the operator chooses to redo the stage, files and starts the new one, then aborts the round
    chosen = await post(client, f"/wb/rounds/{round_id}/choice", {"choice": "redo"})
    assert chosen == {"round_id": round_id, "state": "stage_review"}
    await post(client, "/wb/drafts/run-sheet", {"round_id": round_id, "run_sheet": redo})
    await post(client, "/wb/stages/stage-redo/approve")
    assert (await post(client, "/wb/stages/stage-redo/start"))["right_number"] is not None
    aborted = await post(client, f"/wb/rounds/{round_id}/abort")
    assert aborted == {"round_id": round_id, "state": "aborted"}
    stage = await get(client, "/wb/stages/stage-redo")
    assert stage["state"] == "stopped" and stage["right_number"] is None
    refused = await client.post(f"/wb/rounds/{round_id}/abort", json={}, headers=PAGE)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "state"
