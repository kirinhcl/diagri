"""Persistence of the workflow service: projects, protocols, rounds, stages, approvals, history.

Stage rows carry a revision number. Every update states the revision it was computed from, so
a slow caller that awaited a control call cannot overwrite a newer state (compare-and-set).
Raw records only append: approvals are voided, never deleted; history and interventions grow.
Column names in dynamic SQL come from model field names, never from caller input.
"""

import json
import sqlite3
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from growbridge.archive.db import Database
from growbridge.archive.models import (
    STORED,
    Approval,
    Channel,
    Model,
    ResearchProtocol,
    RightKind,
    RuleAction,
    RunSheet,
)
from growbridge.ports import Denied, Difference, RightScope, StageEvent, StageEventKind
from growbridge.workflow.states import ROUND_TERMINAL, STAGE_TERMINAL, RoundState, StageState

S = StageState

NAMESPACE = "workflow"
LIVE_STATES = (
    StageState.RUNNING,
    StageState.PAUSED,
    StageState.MANUAL,
    StageState.RECOVERY_CHECK,
)

STEPS = (
    "CREATE TABLE wf_projects(id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at REAL NOT NULL)",
    "CREATE TABLE wf_protocols(id TEXT NOT NULL, version INTEGER NOT NULL,"
    " project_id TEXT NOT NULL, digest TEXT NOT NULL, body TEXT NOT NULL,"
    " created_at REAL NOT NULL, PRIMARY KEY(id, version))",
    "CREATE TABLE wf_rounds(id TEXT PRIMARY KEY, project_id TEXT NOT NULL,"
    " protocol_id TEXT NOT NULL, protocol_version INTEGER NOT NULL, state TEXT NOT NULL,"
    " stages_done INTEGER NOT NULL, awaiting_choice TEXT, snapshot_id TEXT,"
    " report_artifact_id TEXT, created_at REAL NOT NULL)",
    "CREATE TABLE wf_run_sheets(id TEXT NOT NULL, version INTEGER NOT NULL,"
    " round_id TEXT NOT NULL, stage_id TEXT NOT NULL, digest TEXT NOT NULL,"
    " body TEXT NOT NULL, submitted_at REAL NOT NULL, PRIMARY KEY(id, version))",
    "CREATE TABLE wf_stages(stage_id TEXT PRIMARY KEY, round_id TEXT NOT NULL,"
    " project_id TEXT NOT NULL, experiment_id TEXT NOT NULL, device_id TEXT NOT NULL,"
    " run_sheet_id TEXT NOT NULL, run_sheet_version INTEGER NOT NULL, state TEXT NOT NULL,"
    " prior_state TEXT, right_number INTEGER, care_right INTEGER, manual_right INTEGER,"
    " manual_operator TEXT, started_at REAL, paused_at REAL, state_at REAL NOT NULL,"
    " end_pending INTEGER NOT NULL DEFAULT 0, onsite_checked INTEGER NOT NULL DEFAULT 0,"
    " recovery_number INTEGER NOT NULL, rev INTEGER NOT NULL DEFAULT 0)",
    "CREATE TABLE wf_approvals(id TEXT PRIMARY KEY, stage_id TEXT NOT NULL,"
    " approved_at REAL NOT NULL, voided_at REAL, body TEXT NOT NULL)",
    "CREATE TABLE wf_events(event_id TEXT PRIMARY KEY, stage_id TEXT, round_id TEXT,"
    " kind TEXT NOT NULL, at REAL NOT NULL, outcome TEXT NOT NULL)",
    "CREATE TABLE wf_history(id INTEGER PRIMARY KEY AUTOINCREMENT, stage_id TEXT NOT NULL,"
    " at REAL NOT NULL, from_state TEXT NOT NULL, to_state TEXT NOT NULL,"
    " event TEXT NOT NULL, detail TEXT NOT NULL)",
    "CREATE TABLE wf_interventions(id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " experiment_id TEXT NOT NULL, stage_id TEXT NOT NULL, at REAL NOT NULL,"
    " kind TEXT NOT NULL, operator TEXT, detail TEXT NOT NULL)",
    "CREATE INDEX wf_stages_round ON wf_stages(round_id)",
    "CREATE INDEX wf_approvals_stage ON wf_approvals(stage_id)",
    # multi-user: who owns a project; whether a released greenhouse took a stage's care away
    "ALTER TABLE wf_projects ADD COLUMN owner TEXT",
    "ALTER TABLE wf_stages ADD COLUMN care_released INTEGER NOT NULL DEFAULT 0",
    "CREATE TABLE wf_project_owner_events(id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " project_id TEXT NOT NULL, from_owner TEXT, to_owner TEXT NOT NULL, actor TEXT NOT NULL,"
    " at REAL NOT NULL, note TEXT NOT NULL)",
)
FINISHED_STATES = (StageState.ENDED, StageState.STOPPED)


