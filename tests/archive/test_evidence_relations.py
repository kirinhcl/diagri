import pytest

from growbridge.archive.evidence_book import card_statuses
from growbridge.archive.evidence_ledger import EvidenceOrigin
from growbridge.archive.evidence_relations import (
    MAX_RELATION_PROPOSALS_PER_TASK,
    MODEL_RELATION_SOURCE,
    REASON_MAX,
    RelationRefused,
    RelationRequest,
    propose_relation,
    record_relation,
    relation_scope,
    review_relation,
    withdraw_relation,
)
from growbridge.archive.models import EvidenceCard


def make_card(archive, ident: str, project: str | None = None) -> None:
    archive.add_evidence(
        EvidenceCard(id=ident, source_class="handbook", citation="Handbook", claim=ident)
    )
    if project is not None:
        archive.ledger.add_origin(
            EvidenceOrigin(
                card_id=ident,
                project_id=project,
                round_id=f"round-{ident}",
                report_artifact_id=f"art-{ident}",
                snapshot_ids=("snap-x",),
                label="exploratory",
                at=0.0,
            )
        )


def request(kind, card, other=None, reason="because"):
    return RelationRequest(kind=kind, card_id=card, other_card_id=other, reason=reason)


def record(archive, kind, card, other=None, viewer=None):
    return record_relation(archive, request(kind, card, other), "op", viewer)


def propose(archive, kind, card, other=None, task="t1", project="P"):
    return propose_relation(archive, request(kind, card, other), task, project)


def refused(call) -> RelationRefused:
    with pytest.raises(RelationRefused) as caught:
        call()
    return caught.value


@pytest.fixture
def cards(archive):
    for ident in ("a", "b", "c", "h"):
        make_card(archive, ident)


# --- request ---------------------------------------------------------------------------------


def test_the_reason_is_trimmed_and_bounded():
    assert request("retracts", "a", reason="  ok  ").reason == "ok"
    with pytest.raises(ValueError):
        request("retracts", "a", reason="   ")
    with pytest.raises(ValueError):
        request("retracts", "a", reason="x" * (REASON_MAX + 1))
    assert request("retracts", "a", reason="x" * REASON_MAX)


# --- denial reasons --------------------------------------------------------------------------


def test_an_unknown_card_is_refused(archive, cards):
    exc = refused(lambda: record(archive, "retracts", "nope"))
    assert exc.reason == "relation_unknown_card"
    assert exc.params == {"card_id": "nope"}


def test_a_round_card_of_another_project_is_unknown(archive, cards):
    make_card(archive, "r", "P")
    exc = refused(lambda: record(archive, "contradicts", "a", "r", viewer="Q"))
    assert (exc.reason, exc.params) == ("relation_unknown_card", {"card_id": "r"})
    exc = refused(lambda: propose(archive, "retracts", "r", project="Q"))
    assert exc.reason == "relation_unknown_card"


def test_the_global_view_sees_no_round_card(archive, cards):
    make_card(archive, "r", "P")
    exc = refused(lambda: record(archive, "retracts", "r", viewer=None))
    assert exc.reason == "relation_unknown_card"


def test_cards_of_two_projects_are_refused(archive, cards):
    make_card(archive, "r", "P")
    make_card(archive, "s", "Q")
    exc = refused(lambda: record(archive, "contradicts", "r", "s", viewer="P"))
    assert exc.reason == "relation_unknown_card"
    assert refused(lambda: relation_scope(archive, request("contradicts", "r", "s"))).reason == (
        "relation_cross_scope"
    )


@pytest.mark.parametrize(
    ("kind", "other"),
    [("supersedes", None), ("contradicts", None), ("retracts", "b")],
)
def test_a_relation_of_the_wrong_shape_is_refused(archive, cards, kind, other):
    exc = refused(lambda: record(archive, kind, "a", other))
    assert (exc.reason, exc.params) == ("relation_shape", {"kind": kind})


