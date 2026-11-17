"""Bridge from the legacy sample store to the project archive."""

import json
from collections.abc import Callable, Sequence

from growbridge.archive.clock import Clock
from growbridge.ports import RawSample
from growbridge.store import Store


class SourceRewound(RuntimeError):
    """The legacy table's newest rowid is below the archive cursor: rowids were reused."""

    def __init__(self, top_rowid: int, cursor: int):
        super().__init__(
            f"legacy samples end at rowid {top_rowid} but the archive cursor is {cursor}; "
            "rows were deleted and rowids reused, so new rows cannot be told apart"
        )
        self.top_rowid = top_rowid
        self.cursor = cursor


class LegacySampleSource:
    """``SampleSource`` over ``Store.samples``; the cursor is the row's ``rowid``.

    The legacy store only keeps the receive time, so ``captured_at`` stays empty (the archive
    then marks the time as a receive time). Rows are labelled unsynced when they were received
    inside a period in which this source saw the clock unsynced; the period runs from the first
    observation of an unsynced clock until the next observation of a synced one. Observations
    happen on every ``read_after`` (call ``observe`` more often for finer resolution). Limit: a
    period that starts and ends while the process is down, or between two observations, is not
    seen, and its rows are labelled synced.
    """

    def __init__(self, store: Store, clock: Clock):
        self.store = store
        self.clock = clock
        self.periods: list[tuple[float, float | None]] = []

    def observe(self) -> None:
        now = self.clock.now()
        open_period = bool(self.periods) and self.periods[-1][1] is None
        if not self.clock.synced and not open_period:
            self.periods.append((now, None))
        elif self.clock.synced and open_period:
            self.periods[-1] = (self.periods[-1][0], now)

    def _synced_at(self, received_at: float) -> bool:
        return not any(
            start <= received_at and (end is None or received_at < end)
            for start, end in self.periods
        )

    def read_after(self, cursor: int, limit: int) -> Sequence[RawSample]:
        self.observe()
        top = self.store.db.execute("SELECT MAX(rowid) FROM samples").fetchone()[0] or 0
        if top < cursor:
            raise SourceRewound(top, cursor)
        rows = self.store.db.execute(
            "SELECT rowid, at, data FROM samples WHERE rowid > ? ORDER BY rowid LIMIT ?",
            (cursor, limit),
        ).fetchall()
        return [
            RawSample(
                cursor=rowid,
                received_at=at,
                clock_synced=self._synced_at(at),
                data=json.loads(data),
            )
            for rowid, at, data in rows
        ]


def protect_history(store: Store, archived_cursor: Callable[[], int], clock: Clock) -> None:
    """From now on ``store.prune`` deletes only archived rows, and nothing while unsynced.

    The newest row is never deleted, which keeps SQLite's rowids increasing.
    """
    store.history_guard = (archived_cursor, clock)
