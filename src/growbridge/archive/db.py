"""SQLite access shared by the Auto Research services.

One connection per database file, explicit transactions, numbered migrations per namespace.
Never ``await`` inside ``transaction()``: every coroutine of the process shares the connection,
so a suspended transaction would absorb another coroutine's writes.
"""

import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

PRAGMAS = ("journal_mode=WAL", "foreign_keys=ON", "synchronous=FULL")


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self.connection = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        for pragma in PRAGMAS:
            self.connection.execute(f"PRAGMA {pragma}")
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_steps("
            "namespace TEXT NOT NULL, step INTEGER NOT NULL, PRIMARY KEY(namespace, step))"
        )
        self.lock = threading.RLock()
        self.depth = 0

    def migrate(self, namespace: str, steps: Sequence[str]) -> None:
        """Run each statement of ``steps`` once; a namespace only ever appends steps."""
        with self.transaction():
            rows = self.query("SELECT step FROM schema_steps WHERE namespace = ?", (namespace,))
            done = {row["step"] for row in rows}
            for index, statement in enumerate(steps):
                if index in done:
                    continue
                self.execute(statement)
                self.execute("INSERT INTO schema_steps VALUES (?, ?)", (namespace, index))

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Commit on exit, roll back on error; nested use rolls back only the inner block."""
        with self.lock:
            savepoint = f"sp{self.depth}"
            outermost = self.depth == 0
            self.connection.execute("BEGIN IMMEDIATE" if outermost else f"SAVEPOINT {savepoint}")
            self.depth += 1
            try:
                yield
            except BaseException:
                self.depth -= 1
                if outermost:
                    self.connection.execute("ROLLBACK")
                else:
                    self.connection.execute(f"ROLLBACK TO {savepoint}")
                    self.connection.execute(f"RELEASE {savepoint}")
                raise
            self.depth -= 1
            self.connection.execute("COMMIT" if outermost else f"RELEASE {savepoint}")

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        with self.lock:
            return self.connection.execute(sql, params)

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.connection.execute(sql, params).fetchall()

    def one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        with self.lock:
            return self.connection.execute(sql, params).fetchone()

    def close(self) -> None:
        with self.lock:
            self.connection.close()
