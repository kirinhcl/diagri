"""Alerts carry the stage, project or device they belong to, and that scope is part of their
identity: two alerts with the same kind and key but different owners never merge."""

import pytest

from growbridge.archive.db import Database
from growbridge.observer.alerts import DEVICE_KINDS, AlertBook
from growbridge.sim.clock import FakeClock


@pytest.fixture
def book(tmp_path):
    db = Database(tmp_path / "alerts.db")
    yield AlertBook(db, FakeClock(), device_id="AC5-LOCAL")
    db.close()


def test_scope_saved_and_kept_on_merge(book):
    first = book.raise_alert("task_missed", "s1:t:1", "warning", "x", ("stage", "s1"))
    again = book.raise_alert("task_missed", "s1:t:1", "critical", "y", ("stage", "s1"))

    assert again.event_id == first.event_id and again.count == 2
    assert again.scope == ("stage", "s1")


def test_same_key_different_scope_stay_apart(book):
    # stage "grow:1" task "water" and stage "grow" task "1:water" make the same key
    key = "grow:1:water:1700000000"
    a = book.raise_alert("task_missed", key, "warning", "A's", ("stage", "grow:1"))
    b = book.raise_alert("task_missed", key, "warning", "B's", ("stage", "grow"))

    assert a.event_id != b.event_id
    assert book.open_for_scope({"task_missed"}, ("stage", "grow")) == (book.get(b.event_id),)


def test_unscoped_legacy_row_not_merged_into_scoped(book):
    legacy = book.raise_alert("agent_task", "task-1", "critical", "old")

    scoped = book.raise_alert("agent_task", "task-1", "critical", "new", ("project", "p1"))

    assert scoped.event_id != legacy.event_id
    assert book.get(legacy.event_id).scope is None and book.get(legacy.event_id).count == 1


def test_resolve_matches_its_scope_and_legacy_rows_only(book):
    legacy = book.raise_alert("audit_task", "audit:s1", "warning", "old")
    mine = book.raise_alert("audit_task", "audit:s1", "warning", "mine", ("stage", "s1"))
    other = book.raise_alert("audit_task", "audit:s1", "warning", "other", ("stage", "s2"))

    book.resolve("audit_task", "audit:s1", ("stage", "s1"))

    assert book.get(legacy.event_id).resolved_at is not None
    assert book.get(mine.event_id).resolved_at is not None
    assert book.get(other.event_id).resolved_at is None


def test_resolve_without_scope_leaves_scoped_rows(book):
    scoped = book.raise_alert("agent_task", "t1", "warning", "x", ("project", "p1"))

    book.resolve("agent_task", "t1")

    assert book.get(scoped.event_id).resolved_at is None


@pytest.mark.parametrize("kind", sorted(DEVICE_KINDS))
def test_device_kinds_belong_to_the_local_device(book, kind):
    alert = book.raise_alert(kind, "temp", "warning", "x")

    assert alert.scope == ("device", "AC5-LOCAL")
    assert book.resolve(kind, "temp") is True


def test_other_unscoped_kinds_stay_unscoped(book):
    assert book.raise_alert("backup_unconfigured", "backup", "warning", "x").scope is None


def test_device_kinds_cover_every_device_producer():
    assert DEVICE_KINDS == {
        "frozen_reading",
        "data_gap",
        "threshold",
        "pump_unreadable",
        "pump_unexpected",
        "pump_watchdog",
    }


def _runtime(book, waiting=(), expired=()):
    from types import SimpleNamespace

    return SimpleNamespace(
        book=book,
        clock=FakeClock(),
        workflow=SimpleNamespace(waiting_stages=lambda: list(waiting)),
        tasks=SimpleNamespace(expire=lambda _now: list(expired)),
        alert=lambda kind, key, message, severity="critical", scope=None, **fields: (
            book.raise_alert(kind, key, severity, message, scope, **fields)
        ),
    )


def test_stage_waiting_belongs_to_its_stage(book):
    from growbridge.runtime_alerts import stage_alerts

    item = {"stage_id": "grow:1", "entry": 7, "event": "disconnect", "state": "paused"}
    stage_alerts(_runtime(book, waiting=[{**item, "detail": {}}]))

    (alert,) = book.open()
    assert (alert.kind, alert.scope) == ("stage_waiting", ("stage", "grow:1"))


def test_task_deadline_and_agent_task_belong_to_the_project(book):
    from types import SimpleNamespace

    from growbridge.runtime_agents import _report_failure
    from growbridge.runtime_alerts import expire_tasks

    task = SimpleNamespace(id="task-1", project_id="p-a", owner_role="planner", input_refs=())
    runtime = _runtime(book, expired=[task])
    expire_tasks(runtime)
    _report_failure(runtime, task, "failed", failed=True)

    scopes = {(a.kind, a.scope) for a in book.open()}
    assert scopes == {("task_deadline", ("project", "p-a")), ("agent_task", ("project", "p-a"))}


def test_audit_task_belongs_to_its_stage_or_project(book):
    from types import SimpleNamespace

    from growbridge.runtime_agents import AUDIT_ROLE, _report_failure

    with_stage = SimpleNamespace(
        id="a1", project_id="p-a", owner_role=AUDIT_ROLE, input_refs=("stage:grow",)
    )
    without = SimpleNamespace(id="a2", project_id="p-a", owner_role=AUDIT_ROLE, input_refs=())
    runtime = _runtime(book)
    _report_failure(runtime, with_stage, "x", failed=True)
    _report_failure(runtime, without, "y", failed=True)

    assert {a.scope for a in book.open()} == {("stage", "grow"), ("project", "p-a")}
