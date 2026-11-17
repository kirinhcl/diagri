"""The refusals of the workflow service, each with its registered reason and params.

One function per reason, so the reason stays a literal at the ``Denied(...)`` call (the AST test
in tests/workbench/test_denial_codes.py reads it there). The coarse code and the English message
are what the service always sent; ``reason`` and ``params`` are what the console builds its text
from (growbridge.denial_codes). The caller raises what these return.
"""

from collections.abc import Sequence

from growbridge.ports import Denied, Difference
from growbridge.workflow.store import RoundRow, StageRow, describe


def _stage(stage: StageRow) -> dict[str, object]:
    return {"stage_id": stage.stage_id, "state": stage.state.value}


# --- design --------------------------------------------------------------------------------------


def project_name_required() -> Denied:
    return Denied("state", "a project needs a name", reason="project_name_required")


def record_not_found(kind: str, record_id: str, message: str) -> Denied:
    params = {"record_kind": kind, "record_id": record_id}
    return Denied("state", message, reason="record_not_found", params=params)


def protocol_version_exists(protocol_id: str, version: int) -> Denied:
    return Denied(
        "state",
        f"protocol {protocol_id} v{version} exists: bump version",
        reason="protocol_version_exists",
        params={"protocol_id": protocol_id, "version": version},
    )


def protocol_not_found(protocol_id: str, project_id: str) -> Denied:
    return Denied(
        "state",
        f"no protocol {protocol_id} saved for project {project_id}",
        reason="protocol_not_found",
        params={"protocol_id": protocol_id, "project_id": project_id},
    )


def drafter_only(role: str) -> Denied:
    return Denied(
        "model_role",
        f"only the {role} files run sheets",
        reason="drafter_only",
        params={"role": role},
    )


def round_not_accepting_run_sheets(rnd: RoundRow) -> Denied:
    return Denied(
        "state",
        f"round is {rnd.state.value}; no run sheet can be submitted",
        reason="round_not_accepting_run_sheets",
        params={"round_id": rnd.id, "state": rnd.state.value},
    )


def run_sheet_mismatch(run_sheet_id: str, record_kind: str, message: str) -> Denied:
    return Denied(
        "state",
        message,
        reason="run_sheet_mismatch",
        params={"run_sheet_id": run_sheet_id, "record_kind": record_kind},
    )


def not_this_project(project_id: str, experiment_id: str) -> Denied:
    return Denied(
        "scope",
        f"experiment {experiment_id} belongs to another project",
        reason="not_this_project",
        params={"project_id": project_id},
    )


def run_sheet_version_in_use(run_sheet_id: str, version: int) -> Denied:
    return Denied(
        "state",
        f"run sheet {run_sheet_id} v{version} is already in use",
        reason="run_sheet_version_in_use",
        params={"run_sheet_id": run_sheet_id, "version": version},
    )


def run_sheet_needs_switch(stage: StageRow) -> Denied:
    return Denied(
        "state",
        f"stage {stage.stage_id} is {stage.state.value}; use a switch",
        reason="run_sheet_needs_switch",
        params=_stage(stage),
    )


def run_sheet_version_conflict(run_sheet_id: str, version: int) -> Denied:
    return Denied(
        "state",
        "same run sheet version with other content: bump version",
        reason="run_sheet_version_conflict",
        params={"run_sheet_id": run_sheet_id, "version": version},
    )


def run_sheet_too_old(run_sheet_id: str, version: int, current: int, message: str) -> Denied:
    return Denied(
        "state",
        message,
        reason="run_sheet_too_old",
        params={"run_sheet_id": run_sheet_id, "version": version, "current_version": current},
    )


# --- approval ------------------------------------------------------------------------------------


def stage_not_awaiting_approval(stage: StageRow, message: str) -> Denied:
    return Denied("state", message, reason="stage_not_awaiting_approval", params=_stage(stage))


def run_sheet_changed_since_review(stage_id: str, expected: str, current: str) -> Denied:
    return Denied(
        "state",
        "the run sheet changed since it was reviewed",
        reason="run_sheet_changed_since_review",
        params={"stage_id": stage_id, "expected_digest": expected, "current_digest": current},
    )


def approval_blocking_findings(stage_id: str, message: str, count: int) -> Denied:
    return Denied(
        "approval_invalid",
        message,
        reason="approval_blocking_findings",
        params={"stage_id": stage_id, "count": count},
    )


def approval_none_valid(stage_id: str) -> Denied:
    return Denied(
        "approval_invalid",
        "no valid approval for this stage",
        reason="approval_none_valid",
        params={"stage_id": stage_id},
    )


def approval_run_sheet_changed(stage_id: str, message: str) -> Denied:
    return Denied(
        "approval_invalid",
        message,
        reason="approval_run_sheet_changed",
        params={"stage_id": stage_id},
    )


