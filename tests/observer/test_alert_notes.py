"""Every reason an operator gives when marking an alert read is kept."""

from growbridge.observer.alerts import AlertBook
from growbridge.ports import Actor

ALICE, BOB = Actor(kind="operator", id="alice"), Actor(kind="operator", id="bob")


def test_each_read_with_a_note_is_kept(db, clock):
    book = AlertBook(db, clock)
    alert = book.raise_alert("frozen_reading", "co2", "warning", "flat")
    book.mark_read(alert.event_id, ALICE, note="wire loose")
    clock.advance(60)
    book.mark_read(alert.event_id, BOB, note="re-seated the probe")
    clock.advance(60)
    book.mark_read(alert.event_id, ALICE)

    notes = book.notes_of("frozen_reading", "co2")
    assert [(n.actor, n.note) for n in notes] == [
        ("alice", "wire loose"),
        ("bob", "re-seated the probe"),
    ]
    assert notes[0].first_at == alert.first_at and notes[0].resolved_at is None
    assert book.get(alert.event_id).read_by == "alice"


def test_a_blank_note_is_not_stored(db, clock):
    book = AlertBook(db, clock)
    alert = book.raise_alert("frozen_reading", "co2", "warning", "flat")
    book.mark_read(alert.event_id, ALICE, note="   ")

    assert book.notes_of("frozen_reading", "co2") == ()


def test_notes_belong_to_their_kind_and_key(db, clock):
    book = AlertBook(db, clock)
    alert = book.raise_alert("frozen_reading", "co2", "warning", "flat")
    book.mark_read(alert.event_id, ALICE, note="wire loose")

    assert book.notes_of("frozen_reading", "temp") == ()
    assert book.notes_of("data_gap", "co2") == ()
