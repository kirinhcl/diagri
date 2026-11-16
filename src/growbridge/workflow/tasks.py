"""Durable research-task board (architecture doc §5 and Appendix B, research-task table).

Only the transitions of the table are allowed; every other one is ``Denied("state")``.
An event ID advances a task once: replaying it returns the task as it is now.
"""

import sqlite3
from collections.abc import Collection

from growbridge.archive.clock import Clock
from growbridge.archive.db import Database
from growbridge.archive.models import ResearchTask
from growbridge.ports import Denied
from growbridge.workflow.states import TASK_TERMINAL, TaskState

S = TaskState

NAMESPACE = "task_board"
STEPS = (
    "CREATE TABLE task_board("
    "seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE, "
    "project_id TEXT NOT NULL, trigger_event_id TEXT NOT NULL UNIQUE, state TEXT NOT NULL, "
    "deadline REAL, revisions INTEGER NOT NULL DEFAULT 0, data TEXT NOT NULL)",
    "CREATE INDEX task_board_project ON task_board(project_id, state)",
    "CREATE TABLE task_events("
    "event_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, state TEXT NOT NULL, "
    "reason TEXT NOT NULL, at REAL NOT NULL)",
)

# Remote job cycle: in progress -> queued -> computing -> fetching -> in progress.
_ALLOWED: dict[TaskState, frozenset[TaskState]] = {
    S.IN_PROGRESS: frozenset({S.REMOTE_QUEUED, S.NEEDS_REVIEW, S.DONE, S.NEEDS_ATTENTION}),
    S.REMOTE_QUEUED: frozenset({S.COMPUTING, S.RECONCILE, S.NEEDS_ATTENTION}),
    S.COMPUTING: frozenset({S.FETCHING, S.RECONCILE, S.NEEDS_ATTENTION}),
    S.FETCHING: frozenset({S.IN_PROGRESS, S.NEEDS_ATTENTION}),
    # Uncertain submission: the user rechecks and resubmits, or abandons with a reason.
    S.RECONCILE: frozenset({S.IN_PROGRESS, S.ENDED, S.NEEDS_ATTENTION}),
    # Limit reached: the user widens the scope, or ends it keeping partial results.
    S.NEEDS_ATTENTION: frozenset({S.IN_PROGRESS, S.ENDED}),
    # Confirmatory claim with open questions: publish as is, or downgrade to exploratory.
    S.NEEDS_REVIEW: frozenset({S.DONE, S.NEEDS_ATTENTION}),
}
_REASON_REQUIRED = frozenset({(S.RECONCILE, S.ENDED), (S.NEEDS_ATTENTION, S.ENDED)})
_EXPIRABLE = (S.IN_PROGRESS, S.REMOTE_QUEUED, S.COMPUTING, S.FETCHING)


