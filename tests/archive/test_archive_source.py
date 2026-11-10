import json
import time

import pytest

from growbridge.archive.source import LegacySampleSource, SourceRewound, protect_history
from growbridge.sim.clock import START
from growbridge.store import Store

DAY = 86400


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "legacy" / "growbridge.db")
    yield s
    s.close()


def insert(store, age_days, now=START, **data):
    store.db.execute(
        "INSERT INTO samples VALUES(?, ?)", (now - age_days * DAY, json.dumps(data or {"t": 1}))
    )
    store.db.commit()


def remaining(store):
    return [r[0] for r in store.db.execute("SELECT rowid FROM samples ORDER BY rowid")]


def test_legacy_source_reads_rows_after_cursor_in_order(store, clock):
    for age in (3, 2, 1):
        insert(store, age, t=age)
    source = LegacySampleSource(store, clock)

    first = source.read_after(0, 2)
    rest = source.read_after(first[-1].cursor, 10)

    assert [s.cursor for s in first] == [1, 2]
    assert [s.cursor for s in rest] == [3]
    assert first[0].received_at == START - 3 * DAY
    assert first[0].captured_at is None
    assert first[0].data == {"t": 3}
    assert source.read_after(3, 10) == []


def test_rows_received_during_a_seen_unsynced_period_are_labelled_unsynced(store, clock):
    source = LegacySampleSource(store, clock)
    insert(store, 0, t=1)  # before the clock was seen unsynced
    assert source.read_after(0, 10)[0].clock_synced is True
    clock.advance(10)

    clock.synced = False
    source.read_after(1, 10)  # the source sees the unsynced clock at START
    clock.advance(100)
    insert(store, 0, now=clock.now(), t=2)  # received during the period
    clock.synced = True
    clock.advance(100)
    source.read_after(1, 10)  # sees the clock synced again: the period is now closed
    insert(store, 0, now=clock.now(), t=3)  # received after the period

    rows = {r.cursor: r.clock_synced for r in source.read_after(0, 10)}
    assert rows == {1: True, 2: False, 3: True}


def test_backlog_read_after_resync_stays_unsynced_for_the_period(store, clock):
    source = LegacySampleSource(store, clock)
    clock.synced = False
    source.read_after(0, 10)
    clock.advance(10)
    insert(store, 0, now=clock.now())
    clock.synced = True
    clock.advance(10)

    assert source.read_after(0, 10)[0].clock_synced is False


def test_source_raises_when_cursor_is_ahead_of_the_table(store, clock):
    insert(store, 1)
    insert(store, 1)
    source = LegacySampleSource(store, clock)

    with pytest.raises(SourceRewound):
        source.read_after(5, 10)
    assert source.read_after(2, 10) == []  # cursor at the top is fine


def test_source_raises_on_empty_table_with_nonzero_cursor(store, clock):
    with pytest.raises(SourceRewound):
        LegacySampleSource(store, clock).read_after(3, 10)
    assert LegacySampleSource(store, clock).read_after(0, 10) == []


def test_prune_never_deletes_the_newest_row_so_rowids_keep_increasing(store, clock):
    insert(store, 60)
    insert(store, 50)
    protect_history(store, lambda: 2, clock)

    store.prune(30)
    assert remaining(store) == [2]

    store.sample({"t": 9}, at=START)
    assert remaining(store) == [2, 3]


def test_unprotected_prune_keeps_existing_behaviour(store):
    insert(store, 40, now=time.time())
    store.sample({"t": 1})

    store.prune(30)

    assert remaining(store) == [2]


def test_old_history_survives_prune_until_archived(store, clock):
    for age in (45, 40, 1):
        insert(store, age)
    archived = 0
    protect_history(store, lambda: archived, clock)

    store.prune(30)
    assert remaining(store) == [1, 2, 3]

    archived = 2
    store.prune(30)
    assert remaining(store) == [3]


def test_archived_but_recent_rows_are_kept(store, clock):
    insert(store, 5)
    protect_history(store, lambda: 1, clock)

    store.prune(30)

    assert remaining(store) == [1]


def test_prune_is_paused_while_clock_is_unsynced(store, clock):
    insert(store, 40)
    insert(store, 0)
    protect_history(store, lambda: 2, clock)
    clock.synced = False

    store.prune(30)
    assert remaining(store) == [1, 2]

    clock.synced = True
    store.prune(30)
    assert remaining(store) == [2]
