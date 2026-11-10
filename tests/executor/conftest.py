import pytest_asyncio
from executor_helpers import build_rig


@pytest_asyncio.fixture
async def make_rig(settings, tmp_path):
    made = []

    async def factory(allow=None, register=True):
        rig = await build_rig(settings, tmp_path, allow, register)
        made.append(rig)
        return rig

    yield factory
    for rig in made:
        await rig.bridge.stop()
        for db in rig.dbs:
            db.close()


@pytest_asyncio.fixture
async def rig(make_rig):
    return await make_rig()
