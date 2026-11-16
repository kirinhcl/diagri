"""A trigger event id makes one task per project: reusing another project's trigger is refused
without telling the caller anything about that task."""

import pytest

from growbridge.ports import Denied


def test_trigger_of_other_project_is_refused_without_its_id(board, make_task):
    board.create(make_task("secret-task", project_id="p-a", trigger_event_id="shared"))

    with pytest.raises(Denied) as denied:
        board.create(make_task("t-b", project_id="p-b", trigger_event_id="shared"))

    assert denied.value.code == "state"
    assert "secret-task" not in str(denied.value)
    assert "p-a" not in str(denied.value)
    assert board.list("p-b") == ()


def test_same_project_repeat_still_returns_the_first_task(board, make_task):
    first = board.create(make_task("t1", project_id="p-a", trigger_event_id="again"))

    again = board.create(make_task("t2", project_id="p-a", trigger_event_id="again"))

    assert again.id == first.id
