"""Device tests (design 2026-11-27): a lock holder's short on-site test of one channel.

On an idle greenhouse (no stage started since its last release) the holder switches light,
exhaust, fan or pump on for a moment to watch it work. The server keeps time: it snapshots the
channel's whole AC5 configuration block, pauses the idle levels, writes the test value under a
TEST right, waits, and writes the block back unchanged (mode, timers and level), so the AC5's
own program is untouched. A channel a protection rule holds is not tested, and is left to the
rule when one starts holding it during the wait.

A test whose restore failed, or that a restart interrupted, stays unsettled: the device then
refuses further tests, stage starts and its holder's release until the restore is retried or the
holder confirms on site.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import nullcontext
from typing import Any

from growbridge.archive.clock import Clock
from growbridge.archive.db import Database
from growbridge.archive.ids import new_id
from growbridge.archive.models import ActionRecord, ActionState, Channel, Model, RightKind
from growbridge.config import Greenhouse
from growbridge.control import refusals
from growbridge.ports import ActionRequest, Actor, ChannelSnapshot, ControlPort, RightScope
from growbridge.service import BridgeError
from growbridge.workflow import denials as workflow_denials
from growbridge.workflow import device_test_denials as denials
from growbridge.workflow.access import Access
from growbridge.workflow.idle import IdleCare
from growbridge.workflow.locks import GreenhouseLocks
from growbridge.workflow.store import WorkflowStore

log = logging.getLogger(__name__)

NAMESPACE = "device_tests"
STEPS = (
    "CREATE TABLE device_tests(test_id TEXT PRIMARY KEY, greenhouse_id TEXT NOT NULL,"
    " device_id TEXT NOT NULL, channel TEXT NOT NULL, operator TEXT NOT NULL,"
    " state TEXT NOT NULL, result TEXT, snapshot TEXT, right_number INTEGER,"
    " started_at REAL NOT NULL, ended_at REAL, note TEXT NOT NULL DEFAULT '')",
)
TEST_LEVELS = {Channel.LIGHT: 100, Channel.EXHAUST: 100, Channel.FAN: 10}
TEST_SECONDS = 10
PUMP_SECONDS = 3
OPEN_STATES = ("running", "restore_failed")
ALERT = "device_test_restore_failed"
HISTORY = 20


class DeviceTestRecord(Model):
    test_id: str
    greenhouse_id: str
    device_id: str
    channel: Channel
    operator: str
    state: str  # running, done, restore_failed, settled_onsite
    result: str | None = None  # restored, restore_failed, protected
    snapshot: ChannelSnapshot | None = None
    right_number: int | None = None
    started_at: float
    ended_at: float | None = None
    note: str = ""


def _ignore(*_args: Any, **_kwargs: Any) -> None:
    return None


class DeviceTests:
    def __init__(
        self,
        db: Database,
        clock: Clock,
        control: ControlPort,
        locks: GreenhouseLocks,
        access: Access,
        store: WorkflowStore,
        idle: IdleCare | None,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_pump_seconds: float = 5,
    ):
        self.db, self.clock, self.control = db, clock, control
        self.locks, self.access, self.store, self.idle = locks, access, store, idle
        self.sleep = sleep
        self.pump_seconds = min(PUMP_SECONDS, max_pump_seconds)
        # bound once the executor and the runtime exist (runtime_access.wire_device_tests)
        self.protected: Callable[[], frozenset[Channel]] = frozenset
        self.alert: Callable[..., None] = _ignore
        self.resolve: Callable[..., object] = _ignore
        self._active: set[str] = set()  # tests this process is running now
        db.migrate(NAMESPACE, STEPS)

    # --- reading -------------------------------------------------------------------------------

    def open_test(self, device_id: str) -> DeviceTestRecord | None:
        """The device's running or unrestored test, if any."""
        row = self.db.one(
            "SELECT * FROM device_tests WHERE device_id = ? AND state IN (?, ?)"
            " ORDER BY started_at DESC, rowid DESC LIMIT 1",
            (device_id, *OPEN_STATES),
        )
        return None if row is None else _record(row)

    def running(self, device_id: str) -> DeviceTestRecord | None:
        """The test this process is running on the device now."""
        record = self.open_test(device_id)
        return record if record is not None and record.test_id in self._active else None

    def unsettled(self, device_id: str) -> DeviceTestRecord | None:
        """A test that did not restore the device, or that a restart interrupted."""
        record = self.open_test(device_id)
        return record if record is not None and record.test_id not in self._active else None

    def record(self, test_id: str) -> DeviceTestRecord | None:
        row = self.db.one("SELECT * FROM device_tests WHERE test_id = ?", (test_id,))
        return None if row is None else _record(row)

    def history(self, greenhouse_id: str, limit: int = HISTORY) -> list[DeviceTestRecord]:
        rows = self.db.query(
            "SELECT * FROM device_tests WHERE greenhouse_id = ?"
            " ORDER BY started_at DESC, rowid DESC LIMIT ?",
            (greenhouse_id, limit),
        )
        return [_record(row) for row in rows]

    def testable(self, row: dict[str, Any], actor: Actor) -> bool:
        """``row`` is one of ``GreenhouseLocks.overview()``."""
        device = row["device_id"]
        mine = row["holder"] == actor.id and device == self.access.local_device
        return mine and self.idle_device(device) and self.open_test(device) is None

    def idle_device(self, device_id: str) -> bool:
        last = self.store.last_started_on(device_id)
        return last is None or last.care_released

    # --- running a test ------------------------------------------------------------------------

    async def run(self, greenhouse_id: str, channel: Channel, actor: Actor) -> dict[str, Any]:
        house = self._check(greenhouse_id, channel, actor)
        record = self._begin(house, channel, actor)
        try:
            snapshot = await self.control.snapshot(channel)
        except BaseException as error:
            self.db.execute("DELETE FROM device_tests WHERE test_id = ?", (record.test_id,))
            if isinstance(error, (BridgeError, ConnectionError, OSError)):
                raise refusals.no_live_link(house.device_id) from error
            raise
        self._active.add(record.test_id)
        try:
            return await self._exercise(record, snapshot)
        finally:
            self._active.discard(record.test_id)

    def _check(self, greenhouse_id: str, channel: Channel, actor: Actor) -> Greenhouse:
        """Every refusal comes before anything is written or stored."""
        house = self.locks.greenhouse(greenhouse_id)
        if self.locks.holder_of_device(house.device_id) != actor.id:
            raise denials.not_held(greenhouse_id)
        if house.device_id != self.access.local_device:
            raise denials.not_local(greenhouse_id)
        self._check_state(house, channel)
        return house

    def _check_state(self, house: Greenhouse, channel: Channel) -> None:
        if not self.idle_device(house.device_id):
            raise denials.not_idle(house.id)
        self._check_free(house)
        if channel in self.protected():
            raise denials.protected(house.id, channel.value)

    def _check_free(self, house: Greenhouse) -> None:
        current = self.open_test(house.device_id)
        if current is None:
            return
        if current.test_id in self._active:
            raise denials.running(house.id, current.channel.value)
        raise denials.unsettled(house.id, current.test_id)

    def _begin(self, house: Greenhouse, channel: Channel, actor: Actor) -> DeviceTestRecord:
        record = DeviceTestRecord(
            test_id=new_id("devtest"),
            greenhouse_id=house.id,
            device_id=house.device_id,
            channel=channel,
            operator=actor.id,
            state="running",
            started_at=self.clock.now(),
        )
        self.db.execute(
            "INSERT INTO device_tests(test_id, greenhouse_id, device_id, channel, operator,"
            " state, started_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                record.test_id,
                house.id,
                house.device_id,
                channel.value,
                actor.id,
                "running",
                record.started_at,
            ),
        )
        return record

    async def _exercise(self, record: DeviceTestRecord, snapshot: ChannelSnapshot) -> dict:
        actions: list[str] = []
        result = "restore_failed"
        async with self._idle_paused():
            right = self._grant(record, snapshot)
            try:
                switched = await self._switch_on(record, right)
                actions.append(switched.request_id)
                if switched.state is ActionState.CONFIRMED and record.channel is not Channel.PUMP:
                    await self.sleep(TEST_SECONDS)
            finally:
                result = await self._put_back(record, right, snapshot, actions)
                await self.control.handover(right, "device test")
                self._finish(record, result)
        return self._reply(record, result, actions)

    def _idle_paused(self):
        return self.idle.paused() if self.idle is not None else nullcontext()

    def _grant(self, record: DeviceTestRecord, snapshot: ChannelSnapshot) -> int:
        scope = RightScope(device_id=record.device_id, channels=(record.channel,))
        right = self.control.grant(RightKind.TEST, scope, record.operator)
        self.db.execute(
            "UPDATE device_tests SET snapshot = ?, right_number = ? WHERE test_id = ?",
            (snapshot.model_dump_json(), right, record.test_id),
        )
        return right

    async def _switch_on(self, record: DeviceTestRecord, right: int) -> ActionRecord:
        if record.channel is Channel.PUMP:
            request = self._request(record, right, f"{record.test_id}-on", 1)
            return await self.control.irrigate(request, self.pump_seconds)
        level = TEST_LEVELS[record.channel]
        return await self.control.submit(
            self._request(record, right, f"{record.test_id}-on", level)
        )

    async def _put_back(
        self, record: DeviceTestRecord, right: int, snapshot: ChannelSnapshot, actions: list[str]
    ) -> str:
        """Write the snapshot back, unless a protection rule now holds the channel."""
        if record.channel in self.protected():
            return "protected"
        request_id = new_id(f"{record.test_id}-restore")
        request = self._request(record, right, request_id, snapshot.level or 0)
        try:
            restored = await self.control.restore(request, snapshot)
        except Exception:
            log.exception("device test %s: restore refused or failed", record.test_id)
            return "restore_failed"
        actions.append(restored.request_id)
        return "restored" if restored.state is ActionState.CONFIRMED else "restore_failed"

    def _request(self, record: DeviceTestRecord, right: int, request_id: str, level: int):
        return ActionRequest(
            request_id=request_id,
            right_number=right,
            channel=record.channel,
            level=level,
            trigger=f"device_test:{record.test_id}",
            operator=record.operator,
        )

    def _finish(self, record: DeviceTestRecord, result: str, resolve: bool = False) -> None:
        state = "restore_failed" if result == "restore_failed" else "done"
        with self.db.transaction():
            self.db.execute(
                "UPDATE device_tests SET state = ?, result = ?, ended_at = ? WHERE test_id = ?",
                (state, result, self.clock.now(), record.test_id),
            )
            note = f"{record.channel.value}: {result}"
            self.locks.note_event(record.greenhouse_id, "test", record.operator, note)
        if state == "restore_failed":
            self._report_failure(record)
        elif resolve:
            self.resolve(ALERT, record.test_id, ("device", record.device_id))

    def _report_failure(self, record: DeviceTestRecord) -> None:
        params = {
            "greenhouse_id": record.greenhouse_id,
            "channel": record.channel.value,
            "test_id": record.test_id,
        }
        message = (
            f"Device test {record.test_id} could not restore {record.channel.value} on"
            f" greenhouse {record.greenhouse_id}; check the device on site"
        )
        scope = ("device", record.device_id)
        self.alert(
            ALERT,
            record.test_id,
            message,
            "critical",
            scope,
            code="device_test_restore_failed",
            params=params,
        )

    # --- unsettled tests -----------------------------------------------------------------------

    async def retry(self, greenhouse_id: str, test_id: str, actor: Actor) -> dict[str, Any]:
        """Write an unrestored test's snapshot back again, under a fresh TEST right."""
        record = self._own_open(greenhouse_id, test_id, actor)
        actions: list[str] = []
        result = await self._restore_again(record, actions)
        return self._reply(record, result, actions)

    def settle(self, greenhouse_id: str, test_id: str, actor: Actor, note: str) -> DeviceTestRecord:
        """The holder checked the device on site: the test no longer blocks the greenhouse."""
        if not note.strip():
            raise ValueError("settling a device test needs a note")
        record = self._own_open(greenhouse_id, test_id, actor)
        with self.db.transaction():
            self._mark_settled(record, actor.id, note.strip())
        return self.record(test_id) or record

    def settle_for_release(self, device_id: str, actor: str, note: str) -> None:
        """An administrator's forced release: the device's unsettled test is settled with it."""
        record = self.unsettled(device_id)
        if record is not None:
            self._mark_settled(record, actor, note)

    async def resume(self) -> None:
        """Each runtime tick: one restore attempt for every test a restart left running, once
        the device link is usable."""
        ready = self.control.connected() and self.control.transport_stopped()
        if not ready or self.control.interlocked():
            return
        rows = self.db.query("SELECT test_id FROM device_tests WHERE state = 'running'")
        for row in rows:
            record = self.record(row["test_id"])
            if record is not None and record.test_id not in self._active:
                await self._restore_again(record, [])

    def _own_open(self, greenhouse_id: str, test_id: str, actor: Actor) -> DeviceTestRecord:
        house = self.locks.greenhouse(greenhouse_id)
        if self.locks.holder_of_device(house.device_id) != actor.id:
            raise denials.not_held(greenhouse_id)
        record = self.record(test_id)
        if record is None or record.greenhouse_id != greenhouse_id:
            raise workflow_denials.record_not_found("device_test", test_id, "no such device test")
        if record.state not in OPEN_STATES:
            raise workflow_denials.record_not_found("device_test", test_id, "test already settled")
        if record.test_id in self._active:
            raise denials.running(greenhouse_id, record.channel.value)
        return record

    async def _restore_again(self, record: DeviceTestRecord, actions: list[str]) -> str:
        if record.snapshot is None:  # cut off before anything was written
            self._finish(record, "restored", resolve=True)
            return "restored"
        self._active.add(record.test_id)
        try:
            async with self._idle_paused():
                right = self._grant(record, record.snapshot)
                try:
                    result = await self._put_back(record, right, record.snapshot, actions)
                finally:
                    await self.control.handover(right, "device test")
            self._finish(record, result, resolve=True)
            return result
        finally:
            self._active.discard(record.test_id)

    def _mark_settled(self, record: DeviceTestRecord, actor: str, note: str) -> None:
        self.db.execute(
            "UPDATE device_tests SET state = 'settled_onsite', note = ? WHERE test_id = ?",
            (note, record.test_id),
        )
        self.locks.note_event(record.greenhouse_id, "test_settled", actor, note)
        self.resolve(ALERT, record.test_id, ("device", record.device_id))

    def _reply(self, record: DeviceTestRecord, result: str, actions: list[str]) -> dict:
        pump = record.channel is Channel.PUMP
        return {
            "test_id": record.test_id,
            "channel": record.channel.value,
            "test_level": 1 if pump else TEST_LEVELS[record.channel],
            "seconds": self.pump_seconds if pump else TEST_SECONDS,
            "result": result,
            "actions": actions,
        }


def _record(row: Any) -> DeviceTestRecord:
    data = dict(row)
    snapshot = data.pop("snapshot")
    if snapshot is not None:
        data["snapshot"] = ChannelSnapshot.model_validate_json(snapshot)
    return DeviceTestRecord.model_validate(data)