class TaskBoard:
    def __init__(self, db: Database, clock: Clock):
        self.db = db
        self.clock = clock
        db.migrate(NAMESPACE, STEPS)

    def create(self, task: ResearchTask) -> ResearchTask:
        """Store a new task (always in progress); one task per trigger event."""
        with self.db.transaction():
            existing = self.db.one(
                "SELECT * FROM task_board WHERE trigger_event_id = ?", (task.trigger_event_id,)
            )
            if existing is not None and existing["project_id"] != task.project_id:
                # say nothing about another project's task, not even that it is one
                raise Denied("state", "this trigger_event_id is already used")
            if existing is not None:
                return self._load(existing)
            if self.db.one("SELECT 1 FROM task_board WHERE id = ?", (task.id,)) is not None:
                raise Denied("state", f"task id {task.id} already exists")
            self._check_depth(task)
            stored = task.model_copy(update={"state": S.IN_PROGRESS})
            self.db.execute(
                "INSERT INTO task_board(id, project_id, trigger_event_id, state, deadline, data) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    stored.id,
                    stored.project_id,
                    stored.trigger_event_id,
                    stored.state.value,
                    stored.deadline,
                    stored.model_dump_json(),
                ),
            )
            return stored

    def transition(
        self, task_id: str, to: TaskState, event_id: str, reason: str = ""
    ) -> ResearchTask:
        with self.db.transaction():
            task, _ = self._advance(task_id, to, event_id, reason)
            return task

    def get(self, task_id: str) -> ResearchTask:
        row = self.db.one("SELECT * FROM task_board WHERE id = ?", (task_id,))
        if row is None:
            raise Denied("state", f"unknown task {task_id}")
        return self._load(row)

    def list(self, project_id: str, state: TaskState | None = None) -> tuple[ResearchTask, ...]:
        sql = "SELECT * FROM task_board WHERE project_id = ?"
        params: list[object] = [project_id]
        if state is not None:
            sql += " AND state = ?"
            params.append(state.value)
        rows = self.db.query(sql + " ORDER BY seq", params)
        return tuple(self._load(row) for row in rows)

    def in_states(
        self, states: Collection[TaskState], limit: int = 100
    ) -> tuple[ResearchTask, ...]:
        """Tasks of any project in one of ``states``, oldest first."""
        wanted = [state.value for state in states]
        if not wanted:
            return ()
        marks = ",".join("?" for _ in wanted)
        rows = self.db.query(
            f"SELECT * FROM task_board WHERE state IN ({marks}) ORDER BY seq LIMIT ?",
            (*wanted, limit),
        )
        return tuple(self._load(row) for row in rows)

    def count_in_states(self, states: Collection[TaskState]) -> int:
        """How many tasks of any project are in one of ``states``."""
        wanted = [state.value for state in states]
        if not wanted:
            return 0
        marks = ",".join("?" for _ in wanted)
        row = self.db.one(f"SELECT COUNT(*) AS n FROM task_board WHERE state IN ({marks})", wanted)
        return row["n"] if row else 0

    def state_since(self, task_ids: Collection[str]) -> dict[str, float]:
        """When each task last changed state (its latest event); tasks without one are absent."""
        ids = list(task_ids)
        if not ids:
            return {}
        marks = ",".join("?" for _ in ids)
        rows = self.db.query(
            f"SELECT task_id, MAX(at) AS at FROM task_events WHERE task_id IN ({marks})"
            " GROUP BY task_id",
            ids,
        )
        return {row["task_id"]: row["at"] for row in rows}

    def open_tasks(self, roles: Collection[str]) -> tuple[ResearchTask, ...]:
        """In-progress tasks owned by one of ``roles``, oldest first."""
        rows = self.db.query(
            "SELECT * FROM task_board WHERE state = ? ORDER BY seq", (S.IN_PROGRESS.value,)
        )
        wanted = set(roles)
        loaded = (self._load(row) for row in rows)
        return tuple(task for task in loaded if task.owner_role in wanted)

    def expire(self, now: float) -> tuple[ResearchTask, ...]:
        """Move active tasks past their deadline to needs-attention, once per deadline."""
        marks = ",".join("?" for _ in _EXPIRABLE)
        expired: list[ResearchTask] = []
        with self.db.transaction():
            rows = self.db.query(
                "SELECT * FROM task_board WHERE deadline IS NOT NULL AND deadline < ? "
                f"AND state IN ({marks}) ORDER BY seq",
                [now, *(state.value for state in _EXPIRABLE)],
            )
            for row in rows:
                event_id = f"expire:{row['id']}:{row['deadline']}"
                task, applied = self._advance(row["id"], S.NEEDS_ATTENTION, event_id, "deadline")
                if applied:
                    expired.append(task)
        return tuple(expired)

    def record_revision(self, task_id: str) -> int:
        """Count one automatic revision; beyond ``max_revisions`` the task goes to the user."""
        with self.db.transaction():
            row = self.db.one("SELECT * FROM task_board WHERE id = ?", (task_id,))
            if row is None:
                raise Denied("state", f"unknown task {task_id}")
            count = row["revisions"] + 1
            if count > self._load(row).budget.max_revisions:
                raise Denied("budget", f"revision limit reached for task {task_id}")
            self.db.execute("UPDATE task_board SET revisions = ? WHERE id = ?", (count, task_id))
            return count

    def _advance(
        self, task_id: str, to: TaskState, event_id: str, reason: str
    ) -> tuple[ResearchTask, bool]:
        """Apply one event inside the caller's transaction; return (task, applied)."""
        seen = self.db.one("SELECT task_id FROM task_events WHERE event_id = ?", (event_id,))
        if seen is not None:
            if seen["task_id"] != task_id:
                raise Denied("state", f"event {event_id} belongs to another task")
            return self.get(task_id), False
        task = self.get(task_id)
        self._check_transition(task, to, reason)
        moved = task.model_copy(update={"state": to})
        self.db.execute(
            "UPDATE task_board SET state = ?, data = ? WHERE id = ?",
            (to.value, moved.model_dump_json(), task_id),
        )
        self.db.execute(
            "INSERT INTO task_events VALUES (?, ?, ?, ?, ?)",
            (event_id, task_id, to.value, reason, self.clock.now()),
        )
        return moved, True

    @staticmethod
    def _check_transition(task: ResearchTask, to: TaskState, reason: str) -> None:
        if task.state in TASK_TERMINAL or to not in _ALLOWED.get(task.state, frozenset()):
            raise Denied("state", f"task {task.id}: {task.state.value} -> {to.value} not allowed")
        if (task.state, to) in _REASON_REQUIRED and not reason.strip():
            raise Denied("state", f"task {task.id}: ending from {task.state.value} needs a reason")

    def _check_depth(self, task: ResearchTask) -> None:
        if task.parent_task_id is None:
            return
        parent = self.get(task.parent_task_id)
        if parent.project_id != task.project_id:
            raise Denied("state", "parent task belongs to another project")
        depth, cursor = 1, parent
        while cursor.parent_task_id is not None:
            depth += 1
            cursor = self.get(cursor.parent_task_id)
        if depth > parent.budget.max_delegation_depth:
            raise Denied("budget", f"delegation depth {depth} exceeds the limit")

    @staticmethod
    def _load(row: sqlite3.Row) -> ResearchTask:
        task = ResearchTask.model_validate_json(row["data"])
        return task.model_copy(update={"state": TaskState(row["state"])})
