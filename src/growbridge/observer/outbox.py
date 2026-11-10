"""Durable notification outbox (architecture doc section 8.3).

A notification is one row per (event id, channel). Delivery records what the channel said:
``accepted``, ``unknown`` (it may or may not have arrived) or ``failed``. Anything not accepted is
retried with exponential backoff up to a cap and an attempt limit, so an ``unknown`` outcome can
produce a duplicate message; that is the accepted cost of never losing an alert.
"""

import logging
from collections.abc import Mapping

from growbridge.archive.clock import Clock
from growbridge.archive.db import Database
from growbridge.observer.channels import NotifyChannel

log = logging.getLogger(__name__)

NAMESPACE = "observer_outbox"
DEFAULT_MAX_ATTEMPTS = 20
MAX_BACKOFF_EXPONENT = 30
STEPS = (
    "CREATE TABLE observer_outbox("
    "event_id TEXT NOT NULL, channel TEXT NOT NULL, text TEXT NOT NULL, "
    "status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0, "
    "created_at REAL NOT NULL, next_at REAL NOT NULL, PRIMARY KEY(event_id, channel))",
    "CREATE TABLE observer_deliveries("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL, channel TEXT NOT NULL, "
    "outcome TEXT NOT NULL, at REAL NOT NULL)",
)


class Outbox:
    def __init__(
        self,
        db: Database,
        clock: Clock,
        base_seconds: float,
        cap_seconds: float,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ):
        self.db = db
        self.clock = clock
        self.base_seconds = base_seconds
        self.cap_seconds = cap_seconds
        self.max_attempts = max_attempts
        db.migrate(NAMESPACE, STEPS)

    def queue_notification(self, event_id: str, channel: str, text: str) -> bool:
        """Idempotent per event id and channel; ``False`` when it was already queued."""
        now = self.clock.now()
        cursor = self.db.execute(
            "INSERT OR IGNORE INTO observer_outbox(event_id, channel, text, created_at, next_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (event_id, channel, text, now, now),
        )
        return cursor.rowcount == 1

    def _due(self, channels: Mapping[str, NotifyChannel]) -> list[tuple[str, str, str, int]]:
        rows = self.db.query(
            "SELECT event_id, channel, text, attempts FROM observer_outbox "
            "WHERE status != 'accepted' AND attempts < ? AND next_at <= ? "
            "ORDER BY created_at, event_id, channel",
            (self.max_attempts, self.clock.now()),
        )
        return [
            (r["event_id"], r["channel"], r["text"], r["attempts"])
            for r in rows
            if r["channel"] in channels
        ]

    def _record(self, event_id: str, channel: str, attempts: int, outcome: str) -> None:
        now = self.clock.now()
        delay = min(self.cap_seconds, self.base_seconds * 2 ** min(attempts, MAX_BACKOFF_EXPONENT))
        with self.db.transaction():
            self.db.execute(
                "UPDATE observer_outbox SET status = ?, attempts = ?, next_at = ? "
                "WHERE event_id = ? AND channel = ?",
                (outcome, attempts + 1, now + delay, event_id, channel),
            )
            self.db.execute(
                "INSERT INTO observer_deliveries(event_id, channel, outcome, at) "
                "VALUES (?, ?, ?, ?)",
                (event_id, channel, outcome, now),
            )

    async def deliver(self, channels: Mapping[str, NotifyChannel]) -> int:
        """Try every due notification once; returns how many were accepted."""
        accepted = 0
        for event_id, name, text, attempts in self._due(channels):
            try:
                outcome = await channels[name].send(text)
            except Exception as error:
                # it may have been sent before the error; log the type only, never the text
                log.warning("channel %s raised %s; outcome unknown", name, type(error).__name__)
                outcome = "unknown"
            self._record(event_id, name, attempts, outcome)
            accepted += outcome == "accepted"
        return accepted

    def status(self, event_id: str, channel: str) -> str | None:
        row = self.db.one(
            "SELECT status FROM observer_outbox WHERE event_id = ? AND channel = ?",
            (event_id, channel),
        )
        return row["status"] if row else None

    def results(self, event_id: str, channel: str) -> tuple[str, ...]:
        rows = self.db.query(
            "SELECT outcome FROM observer_deliveries WHERE event_id = ? AND channel = ? "
            "ORDER BY id",
            (event_id, channel),
        )
        return tuple(row["outcome"] for row in rows)

    def oldest_undelivered(self) -> float | None:
        """Creation time of the oldest notification that no channel has accepted yet."""
        row = self.db.one(
            "SELECT MIN(created_at) AS oldest FROM observer_outbox WHERE status != 'accepted'"
        )
        return row["oldest"] if row else None
