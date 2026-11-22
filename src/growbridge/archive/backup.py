"""Consistent online database backup (architecture doc §11.4).

The copy is made from a separate read-only connection inside one read transaction, in page
steps, so it is a single consistent state and writers are never blocked. It is checked with
``PRAGMA integrity_check`` before it replaces the previous backup, and a small manifest (sha256,
size, time) is written next to it. A failed copy or check raises and leaves the previous backup
and ``last_backup`` untouched.
"""

import os
import sqlite3
from pathlib import Path

from growbridge.archive.clock import Clock
from growbridge.archive.db import Database
from growbridge.archive.ids import canonical_json, file_digest

NAMESPACE = "backup"
STEPS = ("CREATE TABLE backup_log(at REAL NOT NULL)",)
PAGES_PER_STEP = 256
MANIFEST_SUFFIX = ".manifest.json"


def copy_database(source_path: str, partial: Path, *, immutable: bool = False) -> None:
    """Copy the database file at ``source_path`` to ``partial`` without locking writers out.

    ``immutable`` promises that nothing writes the file, so SQLite creates no ``-wal``/``-shm``
    side files beside it (a pre-run copy must stay byte for byte as it was)."""
    uri = Path(source_path).resolve().as_uri() + (
        "?mode=ro&immutable=1" if immutable else "?mode=ro"
    )
    source = sqlite3.connect(uri, uri=True, isolation_level=None)
    copy = sqlite3.connect(partial)
    try:
        source.execute("BEGIN")
        source.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()  # pins the snapshot
        source.backup(copy, pages=PAGES_PER_STEP)
        source.execute("ROLLBACK")
    finally:
        copy.close()
        source.close()


def check_integrity(path: Path) -> str:
    """``"ok"`` when SQLite finds the file sound, otherwise a description of the problem."""
    try:
        connection = sqlite3.connect(path)
        try:
            rows = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        finally:
            connection.close()
    except sqlite3.DatabaseError as error:
        return str(error)
    return "ok" if rows == ["ok"] else "; ".join(rows)


def _write_manifest(target: Path, finished: float) -> None:
    manifest = target.with_name(target.name + MANIFEST_SUFFIX)
    partial = manifest.with_name(manifest.name + ".partial")
    body = {"sha256": file_digest(target), "size": target.stat().st_size, "created_at": finished}
    partial.write_text(canonical_json(body), encoding="utf-8")
    os.replace(partial, manifest)


def backup(db: Database, target: Path, clock: Clock) -> float:
    """Copy the database to ``target`` and return the completion time (UTC seconds)."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with db.lock:
        if db.depth:
            raise RuntimeError("cannot back up inside an open transaction")
    partial = target.with_name(target.name + ".partial")
    try:
        copy_database(db.path, partial)
        verdict = check_integrity(partial)
        if verdict != "ok":
            raise RuntimeError(f"backup integrity check failed: {verdict}")
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    os.replace(partial, target)
    finished = clock.now()
    _write_manifest(target, finished)
    db.migrate(NAMESPACE, STEPS)
    db.execute("INSERT INTO backup_log VALUES (?)", (finished,))
    return finished


def last_backup(db: Database) -> float | None:
    """Time of the most recent successful backup, or None if there never was one."""
    db.migrate(NAMESPACE, STEPS)
    row = db.one("SELECT MAX(at) AS at FROM backup_log")
    return None if row is None or row["at"] is None else float(row["at"])
