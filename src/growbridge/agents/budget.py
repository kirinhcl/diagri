"""Project-level model-call and cost budget shared by every model role (architecture doc §5.2)."""

import sqlite3

from growbridge.archive.clock import Clock
from growbridge.archive.db import Database
from growbridge.archive.models import Budget
from growbridge.ports import Denied

NAMESPACE = "call_budget"
STEPS = (
    "CREATE TABLE call_budget("
    "project_id TEXT PRIMARY KEY, max_calls INTEGER NOT NULL, max_cost REAL NOT NULL, "
    "used_calls INTEGER NOT NULL DEFAULT 0, used_cost REAL NOT NULL DEFAULT 0)",
)


class CallBudget:
    def __init__(self, db: Database, clock: Clock):
        self.db = db
        self.clock = clock
        db.migrate(NAMESPACE, STEPS)

    def set(self, project_id: str, budget: Budget) -> None:
        """Set the limits; usage already recorded is kept."""
        self.db.execute(
            "INSERT INTO call_budget(project_id, max_calls, max_cost) VALUES (?, ?, ?) "
            "ON CONFLICT(project_id) DO UPDATE SET max_calls = excluded.max_calls, "
            "max_cost = excluded.max_cost",
            (project_id, budget.max_calls, budget.max_cost),
        )

    def reserve(self, project_id: str, calls: int = 1) -> None:
        """Atomically check the remaining allowance and take ``calls`` from it."""
        if calls < 1:
            raise ValueError("calls must be at least 1")
        with self.db.transaction():
            row = self._row(project_id)
            if row["used_calls"] + calls > row["max_calls"]:
                raise Denied("budget", f"call budget exhausted for project {project_id}")
            if row["used_cost"] >= row["max_cost"]:
                raise Denied("budget", f"cost budget exhausted for project {project_id}")
            self.db.execute(
                "UPDATE call_budget SET used_calls = used_calls + ? WHERE project_id = ?",
                (calls, project_id),
            )

    def charge(self, project_id: str, cost: float) -> None:
        """Record actual spend. It may overshoot the limit; the next reserve is then denied."""
        if cost < 0:
            raise ValueError("cost must not be negative")
        with self.db.transaction():
            self._row(project_id)
            self.db.execute(
                "UPDATE call_budget SET used_cost = used_cost + ? WHERE project_id = ?",
                (cost, project_id),
            )

    def remaining(self, project_id: str) -> tuple[int, float]:
        row = self._row(project_id)
        return (
            max(0, row["max_calls"] - row["used_calls"]),
            max(0.0, row["max_cost"] - row["used_cost"]),
        )

    def _row(self, project_id: str) -> sqlite3.Row:
        row = self.db.one("SELECT * FROM call_budget WHERE project_id = ?", (project_id,))
        if row is None:
            raise Denied("budget", f"no budget set for project {project_id}")
        return row
