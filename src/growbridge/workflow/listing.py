"""Read-only listings over the workflow store, for the workbench console.

Fixed SQL, values bound with ``?``. Nothing here writes.
"""

from __future__ import annotations

from typing import Any

from growbridge.workflow.store import WorkflowStore


def project_summaries(store: WorkflowStore, limit: int = 200) -> list[dict[str, Any]]:
    """Projects newest first, each with its round count and latest round."""
    projects = store.db.query(
        "SELECT id, name, created_at FROM wf_projects ORDER BY created_at DESC, rowid DESC LIMIT ?",
        (limit,),
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
                else {"round_id": latest["id"], "state": latest["state"]},
            }
        )
    return summaries


def project_detail(store: WorkflowStore, project_id: str) -> dict[str, Any] | None:
    """One project with its rounds (newest first) and latest protocol versions."""
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
        "SELECT p.id, p.version, p.created_at FROM wf_protocols p"
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
            }
            for row in rounds
        ],
        "protocols": [
            {"protocol_id": row["id"], "version": row["version"], "created_at": row["created_at"]}
            for row in protocols
        ],
    }


def rounds_awaiting_choice(store: WorkflowStore, limit: int = 50) -> list[dict[str, Any]]:
    """Rounds waiting for an operator's choice, oldest first."""
    rows = store.db.query(
        "SELECT id, project_id, awaiting_choice, created_at FROM wf_rounds"
        " WHERE awaiting_choice IS NOT NULL AND awaiting_choice != ''"
        " ORDER BY created_at, rowid LIMIT ?",
        (limit,),
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
