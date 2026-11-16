from growbridge.archive.models import Budget, ResearchTask
from growbridge.sim.fixtures import make_protocol
from growbridge.workflow.listing import (
    count_rounds_awaiting_choice,
    project_detail,
    project_summaries,
    rounds_awaiting_choice,
)
from growbridge.workflow.states import TaskState
from growbridge.workflow.tasks import TaskBoard


def build_task(task_id: str, project_id: str) -> ResearchTask:
    return ResearchTask(
        id=task_id,
        project_id=project_id,
        question="does far-red shorten flowering?",
        owner_role="research",
        budget=Budget(max_calls=10, max_cost=5.0),
        trigger_event_id=f"trig-{task_id}",
        correlation_id="corr-1",
    )


async def test_project_summaries_count_rounds_and_show_the_latest(world):
    await world.design()
    (summary,) = project_summaries(world.svc.store)
    assert summary["project_id"] == world.project_id and summary["round_count"] == 1
    assert summary["latest_round"] == {
        "round_id": world.round_id,
        "state": "designing",
        "round_number": 1,
    }


def test_project_summaries_without_projects_are_empty(world):
    assert project_summaries(world.svc.store) == []


async def test_project_detail_lists_only_the_latest_protocol_version(world):
    await world.design()
    second = make_protocol(project_id=world.project_id, version=2)
    world.svc.save_protocol(second, world.op)
    detail = project_detail(world.svc.store, world.project_id)
    assert [p["version"] for p in detail["protocols"]] == [2]
    assert [r["round_id"] for r in detail["rounds"]] == [world.round_id]
    assert detail["rounds"][0]["awaiting_choice"] is None


def test_project_detail_of_an_unknown_project_is_none(world):
    assert project_detail(world.svc.store, "nope") is None


async def test_rounds_awaiting_choice_lists_only_waiting_rounds(world):
    await world.design()
    assert rounds_awaiting_choice(world.svc.store) == []
    world.svc.store.update_round(world.round_id, awaiting_choice="stage-1")
    assert [r["round_id"] for r in rounds_awaiting_choice(world.svc.store)] == [world.round_id]


def test_task_board_in_states_filters_across_projects(world):
    board = TaskBoard(world.db, world.clock)
    board.create(build_task("t1", "p1"))
    board.create(build_task("t2", "p2"))
    board.transition("t2", TaskState.NEEDS_REVIEW, "ev-1", "check")
    assert [t.id for t in board.in_states({TaskState.NEEDS_REVIEW})] == ["t2"]
    assert [t.id for t in board.in_states({TaskState.IN_PROGRESS, TaskState.NEEDS_REVIEW})] == [
        "t1",
        "t2",
    ]
    assert board.in_states(set()) == ()


async def test_count_rounds_awaiting_choice_counts_only_waiting_rounds(world):
    await world.design()
    assert count_rounds_awaiting_choice(world.svc.store) == 0
    world.svc.store.update_round(world.round_id, awaiting_choice="stage-1")
    assert count_rounds_awaiting_choice(world.svc.store) == 1


def test_task_board_count_in_states_counts_across_projects(world):
    board = TaskBoard(world.db, world.clock)
    board.create(build_task("t1", "p1"))
    board.create(build_task("t2", "p2"))
    board.transition("t2", TaskState.NEEDS_REVIEW, "ev-1", "check")
    assert board.count_in_states({TaskState.NEEDS_REVIEW}) == 1
    assert board.count_in_states({TaskState.IN_PROGRESS, TaskState.NEEDS_REVIEW}) == 2
    assert board.count_in_states(set()) == 0
