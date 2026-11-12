"""The planner can query and propose evidence cards; it can never produce a verified one.

A proposal is stored unverified with the planner and the bound task as its source. Only an
operator's verification record (``Archive.verify_evidence``) changes that.
"""

import json

import pytest
from dispatch_helpers import call, script_calls

from growbridge.agents.tools import ROLE_TOOLS
from growbridge.sim.llm import ScriptedClient

CARD = {
    "source_class": "paper",
    "citation": "Doe 2024, Journal of Lettuce Light",
    "claim": "200 umol m-2 s-1 raises leaf area",
    "value": 200.0,
    "unit": "umol m-2 s-1",
}


class FakeSearch:
    def search(self, query: str, limit: int = 5) -> list[dict]:
        return [{"title": "Handbook", "url": "https://example.test/h", "snippet": "verify it"}]


def _payload(outcome) -> dict:
    assert not outcome.is_error, outcome.content
    return json.loads(outcome.content)


async def _propose(env, task_id: str, **extra):
    fields = {**CARD, **extra}
    return await env.invoke("planner", "propose_evidence_card", task_id=task_id, **fields)


def test_both_tools_are_in_the_planners_list_and_only_there():
    assert {"query_evidence", "propose_evidence_card"} <= ROLE_TOOLS["planner"]
    assert "propose_evidence_card" not in ROLE_TOOLS["researcher"]
    assert "propose_evidence_card" not in ROLE_TOOLS["orchestrator"]
    assert "query_evidence" in ROLE_TOOLS["researcher"]
    assert "query_evidence" not in ROLE_TOOLS["orchestrator"]


def test_the_proposal_tool_writes_and_the_query_tool_does_not(env):
    by_name = {tool.name: tool for tool in env.tools()["planner"]}

    assert by_name["propose_evidence_card"].writes and not by_name["query_evidence"].writes


async def test_a_proposed_card_is_stored_unverified_with_the_planner_as_its_source(env):
    task = env.task("planner")

    body = _payload(await _propose(env, task.id))

    (entry,) = env.archive.evidence_entries()
    assert body["card_id"] == entry.card.id and body["verified"] is False
    assert entry.card.verified is False and entry.verified_by is None
    assert entry.source == "model:planner" and entry.task_id == task.id
    assert entry.card.citation == CARD["citation"] and entry.card.value == 200.0
    assert env.archive.evidence_verification(entry.card.id) is None


@pytest.mark.parametrize(
    "extra",
    [
        {"verified": True},
        {"verified_by": "alice"},
        {"source": "operator:alice"},
        {"id": "card-chosen"},
        {"role": "operator"},
        {"approved": True},
    ],
)
async def test_a_proposal_cannot_claim_verification_a_source_or_an_id(env, extra):
    task = env.task("planner")

    outcome = await _propose(env, task.id, **extra)

    assert outcome.is_error and "invalid input" in outcome.content
    assert env.archive.evidence_entries() == ()


async def test_the_card_id_is_made_by_the_server(env):
    task = env.task("planner")

    first = _payload(await _propose(env, task.id))
    second = _payload(await _propose(env, task.id))

    assert first["card_id"] != second["card_id"]


@pytest.mark.parametrize(
    "fields",
    [
        {"citation": ""},
        {"citation": "   "},
        {"citation": "x" * 501},
        {"claim": ""},
        {"source_class": "blog"},
        {"value": float("nan")},
        {"value": float("inf")},
        {"unit": "u" * 41},
    ],
)
async def test_an_unacceptable_proposal_is_refused_and_stores_nothing(env, fields):
    task = env.task("planner")

    outcome = await _propose(env, task.id, **fields)

    assert outcome.is_error and env.archive.evidence_entries() == ()


async def test_a_proposal_needs_the_running_task_not_any_task(env):
    mine = env.task("planner", "ev-mine")
    other = env.task("planner", "ev-other")

    outcome = await env.invoke_as(
        mine.id, "planner", "propose_evidence_card", task_id=other.id, **CARD
    )

    assert outcome.is_error and "denied (scope)" in outcome.content
    assert env.archive.evidence_entries() == ()


async def test_a_proposal_outside_a_dispatched_run_is_refused(env):
    task = env.task("planner")

    outcome = await env.invoke_unbound("planner", "propose_evidence_card", task_id=task.id, **CARD)

    assert outcome.is_error and "denied (scope)" in outcome.content
    assert env.archive.evidence_entries() == ()