def test_a_card_cannot_relate_to_itself(archive, cards):
    exc = refused(lambda: record(archive, "contradicts", "a", "a"))
    assert (exc.reason, exc.params) == ("relation_self", {})


def test_a_round_card_cannot_supersede_a_public_card(archive, cards):
    make_card(archive, "r", "P")
    exc = refused(lambda: record(archive, "supersedes", "r", "a", viewer="P"))
    assert (exc.reason, exc.params) == ("relation_cross_scope", {"kind": "supersedes"})
    stored = record(archive, "contradicts", "r", "a", viewer="P")
    assert stored.relation.project_id == "P"


def test_a_superseder_that_is_not_active_is_refused(archive, cards):
    record(archive, "retracts", "b")
    exc = refused(lambda: record(archive, "supersedes", "b", "a"))
    assert (exc.reason, exc.params) == (
        "relation_card_inactive",
        {"card_id": "b", "validity": "retracted"},
    )


def test_a_retracted_card_cannot_be_retracted_again(archive, cards):
    record(archive, "retracts", "a")
    exc = refused(lambda: record(archive, "retracts", "a"))
    assert (exc.reason, exc.params) == (
        "relation_card_inactive",
        {"card_id": "a", "validity": "retracted"},
    )


def test_a_card_cannot_be_superseded_twice(archive, cards):
    record(archive, "supersedes", "b", "a")
    exc = refused(lambda: record(archive, "supersedes", "c", "a"))
    assert (exc.reason, exc.params) == (
        "relation_already_superseded",
        {"card_id": "a", "replacement_id": "b"},
    )


def test_a_pending_or_confirmed_twin_is_a_duplicate(archive, cards):
    pending = propose(archive, "retracts", "a")
    exc = refused(lambda: record(archive, "retracts", "a", viewer="P"))
    assert (exc.reason, exc.params) == (
        "relation_duplicate",
        {"relation_id": pending.relation.id},
    )
    review_relation(archive, pending.relation.id, "rejected", "op", "", None)
    assert record(archive, "retracts", "a", viewer="P").state == "confirmed"


def test_another_projects_pending_proposal_is_not_a_duplicate(archive, cards):
    propose(archive, "retracts", "a", project="Q")
    assert record(archive, "retracts", "a", viewer="P").state == "confirmed"


def test_a_withdrawn_relation_is_not_a_duplicate(archive, cards):
    first = record(archive, "contradicts", "a", "b")
    withdraw_relation(archive, first.relation.id, "op", "mistake", None)
    assert record(archive, "contradicts", "a", "b").state == "confirmed"


def test_reviewing_a_settled_relation_is_refused(archive, cards):
    done = record(archive, "retracts", "a")
    exc = refused(lambda: review_relation(archive, done.relation.id, "confirmed", "op", "", None))
    assert (exc.reason, exc.params) == (
        "relation_not_pending",
        {"relation_id": done.relation.id, "state": "confirmed"},
    )


def test_withdrawing_a_relation_that_is_not_confirmed_is_refused(archive, cards):
    pending = propose(archive, "retracts", "a")
    exc = refused(lambda: withdraw_relation(archive, pending.relation.id, "op", "why", None))
    assert (exc.reason, exc.params) == (
        "relation_not_confirmed",
        {"relation_id": pending.relation.id, "state": "pending"},
    )


def test_confirming_a_model_proposal_between_public_cards_needs_a_note(archive, cards):
    pending = propose(archive, "contradicts", "a", "b")
    exc = refused(
        lambda: review_relation(archive, pending.relation.id, "confirmed", "op", "  ", None)
    )
    assert (exc.reason, exc.params) == ("relation_note_required", {})
    done = review_relation(archive, pending.relation.id, "confirmed", "op", "checked", None)
    assert done.state == "confirmed"