class DuplicateEvent(Exception):
    """The event id was already recorded; the transaction that tried again rolls back."""


class StageRow(Model):
    stage_id: str
    round_id: str
    project_id: str
    experiment_id: str
    device_id: str
    run_sheet_id: str
    run_sheet_version: int
    state: StageState
    prior_state: StageState | None = None
    right_number: int | None = None
    care_right: int | None = None
    manual_right: int | None = None
    manual_operator: str | None = None
    started_at: float | None = None
    paused_at: float | None = None
    state_at: float
    end_pending: bool = False
    onsite_checked: bool = False
    recovery_number: int
    rev: int = 0
    care_released: bool = False  # a greenhouse release took this stage's care away for good


class RoundRow(Model):
    id: str
    project_id: str
    protocol_id: str
    protocol_version: int
    state: RoundState
    stages_done: int = 0
    awaiting_choice: str | None = None
    snapshot_id: str | None = None
    report_artifact_id: str | None = None


def _db_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bool):
        return int(value)
    return value


def _marks(count: int) -> str:
    return ", ".join("?" * count)


def _assignments(changes: dict[str, Any], allowed: Iterable[str]) -> tuple[str, list[Any]]:
    unknown = set(changes) - set(allowed)
    if unknown:
        raise ValueError(f"unknown columns {sorted(unknown)}")
    sets = ", ".join(f"{column} = ?" for column in changes)
    return sets, [_db_value(value) for value in changes.values()]


