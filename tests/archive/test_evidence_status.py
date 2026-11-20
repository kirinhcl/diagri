from growbridge.archive.evidence_ledger import (
    EvidenceRelation,
    RelationRecord,
    RelationReview,
    RelationWithdrawal,
)
from growbridge.archive.evidence_status import Replacement, derive_statuses


def rec(
    rel_id="rel-1",
    kind="supersedes",
    subject="B",
    object_="A",
    at=0.0,
    confirmed_at=None,
    withdrawn_at=None,
    proposed_in=None,
    reason="why",
    note="",
) -> RelationRecord:
    relation = EvidenceRelation(
        id=rel_id,
        kind=kind,
        subject_id=subject,
        object_id=object_,
        reason=reason,
        source="operator:op",
        task_id=None,
        project_id=None,
        proposed_in=proposed_in,
        at=at,
    )
    review = (
        None
        if confirmed_at is None
        else RelationReview(
            relation_id=rel_id, decision="confirmed", reviewer="op", note=note, at=confirmed_at
        )
    )
    withdrawal = (
        None
        if withdrawn_at is None
        else RelationWithdrawal(relation_id=rel_id, actor="op", reason="x", at=withdrawn_at)
    )
    return RelationRecord(relation=relation, review=review, withdrawal=withdrawal)


def statuses(records, ids=("A", "B", "C"), invalid_at=None, as_of=1000.0, viewer=None):
    return derive_statuses(ids, records, invalid_at or {}, as_of, viewer)


def test_a_pending_relation_changes_nothing_but_shows_as_pending():
    got = statuses([rec(subject="A", object_="B")])["B"]
    assert got.validity == "active" and got.pending == ("rel-1",) and not got.blocks


def test_a_confirmed_supersede_names_the_end_of_the_chain():
    records = [
        rec("r1", subject="B", object_="A", confirmed_at=1),
        rec("r2", subject="C", object_="B", confirmed_at=2),
    ]
    a = statuses(records)["A"]
    assert a.validity == "superseded" and a.superseded_by == "B"
    assert a.current_replacement == Replacement(card_id="C", validity="active")


def test_a_retracted_end_of_chain_keeps_the_old_card_superseded():
    records = [
        rec("r1", subject="B", object_="A", confirmed_at=1),
        rec("r2", kind="retracts", subject="B", object_=None, confirmed_at=2),
    ]
    a = statuses(records)["A"]
    assert a.validity == "superseded"
    assert a.current_replacement.validity == "retracted"


def test_a_supersede_cycle_stops_at_the_card_already_seen():
    records = [
        rec("r1", subject="B", object_="A", confirmed_at=1),
        rec("r2", subject="A", object_="B", confirmed_at=2),
    ]
    assert statuses(records)["A"].current_replacement.card_id in {"A", "B"}


def test_precedence_retracted_then_invalid_then_superseded():
    records = [
        rec("r1", subject="B", object_="A", confirmed_at=1),
        rec("r2", kind="retracts", subject="A", object_=None, confirmed_at=1, reason="bad"),
    ]
    invalid = {"A": (5.0, "snap-1")}
    assert statuses(records, invalid_at=invalid)["A"].validity == "retracted"
    assert statuses(records[:1], invalid_at=invalid)["A"].validity == "dependency_invalid"
    assert statuses(records[:1])["A"].validity == "superseded"


def test_as_of_bounds_are_inclusive_at_confirmation_and_at_withdrawal():
    records = [rec(confirmed_at=100, withdrawn_at=200)]
    got = {t: statuses(records, as_of=t)["A"].validity for t in (99, 100, 199, 200)}
    assert got == {99: "active", 100: "superseded", 199: "superseded", 200: "active"}


def test_invalidation_counts_from_its_time():
    invalid = {"R": (50.0, "snap-1")}
    at_49 = statuses([], ids=("R",), invalid_at=invalid, as_of=49)["R"]
    at_50 = statuses([], ids=("R",), invalid_at=invalid, as_of=50)["R"]
    assert at_49.validity == "active" and at_49.invalid_dependency is None
    assert at_50.validity == "dependency_invalid" and at_50.invalid_dependency == "snap-1"


def test_a_contradiction_counts_only_while_the_other_card_is_active():
    records = [
        rec("r1", kind="contradicts", subject="A", object_="B", confirmed_at=1),
        rec("r2", subject="C", object_="B", confirmed_at=500),
    ]
    assert statuses(records, as_of=499)["A"].contested_with == ("B",)
    assert statuses(records, as_of=500)["A"].contested_with == ()


def test_a_pending_proposal_of_another_project_is_not_shown():
    records = [rec(subject="A", object_="B", proposed_in="P")]
    assert statuses(records, viewer="Q")["B"].pending == ()
    assert statuses(records, viewer="P")["B"].pending == ("rel-1",)


def test_a_retraction_reason_from_another_project_is_the_operators_note():
    records = [
        rec(
            kind="retracts",
            subject="A",
            object_=None,
            confirmed_at=1,
            proposed_in="p1",
            reason="model says so",
            note="operator's own words",
        )
    ]
    assert statuses(records, viewer="p2")["A"].retracted_reason == "operator's own words"
    assert statuses(records, viewer=None)["A"].retracted_reason == "operator's own words"
    assert statuses(records, viewer="p1")["A"].retracted_reason == "model says so"
