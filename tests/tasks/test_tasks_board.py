import itertools

import pytest

from growbridge.archive.models import Budget
from growbridge.ports import Denied
from growbridge.workflow.states import TASK_TERMINAL, TaskState
from growbridge.workflow.tasks import TaskBoard

S = TaskState

# Every allowed transition of the research-task table (Appendix B).
ALLOWED = {
    (S.IN_PROGRESS, S.REMOTE_QUEUED),
    (S.REMOTE_QUEUED, S.COMPUTING),
    (S.COMPUTING, S.FETCHING),
    (S.FETCHING, S.IN_PROGRESS),
    (S.REMOTE_QUEUED, S.RECONCILE),
    (S.COMPUTING, S.RECONCILE),
    (S.RECONCILE, S.IN_PROGRESS),
    (S.RECONCILE, S.ENDED),
    (S.IN_PROGRESS, S.NEEDS_ATTENTION),
    (S.REMOTE_QUEUED, S.NEEDS_ATTENTION),
    (S.COMPUTING, S.NEEDS_ATTENTION),
    (S.FETCHING, S.NEEDS_ATTENTION),
    (S.RECONCILE, S.NEEDS_ATTENTION),
    (S.NEEDS_REVIEW, S.NEEDS_ATTENTION),
    (S.NEEDS_ATTENTION, S.IN_PROGRESS),
    (S.NEEDS_ATTENTION, S.ENDED),
    (S.IN_PROGRESS, S.NEEDS_REVIEW),
    (S.NEEDS_REVIEW, S.DONE),
    (S.IN_PROGRESS, S.DONE),
}

PATHS = {
    S.IN_PROGRESS: [],
    S.REMOTE_QUEUED: [S.REMOTE_QUEUED],
    S.COMPUTING: [S.REMOTE_QUEUED, S.COMPUTING],
    S.FETCHING: [S.REMOTE_QUEUED, S.COMPUTING, S.FETCHING],
    S.RECONCILE: [S.REMOTE_QUEUED, S.RECONCILE],
    S.NEEDS_ATTENTION: [S.NEEDS_ATTENTION],
    S.NEEDS_REVIEW: [S.NEEDS_REVIEW],
    S.DONE: [S.DONE],
    S.ENDED: [S.NEEDS_ATTENTION, S.ENDED],
}
counter = itertools.count()


def reach(board, task_id, state):
    for step in PATHS[state]:
        board.transition(task_id, step, f"setup-{next(counter)}", "setup")
    assert board.get(task_id).state == state


@pytest.mark.parametrize(("src", "dst"), sorted(ALLOWED))
def test_tasks_allowed_transition(board, make_task, src, dst):
    board.create(make_task())
    reach(board, "t1", src)
    result = board.transition("t1", dst, "ev-x", "because")
    assert result.state == dst
    assert board.get("t1").state == dst


ILLEGAL = [
    (src, dst)
    for src in TaskState
    for dst in TaskState
    if (src, dst) not in ALLOWED and src not in TASK_TERMINAL
]


@pytest.mark.parametrize(("src", "dst"), ILLEGAL)
def test_tasks_illegal_transition_is_denied(board, make_task, src, dst):
    board.create(make_task())
    reach(board, "t1", src)
    with pytest.raises(Denied) as info:
        board.transition("t1", dst, "ev-bad", "x")
    assert info.value.code == "state"
    assert board.get("t1").state == src


@pytest.mark.parametrize("terminal", sorted(TASK_TERMINAL))
def test_tasks_terminal_states_have_no_exit(board, make_task, terminal):
    board.create(make_task())
    reach(board, "t1", terminal)
    for dst in TaskState:
        with pytest.raises(Denied):
            board.transition("t1", dst, f"ev-{dst}", "x")


def test_tasks_unknown_task_is_denied(board):
    with pytest.raises(Denied) as info:
        board.transition("nope", S.DONE, "ev-1")
    assert info.value.code == "state"


def test_tasks_same_event_id_is_processed_once(board, make_task):
    board.create(make_task())
    first = board.transition("t1", S.REMOTE_QUEUED, "ev-1")
    again = board.transition("t1", S.REMOTE_QUEUED, "ev-1")
    assert first.state == again.state == S.REMOTE_QUEUED
    board.transition("t1", S.COMPUTING, "ev-2")
    # Replaying the first event must not move the task or raise.
    assert board.transition("t1", S.REMOTE_QUEUED, "ev-1").state == S.COMPUTING


def test_tasks_event_id_reused_for_other_task_is_denied(board, make_task):
    board.create(make_task("t1"))
    board.create(make_task("t2"))
    board.transition("t1", S.NEEDS_REVIEW, "ev-1")
    with pytest.raises(Denied) as info:
        board.transition("t2", S.NEEDS_REVIEW, "ev-1")
    assert info.value.code == "state"
    assert board.get("t2").state == S.IN_PROGRESS


@pytest.mark.parametrize("src", [S.RECONCILE, S.NEEDS_ATTENTION])
def test_tasks_ending_requires_a_reason(board, make_task, src):
    board.create(make_task())
    reach(board, "t1", src)
    with pytest.raises(Denied) as info:
        board.transition("t1", S.ENDED, "ev-end", "  ")
    assert info.value.code == "state"
    assert board.transition("t1", S.ENDED, "ev-end2", "user abandoned").state == S.ENDED


