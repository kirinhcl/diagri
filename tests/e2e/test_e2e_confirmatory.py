"""A DiAGRI round that ends in a confirmatory conclusion, on the simulated AC5.

The operator steps are HTTP requests to ``/wb`` on the app ``serve`` builds; the model steps are
passes of the model-role loop with a scripted client. The code sandbox is a deterministic fake, so
the flow needs no ``sandbox-exec``. Four rounds of one protocol run in turn (the design alternates
the treatments, so the comparison has two independent replicates of each):

1. the operator freezes the analysis script before any stage has started;
2. once a stage has started, freezing is refused (architecture §6.5);
3. each round's data is frozen by the researcher;
4. a report is refused while the operator has not run the frozen analysis on the snapshots;
5. the operator runs the analysis once per snapshot;
6. the researcher publishes: the report is confirmatory and the round is delivered.
"""

import httpx
import pytest
import pytest_asyncio
from e2e_support import ROUND_LIGHT, World, light_schedule

from growbridge.agents.llm import ToolCall
from growbridge.api import create_app
from growbridge.archive.models import Budget, ResearchTask
from growbridge.research.sandbox import SandboxResult
from growbridge.sim.fixtures import make_protocol, make_safety
from growbridge.sim.llm import ScriptedClient, text_reply, tool_reply

LAN_HOST = "lan.test"
LAN_PORT = 9443
BASE = f"http://{LAN_HOST}:{LAN_PORT}"
PAGE = {"Origin": BASE, "x-growbridge-ui": "1"}
OPERATOR = "alice"
SECRET = "correct horse battery staple"  # obviously fake
SCRIPT = "print('pre-registered analysis')\n"
VALUES = (5.0, 4.0, 4.2, 5.5)  # rounds 1-4: high, control, control, high
BEAT_SECONDS = 60.0
MAX_BEATS = 40


class AnalysisSandbox:
    """Stands in for the code sandbox: records what it ran, writes one output file."""

    def __init__(self):
        self.runs: list[bytes] = []

    def run(self, script, snapshot_dir, out_dir, timeout):
        self.runs.append(script.read_bytes())
        (out_dir / "result.txt").write_text("effect: 1.15")
        return SandboxResult(0, "effect: 1.15", "", False)


@pytest.fixture
def settings(settings):
    return settings.model_copy(update={"lan_port": LAN_PORT, "lan_hosts": [LAN_HOST]})


@pytest_asyncio.fixture
async def site(world: World):
    runtime = await world.boot()
    runtime.operators.add(OPERATOR, SECRET)
    runtime.runner.sandbox = AnalysisSandbox()
    app = create_app(world.settings, bridge=runtime.bridge, workbench=runtime.workbench())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client:
        yield runtime, client


async def send(client, method: str, path: str, body: dict | None = None, expect: int = 200):
    if method == "GET":
        response = await client.get(path)
    else:
        response = await client.post(path, json=body or {}, headers=PAGE)
    assert response.status_code == expect, f"{path}: {response.status_code} {response.text}"
    return response.json()


async def reauthenticate(client) -> None:
    """Approving, freezing and running need a re-authentication within the last 300 seconds."""
    await send(client, "POST", "/wb/reauth", {"secret": SECRET})


def call(name: str, **fields) -> ToolCall:
    return ToolCall(id="c1", name=name, input=fields)


def researcher_task(project_id: str, event: str) -> ResearchTask:
    return ResearchTask(
        id=f"task-{event}",
        project_id=project_id,
        question="does more light speed up canopy growth?",
        owner_role="researcher",
        budget=Budget(max_calls=10, max_cost=5.0),
        trigger_event_id=event,
        correlation_id="corr-1",
    )


async def design(client) -> tuple[str, object, list[str]]:
    """Log in, approve the safety configuration, then the project, protocol and four rounds."""
    await send(client, "POST", "/wb/login", {"name": OPERATOR, "secret": SECRET})
    safety = {"config": make_safety().model_dump(mode="json")}
    await send(client, "POST", "/wb/safety/approve", safety)
    project = (await send(client, "POST", "/wb/projects", {"name": "light series"}))["project_id"]
    protocol = make_protocol(project_id=project)
    await send(client, "POST", "/wb/protocols", {"protocol": protocol.model_dump(mode="json")})
    budget = {"max_calls": 50, "max_cost": 100.0}
    await send(client, "POST", f"/wb/projects/{project}/budget", budget)
    rounds = []
    for _ in range(4):
        wanted = {"project_id": project, "protocol_id": protocol.id}
        rounds.append((await send(client, "POST", "/wb/rounds", wanted))["round_id"])
    return project, protocol, rounds


