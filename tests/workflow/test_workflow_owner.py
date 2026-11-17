"""Project owners, owner transfer, and listings filtered by owner before their limits."""

import pytest

from growbridge.archive.db import Database
from growbridge.archive.models import Budget, ResearchTask
from growbridge.ports import Actor, Denied
from growbridge.workflow.listing import (
    count_rounds_awaiting_choice,
    project_summaries,
    rounds_awaiting_choice,
)
from growbridge.workflow.states import TaskState
from growbridge.workflow.store import STEPS, WorkflowStore
from growbridge.workflow.tasks import TaskBoard


def operator(name: str, clock) -> Actor:
    return Actor(kind="operator", id=name, reauth_at=clock.now())


def test_operator_becomes_owner(world):
    project = world.svc.create_project("mine", operator("alice", world.clock))

    assert world.svc.store.project_owner(project) == "alice"


def test_workflow_actor_leaves_owner_empty(world):
    project = world.svc.create_project("system", world.actor("workflow"))

    assert world.svc.store.project_owner(project) is None


def test_legacy_projects_have_no_owner(tmp_path, clock):
    db = Database(tmp_path / "legacy.db")
    db.migrate("workflow", STEPS[:11])  # a database made before owners existed
    db.execute("INSERT INTO wf_projects VALUES ('p-old', 'old', 1.0)")

    store = WorkflowStore(db)

    assert store.project_owner("p-old") is None
    db.close()


def test_owner_transfer_runs_the_eligibility_check_in_its_transaction(world):
    store = world.svc.store
    project = world.svc.create_project("x", operator("alice", world.clock))

    def refuse() -> None:
        raise Denied("state", "not eligible")

    with pytest.raises(Denied):
        store.set_project_owner(project, "carol", "root", "why", world.clock.now(), refuse)
    assert store.project_owner(project) == "alice"

    store.set_project_owner(project, "carol", "root", "alice left", world.clock.now(), lambda: None)
    assert store.project_owner(project) == "carol"
    assert store.owner_events(project)[0]["from_owner"] == "alice"


async def test_project_unfinished(world):
    await world.pending("stage-1")

    assert world.svc.store.project_unfinished(world.project_id) is True
    await world.svc.stop_stage("stage-1", world.op)
    assert world.svc.store.project_unfinished(world.project_id) is False


def _waiting_rounds(world, owner: str, count: int) -> None:
    store = world.svc.store
    for index in range(count):
        project = world.svc.create_project(f"{owner}-{index}", operator(owner, world.clock))
        world.db.execute(
            "INSERT INTO wf_rounds(id, project_id, protocol_id, protocol_version, state,"
            " stages_done, awaiting_choice, created_at) VALUES (?, ?, 'p', 1, 'stage_review',"
            " 0, 'stage-x', ?)",
            (f"round-{owner}-{index}", project, float(index)),
        )
    assert store is world.svc.store


def test_listings_filter_before_limit(world):
    _waiting_rounds(world, "bob", 60)
    _waiting_rounds(world, "alice", 1)
    store = world.svc.store

    assert len(project_summaries(store, 50, only_owner="alice")) == 1
    assert [r["project_id"] for r in rounds_awaiting_choice(store, 50, only_owner="alice")] != []
    assert count_rounds_awaiting_choice(store, only_owner="alice") == 1
    assert count_rounds_awaiting_choice(store) == 61
    assert len(project_summaries(store)) == 61


def test_tasks_filter_before_limit(world):
    board = TaskBoard(world.db, world.clock)
    projects = {
        name: world.svc.create_project(name, operator(name, world.clock))
        for name in ("alice", "bob")
    }
    for index in range(60):
        board.create(_task(f"b{index}", projects["bob"]))
    board.create(_task("a0", projects["alice"]))
    for task_id in [f"b{i}" for i in range(60)] + ["a0"]:
        board.transition(task_id, TaskState.NEEDS_ATTENTION, f"ev-{task_id}", "stuck")
    wanted = (TaskState.NEEDS_ATTENTION,)

    assert [t.id for t in board.in_states(wanted, 50, only_owner="alice")] == ["a0"]
    assert board.count_in_states(wanted, only_owner="alice") == 1
    assert board.count_in_states(wanted) == 61


def _task(task_id: str, project_id: str) -> ResearchTask:
    return ResearchTask(
        id=task_id,
        project_id=project_id,
        question="q",
        owner_role="research",
        budget=Budget(max_calls=1, max_cost=1.0),
        trigger_event_id=f"trig-{task_id}",
        correlation_id="c",
    )
