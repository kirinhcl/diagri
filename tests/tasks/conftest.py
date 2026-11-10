import pytest

from growbridge.archive.db import Database
from growbridge.archive.models import Budget, ResearchTask
from growbridge.sim.clock import FakeClock
from growbridge.workflow.tasks import TaskBoard


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "tasks.db")
    yield database
    database.close()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def board(db, clock):
    return TaskBoard(db, clock)


def build_task(task_id="t1", **overrides) -> ResearchTask:
    fields = {
        "id": task_id,
        "project_id": "p1",
        "question": "does far-red shorten flowering?",
        "owner_role": "research",
        "budget": Budget(max_calls=10, max_cost=5.0),
        "trigger_event_id": f"trig-{task_id}",
        "correlation_id": "corr-1",
    }
    return ResearchTask(**{**fields, **overrides})


@pytest.fixture
def make_task():
    return build_task
