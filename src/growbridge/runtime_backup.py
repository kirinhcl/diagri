"""Scheduled online backups of the runtime's databases (architecture doc §8.2, §12).

``Backups.step`` is called from the tick. It only decides whether a backup is due and starts it as
a background task, so a slow copy never holds up the executor. The age of the oldest "last
successful backup" over all databases feeds the ``offsite_backup`` run-health probe.
"""

import asyncio
import logging
from collections.abc import Callable, Mapping
from pathlib import Path

from growbridge.archive.backup import backup, last_backup
from growbridge.archive.clock import Clock
from growbridge.archive.db import Database

log = logging.getLogger(__name__)

RETRY_SECONDS = 300.0  # real seconds to wait after a failed attempt
LIMIT_FACTOR = 2.0  # the probe fails when the last backup is older than this many intervals

Notify = Callable[..., None]  # (kind, key, message, severity=..., *, code=None, params=None)


class Backups:
    def __init__(
        self,
        databases: Mapping[str, Database],
        directory: Path | None,
        interval_seconds: float,
        clock: Clock,
        alert: Notify,
        resolve: Callable[[str, str], object],
    ):
        self.databases = dict(databases)
        self.directory = directory
        self.interval_seconds = interval_seconds
        self.clock = clock
        self.alert = alert
        self.resolve = resolve
        self.task: asyncio.Task | None = None
        self.retry_at = 0.0

    @property
    def limit_seconds(self) -> float:
        return self.interval_seconds * LIMIT_FACTOR

    def last_success(self) -> float | None:
        """When the least recently backed-up database was last saved; ``None`` if any never was."""
        times = [last_backup(db) for db in self.databases.values()]
        return None if any(t is None for t in times) else min(t for t in times if t is not None)

    def age(self) -> float | None:
        saved = self.last_success()
        return None if saved is None else self.clock.now() - saved

    def step(self) -> None:
        if self.directory is None or (self.task is not None and not self.task.done()):
            return
        age = self.age()
        due = age is None or age >= self.interval_seconds
        if due and asyncio.get_running_loop().time() >= self.retry_at:
            self.task = asyncio.create_task(self._run(self.directory))

    async def _run(self, directory: Path) -> None:
        try:
            for name, db in self.databases.items():
                await asyncio.to_thread(backup, db, directory / f"{name}.sqlite3", self.clock)
        except Exception as error:
            log.exception("backup failed")
            self.retry_at = asyncio.get_running_loop().time() + RETRY_SECONDS
            message = f"Backup failed: {type(error).__name__}: {error}"
            self.alert("backup", "databases", message, code="backup")
            return
        self.resolve("backup", "databases")

    async def close(self) -> None:
        task = self.task
        if task is not None and not task.done():
            task.cancel()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
