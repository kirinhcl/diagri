"""What each operator may see: projects, stages, devices and alerts."""

import pytest
from access_support import People

from growbridge.archive.db import Database
from growbridge.observer.alerts import AlertBook
from growbridge.ports import Actor
from growbridge.sim.fixtures import DEVICE


@pytest.fixture
def people(world) -> People:
    return People(world)


@pytest.fixture
def book(tmp_path, world):
    db = Database(tmp_path / "alerts.db")
    yield AlertBook(db, world.clock, device_id=DEVICE)
    db.close()


def test_owner_and_admin_see_the_project_and_stage(world, people):
    people.pending()
    access = people.access

    assert access.sees_project(people.alice, world.project_id)
    assert access.sees_stage(people.alice, "stage-1")
    assert access.sees_project(people.root, world.project_id)
    assert not access.sees_project(people.bob, world.project_id)
    assert not access.sees_stage(people.bob, "stage-1")
    assert not access.sees_stage(people.alice, "no-such-stage")


def test_devices_follow_the_lock(people):
    people.locks.lock("alice", ["gh-01"])

    assert people.access.sees_device(people.alice, DEVICE)
    assert not people.access.sees_device(people.bob, DEVICE)
    assert people.access.sees_device(people.root, DEVICE)


def test_alerts_follow_their_scope(world, people, book):
    people.pending()
    stage = book.raise_alert("task_missed", "k1", "warning", "s", ("stage", "stage-1"))
    project = book.raise_alert("agent_task", "k2", "warning", "p", ("project", world.project_id))
    device = book.raise_alert("frozen_reading", "temp", "warning", "d")
    system = book.raise_alert("backup_unconfigured", "backup", "warning", "x")
    odd = book.raise_alert("custom", "k", "warning", "x", ("planet", "mars"))
    access = people.access

    assert [access.sees_alert(people.alice, a) for a in (stage, project, device, system, odd)] == [
        True,
        True,
        True,  # alice holds gh-01 (DEVICE) since pending()
        False,
        False,
    ]
    assert not any(access.sees_alert(people.bob, a) for a in (stage, project, device, system))
    assert all(access.sees_alert(people.root, a) for a in (stage, project, device, system, odd))


def test_owner_filter(people):
    assert people.access.owner_filter(people.alice) == "alice"
    assert people.access.owner_filter(people.root) is None


def test_non_operators_are_not_restricted(world, people):
    people.pending()
    model = Actor(kind="model", id="planner")

    assert people.access.sees_project(model, world.project_id)
