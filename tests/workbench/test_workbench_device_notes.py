"""Workbench routes of the memory: a read note on an alert, and notes about the device."""

import pytest
from workbench_support import Bench

from growbridge.workbench.visibility import READ_RULES

DEVICE = "SIMULATED"
NOTES = f"/wb/devices/{DEVICE}/notes"


@pytest.fixture
def bench(tmp_path) -> Bench:
    return Bench(tmp_path)


def raise_frozen(bench: Bench):
    return bench.alerts.raise_alert("frozen_reading", "co2", "warning", "flat")


def test_read_with_a_note_keeps_it(bench):
    alice = bench.user("alice")
    alert = raise_frozen(bench)

    answer = bench.post(alice, f"/wb/alerts/{alert.event_id}/read", {"note": "wire loose"})

    assert answer.status_code == 200
    assert [n.note for n in bench.alerts.notes_of("frozen_reading", "co2")] == ["wire loose"]


def test_read_without_a_body_still_works(bench):
    alice = bench.user("alice")
    alert = raise_frozen(bench)

    answer = alice.post(f"/wb/alerts/{alert.event_id}/read", headers=bench.ui(alice))

    assert answer.status_code == 200 and bench.alerts.get(alert.event_id).read_by == "alice"
    assert bench.alerts.notes_of("frozen_reading", "co2") == ()


def test_note_over_500_is_refused(bench):
    alice = bench.user("alice")
    alert = raise_frozen(bench)

    answer = bench.post(alice, f"/wb/alerts/{alert.event_id}/read", {"note": "x" * 501})

    assert answer.status_code == 422 and bench.alerts.get(alert.event_id).read_by is None


def test_holder_writes_and_reads_notes(bench):
    alice = bench.user("alice")

    written = bench.post(alice, NOTES, {"text": "changed the CO2 probe", "sensor": "co2"})
    listed = alice.get(NOTES)

    assert written.status_code == 200 and written.json()["actor"] == "alice"
    assert [n["text"] for n in listed.json()["notes"]] == ["changed the CO2 probe"]


def test_unknown_device_is_refused(bench):
    alice = bench.user("alice")

    assert alice.get("/wb/devices/elsewhere/notes").status_code == 409
    assert bench.post(alice, "/wb/devices/elsewhere/notes", {"text": "x"}).status_code == 409


def test_environment_names_its_device(bench):
    assert bench.user("alice").get("/wb/environment").json()["device_id"] == DEVICE


def test_device_notes_route_is_registered():
    assert READ_RULES["/wb/devices/{device_id}/notes"] == "device"


def test_device_notes_need_the_lock(tmp_path):
    bench = Bench.full(tmp_path)
    alice, bob, root = bench.user("alice"), bench.user("bob"), bench.user("root", "admin")
    bench.lock("alice")

    for client in (alice, root):
        assert bench.post(client, NOTES, {"text": "fan cleaned"}).status_code == 200
        assert client.get(NOTES).status_code == 200
    for answer in (bob.get(NOTES), bench.post(bob, NOTES, {"text": "x"})):
        assert answer.status_code == 403 and "not_lock_holder" in answer.text
