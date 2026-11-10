"""Fakes for the transport tests: a fake host (pids/signals) and a fake helper app."""

import asyncio
import json
import shutil
import signal
import tempfile
from pathlib import Path

import pytest

from growbridge import transport as transport_module

HELPER_PID = 4242


class FakeHost:
    """Stands in for the OS process table and for kill(2)."""

    def __init__(self):
        self.alive: set[int] = set()
        self.signals: list[tuple[int, int]] = []
        self.sigterm_kills = True

    def pid_alive(self, pid: int) -> bool:
        return pid in self.alive

    def send_signal(self, pid: int, sig: int) -> None:
        self.signals.append((pid, sig))
        if sig == signal.SIGTERM and self.sigterm_kills:
            self.alive.discard(pid)


class FakeProcess:
    def __init__(self):
        self.returncode = None
        self._done = asyncio.Event()

    async def wait(self):
        await self._done.wait()
        return self.returncode

    def finish(self):
        self.returncode = 0
        self._done.set()


class FakeHelper:
    """Plays the Swift helper: connects to events.sock, reports start/connected/ready.

    ``exits_on_hangup`` mirrors the new Swift behaviour (EOF on the channel -> exit).
    """

    def __init__(self, host: FakeHost, pid: int = HELPER_PID, exits_on_hangup: bool = True):
        self.host, self.pid, self.exits_on_hangup = host, pid, exits_on_hangup
        self.spawned = 0
        self.process: FakeProcess | None = None
        self._tasks: list[asyncio.Task] = []

    async def spawn(self, *args, **kwargs):
        self.spawned += 1
        socket_path = args[args.index("--socket") + 1]
        self.process = FakeProcess()
        self.host.alive.add(self.pid)
        reader, writer = await asyncio.open_unix_connection(socket_path)
        for event in (
            {"event": "start", "process_id": self.pid},
            {"event": "connected"},
            {"event": "command_mode_ready"},
        ):
            writer.write(json.dumps(event).encode() + b"\n")
        await writer.drain()
        self._tasks.append(asyncio.create_task(self._watch(reader, writer)))
        return self.process

    async def _watch(self, reader, writer):
        await reader.read()  # returns b"" once Python hangs up
        if self.exits_on_hangup:
            self.exit()
        writer.close()

    def exit(self):
        self.host.alive.discard(self.pid)
        if self.process:
            self.process.finish()

    async def shutdown(self):
        self.exit()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)


@pytest.fixture
def run_root():
    folder = Path(tempfile.mkdtemp(prefix="gbt-", dir="/tmp"))
    yield folder
    shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture
def host():
    return FakeHost()


@pytest.fixture
def helper(host):
    return FakeHelper(host)


@pytest.fixture
def make_native(run_root, host, helper, tmp_path, monkeypatch):
    monkeypatch.setattr(transport_module, "build_native", lambda _: tmp_path / "App.app")

    def factory(**overrides):
        options = {
            "run_root": run_root,
            "halt_timeout": 0.3,
            "poll_interval": 0.005,
            "spawn": helper.spawn,
            "pid_alive": host.pid_alive,
            "signal_pid": host.send_signal,
        }
        options.update(overrides)
        return transport_module.NativeTransport("SF-TEST", tmp_path, **options)

    return factory
