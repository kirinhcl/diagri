import asyncio

import pytest
import pytest_asyncio

from growbridge.archive.db import Database
from growbridge.archive.store import Archive
from growbridge.config import Settings
from growbridge.service import Bridge
from growbridge.sim.clock import FakeClock
from growbridge.sim.device import SimulatedTransport


@pytest.fixture
def settings(tmp_path):
    return Settings(
        device="SIMULATED",
        token="x" * 32,
        data_dir=tmp_path,
        controls_enabled=True,
        pump_cooldown_seconds=0,
    )


@pytest_asyncio.fixture
async def bridge(settings):
    simulator = SimulatedTransport()
    instance = Bridge(settings, lambda _: simulator)
    await instance.start()
    for _ in range(50):
        if instance.identity:
            break
        await asyncio.sleep(0.01)
    yield instance, simulator
    await instance.stop()


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
