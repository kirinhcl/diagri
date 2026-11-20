"""The model's evidence tools: the query shows status, the proposal is checked, relations are
only proposed.  (Lives beside the other dispatch tests for their ``env`` fixture.)"""

import json

import pytest
from dispatch_helpers import call, script_calls

from growbridge.agents.tools import ROLE_TOOLS
from growbridge.archive.evidence_ledger import EvidenceOrigin
from growbridge.archive.evidence_relations import RelationRequest, record_relation
from growbridge.archive.models import EvidenceCard
from growbridge.sim.llm import ScriptedClient

CARD = {
    "source_class": "paper",
    "citation": "Doe 2024, Journal of Lettuce Light",
    "claim": "lettuce grows faster in warm air",
}
RELATION = {"kind": "supersedes", "card_id": "new", "other_card_id": "old", "reason": "repeats it"}


def _payload(outcome) -> dict:
    assert not outcome.is_error, outcome.content
    return json.loads(outcome.content)


def _add(env, ident: str, **fields) -> None:
    values = {"source_class": "handbook", "citation": "H", "claim": f"claim {ident}", **fields}
    env.archive.add_evidence(EvidenceCard(id=ident, **values))


def _supersede(env, old: str, new: str) -> None:
    request = RelationRequest(kind="supersedes", card_id=new, other_card_id=old, reason="newer")
    record_relation(env.archive, request, "op-1", env.project_id)


async def _query(env, **fields) -> dict:
    return _payload(await env.invoke("planner", "query_evidence", **fields))


async def test_text_search_hides_inactive_cards_and_counts_them(env):
    _add(env, "old", claim="light helps")
    _add(env, "new", claim="light helps more")
    _supersede(env, "old", "new")

    body = await _query(env, text="light")

    assert [c["id"] for c in body["cards"]] == ["new"]
    assert body["cards"][0]["status"] == "active" and body["hidden_inactive"] == 1


async def test_an_inactive_card_by_id_has_no_claim_or_value(env):
    _add(env, "old", value=1.0)
    _add(env, "new")
    _supersede(env, "old", "new")

    body = await _query(env, ids=["old"])

    (card,) = body["cards"]
    assert set(card) == {
        "id",
        "source_class",
        "citation",
        "status",
        "superseded_by",
        "current_replacement",
    }
    assert card["status"] == "superseded" and card["current_replacement"]["card_id"] == "new"


async def test_the_variable_filter_accepts_an_alias(env):
    _add(env, "t", variable="air_temperature")
    _add(env, "h", variable="relative_humidity")

    body = await _query(env, variable="temp")

    assert [c["id"] for c in body["cards"]] == ["t"]
    assert body["cards"][0]["variable"] == "air_temperature"


async def test_another_projects_card_is_unknown_to_the_query(env):
    other, _ = env.other_project()
    _add(env, "theirs")
    origin = EvidenceOrigin(
        card_id="theirs",
        project_id=other,
        round_id="r",
        report_artifact_id="a",
        snapshot_ids=("s",),
        label="exploratory",
        at=0.0,
    )
    env.archive.ledger.add_origin(origin)

    by_id = await _query(env, ids=["theirs"])
    by_text = await _query(env, text="theirs")

    assert by_id["cards"] == [] and by_text["cards"] == []
    assert by_text["hidden_inactive"] == 0


async def test_a_proposed_card_with_an_alias_is_refused(env):
    task = env.task("planner")

    denied = await env.refusal(
        "planner", "propose_evidence_card", task_id=task.id, **CARD, variable="temp"
    )

    assert denied.reason == "evidence_card_invalid" and "air_temperature" in str(denied)
    assert env.archive.evidence_entries() == ()


async def test_a_proposed_card_keeps_its_new_fields(env):
    task = env.task("planner")
    fields = {**CARD, "variable": "air_temperature", "value": 22.0, "unit": "C"}

    outcome = await env.invoke(
        "planner", "propose_evidence_card", task_id=task.id, growth_stage="seedling", **fields
    )

    (entry,) = env.archive.evidence_entries()
    assert entry.card.id == _payload(outcome)["card_id"]
    assert entry.card.variable == "air_temperature" and entry.card.growth_stage == "seedling"


async def test_a_proposed_relation_is_pending_and_names_the_project(env):
    task = env.task("planner")
    _add(env, "old")
    _add(env, "new")

    outcome = await env.invoke("planner", "propose_evidence_relation", task_id=task.id, **RELATION)

    body = _payload(outcome)
    record = env.archive.ledger.record(body["relation_id"])
    assert body["state"] == "pending" and record.state == "pending"
    assert record.relation.proposed_in == task.project_id
    assert record.relation.source == "model:planner"


async def test_a_refused_relation_carries_its_registered_code(env):
    task = env.task("planner")
    _add(env, "a")

    denied = await env.refusal(
        "planner",
        "propose_evidence_relation",
        task_id=task.id,
        **{**RELATION, "card_id": "a", "other_card_id": "a"},
    )

    assert denied.reason == "relation_self" and denied.code == "param"


async def test_only_a_planner_task_may_propose_a_relation(env):
    task = env.task("researcher")

    denied = await env.refusal("planner", "propose_evidence_relation", task_id=task.id, **RELATION)

    assert denied.reason == "wrong_task_kind"


@pytest.mark.parametrize("reason", ["r" * 501, "   "])
async def test_a_blank_or_too_long_relation_reason_is_refused_with_the_limit(env, reason):
    task = env.task("planner")
    _add(env, "old")
    _add(env, "new")

    outcome = await env.invoke(
        "planner", "propose_evidence_relation", task_id=task.id, **{**RELATION, "reason": reason}
    )

    assert outcome.is_error and "failed" not in outcome.content
    assert env.archive.ledger.proposed_by(task.id) == 0


class FakeSearch:
    def search(self, query: str, limit: int = 5) -> list[dict]:
        return [{"title": "Handbook", "url": "https://example.test/h", "snippet": "verify it"}]


async def test_a_planner_that_read_the_web_has_no_relation_tool(env):
    task = env.task("planner")
    client = ScriptedClient(script_calls(call("search_and_verify_sources", query="lettuce light")))

    await env.dispatcher(client, env.make_deps(search=FakeSearch())).run_task(task.id)

    later = {tool["name"] for tool in client.requests[1]["tools"]}
    assert "propose_evidence_relation" not in later and "query_evidence" in later


def test_the_relation_tool_is_a_planner_write_tool(env):
    assert "propose_evidence_relation" in ROLE_TOOLS["planner"]
    assert "propose_evidence_relation" not in ROLE_TOOLS["researcher"]
    by_name = {tool.name: tool for tool in env.tools()["planner"]}
    assert by_name["propose_evidence_relation"].writes
