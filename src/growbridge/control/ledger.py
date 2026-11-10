"""Durable state of the control service: host registration, rights, action ledger, safety.

Everything here is synchronous SQLite behind ``Database``; callers never ``await`` inside a
transaction. Rights and actions are never deleted: revoking and voiding write new facts onto
the same row, and every restart or hand-over leaves an event behind (spec 7.1, 7.9).
"""

import json
from typing import Any

from growbridge.archive.db import Database
from growbridge.archive.models import (
    ActionRecord,
    ActionState,
    Channel,
    RightKind,
    RuleAction,
    SafetyConfig,
    WriteRight,
)

NAMESPACE = "control"
STEPS = (
    "CREATE TABLE control_host(device_id TEXT PRIMARY KEY, host_id TEXT NOT NULL,"
    " registered_at REAL NOT NULL)",
    "CREATE TABLE control_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE control_rights(number INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,"
    " device_id TEXT NOT NULL, recovery_number INTEGER NOT NULL, granted_at REAL NOT NULL,"
    " channels TEXT NOT NULL, levels TEXT NOT NULL, experiment_id TEXT, stage_id TEXT,"
    " run_sheet_digest TEXT, operator TEXT, revoked_at REAL)",
    "CREATE TABLE control_actions(request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,"
    " state TEXT NOT NULL, right_number INTEGER NOT NULL, record TEXT NOT NULL)",
    "CREATE INDEX control_actions_state ON control_actions(state)",
    "CREATE TABLE control_safety(id INTEGER PRIMARY KEY AUTOINCREMENT, config TEXT NOT NULL,"
    " recovery_number INTEGER NOT NULL, operator TEXT NOT NULL, approved_at REAL NOT NULL)",
    "CREATE TABLE control_events(id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL,"
    " kind TEXT NOT NULL, detail TEXT NOT NULL)",
)
FLAG_INTERLOCK = "interlock"
FLAG_TRANSPORT_STOPPED = "transport_stopped"
META_RECOVERY = "recovery"
META_LAST_IRRIGATION = "last_irrigation_at"