def test_tasks_reconcile_exits_resubmit_or_abandon(board, make_task):
    board.create(make_task("a"))
    board.create(make_task("b"))
    reach(board, "a", S.RECONCILE)
    reach(board, "b", S.RECONCILE)
    resubmitted = board.transition("a", S.IN_PROGRESS, "ev-a", "checked, resubmit")
    assert resubmitted.state == S.IN_PROGRESS
    assert board.transition("b", S.ENDED, "ev-b", "abandoned").state == S.ENDED


def test_tasks_review_exits_publish_or_downgrade(board, make_task):
    board.create(make_task("a"))
    board.create(make_task("b"))
    reach(board, "a", S.NEEDS_REVIEW)
    reach(board, "b", S.NEEDS_REVIEW)
    assert board.transition("a", S.DONE, "ev-a", "published").state == S.DONE
    assert board.transition("b", S.DONE, "ev-b", "downgraded to exploratory").state == S.DONE


def test_tasks_attention_relaxed_returns_to_progress_or_ends(board, make_task):
    board.create(make_task("a"))
    board.create(make_task("b"))
    reach(board, "a", S.NEEDS_ATTENTION)
    reach(board, "b", S.NEEDS_ATTENTION)
    assert board.transition("a", S.IN_PROGRESS, "ev-a", "budget raised").state == S.IN_PROGRESS
    assert board.transition("b", S.ENDED, "ev-b", "keep partial").state == S.ENDED


def test_tasks_state_survives_reopen(db, clock, make_task):
    TaskBoard(db, clock).create(make_task())
    TaskBoard(db, clock).transition("t1", S.NEEDS_REVIEW, "ev-1")
    assert TaskBoard(db, clock).get("t1").state == S.NEEDS_REVIEW


def test_tasks_get_unknown_raises_denied(board):
    with pytest.raises(Denied):
        board.get("missing")


def test_tasks_create_same_trigger_event_only_once(board, make_task):
    first = board.create(make_task("t1", trigger_event_id="evt-9"))
    second = board.create(make_task("t2", trigger_event_id="evt-9"))
    assert second.id == first.id == "t1"
    assert len(board.list("p1")) == 1


def test_tasks_create_same_id_with_other_trigger_is_denied(board, make_task):
    board.create(make_task("t1"))
    with pytest.raises(Denied) as info:
        board.create(make_task("t1", trigger_event_id="another"))
    assert info.value.code == "state"


def test_tasks_create_always_starts_in_progress(board, make_task):
    created = board.create(make_task(state=S.DONE))
    assert created.state == S.IN_PROGRESS


def test_tasks_list_filters_by_project_and_state(board, make_task):
    board.create(make_task("a"))
    board.create(make_task("b"))
    board.create(make_task("c", project_id="p2"))
    board.transition("b", S.NEEDS_REVIEW, "ev-b")
    assert [t.id for t in board.list("p1")] == ["a", "b"]
    assert [t.id for t in board.list("p1", S.NEEDS_REVIEW)] == ["b"]
    assert board.list("p3") == ()


def test_tasks_delegation_depth_limit(board, make_task):
    small = Budget(max_calls=5, max_cost=1.0, max_delegation_depth=1)
    board.create(make_task("root", budget=small))
    board.create(make_task("child", parent_task_id="root", budget=small))
    with pytest.raises(Denied) as info:
        board.create(make_task("grandchild", parent_task_id="child", budget=small))
    assert info.value.code == "budget"
    assert board.list("p1")[-1].id == "child"


def test_tasks_delegation_with_missing_parent_is_denied(board, make_task):
    with pytest.raises(Denied) as info:
        board.create(make_task("c", parent_task_id="ghost"))
    assert info.value.code == "state"


def test_tasks_expire_moves_overdue_active_tasks_to_attention(board, clock, make_task):
    board.create(make_task("late", deadline=clock.now() + 10))
    board.create(make_task("fine", deadline=clock.now() + 1000))
    board.create(make_task("open"))
    board.create(make_task("waiting", deadline=clock.now() + 10))
    reach(board, "waiting", S.NEEDS_REVIEW)
    expired = board.expire(clock.now() + 11)
    assert [t.id for t in expired] == ["late"]
    assert board.get("late").state == S.NEEDS_ATTENTION
    assert board.get("fine").state == S.IN_PROGRESS
    assert board.get("waiting").state == S.NEEDS_REVIEW


def test_tasks_expire_does_not_reexpire_after_relaxing(board, clock, make_task):
    board.create(make_task("late", deadline=clock.now() + 10))
    later = clock.now() + 11
    assert len(board.expire(later)) == 1
    assert board.expire(later) == ()
    board.transition("late", S.IN_PROGRESS, "ev-relax", "user extended")
    assert board.expire(later + 5) == ()
    assert board.get("late").state == S.IN_PROGRESS


def test_tasks_expire_at_exact_deadline_does_not_fire(board, clock, make_task):
    board.create(make_task("t", deadline=clock.now() + 10))
    assert board.expire(clock.now() + 10) == ()


def test_tasks_record_revision_counts_and_caps(board, make_task):
    board.create(make_task("t", budget=Budget(max_calls=5, max_cost=1.0, max_revisions=2)))
    assert board.record_revision("t") == 1
    assert board.record_revision("t") == 2
    with pytest.raises(Denied) as info:
        board.record_revision("t")
    assert info.value.code == "budget"
    with pytest.raises(Denied):
        board.record_revision("t")


def test_tasks_record_revision_unknown_task(board):
    with pytest.raises(Denied) as info:
        board.record_revision("ghost")
    assert info.value.code == "state"