class WorkflowStore:
    def __init__(self, db: Database):
        self.db = db
        db.migrate(NAMESPACE, STEPS)

    # --- projects and protocols ----------------------------------------------------------------

    def add_project(self, project_id: str, name: str, now: float, owner: str | None = None) -> None:
        self.db.execute(
            "INSERT INTO wf_projects(id, name, created_at, owner) VALUES (?, ?, ?, ?)",
            (project_id, name, now, owner),
        )

    def project_owner(self, project_id: str) -> str | None:
        row = self.db.one("SELECT owner FROM wf_projects WHERE id = ?", (project_id,))
        return None if row is None else row["owner"]

    def set_project_owner(
        self,
        project_id: str,
        owner: str,
        actor: str,
        note: str,
        now: float,
        eligible: Callable[[], None],
    ) -> None:
        """Give the project to ``owner``; ``eligible`` re-checks the transfer in the same step."""
        with self.db.transaction():
            eligible()
            previous = self.project_owner(project_id)
            self.db.execute("UPDATE wf_projects SET owner = ? WHERE id = ?", (owner, project_id))
            self.db.execute(
                "INSERT INTO wf_project_owner_events(project_id, from_owner, to_owner, actor, at,"
                " note) VALUES (?, ?, ?, ?, ?, ?)",
                (project_id, previous, owner, actor, now, note),
            )

    def owner_events(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM wf_project_owner_events WHERE project_id = ? ORDER BY id DESC",
            (project_id,),
        )
        return [dict(row) for row in rows]

    def has_project(self, project_id: str) -> bool:
        return self.db.one("SELECT 1 FROM wf_projects WHERE id = ?", (project_id,)) is not None

    def protocol(self, protocol_id: str, version: int) -> ResearchProtocol | None:
        row = self.db.one(
            "SELECT body FROM wf_protocols WHERE id = ? AND version = ?", (protocol_id, version)
        )
        return None if row is None else ResearchProtocol.model_validate_json(row["body"])

    def protocol_variables_before(self, protocol_id: str, version: int) -> frozenset[str]:
        rows = self.db.query(
            "SELECT body FROM wf_protocols WHERE id = ? AND version < ?", (protocol_id, version)
        )
        declared: set[str] = set()
        for row in rows:
            declared.update(ResearchProtocol.model_validate_json(row["body"]).variables)
        return frozenset(declared)

    def latest_protocol(self, protocol_id: str, project_id: str) -> ResearchProtocol | None:
        row = self.db.one(
            "SELECT body FROM wf_protocols WHERE id = ? AND project_id = ?"
            " ORDER BY version DESC LIMIT 1",
            (protocol_id, project_id),
        )
        return None if row is None else ResearchProtocol.model_validate_json(row["body"])

    def put_protocol(self, protocol: ResearchProtocol, now: float) -> None:
        self.db.execute(
            "INSERT INTO wf_protocols VALUES (?, ?, ?, ?, ?, ?)",
            (
                protocol.id,
                protocol.version,
                protocol.project_id,
                protocol.digest(),
                protocol.model_dump_json(),
                now,
            ),
        )

    # --- rounds --------------------------------------------------------------------------------

    def add_round(self, row: RoundRow, now: float) -> None:
        self.db.execute(
            "INSERT INTO wf_rounds VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row.id,
                row.project_id,
                row.protocol_id,
                row.protocol_version,
                row.state.value,
                row.stages_done,
                row.awaiting_choice,
                row.snapshot_id,
                row.report_artifact_id,
                now,
            ),
        )

    def round(self, round_id: str) -> RoundRow:
        row = self.db.one("SELECT * FROM wf_rounds WHERE id = ?", (round_id,))
        if row is None:
            raise Denied(
                "state",
                f"unknown round {round_id}",
                reason="record_not_found",
                params={"record_kind": "round", "record_id": round_id},
            )
        return RoundRow(**{key: row[key] for key in RoundRow.model_fields})

    def round_number(self, round_id: str) -> int:
        """The round's place among its project's rounds of the same protocol, from 1, in the
        order they were created: the protocol's allocation round it runs. Aborted rounds keep
        their number (a make-up round gets a new one)."""
        row = self.round(round_id)
        found = self.db.one(
            "SELECT COUNT(*) AS n FROM wf_rounds WHERE project_id = ? AND protocol_id = ?"
            " AND rowid <= (SELECT rowid FROM wf_rounds WHERE id = ?)",
            (row.project_id, row.protocol_id, round_id),
        )
        return int(found["n"])

    def started_round_numbers(self, project_id: str, protocol_id: str) -> frozenset[int]:
        """The ``round_number`` of each of the project's rounds of this protocol that has a stage
        that has started: the rounds whose data should exist, whether or not a report cites it."""
        rows = self.db.query(
            "SELECT EXISTS(SELECT 1 FROM wf_stages s WHERE s.round_id = r.id"
            " AND s.started_at IS NOT NULL) AS started FROM wf_rounds r"
            " WHERE r.project_id = ? AND r.protocol_id = ? ORDER BY r.rowid",
            (project_id, protocol_id),
        )
        return frozenset(number for number, row in enumerate(rows, 1) if row["started"])

    def update_round(self, round_id: str, **changes: Any) -> RoundRow:
        sets, values = _assignments(changes, set(RoundRow.model_fields) - {"id"})
        self.db.execute(f"UPDATE wf_rounds SET {sets} WHERE id = ?", (*values, round_id))
        return self.round(round_id)

    # --- run sheets ----------------------------------------------------------------------------

    def run_sheet(self, sheet_id: str, version: int) -> RunSheet:
        row = self.db.one(
            "SELECT body FROM wf_run_sheets WHERE id = ? AND version = ?", (sheet_id, version)
        )
        if row is None:
            raise Denied(
                "state",
                f"unknown run sheet {sheet_id} v{version}",
                reason="record_not_found",
                params={"record_kind": "run_sheet", "record_id": sheet_id},
            )
        return RunSheet.model_validate_json(row["body"], context=STORED)

    def run_sheet_digest(self, sheet_id: str, version: int) -> str | None:
        row = self.db.one(
            "SELECT digest FROM wf_run_sheets WHERE id = ? AND version = ?", (sheet_id, version)
        )
        return None if row is None else row["digest"]

    def put_run_sheet(self, sheet: RunSheet, round_id: str, now: float) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO wf_run_sheets VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                sheet.id,
                sheet.version,
                round_id,
                sheet.stage_id,
                sheet.digest(),
                sheet.model_dump_json(),
                now,
            ),
        )

    # --- stages --------------------------------------------------------------------------------

    @staticmethod
    def _stage_row(row: sqlite3.Row) -> StageRow:
        data = {key: row[key] for key in StageRow.model_fields}
        data["end_pending"] = bool(data["end_pending"])
        data["onsite_checked"] = bool(data["onsite_checked"])
        data["care_released"] = bool(data["care_released"])
        return StageRow(**data)

    def add_stage(self, row: StageRow) -> None:
        columns = list(StageRow.model_fields)
        values = [_db_value(getattr(row, column)) for column in columns]
        self.db.execute(
            f"INSERT INTO wf_stages({', '.join(columns)}) VALUES ({_marks(len(columns))})",
            values,
        )

    def find_stage(self, stage_id: str) -> StageRow | None:
        row = self.db.one("SELECT * FROM wf_stages WHERE stage_id = ?", (stage_id,))
        return None if row is None else self._stage_row(row)

    def stage(self, stage_id: str) -> StageRow:
        row = self.find_stage(stage_id)
        if row is None:
            raise Denied(
                "state",
                f"unknown stage {stage_id}",
                reason="record_not_found",
                params={"record_kind": "stage", "record_id": stage_id},
            )
        return row

    def update_stage(self, row: StageRow, **changes: Any) -> StageRow:
        """Compare-and-set on ``row.rev``: a stale caller gets ``Denied("state")``."""
        sets, values = _assignments(changes, set(StageRow.model_fields) - {"stage_id", "rev"})
        cursor = self.db.execute(
            f"UPDATE wf_stages SET {sets}, rev = rev + 1 WHERE stage_id = ? AND rev = ?",
            (*values, row.stage_id, row.rev),
        )
        if cursor.rowcount != 1:
            raise Denied(
                "state",
                f"stage {row.stage_id} changed while the request was running",
                reason="stage_changed_concurrently",
                params={"stage_id": row.stage_id},
            )
        return self.stage(row.stage_id)

    def stages_of_round(self, round_id: str) -> tuple[StageRow, ...]:
        rows = self.db.query(
            "SELECT * FROM wf_stages WHERE round_id = ? ORDER BY rowid", (round_id,)
        )
        return tuple(self._stage_row(row) for row in rows)

    def stages_in(self, states: Iterable[StageState]) -> tuple[StageRow, ...]:
        wanted = [state.value for state in states]
        rows = self.db.query(
            f"SELECT * FROM wf_stages WHERE state IN ({_marks(len(wanted))}) ORDER BY rowid",
            wanted,
        )
        return tuple(self._stage_row(row) for row in rows)

    def other_care_holders(self, device_id: str, stage_id: str) -> tuple[StageRow, ...]:
        rows = self.db.query(
            "SELECT * FROM wf_stages WHERE device_id = ? AND stage_id != ?"
            " AND care_right IS NOT NULL",
            (device_id, stage_id),
        )
        return tuple(self._stage_row(row) for row in rows)

    def _unfinished(self, column: str, value: str) -> bool:
        done = [state.value for state in FINISHED_STATES]
        row = self.db.one(
            f"SELECT 1 FROM wf_stages WHERE {column} = ? AND state NOT IN ({_marks(len(done))})",
            (value, *done),
        )
        return row is not None

    def device_unfinished(self, device_id: str) -> bool:
        """Whether any stage on the device has not ended or stopped (pending ones included)."""
        return self._unfinished("device_id", device_id)

    def project_unfinished(self, project_id: str) -> bool:
        return self._unfinished("project_id", project_id)

    def unfinished_stages_of_owner(self, owner: str) -> int:
        done = [state.value for state in FINISHED_STATES]
        row = self.db.one(
            "SELECT COUNT(*) AS n FROM wf_stages s JOIN wf_projects p ON p.id = s.project_id"
            f" WHERE p.owner = ? AND s.state NOT IN ({_marks(len(done))})",
            (owner, *done),
        )
        return row["n"] if row else 0

    def release_care_of_device(self, device_id: str) -> None:
        """No finished stage of the device holds or gets care again (a greenhouse release)."""
        done = [state.value for state in FINISHED_STATES]
        self.db.execute(
            "UPDATE wf_stages SET care_right = NULL, care_released = 1, rev = rev + 1"
            f" WHERE device_id = ? AND state IN ({_marks(len(done))})",
            (device_id, *done),
        )

    def drop_care(self, stage_id: str, care_right: int) -> None:
        """Forget a care right a command handed back and was then refused for, so the next
        ``restore_care`` issues care again; a stage whose care changed meanwhile keeps it."""
        self.db.execute(
            "UPDATE wf_stages SET care_right = NULL, rev = rev + 1"
            " WHERE stage_id = ? AND care_right = ?",
            (stage_id, care_right),
        )

    def care_holder(self, device_id: str) -> StageRow | None:
        row = self.db.one(
            "SELECT * FROM wf_stages WHERE device_id = ? AND care_right IS NOT NULL"
            " ORDER BY rowid DESC LIMIT 1",
            (device_id,),
        )
        return None if row is None else self._stage_row(row)

    def live_stage_on(self, device_id: str, stage_id: str) -> str | None:
        """The id of another stage still live or being checked on this device, if any."""
        states = [state.value for state in LIVE_STATES]
        row = self.db.one(
            "SELECT stage_id FROM wf_stages WHERE device_id = ? AND stage_id != ?"
            f" AND state IN ({_marks(len(states))})",
            (device_id, stage_id, *states),
        )
        return None if row is None else str(row["stage_id"])

    def active(self) -> StageRow | None:
        """Latest started stage of a round that is not yet delivered or aborted."""
        row = self.db.one(
            "SELECT s.* FROM wf_stages s JOIN wf_rounds r ON r.id = s.round_id"
            " WHERE s.started_at IS NOT NULL AND r.state NOT IN (?, ?)"
            " ORDER BY s.started_at DESC, s.rowid DESC LIMIT 1",
            (RoundState.DELIVERED.value, RoundState.ABORTED.value),
        )
        return None if row is None else self._stage_row(row)

    def protocol_started(self, protocol_id: str, version: int) -> bool:
        """Whether any stage of any round that runs this protocol version has ever started."""
        row = self.db.one(
            "SELECT 1 FROM wf_stages s JOIN wf_rounds r ON r.id = s.round_id"
            " WHERE r.protocol_id = ? AND r.protocol_version = ? AND s.started_at IS NOT NULL"
            " LIMIT 1",
            (protocol_id, version),
        )
        return row is not None

    def experiments_under(self, protocol_id: str, version: int) -> tuple[str, ...]:
        """The experiments of the stages of the rounds that run this protocol version."""
        rows = self.db.query(
            "SELECT DISTINCT s.experiment_id FROM wf_stages s JOIN wf_rounds r ON r.id = s.round_id"
            " WHERE r.protocol_id = ? AND r.protocol_version = ? ORDER BY s.experiment_id",
            (protocol_id, version),
        )
        return tuple(row["experiment_id"] for row in rows)

    def stage_starts(self, experiment_id: str) -> tuple[float | None, ...]:
        """The start time of every stage that runs this experiment (None: not started yet)."""
        rows = self.db.query(
            "SELECT started_at FROM wf_stages WHERE experiment_id = ? ORDER BY rowid",
            (experiment_id,),
        )
        return tuple(row["started_at"] for row in rows)

    def projects_of_experiment(self, experiment_id: str) -> tuple[str, ...]:
        """The projects whose stages run this experiment (none: no stage owns it)."""
        rows = self.db.query(
            "SELECT DISTINCT project_id FROM wf_stages WHERE experiment_id = ? ORDER BY project_id",
            (experiment_id,),
        )
        return tuple(row["project_id"] for row in rows)

    def protocol_versions_of(self, experiment_id: str) -> tuple[tuple[str, int], ...]:
        """The (protocol id, version) of every round that has a stage for this experiment."""
        rows = self.db.query(
            "SELECT DISTINCT r.protocol_id, r.protocol_version FROM wf_stages s"
            " JOIN wf_rounds r ON r.id = s.round_id WHERE s.experiment_id = ?"
            " ORDER BY r.protocol_id, r.protocol_version",
            (experiment_id,),
        )
        return tuple((row["protocol_id"], row["protocol_version"]) for row in rows)

    def declared_variables(self, experiment_id: str) -> frozenset[str]:
        """The union of the variables of every protocol version a stage of this experiment runs
        under (none: no stage runs it). A round's protocol version is always saved before the
        round; were one missing, its variables would simply not count, which refuses more."""
        declared: set[str] = set()
        for protocol_id, version in self.protocol_versions_of(experiment_id):
            protocol = self.protocol(protocol_id, version)
            if protocol is not None:
                declared.update(protocol.variables)
        return frozenset(declared)

    # --- approvals -----------------------------------------------------------------------------

    def add_approval(self, approval: Approval) -> None:
        self.db.execute(
            "INSERT INTO wf_approvals VALUES (?, ?, ?, NULL, ?)",
            (approval.id, approval.stage_id, approval.approved_at, approval.model_dump_json()),
        )

    def approvals(self, stage_id: str) -> tuple[Approval, ...]:
        rows = self.db.query(
            "SELECT body, voided_at FROM wf_approvals WHERE stage_id = ? ORDER BY rowid",
            (stage_id,),
        )
        return tuple(
            Approval.model_validate_json(row["body"]).model_copy(
                update={"voided_at": row["voided_at"]}
            )
            for row in rows
        )

    def valid_approval(self, stage_id: str) -> Approval | None:
        live = [approval for approval in self.approvals(stage_id) if approval.voided_at is None]
        return live[-1] if live else None

    def void_approvals(self, stage_id: str, now: float) -> None:
        self.db.execute(
            "UPDATE wf_approvals SET voided_at = ? WHERE stage_id = ? AND voided_at IS NULL",
            (now, stage_id),
        )

    # --- events, history, interventions --------------------------------------------------------

    def event_seen(self, event_id: str) -> bool:
        return self.db.one("SELECT 1 FROM wf_events WHERE event_id = ?", (event_id,)) is not None

    def record_event(
        self,
        event_id: str,
        stage_id: str | None,
        round_id: str | None,
        kind: str,
        at: float,
        outcome: str,
    ) -> None:
        try:
            self.db.execute(
                "INSERT INTO wf_events VALUES (?, ?, ?, ?, ?, ?)",
                (event_id, stage_id, round_id, kind, at, outcome),
            )
        except sqlite3.IntegrityError as error:
            raise DuplicateEvent(event_id) from error

    def add_history(
        self, stage_id: str, at: float, before: str, after: str, event: str, detail: dict
    ) -> None:
        self.db.execute(
            "INSERT INTO wf_history(stage_id, at, from_state, to_state, event, detail)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (stage_id, at, before, after, event, json.dumps(detail, sort_keys=True)),
        )

    def history(self, stage_id: str) -> tuple[dict, ...]:
        rows = self.db.query("SELECT * FROM wf_history WHERE stage_id = ? ORDER BY id", (stage_id,))
        return tuple(
            {
                "at": row["at"],
                "from": row["from_state"],
                "to": row["to_state"],
                "event": row["event"],
                "detail": json.loads(row["detail"]),
            }
            for row in rows
        )

    def entered(self, stage_id: str, state: StageState) -> dict | None:
        """The latest history entry that moved the stage into ``state`` from another state."""
        row = self.db.one(
            "SELECT * FROM wf_history WHERE stage_id = ? AND to_state = ?"
            " AND from_state != to_state ORDER BY id DESC LIMIT 1",
            (stage_id, state.value),
        )
        if row is None:
            return None
        detail = json.loads(row["detail"])
        return {"entry": row["id"], "at": row["at"], "event": row["event"], "detail": detail}

    def add_intervention(
        self,
        experiment_id: str,
        stage_id: str,
        at: float,
        kind: str,
        operator: str | None,
        detail: dict,
    ) -> None:
        self.db.execute(
            "INSERT INTO wf_interventions(experiment_id, stage_id, at, kind, operator, detail)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (experiment_id, stage_id, at, kind, operator, json.dumps(detail, sort_keys=True)),
        )

    def interventions(self, experiment_id: str) -> tuple[dict, ...]:
        rows = self.db.query(
            "SELECT * FROM wf_interventions WHERE experiment_id = ? ORDER BY id", (experiment_id,)
        )
        return tuple(
            {
                "stage_id": row["stage_id"],
                "at": row["at"],
                "kind": row["kind"],
                "operator": row["operator"],
                **json.loads(row["detail"]),
            }
            for row in rows
        )

    # --- round state ---------------------------------------------------------------------------

    def stage_total(self, rnd: RoundRow) -> int:
        protocol = self.protocol(rnd.protocol_id, rnd.protocol_version)
        return len(protocol.stages) if protocol is not None else 0

    def round_effect(self, stage: StageRow, effect: str) -> None:
        """What a stage change does to its round (App. B, round table)."""
        rnd = self.round(stage.round_id)
        if rnd.state in ROUND_TERMINAL:
            return
        if effect == "started" and rnd.state is RoundState.STAGE_REVIEW:
            self.update_round(rnd.id, state=RoundState.STAGE_RUNNING)
        elif effect == "to_review" and rnd.state is RoundState.STAGE_RUNNING:
            self.update_round(rnd.id, state=RoundState.STAGE_REVIEW)
        elif effect == "stopped":
            self.update_round(rnd.id, awaiting_choice=stage.stage_id)
        elif effect == "ended" and rnd.state is RoundState.STAGE_RUNNING:
            done = rnd.stages_done + 1
            more = done < self.stage_total(rnd)
            target = RoundState.STAGE_REVIEW if more else RoundState.DATA_VERIFICATION
            self.update_round(rnd.id, state=target, stages_done=done)

    def abort_stage(self, stage: StageRow, now: float) -> None:
        cleared = {"right_number": None, "manual_right": None, "care_right": None}
        if stage.state in STAGE_TERMINAL:
            self.update_stage(stage, **cleared)
            return
        self.void_approvals(stage.stage_id, now)
        self.update_stage(stage, state=S.STOPPED, prior_state=None, state_at=now, **cleared)
        args = (stage.stage_id, now, stage.state.value, S.STOPPED.value)
        self.add_history(*args, "round_aborted", {})

    def mark_round(
        self,
        round_id: str,
        event_id: str,
        kind: str,
        move: tuple[RoundState, RoundState],
        changes: dict[str, Any],
        now: float,
    ) -> RoundState:
        """Advance once per event id; an event that arrives in the wrong state is dropped."""
        expected, target = move
        rnd = self.round(round_id)
        if self.event_seen(event_id):
            return rnd.state
        applies = rnd.state is expected
        try:
            with self.db.transaction():
                outcome = "applied" if applies else "dropped"
                self.record_event(event_id, None, round_id, kind, now, outcome)
                if applies:
                    return self.update_round(round_id, state=target, **changes).state
        except DuplicateEvent:
            pass
        return self.round(round_id).state


