"""Evidence stops being valid, end to end (evidence-validity design 2026-11-19, section 7).

A feedback rule cites a handbook card. A planner proposes that a paper supersedes it; the operator
confirms over HTTP. From then on a submission citing the handbook card is blocked with a pointer
to the paper, a stage that already runs on it carries on and the daily report names it, and a
round card whose snapshot is corrected later blocks the sheets that cite it.
"""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest_asyncio
from e2e_support import OPERATOR as DEVICE_OPERATOR
from e2e_support import STAGE, light_schedule
from test_e2e_agents import call, task

from growbridge.api import create_app
from growbridge.archive.ids import file_digest
from growbridge.archive.models import Artifact, Budget, EvidenceCard, Snapshot
from growbridge.planning.evidence_validity import GATE_CODES
from growbridge.ports import Actor
from growbridge.sim.fixtures import humidity_rule, make_protocol, make_safety
from growbridge.sim.llm import ScriptedClient, text_reply, tool_reply
from growbridge.workflow.states import RoundState, StageState
from growbridge.workflow.store import StageRow

BASE = "http://lan.test:9443"
PAGE = {"Origin": BASE, "x-growbridge-ui": "1"}
OPERATOR, SECRET = "alice", "correct horse battery staple"  # obviously fake
DAY, HOUR = 86400.0, 3600.0


@pytest_asyncio.fixture
async def site(world):
    """The runtime and an HTTP client on the app ``serve`` builds, on the on-site entry."""
    world.settings = world.settings.model_copy(update={"lan_port": 9443, "lan_hosts": ["lan.test"]})
    runtime = await world.boot()
    runtime.operators.add(OPERATOR, SECRET)
    app = create_app(world.settings, bridge=runtime.bridge, workbench=runtime.workbench())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client:
        yield runtime, client


async def post(client, path: str, body: dict | None = None) -> dict:
    response = await client.post(path, json=body or {}, headers=PAGE)
    assert response.status_code == 200, f"{path}: {response.status_code} {response.text}"
    return response.json()


def add_card(runtime, ident: str, source_class: str, claim: str) -> None:
    card = EvidenceCard(id=ident, source_class=source_class, citation=ident, claim=claim)
    runtime.archive.add_evidence(card, verified_by="op-1")


def project_with_protocol(runtime, world, name: str, protocol_id: str):
    flow = runtime.workflow
    project = flow.create_project(name, world.operator)
    protocol = make_protocol(id=protocol_id, project_id=project)
    flow.save_protocol(protocol, world.operator)
    return project, protocol


def sheet_citing(world, project: str, protocol, card_id: str, round_no: int, **fields):
    """A sheet for ``protocol``'s round ``round_no`` whose humidity rule cites ``card_id``."""
    light = {1: 70, 2: 40}[round_no]
    return world.sheet(
        project,
        experiment_id=f"exp-{project}",
        protocol_id=protocol.id,
        protocol_version=protocol.version,
        timed_actions=light_schedule(light),
        feedback_rules=(humidity_rule(evidence=card_id, validity_seconds=120),),
        **fields,
    )


def blocking(findings) -> list:
    return [f for f in findings if f.blocking and f.code in GATE_CODES]


def _ended_stage(world, runtime, project: str, round_id: str) -> None:
    """Round ``round_id`` of ``project`` ran one stage, which has ended."""
    store, now = runtime.workflow.store, world.clock.now()
    sheet = world.sheet(project, id="sheet-done", stage_id="stage-done", experiment_id="exp-done")
    store.put_run_sheet(sheet, round_id, now)
    row = StageRow(
        stage_id="stage-done",
        round_id=round_id,
        project_id=project,
        experiment_id="exp-done",
        device_id=str(runtime.settings.device),
        run_sheet_id=sheet.id,
        run_sheet_version=sheet.version,
        state=StageState.ENDED,
        started_at=now - 5 * DAY,
        state_at=now - HOUR,
        recovery_number=0,
    )
    store.add_stage(row)


def _snapshot(world, runtime) -> None:
    """Snapshot snap-1 of the ended stage's experiment, built from measurement m-1."""
    snap = Snapshot(
        id="snap-1",
        experiment_id="exp-done",
        version=1,
        created_at=world.clock.now(),
        manifest_sha256="0" * 64,
        complete=True,
        coverage=1.0,
    )
    runtime.archive.save_snapshot(snap, ["m-1"])


def _report(world, runtime) -> Artifact:
    """A confirmatory report with a conclusion, resting on snapshot snap-1."""
    path = world.settings.data_dir / "report-done.json"
    body = {"label": "confirmatory", "conclusion": "more light speeds up canopy growth"}
    path.write_text(json.dumps({**body, "evidence_chain": ["snapshot:snap-1"], "holdout_id": None}))
    report = Artifact(
        id="art-done",
        task_id="task-done",
        kind="research_report",
        path=str(path),
        sha256=file_digest(path),
        label="confirmatory",
        snapshot_id="snap-1",
    )
    runtime.archive.add_artifact(report)
    return report


def deliver(world, runtime, project: str, round_id: str) -> None:
    """Round 1 of ``project`` ended and was delivered with a report resting on snapshot snap-1,
    which is built from measurement m-1."""
    _ended_stage(world, runtime, project, round_id)
    _snapshot(world, runtime)
    report = _report(world, runtime)
    store = runtime.workflow.store
    store.update_round(round_id, state=RoundState.DELIVERED, report_artifact_id=report.id)


