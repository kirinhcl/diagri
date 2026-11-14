"""The project conversation (architecture doc §5.1): what the user asked, what each model role
answered and which tools it used, in order, labelled by role.

It is a record for people to read in the workbench and the recent context of the orchestrator's
next run. Work is never handed over through it: handoffs go through the task board and archive ids.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from growbridge.archive.db import Database
from growbridge.archive.models import Model

NAMESPACE = "conversation"
STEPS = (
    "CREATE TABLE conversation("
    "seq INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, task_id TEXT,"
    " role TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, detail TEXT NOT NULL,"
    " at REAL NOT NULL)",
    "CREATE INDEX conversation_project ON conversation(project_id, seq)",
)
MAX_TEXT = 8000
MAX_DETAIL = 4000
PAGE_LIMIT = 500

# message: the user's words; reply: a model role's text; tool: one tool call and its outcome;
# status: what the dispatcher did with a task (finished, handed back, followed up).
Kind = Literal["message", "reply", "tool", "status"]


class Entry(Model):
    seq: int
    project_id: str
    task_id: str | None
    role: str
    kind: Kind
    text: str
    detail: dict[str, Any]
    at: float


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "...[truncated]"


def clip_json(value: Any, limit: int = MAX_DETAIL) -> str:
    return _clip(json.dumps(value, ensure_ascii=False, default=str), limit)


class ConversationLog:
    def __init__(self, db: Database, clock: Any):
        self.db = db
        self.clock = clock
        db.migrate(NAMESPACE, STEPS)

    def add(
        self,
        project_id: str,
        role: str,
        kind: Kind,
        text: str,
        task_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> int:
        cursor = self.db.execute(
            "INSERT INTO conversation(project_id, task_id, role, kind, text, detail, at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                project_id,
                task_id,
                role,
                kind,
                _clip(text, MAX_TEXT),
                json.dumps(detail or {}, ensure_ascii=False, default=str),
                self.clock.now(),
            ),
        )
        return int(cursor.lastrowid or 0)

    def entries(
        self, project_id: str, after: int = 0, limit: int = PAGE_LIMIT
    ) -> tuple[Entry, ...]:
        """Entries after ``after`` in order, at most ``limit`` of them."""
        rows = self.db.query(
            "SELECT * FROM conversation WHERE project_id = ? AND seq > ? ORDER BY seq LIMIT ?",
            (project_id, after, min(limit, PAGE_LIMIT)),
        )
        return tuple(_entry(row) for row in rows)

    def recent(self, project_id: str, kinds: tuple[str, ...], limit: int) -> tuple[Entry, ...]:
        """The newest ``limit`` entries of the given kinds, oldest first."""
        marks = ", ".join("?" for _ in kinds)
        rows = self.db.query(
            f"SELECT * FROM conversation WHERE project_id = ? AND kind IN ({marks})"
            " ORDER BY seq DESC LIMIT ?",
            (project_id, *kinds, limit),
        )
        return tuple(_entry(row) for row in reversed(rows))


def _entry(row: Any) -> Entry:
    return Entry(
        seq=row["seq"],
        project_id=row["project_id"],
        task_id=row["task_id"],
        role=row["role"],
        kind=row["kind"],
        text=row["text"],
        detail=json.loads(row["detail"]),
        at=row["at"],
    )
