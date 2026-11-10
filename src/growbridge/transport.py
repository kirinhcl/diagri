"""One BLE owner: a signed native helper on macOS, Bleak/BlueZ on Linux."""

import asyncio
import contextlib
import hashlib
import json
import os
import plistlib
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from .protocol import NOTIFY_UUID, WRITE_UUID, encode


def build_native(data_dir: Path) -> Path:
    source = Path(__file__).parent / "native" / "BLEHelper.swift"
    app = data_dir / "GrowBridge BLE.app"
    executable = app / "Contents" / "MacOS" / "sf-ble"
    if executable.exists() and executable.stat().st_mtime >= source.stat().st_mtime:
        return app
    executable.parent.mkdir(parents=True, exist_ok=True)
    info = {
        "CFBundleIdentifier": "local.growbridge.ble",
        "CFBundleName": "GrowBridge BLE",
        "CFBundleExecutable": "sf-ble",
        "CFBundlePackageType": "APPL",
        "CFBundleVersion": "1",
        "LSUIElement": True,
        "NSBluetoothAlwaysUsageDescription": "连接 Spider Farmer，读取数据并按你的指令控制设备。",
    }
    (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps(info))
    subprocess.run(
        [
            "xcrun",
            "swiftc",
            str(source),
            "-o",
            str(executable),
            "-framework",
            "CoreBluetooth",
            "-framework",
            "AppKit",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["codesign", "--force", "--sign", "-", str(app)], check=True, capture_output=True
    )
    return app


async def scan_devices(data_dir: Path, seconds: int = 8) -> list[dict]:
    if sys.platform != "darwin":
        from bleak import BleakScanner

        devices = await BleakScanner.discover(timeout=seconds, return_adv=True)
        return [
            {"name": adv.local_name or device.name, "address": device.address, "rssi": adv.rssi}
            for device, adv in devices.values()
            if (adv.local_name or device.name or "").startswith("SF-")
        ]
    app = await asyncio.to_thread(build_native, data_dir)
    with tempfile.TemporaryDirectory(prefix="growbridge-scan-", dir="/tmp") as folder:
        output = Path(folder) / "scan.jsonl"
        process = await asyncio.create_subprocess_exec(
            "open",
            "-n",
            "-W",
            str(app),
            "--args",
            "--output",
            str(output),
            "--scan-seconds",
            str(seconds),
            "--listen-seconds",
            "0",
        )
        await asyncio.wait_for(process.wait(), timeout=110)
        events = [json.loads(line) for line in output.read_text().splitlines()]
        if events[-1].get("reason") != "scan_complete":
            raise RuntimeError(f"Bluetooth scan failed: {events[-1].get('reason')}")
        return [
            {"name": event["name"], "address": event["id"], "rssi": event["rssi"]}
            for event in events
            if event["event"] == "device" and event.get("name", "").startswith("SF-")
        ]


HELPER_NAME = "sf-ble"
HALT_TIMEOUT_SECONDS = 15.0
POLL_INTERVAL_SECONDS = 0.1
SEND_TIMEOUT_SECONDS = 10
START_TIMEOUT_SECONDS = 100


def helper_alive(pid: int) -> bool:
    """True while ``pid`` is a live GrowBridge BLE helper (guards against pid reuse)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False  # alive but not ours, so it cannot be our helper
    name = subprocess.run(
        ["ps", "-o", "comm=", "-p", str(pid)], capture_output=True, text=True, check=False
    ).stdout.strip()
    return name.endswith(HELPER_NAME)


def signal_pid(pid: int, sig: int) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, sig)


def folder_trusted(path: Path, uid: int) -> bool:
    """True for a real directory owned by ``uid`` with no group/other permission bits."""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISDIR(info.st_mode) and info.st_uid == uid and not info.st_mode & 0o077


class NativeTransport:
    """macOS transport. ``halt`` confirms the old helper process (and so its BLE session) ended.

    ``run_root``, ``halt_timeout``, ``poll_interval``, ``spawn``, ``pid_alive`` and
    ``signal_pid`` are injectable so tests never touch a radio or launch the helper app.
    """

    def __init__(
        self,
        device: str,
        data_dir: Path,
        *,
        run_root: Path | None = None,
        halt_timeout: float = HALT_TIMEOUT_SECONDS,
        poll_interval: float = POLL_INTERVAL_SECONDS,
        spawn=None,
        pid_alive=helper_alive,
        signal_pid=signal_pid,
        get_uid=os.getuid,
    ):
        self.device, self.data_dir = device, data_dir
        self.halt_timeout, self.poll_interval = halt_timeout, poll_interval
        self._spawn = spawn or asyncio.create_subprocess_exec
        self._pid_alive, self._signal = pid_alive, signal_pid
        self._get_uid = get_uid
        key = hashlib.sha1(device.encode()).hexdigest()[:8]
        self.folder = (run_root or Path("/tmp")) / f"growbridge-{key}"
        self.commands = self.folder / "commands"
        self.connected = False
        self.halted = False
        self.pending: dict[str, asyncio.Future] = {}
        self.ready = asyncio.Event()
        self.tasks: set[asyncio.Task] = set()
        self.writers: set[asyncio.StreamWriter] = set()
        self.process = None
        self.server = None
        self.failure = None
        self.native_pid = None

    @property
    def pid_file(self) -> Path:
        return self.folder / "helper.pid"

    def _folder_trusted(self) -> bool:
        return folder_trusted(self.folder, self._get_uid())

    def _read_pid(self) -> int | None:
        if not self._folder_trusted():
            return None  # never trust a pid file from a folder others could have written
        try:
            return int(self.pid_file.read_text().strip())
        except (OSError, ValueError):
            return None

    def _write_pid(self, pid: int) -> None:
        temporary = self.pid_file.with_suffix(".tmp")
        temporary.write_text(str(pid))
        temporary.chmod(0o600)
        temporary.replace(self.pid_file)

    def _clear_pid(self) -> None:
        with contextlib.suppress(OSError):
            self.pid_file.unlink()

    async def _wait_dead(self, pid: int, timeout: float) -> bool:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while self._pid_alive(pid):
            if loop.time() >= deadline:
                return False
            await asyncio.sleep(self.poll_interval)
        return True

    async def _stop_stale_helper(self) -> None:
        pid = self._read_pid()
        if pid is not None and self._pid_alive(pid):
            self._signal(pid, signal.SIGTERM)
            if not await self._wait_dead(pid, self.halt_timeout):
                raise RuntimeError(f"Previous BLE helper (pid {pid}) is still running")
        self._clear_pid()

    def _handle_event(self, event: dict) -> None:
        kind = event["event"]
        if kind == "start":
            self.native_pid = event.get("process_id")
            if isinstance(self.native_pid, int):
                self._write_pid(self.native_pid)
        elif kind == "connected":
            self.connected = True
        elif kind == "command_mode_ready":
            self.ready.set()
        elif kind == "value":
            self.callback(bytes.fromhex(event["hex"]))
        elif kind == "command_written":
            future = self.pending.get(event["msgId"])
            if future is not None and not future.done():
                future.set_result(None)
        elif kind in {"complete", "write_error", "command_error"}:
            self.failure = RuntimeError(f"BLE helper: {event.get('reason', kind)}")
            self.connected = False
            self.ready.set()
            self._fail_pending(self.failure)

    def _fail_pending(self, error: Exception) -> None:
        for future in self.pending.values():
            if not future.done():
                future.set_exception(error)

    async def _serve(self, reader, writer) -> None:
        self.writers.add(writer)
        try:
            while line := await reader.readline():
                self._handle_event(json.loads(line))
        finally:
            self.connected = False
            self.ready.set()
            self.writers.discard(writer)
            writer.close()
            await writer.wait_closed()

    def _on_connection(self, reader, writer) -> None:
        task = asyncio.create_task(self._serve(reader, writer))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def _prepare_folder(self) -> None:
        if os.path.lexists(self.folder):
            if not self._folder_trusted():
                raise RuntimeError(
                    f"Untrusted BLE run folder {self.folder}: it must be a real directory "
                    "owned by this user with mode 0700; remove it and retry"
                )
            shutil.rmtree(self.folder)
        self.folder.mkdir(mode=0o700, parents=True)
        if not self._folder_trusted():
            raise RuntimeError(f"Untrusted BLE run folder {self.folder} after creation")
        self.commands.mkdir(mode=0o700)
        self.failure, self.native_pid, self.halted = None, None, False
        self.ready.clear()

    async def connect(self, callback):
        self.callback = callback
        app = await asyncio.to_thread(build_native, self.data_dir)
        await self._stop_stale_helper()
        self._prepare_folder()
        socket_path = self.folder / "events.sock"
        self.server = await asyncio.start_unix_server(
            self._on_connection, str(socket_path), limit=1048576
        )
        self.process = await self._spawn(
            "open",
            "-n",
            "-W",
            str(app),
            "--args",
            "--output",
            str(self.folder / "unused.jsonl"),
            "--socket",
            str(socket_path),
            "--target",
            self.device,
            "--scan-seconds",
            "20",
            "--listen-seconds",
            "0",
            "--command-dir",
            str(self.commands),
        )
        await asyncio.wait_for(self.ready.wait(), START_TIMEOUT_SECONDS)
        if self.failure or not self.connected:
            raise self.failure or RuntimeError("Bluetooth connection unavailable")

    async def send(self, command: dict):
        if self.halted or not self.connected:
            raise ConnectionError("BLE disconnected")
        message_id = command["msgId"]
        future = asyncio.get_running_loop().create_future()
        self.pending[message_id] = future
        path = self.commands / f"{message_id}.json"
        temporary = path.with_suffix(".pending")
        temporary.write_text(json.dumps({"command": command, "transport": "framed"}))
        temporary.chmod(0o600)
        temporary.replace(path)
        try:
            await asyncio.wait_for(future, SEND_TIMEOUT_SECONDS)
        finally:
            self.pending.pop(message_id, None)

    def _request_stop(self) -> None:
        """Ask the helper to stop. This is only a request, never a confirmation."""
        if self.commands.exists():
            (self.commands / "STOP").touch()
        for writer in list(self.writers):
            writer.close()  # EOF on the event channel makes the helper drop its queue and exit

    async def halt(self) -> bool:
        """True only once the helper process (the sole BLE writer) is confirmed gone."""
        self.halted = True
        self.connected = False
        self._fail_pending(ConnectionError("BLE write path halted"))
        pid = self.native_pid or self._read_pid()
        if pid is None:
            return self.process is None or self.process.returncode is not None
        self._request_stop()
        half = self.halt_timeout / 2
        confirmed = await self._wait_dead(pid, half)
        if not confirmed:
            self._signal(pid, signal.SIGTERM)
            confirmed = await self._wait_dead(pid, half)
        if confirmed:
            self._clear_pid()
        return confirmed

    async def close(self):
        confirmed = await self.halt()
        if confirmed and self.process:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.process.wait(), self.halt_timeout)
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        for task in list(self.tasks):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        if confirmed:
            shutil.rmtree(self.folder, ignore_errors=True)
        self.connected = False


class BleakTransport:
    def __init__(self, device: str, data_dir: Path, *, halt_timeout: float = HALT_TIMEOUT_SECONDS):
        self.device = device
        self.halt_timeout = halt_timeout
        self.halted = False
        self.client = None

    @property
    def connected(self):
        return self.client is not None and self.client.is_connected

    async def connect(self, callback):
        from bleak import BleakClient, BleakScanner

        self.halted = False
        device = await BleakScanner.find_device_by_address(self.device, timeout=20)
        if device is None:
            raise ConnectionError("Configured BLE address was not found; run growbridge scan")
        self.client = BleakClient(device, timeout=20)
        await self.client.connect()
        await self.client.start_notify(NOTIFY_UUID, lambda _, data: callback(bytes(data)))

    async def send(self, command: dict):
        for packet in encode(command, chunk_size=80):
            if self.halted:
                raise ConnectionError("BLE write path halted")
            await self.client.write_gatt_char(WRITE_UUID, packet, response=True)
            await asyncio.sleep(0.04)

    async def halt(self) -> bool:
        """True only when the BLE session is confirmed disconnected; no later write can occur."""
        self.halted = True
        client = self.client
        if client is None:
            return True
        try:
            await asyncio.wait_for(client.disconnect(), self.halt_timeout)
        except Exception:  # noqa: BLE001 - any failure to disconnect is "not confirmed"
            return False
        return not client.is_connected

    async def close(self):
        if self.client:
            await self.client.disconnect()


def make_transport(settings):
    backend = NativeTransport if sys.platform == "darwin" else BleakTransport
    return backend(settings.device, settings.data_dir)
