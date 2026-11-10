import pytest

from growbridge.archive.db import Database
from growbridge.archive.store import Archive
from growbridge.sim.clock import FakeClock


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "archive.db")
    yield database
    database.close()


@pytest.fixture
def archive(db, tmp_path, clock):
    return Archive(db, tmp_path / "archive", clock)
