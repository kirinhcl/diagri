import pytest
from dispatch_env import Env

from growbridge.archive.db import Database
from growbridge.sim.clock import FakeClock
from growbridge.sim.control import FakeControl


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "dispatch.db")
    yield database
    database.close()


@pytest.fixture
def env(db, clock, tmp_path):
    return Env(db, clock, FakeControl(clock), tmp_path / "work", tmp_path / "archive")
