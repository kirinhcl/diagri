"""The workbench routes that record, review, withdraw and list relations between evidence cards."""

import pytest
from workbench_support import Bench

from growbridge.archive.evidence_ledger import EvidenceOrigin
from growbridge.archive.evidence_relations import RelationRequest, propose_relation
from growbridge.archive.models import EvidenceCard

RELATIONS = "/wb/evidence/relations"


def card(bench, ident: str, project: str | None = None) -> str:
    bench.archive.add_evidence(
        EvidenceCard(id=ident, source_class="paper", citation="Doe", claim=ident)
    )
    if project is not None:
        bench.archive.ledger.add_origin(
            EvidenceOrigin(
                card_id=ident,
                project_id=project,
                round_id="r-" + ident,
                report_artifact_id="art-" + ident,
                snapshot_ids=("s",),
                label="exploratory",
                at=0.0,
            )
        )
    return ident


def record(bench, client, kind="contradicts", card_id="a", other="b", reason="why"):
    body = {"kind": kind, "card_id": card_id, "reason": reason}
    if other is not None:
        body["other_card_id"] = other
    return bench.post(client, RELATIONS, body)


def propose(bench, kind, card_id, other, project="P", task="t1"):
    request = RelationRequest(
        kind=kind, card_id=card_id, other_card_id=other, reason="model reason"
    )
    return propose_relation(bench.archive, request, task, project).relation.id


@pytest.fixture
def cards(bench):
    for ident in ("a", "b", "c"):
        card(bench, ident)


def test_an_operator_records_a_confirmed_relation(bench, operator, cards):
    response = record(bench, operator)

    body = response.json()
    assert response.status_code == 200 and body["state"] == "confirmed"
    assert body["relation"]["source"] == "operator:alice" and body["relation"]["reason"] == "why"
    listed = operator.get(RELATIONS).json()["relations"]
    assert [r["relation"]["id"] for r in listed] == [body["relation"]["id"]]


def test_review_and_withdraw_keep_the_first_record(bench, operator, cards):
    pending = propose(bench, "contradicts", "a", "b")
    url = f"{RELATIONS}/{pending}"

    first = bench.post(operator, f"{url}/review", {"decision": "rejected", "note": "no"})
    second = bench.post(operator, f"{url}/review", {"decision": "confirmed"})

    assert first.json()["state"] == "rejected"
    assert second.json()["detail"]["reason"] == "relation_not_pending"
    made = record(bench, operator, card_id="a", other="c").json()["relation"]["id"]
    one = bench.post(operator, f"{RELATIONS}/{made}/withdraw", {"reason": "first"})
    again = bench.post(operator, f"{RELATIONS}/{made}/withdraw", {"reason": "second"})
    assert one.json()["state"] == "withdrawn"
    assert again.json()["detail"]["reason"] == "relation_not_confirmed"
    assert bench.archive.ledger.record(made).withdrawal.reason == "first"


def test_withdrawing_needs_a_reason(bench, operator, cards):
    made = record(bench, operator).json()["relation"]["id"]
    for reason in ("", "   ", "x" * 501):
        response = bench.post(operator, f"{RELATIONS}/{made}/withdraw", {"reason": reason})
        assert response.status_code == 422


def test_confirming_a_model_proposal_between_public_cards_needs_a_note(bench, operator, cards):
    pending = propose(bench, "contradicts", "a", "b")
    url = f"{RELATIONS}/{pending}/review"

    bare = bench.post(operator, url, {"decision": "confirmed"})
    noted = bench.post(operator, url, {"decision": "confirmed", "note": "checked"})

    assert bare.json()["detail"]["reason"] == "relation_note_required"
    assert noted.json()["state"] == "confirmed"


def test_a_pending_proposal_of_project_p_is_not_listed_globally(bench, operator, cards):
    propose(bench, "contradicts", "a", "b", project="P")

    assert operator.get(RELATIONS).json()["relations"] == []
    from_p = operator.get(RELATIONS, params={"project_id": "P"}).json()["relations"]
    assert [r["state"] for r in from_p] == ["pending"]


def test_a_rejected_proposal_of_project_p_is_hidden_elsewhere(bench, operator, cards):
    rid = propose(bench, "contradicts", "a", "b", project="P")
    bench.archive.ledger.review(rid, "rejected", "alice", "")

    assert operator.get(RELATIONS).json()["relations"] == []
    assert operator.get(RELATIONS, params={"project_id": "Q"}).json()["relations"] == []
    assert len(operator.get(RELATIONS, params={"project_id": "P"}).json()["relations"]) == 1


def test_an_unknown_relation_is_not_found(bench, operator):
    for action, body in (("review", {"decision": "rejected"}), ("withdraw", {"reason": "r"})):
        response = bench.post(operator, f"{RELATIONS}/nope/{action}", body)
        assert response.json()["detail"]["reason"] == "record_not_found"


def test_a_model_role_is_refused(bench, cards):
    response = bench.post(
        bench.lan,
        RELATIONS,
        {"kind": "contradicts", "card_id": "a", "other_card_id": "b", "reason": "r"},
        headers=bench.model(),
    )
    assert response.json()["detail"]["code"] == "model_role"


def test_a_confirmed_model_proposal_shows_the_note_to_other_projects(bench, operator, cards):
    rid = propose(bench, "contradicts", "a", "b", project="P")
    bench.archive.ledger.review(rid, "confirmed", "alice", "checked it")

    for project, shows_model in ((None, False), ("Q", False), ("P", True)):
        params = {} if project is None else {"project_id": project}
        (row,) = operator.get(RELATIONS, params=params).json()["relations"]
        relation = row["relation"]
        assert relation["reason"] == ("model reason" if shows_model else "checked it")
        assert (relation["task_id"] == "t1") is shows_model


def test_the_review_response_is_shown_as_the_proposing_project_sees_it(bench, operator, cards):
    rid = propose(bench, "contradicts", "a", "b", project="P")

    response = bench.post(
        operator, f"{RELATIONS}/{rid}/review", {"decision": "confirmed", "note": "checked it"}
    )

    (row,) = operator.get(RELATIONS, params={"project_id": "P"}).json()["relations"]
    assert response.status_code == 200 and response.json() == row
    assert row["relation"]["reason"] == "model reason"


@pytest.fixture
def world(tmp_path):
    bench = Bench.full(tmp_path)
    alice, bob = bench.user("alice"), bench.user("bob")
    bench.seed_round_as("alice")
    yield bench, alice, bob
    bench.db.close()


def test_a_relation_with_another_users_project_card_is_hidden(world):
    bench, alice, bob = world
    card(bench, "pub")
    card(bench, "mine", bench.project_id)
    body = {"kind": "contradicts", "card_id": "mine", "other_card_id": "pub", "reason": "r"}

    refused = bench.post(bob, RELATIONS, body)
    allowed = bench.post(alice, RELATIONS, body)

    assert allowed.status_code == 200
    assert refused.json()["detail"]["reason"] == "record_not_found"
    rid = allowed.json()["relation"]["id"]
    for action, payload in (("review", {"decision": "rejected"}), ("withdraw", {"reason": "r"})):
        response = bench.post(bob, f"{RELATIONS}/{rid}/{action}", payload)
        assert response.json()["detail"]["reason"] == "record_not_found"
    listing = bob.get(RELATIONS, params={"project_id": bench.project_id})
    assert listing.json()["detail"]["reason"] == "record_not_found"
