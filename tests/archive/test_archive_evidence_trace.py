"""Evidence cards keep who entered them, and a verification is a record of its own.

The card text is never edited: ``verified`` on the cards ``Archive.evidence`` returns comes from
an appended verification record, so ``check_evidence`` can use the cards directly.
"""

import pytest

from growbridge.archive.models import EvidenceCard
from growbridge.archive.store import Archive


def card(ident: str = "card-1", **fields) -> EvidenceCard:
    values = {
        "id": ident,
        "source_class": "handbook",
        "citation": "Handbook of Lettuce Production",
        "claim": "200 umol m-2 s-1 suits lettuce",
        **fields,
    }
    return EvidenceCard(**values)


def stored_body(archive, ident: str) -> str:
    return archive.db.one("SELECT body FROM evidence WHERE id = ?", (ident,))["body"]


def test_a_card_added_the_old_way_is_unverified_and_has_no_source(archive):
    archive.add_evidence(card())

    (found,) = archive.evidence()
    (entry,) = archive.evidence_entries()

    assert found.verified is False
    assert entry.source is None and entry.verified_by is None


def test_a_card_records_its_source_and_task(archive):
    archive.add_evidence(card(), source="model:planner", task_id="task-1")

    (entry,) = archive.evidence_entries()

    assert entry.source == "model:planner" and entry.task_id == "task-1"
    assert entry.added_at == archive.clock.now()
    assert entry.verified_by is None


def test_a_verification_is_a_new_record_and_leaves_the_card_text_alone(archive):
    archive.add_evidence(card(), source="model:planner", task_id="task-1")
    before = stored_body(archive, "card-1")

    record = archive.verify_evidence("card-1", "alice", "checked the handbook")

    assert stored_body(archive, "card-1") == before
    assert record.verifier == "alice" and record.note == "checked the handbook"
    (found,) = archive.evidence()
    assert found.verified is True


def test_verifying_twice_keeps_the_first_record(archive, clock):
    archive.add_evidence(card())
    first = archive.verify_evidence("card-1", "alice", "first")
    clock.advance(60)

    second = archive.verify_evidence("card-1", "bob", "second")

    assert second == first
    assert len(archive.db.query("SELECT * FROM evidence_verifications")) == 1


def test_verifying_an_unknown_card_is_refused(archive):
    with pytest.raises(ValueError, match="unknown evidence card"):
        archive.verify_evidence("card-none", "alice")


def test_an_operator_card_is_added_and_verified_in_one_step(archive):
    archive.add_evidence(card(), source="operator:alice", verified_by="alice")

    (entry,) = archive.evidence_entries()
    (found,) = archive.evidence()

    assert entry.source == "operator:alice" and entry.verified_by == "alice"
    assert found.verified is True
    assert '"verified":false' in stored_body(archive, "card-1").replace(" ", "")


def test_evidence_by_id_also_reflects_verifications(archive):
    archive.add_evidence(card("card-1"))
    archive.add_evidence(card("card-2"))
    archive.verify_evidence("card-2", "alice")

    flags = {c.id: c.verified for c in archive.evidence(["card-1", "card-2"])}

    assert flags == {"card-1": False, "card-2": True}


def test_a_stored_card_cannot_claim_to_be_verified_by_itself(archive):
    archive.add_evidence(card(verified=True), source="model:planner", task_id="task-1")

    (found,) = archive.evidence()
    (entry,) = archive.evidence_entries()

    assert found.verified is False and entry.verified_by is None


def test_cards_proposed_by_a_task_are_counted(archive):
    archive.add_evidence(card("card-1"), source="model:planner", task_id="task-1")
    archive.add_evidence(card("card-2"), source="model:planner", task_id="task-1")
    archive.add_evidence(card("card-3"), source="model:planner", task_id="task-2")

    assert archive.evidence_count_from("task-1") == 2
    assert archive.evidence_count_from("task-none") == 0


def test_evidence_records_survive_a_restart(db, tmp_path, clock):
    first = Archive(db, tmp_path / "a", clock)
    first.add_evidence(card(), source="operator:alice", verified_by="alice")

    restarted = Archive(db, tmp_path / "a", clock)

    (found,) = restarted.evidence()
    assert found.verified is True


# --- calibration: only an operator vouches for it ---------------------------------------------


def test_a_model_proposed_card_is_uncalibrated_whatever_the_card_says(archive):
    archive.add_evidence(card(calibrated=True), source="model:planner", task_id="task-1")

    (found,) = archive.evidence()

    assert found.calibrated is False
    assert '"calibrated":false' in stored_body(archive, "card-1").replace(" ", "")


def test_verifying_without_an_attestation_leaves_a_proposed_card_uncalibrated(archive):
    archive.add_evidence(card(), source="model:planner", task_id="task-1")

    record = archive.verify_evidence("card-1", "alice")

    (found,) = archive.evidence()
    assert record.calibrated is False
    assert found.verified is True and found.calibrated is False


def test_an_operator_attestation_makes_a_proposed_card_calibrated(archive):
    archive.add_evidence(card(), source="model:planner", task_id="task-1")

    record = archive.verify_evidence("card-1", "alice", "measured against our sensor", True)

    (found,) = archive.evidence()
    (entry,) = archive.evidence_entries()
    assert record.calibrated is True
    assert found.calibrated is True and entry.card.calibrated is True


def test_an_unverified_proposed_card_is_never_calibrated(archive):
    archive.add_evidence(card(), source="model:planner", task_id="task-1")

    assert archive.evidence()[0].calibrated is False


def test_the_first_verification_decides_a_later_attestation_changes_nothing(archive):
    archive.add_evidence(card(), source="model:planner", task_id="task-1")
    first = archive.verify_evidence("card-1", "alice")

    again = archive.verify_evidence("card-1", "bob", "later", True)

    assert again == first and archive.evidence()[0].calibrated is False


@pytest.mark.parametrize("entered", [True, False])
def test_an_operator_entered_card_keeps_the_calibration_the_operator_entered(archive, entered):
    archive.add_evidence(card(calibrated=entered), source="operator:alice", verified_by="alice")

    (found,) = archive.evidence()

    assert found.calibrated is entered and found.verified is True


def test_a_card_with_no_source_keeps_the_calibration_it_was_stored_with(archive):
    archive.add_evidence(card("card-1", calibrated=False))
    archive.add_evidence(card("card-2", calibrated=True))

    flags = {c.id: c.calibrated for c in archive.evidence()}

    assert flags == {"card-1": False, "card-2": True}
