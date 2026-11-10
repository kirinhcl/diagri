import pytest
import pytest_asyncio
from e2e_support import World, local

from growbridge.config import Settings
from growbridge.sim.clock import FakeClock


@pytest.fixture
def clock():
    return FakeClock(now=local("10:00"))


@pytest.fixture
def settings(tmp_path):
    return Settings(
        device="SIMULATED",
        token="x" * 32,
        data_dir=tmp_path / "data",
        controls_enabled=True,
        pump_cooldown_seconds=0,
        auto_research=True,
    )


@pytest_asyncio.fixture
async def world(settings, clock):
    instance = World(settings, clock)
    yield instance
    await instance.shutdown()
