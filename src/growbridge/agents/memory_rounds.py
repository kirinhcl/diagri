"""A project's closed rounds as a model reads them (memory design 2026-11-17, section 5.1).

Each round carries its report and the decisions people made. A report is downgraded, and then
gives no conclusion and no numbers, when its file is missing or changed (``unavailable``), when it
or any snapshot it used was invalidated by a later correction (``invalid``), or when it read a
holdout (``held_out``). Only snapshots of the project count: ``evidence_chain`` is partly written
by the model, and a foreign id must not reveal anything about another project.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Iterator
from pathlib import Path
from typing import Any

from growbridge.agents.memory_sources import MemorySources
from growbridge.archive.ids import file_digest
from growbridge.planning.treatment import allocated
from growbridge.ports import Denied
from growbridge.workflow.states import RoundState

MAX_ROUNDS = 5
MAX_DECISIONS = 8
MAX_LIMITATIONS = 3
CLOSED = (RoundState.DELIVERED.value, RoundState.ABORTED.value)
SNAPSHOT_REF = "snapshot:"


def round_summaries(src: MemorySources, project_id: str, skip: Collection[str]) -> list[dict]:
    """The project's closed rounds, newest first, without those in ``skip``."""
    rows = src.workflow.store.db.query(
        "SELECT id FROM wf_rounds WHERE project_id = ? AND state IN (?, ?)"
        " ORDER BY created_at DESC, rowid DESC",
        (project_id, *CLOSED),
    )
    ids = [row["id"] for row in rows if row["id"] not in skip][:MAX_ROUNDS]
    return [_summary(src, project_id, round_id) for round_id in ids]


def round_record(src: MemorySources, project_id: str, round_id: str) -> dict:
    """One round of the project in full; another project's round reads as an unknown one."""
    rnd = src.workflow.store.round(round_id)
    if rnd.project_id != project_id:
        raise Denied("state", f"unknown round {round_id}")
    downgrade, body = load_report(src, project_id, rnd.report_artifact_id)
    return {**_base(src, rnd), "report": downgrade or body, "decisions": decisions(src, round_id)}


def _summary(src: MemorySources, project_id: str, round_id: str) -> dict:
    rnd = src.workflow.store.round(round_id)
    downgrade, body = load_report(src, project_id, rnd.report_artifact_id)
    report = downgrade or (report_summary(body) if body is not None else None)
    picked = decisions(src, round_id)[:MAX_DECISIONS]
    return {**_base(src, rnd), "report": report, "decisions": picked}


def _base(src: MemorySources, rnd: Any) -> dict:
    store = src.workflow.store
    protocol = store.protocol(rnd.protocol_id, rnd.protocol_version)
    number = store.round_number(rnd.id)
    treatment = None if protocol is None else allocated(protocol, number)
    ends = [h["at"] for s in store.stages_of_round(rnd.id) for h in store.history(s.stage_id)]
    return {
        "round_id": rnd.id,
        "state": rnd.state.value,
        "protocol_id": rnd.protocol_id,
        "protocol_version": rnd.protocol_version,
        "protocol_round": number,
        "treatment": None if treatment is None else treatment.model_dump(mode="json"),
        "ended_at": max(ends, default=None),
    }


# --- reports -------------------------------------------------------------------------------------


def load_report(
    src: MemorySources, project_id: str, artifact_id: str | None
) -> tuple[dict | None, dict | None]:
    """``(downgrade, body)``: exactly one is set when the round has a report, neither otherwise."""
    if artifact_id is None:
        return None, None
    artifact = src.archive.artifact(artifact_id)
    body = None if artifact is None else _read(artifact)
    if body is None:
        return {"unavailable": True}, None
    if _invalid(src, project_id, artifact, body):
        return {"invalid": True, "label": artifact.label}, None
    if _held_out(src, project_id, body):
        return {"held_out": True, "label": artifact.label}, None
    return None, body


def report_summary(body: dict) -> dict:
    estimate = body.get("estimate") or {}
    return {
        "label": body.get("label"),
        "conclusion": body.get("conclusion"),
        "effect": estimate.get("effect"),
        "p_value": estimate.get("p_value"),
        "limitations": list(body.get("limitations", ()))[:MAX_LIMITATIONS],
        "next_round": body.get("next_round"),
        "unresolved": list(body.get("unresolved", ())),
    }


def _read(artifact: Any) -> dict | None:
    path = Path(artifact.path)
    try:
        if file_digest(path) != artifact.sha256:
            return None
        body = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return body if isinstance(body, dict) else None


def _invalid(src: MemorySources, project_id: str, artifact: Any, body: dict) -> bool:
    ids = {artifact.id, *_own_snapshots(src, project_id, body)}
    if artifact.snapshot_id is not None:
        ids.add(artifact.snapshot_id)
    return any(src.archive.is_invalid(record_id) for record_id in ids)


def _own_snapshots(src: MemorySources, project_id: str, body: dict) -> Iterator[str]:
    """Snapshots named in the evidence chain that belong to this project only."""
    for ref in body.get("evidence_chain", ()):
        if not (isinstance(ref, str) and ref.startswith(SNAPSHOT_REF)):
            continue
        snap = src.archive.snapshot(ref[len(SNAPSHOT_REF) :])
        owners = (
            () if snap is None else src.workflow.store.projects_of_experiment(snap.experiment_id)
        )
        if tuple(owners) == (project_id,):
            yield snap.id


def _held_out(src: MemorySources, project_id: str, body: dict) -> bool:
    if "holdout_id" in body:
        return body["holdout_id"] is not None
    # written before reports named their holdout: any holdout of the project may be behind it
    return src.holdout is not None and bool(src.holdout.holdouts(project_id))


# --- decisions -----------------------------------------------------------------------------------


def decisions(src: MemorySources, round_id: str) -> list[dict]:
    """What people decided about the round, newest first: approvals, their own stage actions
    (history entries that name who did them), choices after a stop, and an abort."""
    store = src.workflow.store
    stages = store.stages_of_round(round_id)
    choices = [
        {"at": c["at"], "kind": "choice", "choice": c["choice"], "by": c["by"]}
        for c in store.choices(round_id)
    ]
    found = [*choices, *_approvals(store, stages), *_actions(store, stages)]
    if not any(c["choice"] == "abort" for c in choices):
        found += _old_abort(store, stages)
    return sorted(found, key=lambda item: item["at"], reverse=True)


def _approvals(store: Any, stages: Any) -> list[dict]:
    return [
        {
            "at": a.approved_at,
            "kind": "approved",
            "by": a.operator,
            "voided": a.voided_at is not None,
        }
        for stage in stages
        for a in store.approvals(stage.stage_id)
    ]


def _actions(store: Any, stages: Any) -> list[dict]:
    return [
        {
            "at": h["at"],
            "kind": h["event"],
            "by": h["detail"]["by"],
            "reason": h["detail"].get("reason"),
        }
        for stage in stages
        for h in store.history(stage.stage_id)
        if "by" in h["detail"]
    ]


def _old_abort(store: Any, stages: Any) -> list[dict]:
    """An abort recorded before choices were: its history entry, once, with no one named."""
    aborts = [h for s in stages for h in store.history(s.stage_id) if h["event"] == "round_aborted"]
    if not aborts:
        return []
    return [{"at": aborts[0]["at"], "kind": "round_aborted", "by": None, "reason": None}]
