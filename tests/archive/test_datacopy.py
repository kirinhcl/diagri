import sqlite3
import stat
from pathlib import Path

import pytest

from growbridge.archive.datacopy import copy_data_dir, relocate_paths


def _make_db(path: Path, ddl: str, rows: list[tuple]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute(ddl)
    for row in rows:
        db.execute(f"INSERT INTO t VALUES ({','.join('?' * len(row))})", row)
    db.commit()
    db.close()


def _values(path: Path) -> list[tuple]:
    db = sqlite3.connect(path)
    try:
        return db.execute("SELECT * FROM t").fetchall()
    finally:
        db.close()


def test_copies_databases_files_and_skips_traces(tmp_path):
    src = tmp_path / "src"
    _make_db(src / "archive.sqlite3", "CREATE TABLE t(v TEXT)", [("row",)])
    (src / "agent_work" / "reports").mkdir(parents=True)
    (src / "agent_work" / "reports" / "r.json").write_text("{}")
    (src / "host_id").write_text("host-1")
    (src / "model_traces").mkdir()
    (src / "model_traces" / "x.jsonl").write_text("{}")
    (src / "archive.sqlite3-wal").write_text("junk")

    copy_data_dir(src, tmp_path / "copy")

    copy = tmp_path / "copy"
    assert _values(copy / "archive.sqlite3") == [("row",)]
    assert (copy / "agent_work" / "reports" / "r.json").read_text() == "{}"
    assert (copy / "host_id").read_text() == "host-1"
    assert not (copy / "model_traces").exists()
    assert not (copy / "archive.sqlite3-wal").exists()


def test_copy_includes_uncheckpointed_wal_writes(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    db = sqlite3.connect(src / "a.sqlite3")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE t(v TEXT)")
    db.execute("INSERT INTO t VALUES ('x')")
    db.commit()
    try:
        copy_data_dir(src, tmp_path / "copy")
    finally:
        db.close()
    assert _values(tmp_path / "copy" / "a.sqlite3") == [("x",)]


def test_target_must_not_exist(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (tmp_path / "copy").mkdir()
    with pytest.raises(FileExistsError):
        copy_data_dir(src, tmp_path / "copy")


def test_copy_dirs_are_0700(tmp_path):
    src = tmp_path / "src"
    (src / "agent_work" / "reports").mkdir(parents=True)
    (src / "agent_work" / "reports" / "r.json").write_text("{}")
    copy_data_dir(src, tmp_path / "copy")
    for rel in (".", "agent_work", "agent_work/reports"):
        mode = stat.S_IMODE((tmp_path / "copy" / rel).stat().st_mode)
        assert mode == 0o700, rel


def test_relocate_rewrites_paths_inside_json_bodies(tmp_path):
    db = tmp_path / "a.sqlite3"
    _make_db(
        db,
        "CREATE TABLE t(body TEXT)",
        [('{"path": "/x/data/agent_work/r.json"}',), ('{"other": 1}',)],
    )
    assert relocate_paths(tmp_path, "/x/data", "/y/copy") == 1
    assert _values(db) == [('{"path": "/y/copy/agent_work/r.json"}',), ('{"other": 1}',)]


def test_relocate_sets_values_equal_to_old(tmp_path):
    db = tmp_path / "a.sqlite3"
    _make_db(db, "CREATE TABLE t(v TEXT)", [("/x/data",)])
    assert relocate_paths(tmp_path, "/x/data", "/y/copy") == 1
    assert _values(db) == [("/y/copy",)]


def test_relocate_leaves_a_longer_sibling_path_alone(tmp_path):
    db = tmp_path / "a.sqlite3"
    _make_db(db, "CREATE TABLE t(v TEXT)", [("/x/database/a",), ("/x/data/a",)])
    assert relocate_paths(tmp_path, "/x/data", "/y/copy") == 1
    assert _values(db) == [("/x/database/a",), ("/y/copy/a",)]


def test_relocate_skips_non_text_columns(tmp_path):
    db = tmp_path / "a.sqlite3"
    _make_db(db, "CREATE TABLE t(v BLOB)", [(b"/x/data/a",)])
    assert relocate_paths(tmp_path, "/x/data", "/y/copy") == 0
    assert _values(db) == [(b"/x/data/a",)]
