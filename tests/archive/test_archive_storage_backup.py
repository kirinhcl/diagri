import json
import threading
from collections import namedtuple

import pytest

from growbridge.archive import backup
from growbridge.archive.db import Database
from growbridge.archive.ids import file_digest
from growbridge.archive.models import SampleRecord
from growbridge.archive.storage import StorageGuard
from growbridge.archive.store import Archive
from growbridge.sim.clock import START

Usage = namedtuple("Usage", "total used free")
LOW, CRITICAL = 1000, 100
GATED_LOW = ("research_cache", "bulk_transfer", "unplanned_image")
ALWAYS = ("care", "protection", "sample")


def guard(tmp_path, free):
    return StorageGuard(tmp_path, LOW, CRITICAL, usage=lambda _: Usage(10_000, 0, free))


def test_plenty_of_space_allows_everything(tmp_path):
    g = guard(tmp_path, 5000)

    assert g.level() == "ok"
    for kind in (*GATED_LOW, "experiment_action", *ALWAYS):
        assert g.allows(kind)


def test_low_space_blocks_cache_bulk_and_unplanned_images_only(tmp_path):
    g = guard(tmp_path, 500)

    assert g.level() == "low"
    assert not any(g.allows(kind) for kind in GATED_LOW)
    assert g.allows("experiment_action")
    assert all(g.allows(kind) for kind in ALWAYS)


def test_critical_space_also_blocks_experiment_actions_but_never_care(tmp_path):
    g = guard(tmp_path, 50)

    assert g.level() == "critical"
    assert not g.allows("experiment_action")
    assert not any(g.allows(kind) for kind in GATED_LOW)
    assert all(g.allows(kind) for kind in ALWAYS)


def test_boundaries_are_inclusive_of_the_healthy_side(tmp_path):
    assert guard(tmp_path, LOW).level() == "ok"
    assert guard(tmp_path, CRITICAL).level() == "low"
    assert guard(tmp_path, CRITICAL - 1).level() == "critical"


def test_unknown_kind_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        guard(tmp_path, 5000).allows("mystery")


def test_default_usage_reads_the_real_disk(tmp_path):
    assert StorageGuard(tmp_path, 1, 1).level() == "ok"


def test_backup_can_be_restored_with_the_same_records(db, archive, tmp_path, clock):
    for i in range(3):
        archive.append_sample(
            SampleRecord(
                id=f"d:{i}",
                experiment_id="exp-1",
                stage_id=None,
                device_id="d",
                captured_at=START + i,
                received_at=START + i,
                clock_synced=True,
                data={"t": 20.0 + i},
            )
        )
    target = tmp_path / "off-host" / "archive.db"

    finished = backup.backup(db, target, clock)

    assert finished == clock.now()
    restored = Database(target)
    try:
        again = Archive(restored, tmp_path / "other", clock)
        assert again.samples("exp-1") == archive.samples("exp-1")
    finally:
        restored.close()


def test_repeated_backup_replaces_target_and_leaves_no_temp_files(db, tmp_path, clock):
    target = tmp_path / "b" / "archive.db"
    backup.backup(db, target, clock)
    clock.advance(60)

    backup.backup(db, target, clock)

    assert sorted(p.name for p in target.parent.iterdir()) == [
        "archive.db",
        "archive.db.manifest.json",
    ]


def test_backup_writes_manifest_with_digest_size_and_time(db, tmp_path, clock):
    target = tmp_path / "b" / "archive.db"

    finished = backup.backup(db, target, clock)

    manifest = json.loads((tmp_path / "b" / "archive.db.manifest.json").read_text())
    assert manifest["sha256"] == file_digest(target)
    assert manifest["size"] == target.stat().st_size
    assert manifest["created_at"] == finished


def test_failed_integrity_check_raises_and_keeps_last_backup(db, tmp_path, clock, monkeypatch):
    target = tmp_path / "b" / "archive.db"
    first = backup.backup(db, target, clock)
    before = target.read_bytes()
    clock.advance(60)
    monkeypatch.setattr(backup, "check_integrity", lambda path: "page 3 is corrupt")

    with pytest.raises(RuntimeError, match="integrity"):
        backup.backup(db, target, clock)

    assert backup.last_backup(db) == first
    assert target.read_bytes() == before
    assert sorted(p.name for p in target.parent.iterdir()) == [
        "archive.db",
        "archive.db.manifest.json",
    ]


def test_integrity_check_reports_ok_for_a_good_copy_and_flags_garbage(db, tmp_path, clock):
    target = tmp_path / "b" / "archive.db"
    backup.backup(db, target, clock)
    garbage = tmp_path / "garbage.db"
    garbage.write_bytes(b"not a database" * 100)

    assert backup.check_integrity(target) == "ok"
    assert backup.check_integrity(garbage) != "ok"


def test_copy_does_not_hold_the_database_lock(db, tmp_path, clock, monkeypatch):
    seen = {}
    real_copy = backup.copy_database

    def watching_copy(source, partial):
        def try_lock():
            seen["free"] = db.lock.acquire(timeout=1)
            if seen["free"]:
                db.lock.release()

        worker = threading.Thread(target=try_lock)
        worker.start()
        worker.join()
        real_copy(source, partial)

    monkeypatch.setattr(backup, "copy_database", watching_copy)

    backup.backup(db, tmp_path / "b" / "archive.db", clock)

    assert seen["free"] is True


def test_backup_is_a_consistent_copy_while_the_source_is_written(db, archive, tmp_path, clock):
    for i in range(300):
        archive.append_sample(
            SampleRecord(
                id=f"d:{i}",
                experiment_id="exp-1",
                stage_id=None,
                device_id="d",
                captured_at=START + i,
                received_at=START + i,
                clock_synced=True,
                data={"pad": "x" * 500},
            )
        )
    target = tmp_path / "b" / "archive.db"

    backup.backup(db, target, clock)

    assert backup.check_integrity(target) == "ok"
    restored = Database(target)
    try:
        assert len(Archive(restored, tmp_path / "o", clock).samples("exp-1")) == 300
    finally:
        restored.close()


def test_last_backup_is_none_before_and_latest_time_after(db, tmp_path, clock):
    assert backup.last_backup(db) is None

    backup.backup(db, tmp_path / "x.db", clock)
    clock.advance(100)
    second = backup.backup(db, tmp_path / "x.db", clock)

    assert backup.last_backup(db) == second


def test_backup_refuses_inside_an_open_transaction(db, tmp_path, clock):
    with db.transaction(), pytest.raises(RuntimeError):
        backup.backup(db, tmp_path / "x.db", clock)
    assert backup.last_backup(db) is None
