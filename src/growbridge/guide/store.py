"""The record of a guided protocol setup: a session and its numbered, append-only events.

Nothing here updates or deletes a row. The draft is worked out from the ``chosen`` events by
whoever reads them, so there is no mutable draft to drift from what was actually decided.
"""

import json
import secrets
from collections.abc import Sequence
from typing import Any, Literal

from growbridge.archive.clock import Clock
from growbridge.archive.db import Database
from growbridge.archive.models import Model

NAMESPACE = "guide"
STEPS = (
    "CREATE TABLE guide_sessions(session_id TEXT PRIMARY KEY, project_id TEXT NOT NULL,"
    " operator TEXT NOT NULL, started_at REAL NOT NULL, lang TEXT NOT NULL,"
    " seed INTEGER NOT NULL)",
    "CREATE TABLE guide_events(session_id TEXT NOT NULL REFERENCES guide_sessions(session_id),"
    " seq INTEGER NOT NULL, step TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,"
    " actor TEXT NOT NULL, at REAL NOT NULL, PRIMARY KEY (session_id, seq))",
    "CREATE INDEX guide_events_by_session ON guide_events(session_id)",
)

EventKind = Literal["offered", "suggested", "chosen", "reopened", "saved"]
Lang = Literal["en", "zh"]


class GuideSession(Model):
    session_id: str
    project_id: str
    operator: str
    started_at: float
    lang: Lang
    seed: int


class GuideEvent(Model):
    session_id: str
    seq: int
    step: str
    kind: EventKind
    payload: dict[str, Any]
    actor: str
    at: float


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _event(row: Any) -> GuideEvent:
    fields = dict(row)
    fields["payload"] = json.loads(fields["payload"])
    return GuideEvent(**fields)


class GuideStore:
    def __init__(self, db: Database, clock: Clock) -> None:
        self.db = db
        self.clock = clock
        db.migrate(NAMESPACE, STEPS)

    def start(self, project_id: str, operator: str, lang: Lang) -> GuideSession:
        session = GuideSession(
            session_id="guide-" + secrets.token_hex(8),
            project_id=project_id,
            operator=operator,
            started_at=self.clock.now(),
            lang=lang,
            seed=secrets.randbelow(2**31 - 1) + 1,
        )
        self.db.execute(
            "INSERT INTO guide_sessions(session_id, project_id, operator, started_at, lang, seed)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                session.session_id,
                session.project_id,
                session.operator,
                session.started_at,
                session.lang,
                session.seed,
            ),
        )
        return session

    def session(self, session_id: str) -> GuideSession | None:
        row = self.db.one("SELECT * FROM guide_sessions WHERE session_id = ?", (session_id,))
        return None if row is None else GuideSession(**dict(row))

    def append(
        self, session_id: str, step: str, kind: EventKind, payload: dict[str, Any], actor: str
    ) -> GuideEvent:
        return self.append_many(session_id, [(step, kind, payload)], actor)[0]

    def append_many(
        self,
        session_id: str,
        items: Sequence[tuple[str, EventKind, dict[str, Any]]],
        actor: str,
    ) -> tuple[GuideEvent, ...]:
        """Write all ``items`` in one transaction, numbered after the session's last event."""
        written: list[GuideEvent] = []
        with self.db.transaction():
            if self.session(session_id) is None:
                raise KeyError(session_id)
            row = self.db.one(
                "SELECT COALESCE(MAX(seq), 0) AS last FROM guide_events WHERE session_id = ?",
                (session_id,),
            )
            at = self.clock.now()
            for offset, (step, kind, payload) in enumerate(items, start=1):
                event = GuideEvent(
                    session_id=session_id,
                    seq=row["last"] + offset,
                    step=step,
                    kind=kind,
                    payload=payload,
                    actor=actor,
                    at=at,
                )
                self.db.execute(
                    "INSERT INTO guide_events(session_id, seq, step, kind, payload, actor, at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (session_id, event.seq, step, kind, _canonical(payload), actor, at),
                )
                written.append(event)
        return tuple(written)

    def events(self, session_id: str) -> tuple[GuideEvent, ...]:
        rows = self.db.query(
            "SELECT * FROM guide_events WHERE session_id = ? ORDER BY seq", (session_id,)
        )
        return tuple(_event(row) for row in rows)
