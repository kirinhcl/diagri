import pytest

from growbridge.archive.db import Database
from growbridge.archive.ids import canonical_json, content_digest, file_digest, new_id


def make(tmp_path):
    db = Database(tmp_path / "demo.sqlite3")
    db.migrate("demo", ["CREATE TABLE item(id TEXT PRIMARY KEY, note TEXT)"])
    return db


def test_migrate_applies_each_step_once(tmp_path):
    db = make(tmp_path)
    db.execute("INSERT INTO item VALUES (?, ?)", ("a", "kept"))

    db.migrate(
        "demo",
        ["CREATE TABLE item(id TEXT PRIMARY KEY, note TEXT)", "ALTER TABLE item ADD COLUMN n INT"],
    )

    row = db.one("SELECT note, n FROM item WHERE id = ?", ("a",))
    assert (row["note"], row["n"]) == ("kept", None)
    db.close()


def test_namespaces_do_not_share_step_numbers(tmp_path):
    db = make(tmp_path)

    db.migrate("other", ["CREATE TABLE other_item(id TEXT PRIMARY KEY)"])

    assert db.query("SELECT * FROM other_item") == []
    db.close()


def test_outer_transaction_rolls_back_every_write(tmp_path):
    db = make(tmp_path)

    with pytest.raises(RuntimeError):
        with db.transaction():
            db.execute("INSERT INTO item VALUES (?, ?)", ("a", None))
            raise RuntimeError("abort")

    assert db.query("SELECT * FROM item") == []
    db.close()


def test_nested_transaction_rolls_back_only_the_inner_write(tmp_path):
    db = make(tmp_path)

    with db.transaction():
        db.execute("INSERT INTO item VALUES (?, ?)", ("outer", None))
        with pytest.raises(RuntimeError):
            with db.transaction():
                db.execute("INSERT INTO item VALUES (?, ?)", ("inner", None))
                raise RuntimeError("abort inner")

    assert [row["id"] for row in db.query("SELECT id FROM item")] == ["outer"]
    db.close()


def test_committed_state_survives_reopen(tmp_path):
    db = make(tmp_path)
    with db.transaction():
        db.execute("INSERT INTO item VALUES (?, ?)", ("a", "durable"))
    db.close()

    reopened = make(tmp_path)

    assert reopened.one("SELECT note FROM item")["note"] == "durable"
    reopened.close()


def test_one_returns_none_when_nothing_matches(tmp_path):
    db = make(tmp_path)

    assert db.one("SELECT * FROM item WHERE id = ?", ("missing",)) is None
    db.close()


def test_content_digest_ignores_key_order_and_keeps_unicode():
    left = {"b": 1, "a": {"y": "光照", "x": [1, 2]}}
    right = {"a": {"x": [1, 2], "y": "光照"}, "b": 1}

    assert canonical_json(left) == '{"a":{"x":[1,2],"y":"光照"},"b":1}'
    assert content_digest(left) == content_digest(right)
    assert content_digest(left) != content_digest({**left, "b": 2})


def test_new_id_is_prefixed_and_unique():
    first, second = new_id("task"), new_id("task")

    assert first.startswith("task_") and first != second


def test_file_digest_matches_content(tmp_path):
    path = tmp_path / "data.bin"
    path.write_bytes(b"abc")

    assert file_digest(path) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