def approval_other_target(stage_id: str, message: str) -> Denied:
    return Denied(
        "approval_invalid", message, reason="approval_other_target", params={"stage_id": stage_id}
    )


def capabilities_changed(stage_id: str, message: str) -> Denied:
    return Denied(
        "approval_invalid",
        message,
        reason="capabilities_changed",
        params={"stage_id": stage_id, "detail": message},
    )


def approval_recovery_changed(stage_id: str, message: str) -> Denied:
    return Denied(
        "approval_invalid",
        message,
        reason="approval_recovery_changed",
        params={"stage_id": stage_id},
    )


# --- stage control -------------------------------------------------------------------------------


def stage_not_startable(stage: StageRow) -> Denied:
    return Denied(
        "state",
        f"stage {stage.stage_id} is {stage.state.value}; it cannot start",
        reason="stage_not_startable",
        params=_stage(stage),
    )


def safety_conflict(stage_id: str, conflicts: Sequence[str]) -> Denied:
    return Denied(
        "safety_conflict",
        "; ".join(conflicts),
        reason="safety_conflict",
        params={"stage_id": stage_id},
    )


def pump_unconfirmed(device_id: str) -> Denied:
    return Denied(
        "interlock",
        "the pump interlock is on; check the device on site",
        reason="pump_unconfirmed",
        params={"device_id": device_id},
    )


def device_busy(stage: StageRow, other_stage_id: str) -> Denied:
    return Denied(
        "state",
        "another stage on this device is still live or being checked",
        reason="device_busy",
        params={
            "stage_id": stage.stage_id,
            "device_id": stage.device_id,
            "other_stage_id": other_stage_id,
        },
    )


def stage_not_pausable(stage: StageRow) -> Denied:
    return Denied(
        "state",
        f"stage {stage.stage_id} is {stage.state.value}; it cannot pause",
        reason="stage_not_pausable",
        params=_stage(stage),
    )


def stage_not_resumable(stage: StageRow) -> Denied:
    return Denied(
        "state",
        f"stage {stage.stage_id} is {stage.state.value}; it cannot resume",
        reason="stage_not_resumable",
        params=_stage(stage),
    )


def unsettled_actions(stage_id: str, count: int) -> Denied:
    return Denied(
        "state",
        "actions with unknown results must be settled first",
        reason="unsettled_actions",
        params={"stage_id": stage_id, "count": count},
    )


def device_differs_from_run_sheet(stage_id: str, diffs: Sequence[Difference]) -> Denied:
    return Denied(
        "state",
        f"device differs from the run sheet: {describe(diffs)}",
        reason="device_differs_from_run_sheet",
        params={
            "stage_id": stage_id,
            "channels": [diff.channel.value for diff in diffs],
            "diffs": [diff.model_dump(mode="json") for diff in diffs],
        },
    )


def stage_already_ended(stage: StageRow) -> Denied:
    return Denied(
        "state",
        f"stage {stage.stage_id} is already {stage.state.value}",
        reason="stage_already_ended",
        params=_stage(stage),
    )


def stage_not_takeoverable(stage: StageRow) -> Denied:
    return Denied(
        "state",
        f"stage {stage.stage_id} is {stage.state.value}; cannot take over",
        reason="stage_not_takeoverable",
        params=_stage(stage),
    )


def stage_not_in_manual(stage: StageRow) -> Denied:
    return Denied(
        "state",
        f"stage {stage.stage_id} is {stage.state.value}; nothing to hand back",
        reason="stage_not_in_manual",
        params=_stage(stage),
    )


def stage_not_switchable(stage: StageRow) -> Denied:
    return Denied(
        "state",
        f"stage {stage.stage_id} is {stage.state.value}; cannot switch",
        reason="stage_not_switchable",
        params=_stage(stage),
    )


def stage_changed_concurrently(stage_id: str) -> Denied:
    return Denied(
        "state",
        f"stage {stage_id} changed while the request was running",
        reason="stage_changed_concurrently",
        params={"stage_id": stage_id},
    )


# --- rounds --------------------------------------------------------------------------------------


def no_choice_pending(round_id: str) -> Denied:
    return Denied(
        "state",
        "no stopped stage is waiting for a choice",
        reason="no_choice_pending",
        params={"round_id": round_id},
    )


def no_next_stage(round_id: str) -> Denied:
    return Denied(
        "state",
        "no stage is left to move on to; verify the data instead",
        reason="no_next_stage",
        params={"round_id": round_id},
    )


def unknown_choice(choice: str) -> Denied:
    return Denied(
        "state", f"unknown choice {choice!r}", reason="unknown_choice", params={"choice": choice}
    )


def round_already_ended(round_id: str, state: str) -> Denied:
    return Denied(
        "state",
        f"round is already {state}",
        reason="round_already_ended",
        params={"round_id": round_id, "state": state},
    )
