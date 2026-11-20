import sqlite3

import pytest

from growbridge.archive.evidence_ledger import EvidenceOrigin, EvidenceRelation
from growbridge.archive.models import Snapshot


def relation(**over) -> EvidenceRelation:
    base = dict(
        id="rel-1",
        kind="supersedes",
        subject_id="ev-new",
        object_id="ev-old",
        reason="2nd edition",
        source="operator:op",
        task_id=None,
        project_id=None,
        proposed_in=None,
        at=0.0,
    )
    return EvidenceRelation(**{**base, **over})


def test_an_operator_relation_is_confirmed_in_the_same_step(archive, clock):
    rec = archive.ledger.add_relation(relation(at=clock.now()), confirmed_by="op")
    assert rec.state == "confirmed" and rec.review.at == rec.relation.at


def test_a_relation_without_review_is_pending(archive):
    assert archive.ledger.add_relation(relation()).state == "pending"


def test_the_first_review_and_the_first_withdrawal_stay(archive):
    archive.ledger.add_relation(relation(source="model:planner"))
    archive.ledger.review("rel-1", "confirmed", "op", "ok")
    assert archive.ledger.review("rel-1", "rejected", "op2").review.decision == "confirmed"
    archive.ledger.withdraw("rel-1", "op", "conditions differ")
    assert archive.ledger.withdraw("rel-1", "op2", "again").withdrawal.actor == "op"
    assert archive.ledger.record("rel-1").state == "withdrawn"


def test_a_rejected_relation_reports_rejected(archive):
    archive.ledger.add_relation(relation())
    assert archive.ledger.review("rel-1", "rejected", "op").state == "rejected"


def test_records_of_a_project_include_the_global_ones_only(archive):
    archive.ledger.add_relation(relation(id="g"))
    archive.ledger.add_relation(relation(id="p", project_id="P"))
    archive.ledger.add_relation(relation(id="q", project_id="Q"))
    assert [r.relation.id for r in archive.ledger.records("P")] == ["g", "p"]
    assert [r.relation.id for r in archive.ledger.records(None)] == ["g"]


def test_reviewing_an_unknown_relation_is_refused(archive):
    with pytest.raises(ValueError):
        archive.ledger.review("nope", "confirmed", "op")
    with pytest.raises(ValueError):
        archive.ledger.withdraw("nope", "op", "why")


def test_proposed_by_counts_the_relations_of_a_task(archive):
    archive.ledger.add_relation(relation(id="a", task_id="t1"))
    archive.ledger.add_relation(relation(id="b", task_id="t1"))
    archive.ledger.add_relation(relation(id="c", task_id="t2"))
    assert archive.ledger.proposed_by("t1") == 2
    assert archive.ledger.proposed_by("none") == 0


def test_one_origin_per_report_and_its_snapshots_round_trip(archive):
    origin = EvidenceOrigin(
        card_id="ev-r",
        project_id="P",
        round_id="r1",
        report_artifact_id="art-1",
        snapshot_ids=("snap-1", "snap-2"),
        label="confirmatory",
        at=0.0,
    )
    archive.ledger.add_origin(origin)
    assert archive.ledger.origin_of_report("art-1") == origin
    assert archive.ledger.origin("ev-r") == origin
    assert archive.ledger.origins() == {"ev-r": origin}
    assert archive.ledger.origin("nope") is None
    with pytest.raises(sqlite3.IntegrityError):
        archive.ledger.add_origin(origin.model_copy(update={"card_id": "ev-r2"}))


def freeze_from(archive, clock, snapshot_id, record_id):
    snap = Snapshot(
        id=snapshot_id,
        experiment_id="exp-1",
        version=1,
        created_at=clock.now(),
        manifest_sha256="x",
        complete=True,
        coverage=1.0,
    )
    archive.save_snapshot(snap, [record_id])


def test_invalidated_at_is_the_earliest_invalidation(archive, clock):
    freeze_from(archive, clock, "snap-1", "rec-1")
    freeze_from(archive, clock, "snap-2", "rec-2")
    t1 = clock.now()
    archive.mark_dependents_invalid("rec-1")
    clock.advance(60)
    archive.mark_dependents_invalid("rec-2")
    assert archive.invalidated_at(["snap-2", "snap-1"]) == (t1, "snap-1")
    assert archive.invalidated_at(["snap-2"]) == (clock.now(), "snap-2")
    assert archive.invalidated_at(["snap-3"]) is None
    assert archive.invalidated_at([]) is None


def test_an_invalid_decision_raises_and_leaves_the_relation_pending(archive):
    archive.ledger.add_relation(relation(source="model:planner"))
    with pytest.raises(ValueError):
        archive.ledger.review("rel-1", "approved", "op")
    assert archive.ledger.record("rel-1").state == "pending"


@pytest.mark.parametrize("reviewer", [None, ""])
def test_a_missing_reviewer_raises(archive, reviewer):
    archive.ledger.add_relation(relation(source="model:planner"))
    with pytest.raises(ValueError):
        archive.ledger.review("rel-1", "confirmed", reviewer)
    assert archive.ledger.record("rel-1").state == "pending"


def test_an_empty_confirmer_refuses_the_whole_relation(archive):
    with pytest.raises(ValueError):
        archive.ledger.add_relation(relation(), confirmed_by="")
    assert archive.ledger.record("rel-1") is None


@pytest.mark.parametrize("actor", [None, ""])
def test_a_withdrawal_without_an_actor_raises(archive, actor):
    archive.ledger.add_relation(relation())
    with pytest.raises(ValueError):
        archive.ledger.withdraw("rel-1", actor, "why")
    assert archive.ledger.record("rel-1").state == "pending"