async def run_stage(world, runtime, client, project, protocol, round_id, number: int) -> str:
    """File, approve and start one stage, run it to its end, record its measurement."""
    stage, experiment = f"stage-{number}", f"experiment-{number}"
    sheet = world.sheet(
        project,
        id=f"sheet-{number}",
        stage_id=stage,
        experiment_id=experiment,
        protocol_id=protocol.id,
        protocol_version=protocol.version,
        timed_actions=light_schedule(ROUND_LIGHT[number]),  # the round's allocated treatment
    )
    draft = {"round_id": round_id, "run_sheet": sheet.model_dump(mode="json")}
    await send(client, "POST", "/wb/drafts/run-sheet", draft)
    await reauthenticate(client)
    sheet = await send(client, "GET", f"/wb/stages/{stage}/run-sheet")
    digest = {"expected_digest": sheet["run_sheet_digest"]}
    await send(client, "POST", f"/wb/stages/{stage}/approve", digest)
    await send(client, "POST", f"/wb/stages/{stage}/start")
    for _ in range(MAX_BEATS):
        await world.beat(runtime, BEAT_SECONDS)
        view = await send(client, "GET", f"/wb/stages/{stage}")
        if view["state"] == "ended":
            break
    else:
        raise AssertionError("the stage did not end")
    measurement = {
        "id": f"m-{number}",
        "experiment_id": experiment,
        "batch": "batch-1",
        "plant_id": "plant-1",
        "layout_version": "layout-1",
        "measured_at": view["started_at"] + 10,
        "position": "tent-1",
        "method": "image",
        "metric": "canopy_area_growth",
        "value": VALUES[number - 1],
        "unit": "cm2/d",
    }
    await send(client, "POST", "/wb/measurements", measurement)
    return stage


async def freeze_data(runtime, project, round_id, stage: str, number: int) -> None:
    task = researcher_task(project, f"ev-freeze-{number}")
    runtime.tasks.create(task)
    freeze = call("freeze_dataset", task_id=task.id, stage_id=stage, round_id=round_id)
    client = ScriptedClient([tool_reply(freeze), text_reply("frozen")])
    assert await runtime.run_agents(client) == 1


def publish_call(task_id: str, protocol, snapshot_ids: list[str], round_id: str) -> ToolCall:
    return call(
        "publish_research_report",
        task_id=task_id,
        protocol_id=protocol.id,
        treatment_id="high",
        snapshots=[{"snapshot_id": s, "round": n} for n, s in enumerate(snapshot_ids, 1)],
        evidence_chain=["measurements m-1 to m-4"],
        limitations=["one cultivar"],
        next_round="repeat with a second cultivar",
        unresolved=[],
        round_id=round_id,
    )


async def test_a_round_ends_in_a_confirmatory_conclusion_through_the_workbench(world, site):
    runtime, client = site
    project, protocol, rounds = await design(client)
    path = f"/wb/protocols/{protocol.id}/analysis"

    # 1. the operator freezes the script while nothing has started
    frozen = await send(client, "POST", path, {"project_id": project, "script": SCRIPT})
    assert frozen["version"] == protocol.version and frozen["script_sha256"]

    # 2.+3. the stages run in turn; once one has started the script can no longer be frozen
    for number, round_id in enumerate(rounds, 1):
        stage = await run_stage(world, runtime, client, project, protocol, round_id, number)
        if number == 1:
            await reauthenticate(client)
            late = {"project_id": project, "script": SCRIPT}
            refused = await send(client, "POST", path, late, expect=409)
            assert (
                refused["detail"]["code"] == "state"
                and "already started" in refused["detail"]["message"]
            )
        await freeze_data(runtime, project, round_id, stage, number)
    state = await send(client, "GET", f"{path}?project_id={project}")
    snapshot_ids = [item["snapshot_id"] for item in state["snapshots"]]
    assert state["started"] is True and len(snapshot_ids) == 4
    assert {item["run_status"] for item in state["snapshots"]} == {"none"}

    # 4. a report is refused until the frozen analysis has run on every snapshot
    task = researcher_task(project, "ev-early")
    runtime.tasks.create(task)
    attempt = publish_call(task.id, protocol, snapshot_ids, rounds[-1])
    early = ScriptedClient([tool_reply(attempt), text_reply("waiting")])
    assert await runtime.run_agents(early) == 1
    refusal = early.requests[-1]["messages"][-1]["content"][-1]
    assert refusal["is_error"] and "POST /wb/analysis/runs" in refusal["content"]
    assert runtime.archive.artifacts(task.id) == ()
    assert (await send(client, "GET", f"/wb/rounds/{rounds[-1]}"))["state"] == "analysis"

    # 5. the operator runs the analysis once per snapshot (a second run of one is refused)
    await reauthenticate(client)
    for snapshot_id in snapshot_ids:
        body = {"project_id": project, "protocol_id": protocol.id, "snapshot_id": snapshot_id}
        done = await send(client, "POST", "/wb/analysis/runs", body)
        assert done["status"] == "succeeded" and done["stdout"] == "effect: 1.15"
    again = {"project_id": project, "protocol_id": protocol.id, "snapshot_id": snapshot_ids[0]}
    repeat = await send(client, "POST", "/wb/analysis/runs", again, expect=403)
    assert repeat["detail"]["code"] == "already_run"
    assert runtime.runner.sandbox.runs == [SCRIPT.encode()] * 4

    # 6. the researcher publishes: confirmatory, and the round is delivered
    final = researcher_task(project, "ev-final")
    runtime.tasks.create(final)
    publish = publish_call(final.id, protocol, snapshot_ids, rounds[-1])
    client_ = ScriptedClient([tool_reply(publish), text_reply("published")])
    assert await runtime.run_agents(client_) == 1
    delivered = await send(client, "GET", f"/wb/rounds/{rounds[-1]}")
    assert delivered["state"] == "delivered"
    artifact = runtime.archive.artifact(delivered["report_artifact_id"])
    assert artifact.label == "confirmatory"
    status = await send(client, "GET", f"{path}?project_id={project}")
    assert {item["run_status"] for item in status["snapshots"]} == {"succeeded"}
