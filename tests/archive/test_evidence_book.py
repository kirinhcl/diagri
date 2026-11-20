from growbridge.archive import snapshot as snap
from growbridge.archive.evidence_book import card_project, card_statuses, visible_cards
from growbridge.archive.evidence_ledger import EvidenceOrigin, EvidenceRelation
from growbridge.archive.models import EvidenceCard, SampleRecord
from growbridge.sim.clock import START

STEP = 60.0


def card(ident: str) -> EvidenceCard:
    return EvidenceCard(
        id=ident, source_class="handbook", citation="Handbook", claim=f"claim {ident}"
    )


def round_card(archive, ident: str, project: str, snapshot_ids=("snap-x",)) -> None:
    archive.add_evidence(card(ident))
    archive.ledger.add_origin(
        EvidenceOrigin(
            card_id=ident,
            project_id=project,
            round_id=f"round-{ident}",
            report_artifact_id=f"art-{ident}",
            snapshot_ids=tuple(snapshot_ids),
            label="exploratory",
            at=0.0,
        )
    )


def relate(archive, rid: str, kind: str, subject: str, obj: str | None, project=None, at=1.0):
    relation = EvidenceRelation(
        id=rid,
        kind=kind,
        subject_id=subject,
        object_id=obj,
        reason="why",
        source="operator:op",
        task_id=None,
        project_id=project,
        proposed_in=None,
        at=at,
    )
    archive.ledger.add_relation(relation, confirmed_by="op")


def frozen_snapshot(archive, clock) -> str:
    archive.append_sample(
        SampleRecord(
            id="d:0",
            experiment_id="exp-1",
            stage_id="veg",
            device_id="d",
            captured_at=START,
            received_at=START,
            clock_synced=True,
            data={"t": 24.0},
        )
    )
    frozen = snap.freeze(
        archive, "exp-1", clock, START, START + STEP, expected_interval=STEP, max_gap=STEP * 1.5
    )
    return frozen.id


def test_another_projects_round_card_is_invisible(archive):
    round_card(archive, "R", "P")
    assert "R" in visible_cards(archive, "P")
    assert "R" not in visible_cards(archive, "Q")
    assert "R" not in visible_cards(archive, None)
    assert card_statuses(archive, ["R"], "Q") == {}
    assert card_project(archive, "R") == "P"


def test_a_public_card_has_no_project(archive):
    archive.add_evidence(card("H"))
    assert card_project(archive, "H") is None
    assert "H" in visible_cards(archive, "Q")


def test_a_project_relation_does_not_change_the_status_elsewhere(archive):
    archive.add_evidence(card("H"))
    round_card(archive, "R", "P")
    relate(archive, "rel-1", "contradicts", "R", "H", project="P")
    assert card_statuses(archive, ["H"], "P")["H"].contested_with == ("R",)
    assert card_statuses(archive, ["H"], "Q")["H"].contested_with == ()
    assert card_statuses(archive, ["H"], None)["H"].contested_with == ()


def test_a_round_card_is_invalid_once_its_snapshot_is_marked(archive, clock):
    snapshot_id = frozen_snapshot(archive, clock)
    round_card(archive, "R", "P", snapshot_ids=(snapshot_id,))
    assert card_statuses(archive, ["R"], "P")["R"].validity == "active"
    archive.mark_dependents_invalid("d:0")
    status = card_statuses(archive, ["R"], "P")["R"]
    assert status.validity == "dependency_invalid"
    assert status.invalid_dependency == snapshot_id


def test_only_requested_visible_cards_come_back(archive):
    archive.add_evidence(card("H"))
    archive.add_evidence(card("H2"))
    round_card(archive, "R", "P")
    relate(archive, "rel-1", "supersedes", "R", "H", project="P")
    assert set(card_statuses(archive, ["H"], "P")) == {"H"}
    assert set(card_statuses(archive, ["H", "H2", "missing"], "P")) == {"H", "H2"}


def test_a_replacement_round_card_with_an_invalid_snapshot_is_flagged(archive, clock):
    snapshot_id = frozen_snapshot(archive, clock)
    archive.add_evidence(card("H"))
    round_card(archive, "R", "P", snapshot_ids=(snapshot_id,))
    relate(archive, "rel-1", "supersedes", "R", "H", project="P")
    archive.mark_dependents_invalid("d:0")
    status = card_statuses(archive, ["H"], "P")["H"]
    assert status.validity == "superseded"
    assert status.current_replacement.card_id == "R"
    assert status.current_replacement.validity == "dependency_invalid"
