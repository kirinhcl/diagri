from growbridge.agents.conversation import MAX_TEXT, ConversationLog
from growbridge.archive.db import Database
from growbridge.sim.clock import FakeClock


def make_log(tmp_path) -> ConversationLog:
    return ConversationLog(Database(tmp_path / "c.db"), FakeClock())


def test_entries_come_in_order_after_a_sequence_number_and_per_project(tmp_path):
    log = make_log(tmp_path)
    first = log.add("p1", "user", "message", "hello", "t1", {"operator": "dev"})
    log.add("p2", "user", "message", "elsewhere")
    second = log.add("p1", "orchestrator", "reply", "hi", "t1")

    assert [e.text for e in log.entries("p1")] == ["hello", "hi"]
    assert [e.seq for e in log.entries("p1", after=first)] == [second]
    assert log.entries("p1")[0].detail == {"operator": "dev"}


def test_recent_keeps_the_newest_of_the_asked_kinds_oldest_first(tmp_path):
    log = make_log(tmp_path)
    for n in range(5):
        log.add("p", "user", "message", f"m{n}")
        log.add("p", "planner", "tool", "validate_run_sheet")

    assert [e.text for e in log.recent("p", ("message",), 2)] == ["m3", "m4"]


def test_a_long_text_is_clipped(tmp_path):
    log = make_log(tmp_path)
    log.add("p", "orchestrator", "reply", "x" * (MAX_TEXT + 10))

    assert log.entries("p")[0].text.endswith("...[truncated]")
