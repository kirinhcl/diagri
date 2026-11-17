"""Every refusal of the task board carries a registered reason and the params the console builds
its text from; the coarse code and the English message stay as they were."""

import pytest

from growbridge.archive.models import Budget
from growbridge.ports import Denied
from growbridge.workflow.states import TaskState as S


def refused(call, code: str) -> Denied:
    with pytest.raises(Denied) as exc:
        call()
    assert exc.value.code == code
    return exc.value


def test_task_transition_not_allowed_carries_the_task_and_both_statuses(board, make_task):
    board.create(make_task())
    exc = refused(lambda: board.transition("t1", S.COMPUTING, "ev-1", "x"), "state")
    assert exc.reason == "task_transition_not_allowed"
    assert exc.params == {"task_id": "t1", "from_status": "in_progress", "to_status": "computing"}


def test_task_end_needs_reason_carries_the_task(board, make_task):
    board.create(make_task())
    board.transition("t1", S.NEEDS_ATTENTION, "ev-1", "stuck")
    exc = refused(lambda: board.transition("t1", S.ENDED, "ev-2", "  "), "state")
    assert exc.reason == "task_end_needs_reason" and exc.params == {"task_id": "t1"}


def test_task_board_conflict_carries_the_task_and_its_parent_for_a_repeated_id(board, make_task):
    board.create(make_task())
    exc = refused(lambda: board.create(make_task(trigger_event_id="other")), "state")
    assert exc.reason == "task_board_conflict"
    assert exc.params == {"task_id": "t1", "parent_task_id": None}


def test_task_board_conflict_carries_the_parent_that_belongs_to_another_project(board, make_task):
    board.create(make_task())
    child = make_task("t2", parent_task_id="t1", project_id="p2")
    exc = refused(lambda: board.create(child), "state")
    assert exc.reason == "task_board_conflict"
    assert exc.params == {"task_id": "t2", "parent_task_id": "t1"}


def test_task_board_conflict_carries_the_task_for_an_event_of_another_task(board, make_task):
    board.create(make_task())
    board.create(make_task("t2"))
    board.transition("t1", S.NEEDS_ATTENTION, "ev-1", "x")
    exc = refused(lambda: board.transition("t2", S.NEEDS_ATTENTION, "ev-1", "x"), "state")
    assert exc.reason == "task_board_conflict"
    assert exc.params == {"task_id": "t2", "parent_task_id": None}


def test_record_not_found_carries_the_task_kind_and_id_when_a_task_is_unknown(board):
    exc = refused(lambda: board.get("ghost"), "state")
    assert exc.reason == "record_not_found"
    assert exc.params == {"record_kind": "task", "record_id": "ghost"}


def test_record_not_found_carries_the_task_when_a_revision_is_counted_for_an_unknown_one(board):
    exc = refused(lambda: board.record_revision("ghost"), "state")
    assert exc.reason == "record_not_found"
    assert exc.params == {"record_kind": "task", "record_id": "ghost"}


def test_budget_revision_limit_carries_the_task_and_the_limit(board, make_task):
    board.create(make_task(budget=Budget(max_calls=5, max_cost=1.0, max_revisions=1)))
    board.record_revision("t1")
    exc = refused(lambda: board.record_revision("t1"), "budget")
    assert exc.reason == "budget_revision_limit"
    assert exc.params == {"task_id": "t1", "max_revisions": 1}


def test_delegation_depth_exceeded_carries_the_task_the_depth_and_the_limit(board, make_task):
    board.create(make_task(budget=Budget(max_calls=5, max_cost=1.0, max_delegation_depth=0)))
    exc = refused(lambda: board.create(make_task("t2", parent_task_id="t1")), "budget")
    assert exc.reason == "delegation_depth_exceeded"
    assert exc.params == {"task_id": "t2", "depth": 1, "max_depth": 0}
