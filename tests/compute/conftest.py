from types import SimpleNamespace

import pytest_asyncio
from compute_support import MEMBERS, TEMPLATE

from growbridge.archive.db import Database
from growbridge.compute.service import ComputeService
from growbridge.sim.clock import FakeClock
from growbridge.sim.compute import FakeBackend


@pytest_asyncio.fixture
async def env(tmp_path):
    """A service with generous caps and a balance already recorded."""
    db = Database(tmp_path / "compute.db")
    clock = FakeClock()
    backend = FakeBackend()
    backend.balance_value = 1000.0

    async def build(cpu_cap=100.0, storage_cap=100.0, task_cpu=100.0, task_storage=100.0):
        service = ComputeService(
            db,
            clock,
            backend,
            [TEMPLATE],
            MEMBERS,
            service_cpu_cap=cpu_cap,
            service_storage_cap=storage_cap,
        )
        service.set_task_budget("t1", task_cpu, task_storage)
        await service.refresh_balance()
        return service

    service = await build()
    yield SimpleNamespace(
        db=db, clock=clock, backend=backend, service=service, build=build, tmp=tmp_path
    )
    db.close()
