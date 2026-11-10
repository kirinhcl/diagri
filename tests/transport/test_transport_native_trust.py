import os

import pytest

STALE_PID = 31337


def plant_pid(folder):
    (folder / "helper.pid").write_text(str(STALE_PID))


def assert_refused_quietly(transport, host, helper):
    assert transport._read_pid() is None  # untrusted folder: pid file never read
    assert host.signals == []
    assert helper.spawned == 0


async def test_symlinked_run_folder_is_refused_and_nothing_is_signalled(
    make_native, host, helper, run_root
):
    transport = make_native()
    target = run_root / "elsewhere"
    target.mkdir(mode=0o700)
    plant_pid(target)
    transport.folder.symlink_to(target)
    host.alive.add(STALE_PID)

    with pytest.raises(RuntimeError, match=str(transport.folder)):
        await transport.connect(lambda _: None)

    assert_refused_quietly(transport, host, helper)
    assert host.alive == {STALE_PID}
    assert transport.folder.is_symlink()  # not followed, not removed


async def test_group_or_other_accessible_folder_is_refused(make_native, host, helper):
    transport = make_native()
    transport.folder.mkdir()
    transport.folder.chmod(0o755)
    plant_pid(transport.folder)
    host.alive.add(STALE_PID)

    with pytest.raises(RuntimeError, match=str(transport.folder)):
        await transport.connect(lambda _: None)

    assert_refused_quietly(transport, host, helper)


async def test_folder_owned_by_another_uid_is_refused(make_native, host, helper):
    transport = make_native(get_uid=lambda: os.getuid() + 1)
    transport.folder.mkdir(mode=0o700)
    plant_pid(transport.folder)
    host.alive.add(STALE_PID)

    with pytest.raises(RuntimeError, match=str(transport.folder)):
        await transport.connect(lambda _: None)

    assert_refused_quietly(transport, host, helper)


async def test_halt_does_not_trust_a_planted_pid_file(make_native, host):
    transport = make_native()
    transport.folder.mkdir()
    transport.folder.chmod(0o777)
    plant_pid(transport.folder)
    host.alive.add(STALE_PID)

    await transport.halt()

    assert host.signals == []


async def test_private_folder_owned_by_current_user_still_works(make_native, host, helper):
    transport = make_native()
    transport.folder.mkdir(mode=0o700)
    transport.folder.chmod(0o700)
    plant_pid(transport.folder)
    host.alive.add(STALE_PID)

    await transport.connect(lambda _: None)

    assert helper.spawned == 1
    assert (transport.folder.stat().st_mode & 0o777) == 0o700
    await transport.halt()
    await transport.close()
