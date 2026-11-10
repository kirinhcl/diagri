from conftest import build_task

from growbridge.workflow.states import TaskState


def test_open_tasks_lists_in_progress_tasks_of_the_roles_oldest_first(board):
    board.create(build_task("t1", owner_role="planner"))
    board.create(build_task("t2", owner_role="researcher"))
    board.create(build_task("t3", owner_role="planner", project_id="p2"))
    board.create(build_task("t4", owner_role="orchestrator"))

    found = board.open_tasks({"planner", "researcher"})

    assert [task.id for task in found] == ["t1", "t2", "t3"]


def test_open_tasks_leaves_out_tasks_that_are_no_longer_in_progress(board):
    board.create(build_task("t1", owner_role="planner"))
    board.create(build_task("t2", owner_role="planner"))
    board.transition("t1", TaskState.DONE, "ev-done", "finished")

    assert [task.id for task in board.open_tasks(["planner"])] == ["t2"]


def test_open_tasks_with_no_roles_is_empty(board):
    board.create(build_task("t1", owner_role="planner"))

    assert board.open_tasks([]) == ()
