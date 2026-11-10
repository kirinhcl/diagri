import signal

import pytest

STALE_PID = 31337


def write_pid(transport, text):
    transport.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    transport.folder.chmod(0o700)
    (transport.folder / "helper.pid").write_text(text)


async def test_helper_pid_is_persisted_to_folder_on_start(make_native, helper):
    transport = make_native()
    await transport.connect(lambda _: None)

    assert (transport.folder / "helper.pid").read_text().strip() == str(helper.pid)
    await transport.halt()
    await transport.close()


async def test_pid_file_is_read_back_after_restart(make_native, host, helper):
    first = make_native()
    await first.connect(lambda _: None)
    helper.exits_on_hangup = False
    host.sigterm_kills = False  # the old helper is still alive when Python restarts

    second = make_native()
    with pytest.raises(RuntimeError, match="still running"):
        await second.connect(lambda _: None)
    assert helper.spawned == 1  # no second helper was started
    await helper.shutdown()


async def test_stale_live_pid_is_stopped_before_new_helper_starts(make_native, host, helper):
    transport = make_native()
    write_pid(transport, str(STALE_PID))
    host.alive.add(STALE_PID)

    await transport.connect(lambda _: None)

    assert (STALE_PID, signal.SIGTERM) in host.signals
    assert STALE_PID not in host.alive
    assert helper.spawned == 1
    await transport.halt()
    await transport.close()


async def test_stale_pid_that_will_not_die_blocks_new_helper(make_native, host, helper):
    host.sigterm_kills = False
    transport = make_native()
    write_pid(transport, str(STALE_PID))
    host.alive.add(STALE_PID)

    with pytest.raises(RuntimeError, match="still running"):
        await transport.connect(lambda _: None)

    assert helper.spawned == 0
    assert (transport.folder / "helper.pid").read_text().strip() == str(STALE_PID)


async def test_dead_stale_pid_is_cleared_without_signals(make_native, host, helper):
    transport = make_native()
    write_pid(transport, str(STALE_PID))

    await transport.connect(lambda _: None)

    assert host.signals == []
    assert helper.spawned == 1
    await transport.halt()
    await transport.close()


async def test_garbage_pid_file_is_ignored(make_native, host, helper):
    transport = make_native()
    write_pid(transport, "not-a-number")

    await transport.connect(lambda _: None)

    assert host.signals == []
    assert helper.spawned == 1
    await transport.halt()
    await transport.close()


async def test_pid_file_removed_after_confirmed_stop_and_kept_otherwise(make_native, host, helper):
    transport = make_native()
    await transport.connect(lambda _: None)
    assert await transport.halt() is True
    await transport.close()
    assert not (transport.folder / "helper.pid").exists()

    helper.exits_on_hangup = False
    host.sigterm_kills = False
    stuck = make_native(halt_timeout=0.05)
    await stuck.connect(lambda _: None)
    await stuck.close()
    assert (stuck.folder / "helper.pid").read_text().strip() == str(helper.pid)
    await helper.shutdown()