def test_the_eleventh_proposal_of_a_task_is_refused(archive):
    for i in range(MAX_RELATION_PROPOSALS_PER_TASK + 1):
        make_card(archive, f"c{i}")
    for i in range(MAX_RELATION_PROPOSALS_PER_TASK):
        propose(archive, "retracts", f"c{i}")
    exc = refused(lambda: propose(archive, "retracts", f"c{MAX_RELATION_PROPOSALS_PER_TASK}"))
    assert (exc.reason, exc.params) == (
        "quota_proposal_limit",
        {"max_proposals": MAX_RELATION_PROPOSALS_PER_TASK},
    )
    assert propose(archive, "retracts", f"c{MAX_RELATION_PROPOSALS_PER_TASK}", task="t2")


def test_an_unknown_relation_is_not_found(archive, cards):
    exc = refused(lambda: review_relation(archive, "rel-x", "rejected", "op", "", None))
    assert (exc.reason, exc.params) == (
        "record_not_found",
        {"record_kind": "evidence_relation", "record_id": "rel-x"},
    )
    assert refused(lambda: withdraw_relation(archive, "rel-x", "op", "why", None)).reason == (
        "record_not_found"
    )


def test_a_relation_on_cards_the_viewer_cannot_see_is_not_found(archive, cards):
    make_card(archive, "r", "P")
    made = record(archive, "retracts", "r", viewer="P")
    pending = propose(archive, "contradicts", "r", "a")
    for viewer in ("Q", None):
        exc = refused(lambda v=viewer: withdraw_relation(archive, made.relation.id, "op", "w", v))
        assert exc.reason == "record_not_found"
        exc = refused(
            lambda v=viewer: review_relation(archive, pending.relation.id, "rejected", "op", "", v)
        )
        assert exc.reason == "record_not_found"
    assert withdraw_relation(archive, made.relation.id, "op", "w", "P").state == "withdrawn"


# --- what is stored --------------------------------------------------------------------------


def test_a_proposal_is_pending_and_marked_as_the_models(archive, cards):
    stored = propose(archive, "supersedes", "b", "a", task="t9", project="P")
    relation = stored.relation
    assert stored.state == "pending"
    assert (relation.source, relation.task_id, relation.proposed_in, relation.project_id) == (
        MODEL_RELATION_SOURCE,
        "t9",
        "P",
        None,
    )
    assert (relation.subject_id, relation.object_id) == ("b", "a")


def test_a_recorded_relation_is_confirmed_by_the_operator(archive, cards):
    stored = record_relation(archive, request("retracts", "a"), "ann", None)
    assert stored.state == "confirmed"
    assert stored.relation.source == "operator:ann"
    assert stored.review is not None and stored.review.reviewer == "ann"


def test_a_contradiction_is_stored_once_whatever_the_order(archive, cards):
    record(archive, "contradicts", "b", "a")
    exc = refused(lambda: record(archive, "contradicts", "a", "b"))
    assert exc.reason == "relation_duplicate"
    stored = archive.ledger.records(None)[0].relation
    assert stored.subject_id == "a"
    assert stored.object_id == "b"


def test_a_supersede_chain_cannot_loop(archive, cards):
    record(archive, "supersedes", "b", "a")
    exc = refused(lambda: record(archive, "supersedes", "a", "b"))
    assert exc.reason == "relation_card_inactive"
    assert exc.params["card_id"] == "a"


def test_confirming_after_the_object_was_superseded_elsewhere_is_refused(archive, cards):
    pending = propose(archive, "supersedes", "a", "h")
    record(archive, "supersedes", "b", "h")
    exc = refused(
        lambda: review_relation(archive, pending.relation.id, "confirmed", "op", "n", None)
    )
    assert exc.reason == "relation_already_superseded"
    assert review_relation(archive, pending.relation.id, "rejected", "op", "", None).state == (
        "rejected"
    )


def test_confirming_does_not_count_the_relation_itself_as_a_duplicate(archive, cards):
    pending = propose(archive, "retracts", "a", task="t1")
    done = review_relation(archive, pending.relation.id, "confirmed", "op", "n", None)
    assert done.state == "confirmed"
    assert card_statuses(archive, ["a"], None)["a"].validity == "retracted"
