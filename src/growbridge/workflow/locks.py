"""Greenhouse locks: which operator holds which greenhouse (design 2026-11-16, multi-user).

A lock is taken for a whole selection at once or not at all. Releasing hands the device's care
right back first (the control service voids its queued writes) and then, in one transaction,
re-checks that nothing unfinished runs on the device, clears the stage's care pointer, marks the
stage so a restart does not restore that care, and deletes the lock. The device keeps its current
settings; protection rules keep running. Nothing here writes to a device.

The locks live in the workflow database, next to the stages: a run sheet submission checks the
lock in the transaction that inserts its stage, so it and a release never interleave.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from growbridge.archive.clock import Clock
from growbridge.archive.db import Database
from growbridge.config import Greenhouse
from growbridge.ports import ControlPort, Denied
from growbridge.workflow.store import WorkflowStore

NAMESPACE = "greenhouse_locks"
STEPS = (
    "CREATE TABLE greenhouse_locks(greenhouse_id TEXT PRIMARY KEY, holder TEXT NOT NULL,"
    " locked_at REAL NOT NULL)",
    "CREATE TABLE greenhouse_lock_events(id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " greenhouse_id TEXT NOT NULL, holder TEXT, action TEXT NOT NULL, actor TEXT NOT NULL,"
    " at REAL NOT NULL, note TEXT NOT NULL DEFAULT '')",
)


class GreenhouseLocks:
    def __init__(
        self,
        db: Database,
        clock: Clock,
        registry: Sequence[Greenhouse],
        store: WorkflowStore,
        control: ControlPort,
    ):
        self.db = db
        self.clock = clock
        self.registry = {house.id: house for house in registry}
        self.store = store
        self.control = control
        db.migrate(NAMESPACE, STEPS)

    # --- reading -------------------------------------------------------------------------------

    def greenhouse(self, greenhouse_id: str) -> Greenhouse:
        house = self.registry.get(greenhouse_id)
        if house is None:
            raise Denied("state", f"unknown greenhouse {greenhouse_id}")
        return house

    def _row(self, greenhouse_id: str) -> Any:
        return self.db.one(
            "SELECT * FROM greenhouse_locks WHERE greenhouse_id = ?", (greenhouse_id,)
        )

    def _of_device(self, device_id: str) -> Any:
        house = next((h for h in self.registry.values() if h.device_id == device_id), None)
        return None if house is None else self._row(house.id)

    def holder_of_device(self, device_id: str) -> str | None:
        row = self._of_device(device_id)
        return None if row is None else row["holder"]

    def locked_at(self, device_id: str) -> float | None:
        row = self._of_device(device_id)
        return None if row is None else row["locked_at"]

    def held_by(self, holder: str) -> tuple[str, ...]:
        rows = self.db.query(
            "SELECT greenhouse_id FROM greenhouse_locks WHERE holder = ? ORDER BY greenhouse_id",
            (holder,),
        )
        return tuple(row["greenhouse_id"] for row in rows)

    def overview(self) -> list[dict[str, Any]]:
        """Every registered greenhouse in registry order, with its holder (None when free)."""
        rows = {
            row["greenhouse_id"]: row for row in self.db.query("SELECT * FROM greenhouse_locks")
        }
        return [
            {
                "id": house.id,
                "name": house.name,
                "device_id": house.device_id,
                "holder": rows[house.id]["holder"] if house.id in rows else None,
                "locked_at": rows[house.id]["locked_at"] if house.id in rows else None,
            }
            for house in self.registry.values()
        ]

    def events(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM greenhouse_lock_events ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [dict(row) for row in rows]

    # --- locking -------------------------------------------------------------------------------

    def lock(self, holder: str, ids: Sequence[str]) -> tuple[str, ...]:
        """Lock every greenhouse in ``ids`` for ``holder``, or none of them."""
        wanted = tuple(ids)
        if not wanted or len(set(wanted)) != len(wanted):
            raise Denied("state", "name each greenhouse once")
        for greenhouse_id in wanted:
            self.greenhouse(greenhouse_id)
        now = self.clock.now()
        with self.db.transaction():
            taken = [gid for gid in wanted if self._row(gid) is not None]
            if taken:
                raise Denied("lock_taken", f"already locked: {', '.join(taken)}")
            for greenhouse_id in wanted:
                self.db.execute(
                    "INSERT INTO greenhouse_locks VALUES (?, ?, ?)", (greenhouse_id, holder, now)
                )
                self._record(greenhouse_id, holder, "lock", holder, "")
        return wanted

    def _record(self, greenhouse_id: str, holder: str | None, action: str, actor: str, note: str):
        self.db.execute(
            "INSERT INTO greenhouse_lock_events(greenhouse_id, holder, action, actor, at, note)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (greenhouse_id, holder, action, actor, self.clock.now(), note),
        )

    # --- releasing -----------------------------------------------------------------------------

    def _check_release(self, greenhouse_id: str, actor: str, force: bool) -> Any:
        house = self.greenhouse(greenhouse_id)
        row = self._row(greenhouse_id)
        if row is None or (not force and row["holder"] != actor):
            raise Denied("not_lock_holder", f"you do not hold greenhouse {greenhouse_id}")
        if self.store.device_unfinished(house.device_id):
            raise Denied("greenhouse_busy", "a stage on this greenhouse has not ended or stopped")
        return row

    async def release(
        self, greenhouse_id: str, actor: str, *, force: bool = False, note: str = ""
    ) -> None:
        """Hand the device's care back, then free the greenhouse (see the module docstring)."""
        self._check_release(greenhouse_id, actor, force)
        holder = self.store.care_holder(self.greenhouse(greenhouse_id).device_id)
        if holder is not None and holder.care_right is not None:
            await self.control.handover(holder.care_right, "release")
        self._finish_release(greenhouse_id, actor, force, note)

    def _finish_release(self, greenhouse_id: str, actor: str, force: bool, note: str) -> None:
        with self.db.transaction():
            row = self._check_release(greenhouse_id, actor, force)
            holder = self.store.care_holder(self.greenhouse(greenhouse_id).device_id)
            if holder is not None:
                self.store.update_stage(holder, care_right=None, care_released=True)
            self.db.execute(
                "DELETE FROM greenhouse_locks WHERE greenhouse_id = ?", (greenhouse_id,)
            )
            action = "force_release" if force else "release"
            self._record(greenhouse_id, row["holder"], action, actor, note)
