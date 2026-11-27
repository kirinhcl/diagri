import threading

import pytest

from growbridge.archive.db import Database
from growbridge.guide.store import GuideStore
from growbridge.sim.clock import FakeClock


@pytest.fixture
def store(tmp_path):
    return GuideStore(Database(tmp_path / "guide.db"), FakeClock(1000.0))


def test_a_session_gets_an_id_a_seed_and_no_events(store):
    s = store.start("project-1", "alice", "zh")
    assert s.session_id.startswith("guide-") and 1 <= s.seed < 2**31
    assert store.session(s.session_id) == s
    assert store.events(s.session_id) == ()


def test_events_are_numbered_in_order_and_kept_as_written(store):
    s = store.start("project-1", "alice", "zh")
    first = store.append(s.session_id, "question", "chosen", {"answer": {"question": "Q"}}, "alice")
    store.append_many(
        s.session_id,
        [("crop", "offered", {"options": []}), ("crop", "chosen", {"answer": {}})],
        "alice",
    )
    events = store.events(s.session_id)
    assert [e.seq for e in events] == [1, 2, 3]
    assert [e.kind for e in events] == ["chosen", "offered", "chosen"]
    assert events[0] == first
    assert first.payload == {"answer": {"question": "Q"}} and first.at == 1000.0


def test_an_unknown_session_takes_no_event(store):
    assert store.session("guide-nope") is None
    with pytest.raises(KeyError):
        store.append("guide-nope", "question", "chosen", {}, "alice")
    with pytest.raises(KeyError):
        store.append_many("guide-nope", [("question", "chosen", {})], "alice")
    assert store.events("guide-nope") == ()


def test_concurrent_appends_get_distinct_numbers(tmp_path):
    path = tmp_path / "guide.db"
    first = GuideStore(Database(path), FakeClock(1000.0))
    second = GuideStore(Database(path), FakeClock(1000.0))
    session = first.start("project-1", "alice", "en")
    per_thread = 25

    def write(store, name):
        for index in range(per_thread):
            store.append(session.session_id, "crop", "chosen", {"n": index}, name)

    threads = [
        threading.Thread(target=write, args=(first, "alice")),
        threading.Thread(target=write, args=(second, "bob")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert [e.seq for e in first.events(session.session_id)] == list(range(1, 2 * per_thread + 1))