# --- stage plans: what a change of stage state consists of ----------------------------------------


@dataclass(frozen=True)
class Grant:
    kind: RightKind
    column: str  # the StageRow column that receives the new right number
    operator: str | None = None


Hook = Callable[[StageRow], None]


@dataclass(frozen=True)
class Plan:
    """Enter ``state``: hand over ``handover`` rights first, then grant ``grants``, then save."""

    state: StageState
    event: str
    updates: dict[str, Any] = field(default_factory=dict)
    handover: tuple[int, ...] = ()
    grants: tuple[Grant, ...] = ()
    reason: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    round_effect: Literal["started", "ended", "stopped", "to_review"] | None = None
    sheet: RunSheet | None = None  # governs the new rights when the run sheet changes
    extra: Hook | None = None  # more records, written inside the same transaction


def held(*numbers: int | None) -> tuple[int, ...]:
    return tuple(number for number in numbers if number is not None)


def care_if_missing(stage: StageRow) -> tuple[Grant, ...]:
    return () if stage.care_right is not None else (Grant(RightKind.CARE, "care_right"),)


def describe(diffs: Sequence[Difference]) -> str:
    return ", ".join(f"{d.channel.value}.{d.field} {d.expected} != {d.actual}" for d in diffs)


def right_scope(stage: StageRow, sheet: RunSheet, kind: RightKind) -> RightScope | None:
    hosted: tuple[Channel, ...] = sheet.host_channels()
    base = {"device_id": sheet.device_id, "experiment_id": stage.experiment_id}
    base["stage_id"] = stage.stage_id
    if kind is RightKind.MANUAL:
        return RightScope(**base, channels=hosted)
    if kind is RightKind.STAGE:
        return RightScope(**base, run_sheet_digest=sheet.digest(), channels=hosted)
    steps = [step for rule in sheet.care_rules for step in rule.schedule if step.channel in hosted]
    if not steps:
        return None  # a run sheet without care rules gets no care right
    levels = tuple(dict.fromkeys(RuleAction(channel=s.channel, level=s.level) for s in steps))
    channels = tuple(dict.fromkeys(step.channel for step in steps))
    return RightScope(**base, run_sheet_digest=sheet.digest(), channels=channels, levels=levels)


