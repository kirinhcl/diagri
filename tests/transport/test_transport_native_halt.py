import asyncio
import contextlib
import signal

import pytest


async def started(make_native):
    transport = make_native()
    await transport.connect(lambda _: None)
    return transport


async def test_halt_true_when_helper_exits_after_channel_hangup(make_native, host, helper):
    transport = await started(make_native)
    assert helper.pid in host.alive

    assert await transport.halt() is True
    assert helper.pid not in host.alive
    await transport.close()


async def test_halt_false_when_helper_ignores_hangup_and_stop(make_native, host, helper):
    helper.exits_on_hangup = False
    host.sigterm_kills = False
    transport = await started(make_native)

    assert await transport.halt() is False
    assert helper.pid in host.alive
    await helper.shutdown()


async def test_halt_false_when_only_a_stop_signal_was_sent(make_native, host, helper):
    helper.exits_on_hangup = False
    host.sigterm_kills = False
    transport = await started(make_native)

    assert await transport.halt() is False
    assert (helper.pid, signal.SIGTERM) in host.signals
    await helper.shutdown()


async def test_halt_true_when_helper_only_dies_after_sigterm(make_native, host, helper):
    helper.exits_on_hangup = False  # SIGTERM kills it in FakeHost
    transport = await started(make_native)

    assert await transport.halt() is True
    assert helper.pid not in host.alive
    await helper.shutdown()


async def test_halt_not_true_while_command_file_waits_in_helper_queue(make_native, host, helper):
    helper.exits_on_hangup = False
    host.sigterm_kills = False
    transport = await started(make_native)
    sender = asyncio.create_task(transport.send({"msgId": "m1", "method": "setLight"}))
    await asyncio.sleep(0.02)
    assert (transport.commands / "m1.json").exists()  # written, helper never acked

    assert await transport.halt() is False
    sender.cancel()
    with contextlib.suppress(asyncio.CancelledError, ConnectionError):
        await sender
    await helper.shutdown()


async def test_dropping_the_python_waiter_does_not_confirm_halt(make_native, host, helper):
    helper.exits_on_hangup = False
    host.sigterm_kills = False
    transport = await started(make_native)
    sender = asyncio.create_task(transport.send({"msgId": "m2", "method": "setFan"}))
    await asyncio.sleep(0.02)
    sender.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await sender
    assert transport.pending == {}  # waiter is gone

    assert await transport.halt() is False
    await helper.shutdown()


async def test_halt_true_when_nothing_was_ever_started(make_native):
    assert await make_native().halt() is True


async def test_halt_false_when_helper_pid_unknown_and_launcher_still_running(make_native):
    transport = make_native()
    transport.process = type("P", (), {"returncode": None})()
    assert transport.native_pid is None

    assert await transport.halt() is False


async def test_halt_true_when_helper_pid_unknown_but_launcher_has_exited(make_native):
    transport = make_native()
    transport.process = type("P", (), {"returncode": 0})()

    assert await transport.halt() is True


async def test_send_is_refused_after_halt(make_native):
    transport = await started(make_native)
    await transport.halt()

    with pytest.raises(ConnectionError):
        await transport.send({"msgId": "m3", "method": "setLight"})
    await transport.close()
