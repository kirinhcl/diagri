"""Copy a data directory while the service may be writing to it, and relocate stored paths.

Databases are copied through the online backup API (one consistent snapshot each, writers are
never locked out); ``-wal``/``-shm``/``-journal`` side files and the model-trace directory are
left behind. Report artifacts are stored with their absolute path inside database columns, so
``relocate_paths`` rewrites those paths in the copy to point at the copy.
"""

import shutil
import sqlite3
from pathlib import Path

from growbridge.agents.trace import TRACE_DIR
from growbridge.archive.backup import copy_database

DATABASE_SUFFIX = ".sqlite3"
SKIPPED_SUFFIXES = ("-wal", "-shm", "-journal")
DIR_MODE = 0o700


def copy_data_dir(source: Path, target: Path, *, immutable: bool = False) -> None:
    """Copy ``source`` to the not yet existing ``target`` without writing to ``source``."""
    if target.exists():
        raise FileExistsError(f"copy target already exists: {target}")
    target.mkdir(mode=DIR_MODE, parents=True)
    target.chmod(DIR_MODE)
    _copy_tree(source, target, is_root=True, immutable=immutable)


def _copy_tree(source: Path, target: Path, *, is_root: bool, immutable: bool) -> None:
    for entry in sorted(source.iterdir()):
        if is_root and entry.name == TRACE_DIR:
            continue
        destination = target / entry.name
        if entry.is_dir():
            destination.mkdir(mode=DIR_MODE)
            destination.chmod(DIR_MODE)
            _copy_tree(entry, destination, is_root=False, immutable=immutable)
        elif entry.name.endswith(SKIPPED_SUFFIXES):
            continue
        elif entry.name.endswith(DATABASE_SUFFIX):
            copy_database(str(entry), destination, immutable=immutable)
        else:
            shutil.copy2(entry, destination)


def relocate_paths(data_dir: Path, old: str, new: str) -> int:
    """Rewrite ``old`` path prefixes to ``new`` in every text column of every database."""
    changed = 0
    for database in sorted(data_dir.rglob(f"*{DATABASE_SUFFIX}")):
        changed += _relocate_database(database, old, new)
    return changed


def _relocate_database(path: Path, old: str, new: str) -> int:
    connection = sqlite3.connect(path, isolation_level=None)
    changed = 0
    try:
        connection.execute("BEGIN IMMEDIATE")
        try:
            for table in _tables(connection):
                changed += _relocate_table(connection, table, old, new)
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        connection.execute("COMMIT")
    finally:
        connection.close()
    return changed


def _tables(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    )
    return [row[0] for row in rows]


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _relocate_table(connection: sqlite3.Connection, table: str, old: str, new: str) -> int:
    columns = [
        _quote(row[1])
        for row in connection.execute(f"PRAGMA table_info({_quote(table)})")
        if "TEXT" in (row[2] or "").upper()
    ]
    if not columns:
        return 0
    assignments = ", ".join(
        f"{c} = CASE WHEN typeof({c}) = 'text' THEN "
        f"CASE WHEN {c} = :old THEN :new ELSE replace({c}, :old_slash, :new_slash) END "
        f"ELSE {c} END"
        for c in columns
    )
    matches = " OR ".join(
        f"(typeof({c}) = 'text' AND ({c} = :old OR instr({c}, :old_slash) > 0))" for c in columns
    )
    params = {"old": old, "new": new, "old_slash": old + "/", "new_slash": new + "/"}
    cursor = connection.execute(f"UPDATE {_quote(table)} SET {assignments} WHERE {matches}", params)
    return cursor.rowcount
