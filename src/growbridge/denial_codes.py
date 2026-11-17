"""The registry of denial reasons: ``DENIAL_CODES[reason]`` is a ``Code`` whose ``of`` is the
coarse ``Denied`` code it refines and whose ``params`` are the values a refusal carries.

A refusal is ``Denied(code, message, reason=..., params=...)``. The console builds its two
sentences from the reason and params; the English message stays for logs and the model. The
registry is merged into ``growbridge.codes.CODES`` as the ``denial`` family.
"""

from __future__ import annotations

# Bound before the import below: growbridge.codes imports this module while it loads.
DENIAL_CODES: dict[str, Code] = {}

from growbridge.codes import Code  # noqa: E402


def _register(coarse: str, *reasons: tuple[str, tuple[str, ...]], action: bool = True) -> None:
    for reason, params in reasons:
        DENIAL_CODES[reason] = Code(params, action=action, of=coarse)


_STAGE = ("stage_id", "state")

# --- workflow service (workflow/service.py, via workflow/denials.py) ---------------------------
_register(
    "state",
    ("project_name_required", ()),
    ("record_not_found", ("record_kind", "record_id")),
    ("protocol_not_found", ("protocol_id", "project_id")),
    ("protocol_version_exists", ("protocol_id", "version")),
    ("round_not_accepting_run_sheets", ("round_id", "state")),
    ("run_sheet_mismatch", ("run_sheet_id", "record_kind")),
    ("run_sheet_needs_switch", _STAGE),
    ("run_sheet_version_conflict", ("run_sheet_id", "version")),
    ("run_sheet_too_old", ("run_sheet_id", "version", "current_version")),
    ("run_sheet_version_in_use", ("run_sheet_id", "version")),
    ("run_sheet_changed_since_review", ("stage_id", "expected_digest", "current_digest")),
    ("stage_not_awaiting_approval", _STAGE),
    ("stage_not_startable", _STAGE),
    ("stage_not_pausable", _STAGE),
    ("stage_not_resumable", _STAGE),
    ("stage_already_ended", _STAGE),
    ("stage_not_takeoverable", _STAGE),
    ("stage_not_in_manual", _STAGE),
    ("stage_not_switchable", _STAGE),
    ("device_busy", ("stage_id", "device_id", "other_stage_id")),
    ("unsettled_actions", ("stage_id", "count")),
    ("device_differs_from_run_sheet", ("stage_id", "channels", "diffs")),
    ("stage_changed_concurrently", ("stage_id",)),
    ("no_choice_pending", ("round_id",)),
    ("no_next_stage", ("round_id",)),
    ("round_already_ended", ("round_id", "state")),
)
_register("state", ("unknown_choice", ("choice",)), action=False)

_register(
    "approval_invalid",
    ("approval_blocking_findings", ("stage_id", "count")),
    ("approval_none_valid", ("stage_id",)),
    ("approval_run_sheet_changed", ("stage_id",)),
    ("approval_other_target", ("stage_id",)),
    ("capabilities_changed", ("stage_id", "detail")),
    ("approval_recovery_changed", ("stage_id",)),
)
_register("safety_conflict", ("safety_conflict", ("stage_id",)))
_register("interlock", ("pump_unconfirmed", ("device_id",)))
_register("model_role", ("drafter_only", ("role",)), action=False)
_register("scope", ("not_this_project", ("project_id",)))

# --- task board, store, recovery, permissions, workbench reads and rounds, alerts --------------
_register(
    "state",
    ("task_transition_not_allowed", ("task_id", "from_status", "to_status")),
    ("task_end_needs_reason", ("task_id",)),
    ("task_board_conflict", ("task_id", "parent_task_id")),
    ("request_id_reused_for_other_goal", ("task_id", "request_id")),
    ("report_not_published", ("round_id",)),
    ("report_file_missing", ("round_id",)),
    ("artifact_digest_mismatch", ("round_id", "artifact_id")),
    ("round_not_in_project", ("round_id", "project_id")),
    ("onsite_check_not_open", _STAGE),
    ("archive_not_mounted", ()),
)
_register(
    "budget",
    ("budget_calls_exhausted", ("project_id",)),
    ("budget_cost_exhausted", ("project_id",)),
    ("budget_revision_limit", ("task_id", "max_revisions")),
    ("budget_depth_limit", ("depth", "max_depth")),
)
_register("model_role", ("model_no_controls", ("role",)), action=False)
_register("not_operator", ("not_operator", ()))
_register("reauth_required", ("reauth_required", ()))
_register("scope", ("compute_task_unknown", ("task_id",)))
_register(
    "param",
    ("id_length", ("max_length",)),
    ("protocol_version_range", ("max_version",)),
    ("numbers_not_finite", ("paths",)),
)