def pause_plan(stage: StageRow, event: str, now: float) -> Plan:
    updates = {"right_number": None, "paused_at": now}
    return Plan(S.PAUSED, event, updates, handover=held(stage.right_number), reason=event)


def recovery_plan(stage: StageRow, event: str) -> Plan:
    """Old writes or the pump cannot be confirmed: nothing may write until it is checked."""
    cleared = {"right_number": None, "manual_right": None, "care_right": None}
    return Plan(
        S.RECOVERY_CHECK,
        event,
        updates={**cleared, "prior_state": stage.state, "onsite_checked": False},
        handover=held(stage.right_number, stage.manual_right, stage.care_right),
        reason=event,
    )


def end_actions_plan(stage: StageRow, event: StageEvent) -> Plan | None:
    if stage.state is not S.RUNNING or not stage.end_pending:
        return None
    if not event.detail.get("confirmed", False):
        return recovery_plan(stage, event.kind.value)
    return Plan(
        S.ENDED,
        event.kind.value,
        updates={"right_number": None, "end_pending": False},
        handover=held(stage.right_number),
        reason="stage ended",
        detail={"confirmed": True},
        round_effect="ended",
    )


def expiry_plan(outcome: StageState) -> Plan:
    """The longest wait is over: the run sheet says whether the stage stays paused or stops."""
    event = StageEventKind.MAX_WAIT_EXPIRED.value
    if outcome is S.STOPPED:
        updates = {"prior_state": None}
        return Plan(S.STOPPED, event, updates, detail={"on_expiry": "stop"}, round_effect="stopped")
    return Plan(S.PAUSED, event, detail={"on_expiry": "stay_paused"})
