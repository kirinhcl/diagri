"""The runtime's sandbox denies reads of the data directory and of the backup directory."""

import sys

import pytest

from growbridge.research.sandbox import SeatbeltSandbox


@pytest.fixture
def settings(settings, tmp_path):
    return settings.model_copy(update={"backup_dir": tmp_path / "backups"})


async def test_the_runtime_sandbox_denies_the_data_and_backup_directories(world, settings):
    if sys.platform != "darwin":
        pytest.skip("the isolation backend is macOS only")
    runtime = await world.boot()

    sandbox = runtime.sandbox
    if not isinstance(sandbox, SeatbeltSandbox):
        pytest.skip("sandbox-exec is not available")

    assert settings.data_dir.resolve() in sandbox.deny_read
    assert settings.backup_dir.resolve() in sandbox.deny_read