async def test_only_a_planner_task_may_propose(env):
    task = env.task("researcher")

    outcome = await _propose(env, task.id)

    assert outcome.is_error and "denied (scope)" in outcome.content
    assert env.archive.evidence_entries() == ()


@pytest.mark.parametrize("role", ["researcher", "orchestrator"])
async def test_the_other_roles_cannot_call_the_proposal_tool(env, role):
    task = env.task(role)

    outcome = await env.invoke(role, "propose_evidence_card", task_id=task.id, **CARD)

    assert outcome.is_error and env.archive.evidence_entries() == ()


async def test_a_task_may_propose_only_a_limited_number_of_cards(env):
    task = env.task("planner")
    for number in range(20):
        _payload(await _propose(env, task.id, claim=f"claim {number}"))

    outcome = await _propose(env, task.id, claim="one too many")

    assert outcome.is_error and "denied (quota)" in outcome.content
    assert len(env.archive.evidence_entries()) == 20


async def test_a_scripted_planner_run_stores_its_proposal_unverified(env):
    task = env.task("planner")
    request = call("propose_evidence_card", task_id=task.id, **CARD)
    client = ScriptedClient(script_calls(request))

    run = await env.dispatcher(client).run_task(task.id)

    assert run is not None and not run.tool_calls[0].is_error
    (entry,) = env.archive.evidence_entries()
    assert entry.card.verified is False and entry.source == "model:planner"


async def test_a_planner_that_read_the_web_can_no_longer_propose(env):
    task = env.task("planner")
    client = ScriptedClient(script_calls(call("search_and_verify_sources", query="lettuce light")))

    await env.dispatcher(client, env.make_deps(search=FakeSearch())).run_task(task.id)

    later = {tool["name"] for tool in client.requests[1]["tools"]}
    assert "propose_evidence_card" not in later and "query_evidence" in later


async def test_the_planner_queries_cards_with_their_verification_state(env):
    task = env.task("planner")
    card_id = _payload(await _propose(env, task.id))["card_id"]

    before = _payload(await env.invoke("planner", "query_evidence", text="leaf area"))
    env.archive.verify_evidence(card_id, "alice")
    after = _payload(await env.invoke("planner", "query_evidence", text="leaf area"))

    assert [c["verified"] for c in before["cards"]] == [False]
    assert [c["verified"] for c in after["cards"]] == [True]


async def test_the_proposed_card_can_be_cited_and_is_flagged_until_verified(env):
    task = env.task("planner")
    card_id = _payload(await _propose(env, task.id))["card_id"]
    cited = {"id": "light-on", "channel": "light", "at": "06:00", "level": 60, "evidence": card_id}
    sheet = env.sheet_json(timed_actions=[cited])

    unverified = _payload(await env.invoke("planner", "validate_run_sheet", run_sheet=sheet))
    env.archive.verify_evidence(card_id, "alice")
    verified = _payload(await env.invoke("planner", "validate_run_sheet", run_sheet=sheet))

    assert "unverified_source" in {f["code"] for f in unverified["findings"]}
    assert "unverified_source" not in {f["code"] for f in verified["findings"]}


async def test_a_model_cannot_propose_a_local_card(env):
    """A model cannot have taken a local measurement: only an operator records one."""
    task = env.task("planner")

    outcome = await _propose(env, task.id, source_class="local", citation="our tent log")

    assert outcome.is_error and "denied (param)" in outcome.content
    assert "operator" in outcome.content and "local measurement" in outcome.content
    assert env.archive.evidence_entries() == ()


async def test_a_refused_local_proposal_does_not_use_up_the_tasks_proposals(env):
    task = env.task("planner")
    await _propose(env, task.id, source_class="local")

    assert env.archive.evidence_count_from(task.id) == 0


async def test_a_local_card_without_a_verification_is_flagged_in_the_plan_check(env):
    """Even a card that got into the archive as unverified local evidence earns no exemption."""
    from growbridge.archive.models import EvidenceCard

    seeded = EvidenceCard(id="card-l", source_class="local", citation="tent log", claim="par 180")
    env.archive.add_evidence(seeded, source="model:planner", task_id="task-1")
    cited = {"id": "light-on", "channel": "light", "at": "06:00", "level": 60, "evidence": "card-l"}
    sheet = env.sheet_json(timed_actions=[cited])

    body = _payload(await env.invoke("planner", "validate_run_sheet", run_sheet=sheet))

    assert "unverified_source" in {f["code"] for f in body["findings"]}