async def _a_stage_runs_citing_the_handbook(world, runtime, model) -> str:
    """Step 1: a stage of project "running" runs on a rule that cites the handbook card."""
    flow = runtime.workflow
    running, protocol = project_with_protocol(runtime, world, "running", "proto-run")
    first = flow.create_round(running, protocol.id, world.operator)
    cited = sheet_citing(world, running, protocol, "handbook-h", 1, stage_id=STAGE)
    findings = flow.submit_run_sheet(first, cited, model)
    assert not [f for f in findings if f.blocking], findings
    flow.approve(STAGE, world.operator)
    await flow.start_stage(STAGE, world.operator)
    return running


async def _the_planner_proposes(runtime, client, running: str) -> dict:
    """Step 2a: the planner proposes that the paper supersedes the handbook card; it waits."""
    runtime.tasks.create(task(running, "planner", "ev-rel"))
    proposal = call(
        "propose_evidence_relation",
        task_id="task-ev-rel",
        kind="supersedes",
        card_id="paper-p",
        other_card_id="handbook-h",
        reason="the paper repeats the trial at higher light",
    )
    runtime.budget.set(running, Budget(max_calls=50, max_cost=100.0))
    model_client = ScriptedClient([tool_reply(proposal), text_reply("proposed")])
    assert await runtime.run_agents(model_client) == 1
    path = f"/wb/evidence/relations?project_id={running}"
    (pending,) = (await client.get(path)).json()["relations"]
    assert pending["state"] == "pending"
    return pending


async def _nothing_changes_until_the_operator_confirms(world, runtime, client, pending, model):
    """Step 2b: until the operator confirms, another project's sheet citing the card passes."""
    flow = runtime.workflow
    other, protocol = project_with_protocol(runtime, world, "other", "proto-other")
    second = flow.create_round(other, protocol.id, world.operator)
    open_sheet = sheet_citing(
        world, other, protocol, "handbook-h", 1, id="sheet-open", stage_id="stage-open"
    )
    assert not blocking(flow.submit_run_sheet(second, open_sheet, model))
    review = f"/wb/evidence/relations/{pending['relation']['id']}/review"
    confirmed = await post(client, review, {"decision": "confirmed", "note": "checked the paper"})
    assert confirmed["state"] == "confirmed"
    return other, protocol, second


def _the_next_submission_is_blocked(world, runtime, other_round, model) -> None:
    """Step 3: the next submission that cites the handbook card is blocked and names the paper."""
    other, protocol, second = other_round
    retry = sheet_citing(
        world, other, protocol, "handbook-h", 1, id="sheet-retry", stage_id="stage-retry"
    )
    (finding,) = blocking(runtime.workflow.submit_run_sheet(second, retry, model))
    assert finding.code == "superseded_source"
    assert finding.params["card_id"] == "handbook-h"
    assert finding.params["replacement_id"] == "paper-p"
    assert runtime.workflow.store.find_stage("stage-retry") is None


def _the_running_stage_goes_on_and_the_report_says_so(world, runtime) -> None:
    """Step 4: the stage that already runs on it goes on, and the daily report says what is
    stale."""
    flow = runtime.workflow
    assert flow.stage(STAGE).state is StageState.RUNNING
    zone = ZoneInfo(runtime.settings.report_timezone)
    today = datetime.fromtimestamp(world.clock.now(), zone).date()
    text = runtime._report_text(flow.stage(STAGE), today)
    assert "Evidence no longer valid:" in text
    assert "card handbook-h is superseded; use paper-p" in text


async def _a_corrected_round_card_blocks(world, runtime, client, model) -> None:
    """Step 5: a delivered round becomes a card; correcting its data invalidates the card."""
    flow = runtime.workflow
    finished, protocol = project_with_protocol(runtime, world, "finished", "proto-done")
    done = flow.create_round(finished, protocol.id, world.operator)
    deliver(world, runtime, finished, done)
    converted = await post(client, f"/wb/rounds/{done}/evidence", {})
    assert converted["verified"] is True and converted["label"] == "confirmatory"
    card_id = converted["card_id"]
    next_round = flow.create_round(finished, protocol.id, world.operator)
    based = sheet_citing(
        world, finished, protocol, card_id, 2, id="sheet-next", stage_id="stage-next"
    )
    assert not blocking(flow.submit_run_sheet(next_round, based, model))
    runtime.archive.mark_dependents_invalid("m-1")
    again = sheet_citing(
        world, finished, protocol, card_id, 2, id="sheet-again", stage_id="stage-again"
    )
    (stale,) = blocking(flow.submit_run_sheet(next_round, again, model))
    assert stale.code == "dependency_invalid_source"
    assert stale.params["card_id"] == card_id


async def test_a_superseded_card_blocks_new_sheets_and_a_corrected_round_card_does_too(world, site):
    runtime, client = site
    model = Actor(kind="model", id="planner")
    await post(client, "/wb/login", {"name": OPERATOR, "secret": SECRET})
    runtime.control.approve_safety(make_safety(), DEVICE_OPERATOR)
    add_card(runtime, "handbook-h", "handbook", "light above 300 umol is enough")
    add_card(runtime, "paper-p", "paper", "light above 500 umol is needed")

    running = await _a_stage_runs_citing_the_handbook(world, runtime, model)  # 1
    pending = await _the_planner_proposes(runtime, client, running)  # 2
    other_round = await _nothing_changes_until_the_operator_confirms(
        world, runtime, client, pending, model
    )
    _the_next_submission_is_blocked(world, runtime, other_round, model)  # 3
    _the_running_stage_goes_on_and_the_report_says_so(world, runtime)  # 4
    await _a_corrected_round_card_blocks(world, runtime, client, model)  # 5
