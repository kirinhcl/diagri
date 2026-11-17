"""Read-only listings over the workflow store, for the workbench console.

Fixed SQL, values bound with ``?``. Nothing here writes.
"""

from __future__ import annotations

import json
from typing import Any

from growbridge.workflow.store import WorkflowStore


def _owned(only_owner: str | None, alias: str = "") -> tuple[str, tuple[str, ...]]:
    """The SQL condition (placed before any LIMIT) that keeps one owner's projects."""
    if only_owner is None:
        return "", ()
    column = f"{alias}owner" if alias else "owner"
    return f" AND {column} = ?", (only_owner,)


def project_summaries(
    store: WorkflowStore, limit: int = 200, *, only_owner: str | None = None
) -> list[dict[str, Any]]:
    """Projects newest first, each with its round count and latest round (and that round's
    ``round_number``, as ``WorkflowStore.round_number`` counts it). ``only_owner`` keeps one
    operator's projects."""
    condition, params = _owned(only_owner)
    projects = store.db.query(
        f"SELECT id, name, created_at FROM wf_projects WHERE 1 = 1{condition}"
        " ORDER BY created_at DESC, rowid DESC LIMIT ?",
        (*params, limit),
    )
    summaries: list[dict[str, Any]] = []
    for project in projects:
        count = store.db.one(
            "SELECT COUNT(*) AS n FROM wf_rounds WHERE project_id = ?", (project["id"],)
        )
        latest = store.db.one(
            "SELECT id, state FROM wf_rounds WHERE project_id = ?"
            " ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (project["id"],),
        )
        summaries.append(
            {
                "project_id": project["id"],
                "name": project["name"],
                "created_at": project["created_at"],
                "round_count": count["n"] if count else 0,
                "latest_round": None
                if latest is None
                else {
                    "round_id": latest["id"],
                    "state": latest["state"],
                    "round_number": store.round_number(latest["id"]),
                },
            }
        )
    return summaries


def _analysis_summary(body: str) -> dict[str, str | None]:
    """The primary endpoint and method of a stored protocol body, ``None`` when it has none."""
    try:
        analysis = json.loads(body).get("analysis")
    except (ValueError, AttributeError):
        analysis = None
    analysis = analysis if isinstance(analysis, dict) else {}
    return {key: _text_or_none(analysis.get(key)) for key in ("primary_endpoint", "method")}


def _text_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def project_detail(store: WorkflowStore, project_id: str) -> dict[str, Any] | None:
    """One project with its rounds (newest first, each with its ``round_number``) and latest
    protocol versions."""
    project = store.db.one(
        "SELECT id, name, created_at FROM wf_projects WHERE id = ?", (project_id,)
    )
    if project is None:
        return None
    rounds = store.db.query(
        "SELECT id, state, protocol_id, protocol_version, awaiting_choice, created_at"
        " FROM wf_rounds WHERE project_id = ? ORDER BY created_at DESC, rowid DESC",
        (project_id,),
    )
    protocols = store.db.query(
        "SELECT p.id, p.version, p.created_at, p.body FROM wf_protocols p"
        " WHERE p.project_id = ? AND p.version = (SELECT MAX(q.version) FROM wf_protocols q"
        " WHERE q.id = p.id AND q.project_id = p.project_id)"
        " ORDER BY p.created_at, p.id",
        (project_id,),
    )
    return {
        "project_id": project["id"],
        "name": project["name"],
        "created_at": project["created_at"],
        "rounds": [
            {
                "round_id": row["id"],
                "state": row["state"],
                "protocol_id": row["protocol_id"],
                "protocol_version": row["protocol_version"],
                "awaiting_choice": row["awaiting_choice"],
                "created_at": row["created_at"],
                "round_number": store.round_number(row["id"]),
            }
            for row in rounds
        ],
        "protocols": [
            {
                "protocol_id": row["id"],
                "version": row["version"],
                "created_at": row["created_at"],
                **_analysis_summary(row["body"]),
            }
            for row in protocols
        ],
    }


_WAITING_ROUNDS = (
    " FROM wf_rounds r JOIN wf_projects p ON p.id = r.project_id"
    " WHERE r.awaiting_choice IS NOT NULL AND r.awaiting_choice != ''"
)


def count_rounds_awaiting_choice(store: WorkflowStore, *, only_owner: str | None = None) -> int:
    """How many rounds wait for an operator's choice (of one owner's projects, if given)."""
    condition, params = _owned(only_owner, "p.")
    row = store.db.one(f"SELECT COUNT(*) AS n{_WAITING_ROUNDS}{condition}", params)
    return row["n"] if row else 0


def rounds_awaiting_choice(
    store: WorkflowStore, limit: int = 50, *, only_owner: str | None = None
) -> list[dict[str, Any]]:
    """Rounds waiting for an operator's choice, oldest first (of one owner's projects, if
    given; the owner is filtered before the limit)."""
    condition, params = _owned(only_owner, "p.")
    rows = store.db.query(
        "SELECT r.id AS id, r.project_id AS project_id, r.awaiting_choice AS awaiting_choice,"
        f" r.created_at AS created_at{_WAITING_ROUNDS}{condition}"
        " ORDER BY r.created_at, r.rowid LIMIT ?",
        (*params, limit),
    )
    return [
        {
            "round_id": row["id"],
            "project_id": row["project_id"],
            "awaiting_choice": row["awaiting_choice"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]