class Ledger:
    def __init__(self, db: Database):
        self.db = db
        db.migrate(NAMESPACE, STEPS)

    # --- host and flags -----------------------------------------------------------------------

    def register_host(self, device_id: str, host_id: str, at: float) -> bool:
        """Claim the device for ``host_id``; False when another host already holds it."""
        with self.db.transaction():
            row = self.db.one("SELECT host_id FROM control_host WHERE device_id = ?", (device_id,))
            if row is None:
                self.db.execute(
                    "INSERT INTO control_host VALUES (?, ?, ?)", (device_id, host_id, at)
                )
                return True
            return bool(row["host_id"] == host_id)

    def host_of(self, device_id: str) -> str | None:
        row = self.db.one("SELECT host_id FROM control_host WHERE device_id = ?", (device_id,))
        return None if row is None else str(row["host_id"])

    def meta(self, key: str, default: str = "") -> str:
        row = self.db.one("SELECT value FROM control_meta WHERE key = ?", (key,))
        return default if row is None else str(row["value"])

    def set_meta(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO control_meta VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def flag(self, key: str) -> bool:
        return self.meta(key, "0") == "1"

    def set_flag(self, key: str, value: bool) -> None:
        self.set_meta(key, "1" if value else "0")

    def recovery(self) -> int:
        return int(self.meta(META_RECOVERY, "1"))

    def event(self, kind: str, detail: dict[str, Any], at: float) -> None:
        self.db.execute(
            "INSERT INTO control_events(at, kind, detail) VALUES (?, ?, ?)",
            (at, kind, json.dumps(detail, sort_keys=True, default=str)),
        )

    # --- rights -------------------------------------------------------------------------------

    def add_right(self, right: WriteRight) -> int:
        cursor = self.db.execute(
            "INSERT INTO control_rights(kind, device_id, recovery_number, granted_at, channels,"
            " levels, experiment_id, stage_id, run_sheet_digest, operator)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                right.kind.value,
                right.device_id,
                right.recovery_number,
                right.granted_at,
                json.dumps([channel.value for channel in right.channels]),
                json.dumps([level.model_dump(mode="json") for level in right.levels]),
                right.experiment_id,
                right.stage_id,
                right.run_sheet_digest,
                right.operator,
            ),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def right(self, number: int) -> WriteRight | None:
        row = self.db.one("SELECT * FROM control_rights WHERE number = ?", (number,))
        return None if row is None else _right(row)

    def active_rights(
        self, device_id: str, recovery: int, kind: RightKind | None = None
    ) -> list[WriteRight]:
        kind_value = None if kind is None else kind.value
        rows = self.db.query(
            "SELECT * FROM control_rights WHERE device_id = ? AND recovery_number = ?"
            " AND revoked_at IS NULL AND (? IS NULL OR kind = ?) ORDER BY number",
            (device_id, recovery, kind_value, kind_value),
        )
        return [_right(row) for row in rows]

    def revoke(self, number: int, at: float) -> None:
        self.db.execute(
            "UPDATE control_rights SET revoked_at = ? WHERE number = ? AND revoked_at IS NULL",
            (at, number),
        )

    def revoke_all(self, at: float) -> None:
        self.db.execute("UPDATE control_rights SET revoked_at = ? WHERE revoked_at IS NULL", (at,))

    # --- actions ------------------------------------------------------------------------------

    def action(self, request_id: str) -> tuple[ActionRecord, str] | None:
        row = self.db.one(
            "SELECT record, fingerprint FROM control_actions WHERE request_id = ?", (request_id,)
        )
        if row is None:
            return None
        return ActionRecord.model_validate_json(row["record"]), str(row["fingerprint"])

    def insert_action(self, record: ActionRecord, fingerprint: str) -> None:
        self.db.execute(
            "INSERT INTO control_actions VALUES (?, ?, ?, ?, ?)",
            (
                record.request_id,
                fingerprint,
                record.state.value,
                record.right_number,
                record.model_dump_json(),
            ),
        )

    def update_action(self, record: ActionRecord) -> None:
        self.db.execute(
            "UPDATE control_actions SET state = ?, record = ? WHERE request_id = ?",
            (record.state.value, record.model_dump_json(), record.request_id),
        )

    def actions_in(
        self, *states: ActionState, right_number: int | None = None
    ) -> list[ActionRecord]:
        marks = ", ".join("?" for _ in states)
        rows = self.db.query(
            f"SELECT record FROM control_actions WHERE state IN ({marks})"
            " AND (? IS NULL OR right_number = ?) ORDER BY rowid",
            (*(state.value for state in states), right_number, right_number),
        )
        return [ActionRecord.model_validate_json(row["record"]) for row in rows]

    def unsettled(self) -> list[ActionRecord]:
        return [r for r in self.actions_in(ActionState.UNKNOWN) if r.settled_at is None]

    # --- safety configuration -----------------------------------------------------------------

    def save_safety(self, config: SafetyConfig, recovery: int, operator: str, at: float) -> None:
        self.db.execute(
            "INSERT INTO control_safety(config, recovery_number, operator, approved_at)"
            " VALUES (?, ?, ?, ?)",
            (config.model_dump_json(), recovery, operator, at),
        )

    def latest_safety(self) -> tuple[SafetyConfig, int] | None:
        row = self.db.one(
            "SELECT config, recovery_number FROM control_safety ORDER BY id DESC LIMIT 1"
        )
        if row is None:
            return None
        return SafetyConfig.model_validate_json(row["config"]), int(row["recovery_number"])


def _right(row: Any) -> WriteRight:
    return WriteRight(
        number=row["number"],
        kind=RightKind(row["kind"]),
        device_id=row["device_id"],
        recovery_number=row["recovery_number"],
        granted_at=row["granted_at"],
        channels=tuple(Channel(value) for value in json.loads(row["channels"])),
        levels=tuple(RuleAction.model_validate(item) for item in json.loads(row["levels"])),
        experiment_id=row["experiment_id"],
        stage_id=row["stage_id"],
        run_sheet_digest=row["run_sheet_digest"],
        operator=row["operator"],
        revoked_at=row["revoked_at"],
    )
