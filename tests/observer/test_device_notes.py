"""Notes people write about a device: newest first, per device, bounded in length."""

import pytest

from growbridge.observer.device_notes import NOTE_MAX, DeviceNotes
from growbridge.ports import Denied


def test_device_notes_newest_first_and_per_device(db, clock):
    notes = DeviceNotes(db, clock)
    notes.add("ac5-1", "alice", "changed the CO2 probe", sensor="co2")
    clock.advance(60)
    notes.add("ac5-1", "bob", "fan cleaned")
    notes.add("ac5-2", "bob", "other greenhouse")

    found = notes.recent("ac5-1")
    assert [(n.actor, n.text, n.sensor) for n in found] == [
        ("bob", "fan cleaned", None),
        ("alice", "changed the CO2 probe", "co2"),
    ]
    assert notes.recent("ac5-1", since=found[0].at) == (found[0],)
    assert len(notes.recent("ac5-1", limit=1)) == 1


def test_device_note_text_is_bounded(db, clock):
    notes = DeviceNotes(db, clock)
    for text in ("x" * (NOTE_MAX + 1), "   "):
        with pytest.raises(Denied) as refused:
            notes.add("ac5-1", "alice", text)
        assert refused.value.code == "param"
    assert notes.add("ac5-1", "alice", "  ok  ").text == "ok"
