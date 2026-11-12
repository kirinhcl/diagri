"""What the workbench shows of the compute service: balance, budgets, usage, open and stuck jobs."""

from typing import Any

from growbridge.archive.clock import Clock
from growbridge.archive.db import Database
from growbridge.compute.phases import (
    LIVE,
    PHASE_STATE,
    POLLED,
    RECONCILE_AFTER_SECONDS,
    STUCK_AFTER_SECONDS,
)


def build_overview(
    db: Database, clock: Clock, cpu_cap: float, storage_cap: float
) -> dict[str, Any]:
    return {
        "balance": _balance(db),
        "tasks": _task_usage(db),
        "service": _service_usage(db, cpu_cap, storage_cap),
        "jobs": _open_jobs(db),
        "stuck": _stuck(db, clock.now()),
    }


def _balance(db: Database) -> dict[str, Any] | None:
    record = db.one("SELECT * FROM compute_balances ORDER BY id DESC LIMIT 1")
    if record is None:
        return None
    return {
        "cpu_hours": record["balance"],
        "entered_by": record["entered_by"],
        "note": record["note"],
        "recorded_at": record["recorded_at"],
    }


def _task_usage(db: Database) -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT b.task_id, b.cpu_hours, b.storage_gb, COALESCE(SUM(a.used_cpu), 0) AS uc,"
        " COALESCE(SUM(a.used_storage), 0) AS us, COALESCE(SUM(a.reserved_cpu), 0) AS rc,"
        " COALESCE(SUM(a.reserved_storage), 0) AS rs FROM compute_task_budgets b"
        " LEFT JOIN compute_attempts a ON a.task_id = b.task_id"
        " GROUP BY b.task_id ORDER BY b.task_id"
    )
    return [
        {
            "task_id": row["task_id"],
            "cpu_hours_budget": row["cpu_hours"],
            "storage_gb_budget": row["storage_gb"],
            "cpu_hours_used": row["uc"],
            "storage_gb_used": row["us"],
            "cpu_hours_reserved": row["rc"],
            "storage_gb_reserved": row["rs"],
        }
        for row in rows
    ]


def _service_usage(db: Database, cpu_cap: float, storage_cap: float) -> dict[str, float]:
    row = db.one(
        "SELECT COALESCE(SUM(reserved_cpu + used_cpu), 0) AS c,"
        " COALESCE(SUM(reserved_storage + used_storage), 0) AS s FROM compute_attempts"
    )
    return {
        "cpu_hours_cap": cpu_cap,
        "storage_gb_cap": storage_cap,
        "cpu_hours_committed": row["c"],
        "storage_gb_committed": row["s"],
    }


def _open_jobs(db: Database) -> list[dict[str, Any]]:
    phases = (*LIVE, "fetching")
    rows = db.query(
        "SELECT id, task_id, template_id, phase, remote_job_id, created_at FROM"
        f" compute_attempts WHERE phase IN ({', '.join('?' * len(phases))})"
        " ORDER BY created_at, id",
        phases,
    )
    return [
        {
            "attempt_id": row["id"],
            "task_id": row["task_id"],
            "template_id": row["template_id"],
            "phase": row["phase"],
            "task_state": PHASE_STATE[row["phase"]].value,
            "remote_job_id": row["remote_job_id"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def _why_stuck(row: Any, now: float) -> str | None:
    """The reason an open attempt needs a person, or None while it is on its way."""
    age = now - row["updated_at"]
    if row["phase"] in ("prepared", "reconcile"):  # its error only says why it is waiting
        if age > RECONCILE_AFTER_SECONDS:
            return "waiting for reconciliation: the outcome of the submit is unknown"
        return None
    if row["error"]:
        return f"error: {row['error']}"
    if row["phase"] in POLLED and age > STUCK_AFTER_SECONDS:
        return f"not refreshed for {int(age)} seconds"
    return None


def _stuck(db: Database, now: float) -> list[dict[str, Any]]:
    phases = (*LIVE, "fetching", "needs_review")
    rows = db.query(
        "SELECT id, task_id, phase, error, updated_at FROM compute_attempts WHERE phase IN"
        f" ({', '.join('?' * len(phases))}) ORDER BY updated_at, id",
        phases,
    )
    found = []
    for row in rows:
        reason = _why_stuck(row, now)
        if reason is not None:
            found.append(
                {
                    "attempt_id": row["id"],
                    "task_id": row["task_id"],
                    "phase": row["phase"],
                    "reason": reason,
                    "since": row["updated_at"],
                }
            )
    return found
