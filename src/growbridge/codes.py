"""The registry of message codes the server sends to the console.

The server sends a stable ``code`` plus structured ``params``; the console builds the text from its
catalog. Each family below maps a code to the params it carries and whether it asks the operator to
act. ``checked`` is called where a message is emitted: it logs a code or params that differ from
the registry, and never raises, so the registry cannot stop an alert or message from being sent.
The console's tests read the export (tests/web/fixtures/message-codes.json), written by
``PYTHONPATH=src python scripts/export_message_codes.py``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Code:
    params: tuple[str, ...] = ()
    action: bool = True
    of: str | None = None  # a denial reason names the coarse ``Denied`` code it refines


# denial_codes needs Code and codes needs DENIAL_CODES: whichever loads first still finds both,
# because denial_codes binds the dict before it imports Code.
from growbridge.denial_codes import DENIAL_CODES  # noqa: E402

CODES: dict[str, dict[str, Code]] = {
    "alert": {
        "data_gap": Code(("sensor",)),
        "threshold": Code(("sensor", "op", "value", "duration_seconds", "rule")),
        "frozen_watch": Code(),
        "stage_checks": Code(),
        "frozen_reading": Code(("sensor", "value")),
        "task_missed": Code(("stage_id", "task_id", "task_kind", "due_at")),
        "measurement_missing": Code(
            ("stage_id", "task_id", "window_start", "window_end", "timezone")
        ),
        "measurement_outside_window": Code(("stage_id", "measurement_id", "metric", "measured_at")),
        "pump_unexpected_off": Code(),
        "pump_unexpected_interlocked": Code(),
        "pump_unexpected_failed": Code(),
        "pump_unreadable": Code(),
        "pump_watchdog_step": Code(),
        "pump_watchdog_record": Code(),
        "backup_unconfigured": Code(),
        "notify_unconfigured": Code(),
        "monitor_unconfigured": Code(),
        "not_write_host": Code(),
        "tick_step": Code(("step",)),
        "source_rewound": Code(("top_rowid", "cursor")),
        # intervention_kind is a name for the technical details, not a placeholder
        "intervention_mirror": Code(("intervention_kind",)),
        "stage_waiting": Code(("stage_id", "entry_id", "state", "event", "detail")),
        "task_deadline": Code(("task_id", "project_id", "role")),
        "run_health": Code(("failures",)),
        "external_monitor": Code(("signal",)),
        "backup": Code(),
        "agent_task_failed": Code(("task_id", "project_id", "role")),
        "agent_task_attention": Code(("task_id", "project_id", "role")),
        "audit_task_failed": Code(("stage_id", "task_id")),
        "audit_task_attention": Code(("stage_id", "task_id")),
        "audit_schedule": Code(),
        "model_client": Code(),
        "audit_finding": Code(("stage_id", "summary", "evidence")),
    },
    "finding": {
        "device_owned_write": Code(("source_kind", "source", "channel")),
        "pump_action": Code(("source_kind", "source")),
        "level_range": Code(("source_kind", "source", "channel", "level", "min", "max")),
        "pump_device_owned": Code(),
        "unknown_sensor": Code(("rule", "sensor")),
        "unit_mismatch": Code(("rule", "sensor", "device_unit", "rule_unit")),
        "humidity_exhaust_only": Code(("rule",)),
        "rule_conflict": Code(("rule_a", "rule_b", "channel", "priority")),
        "safety_conflict": Code(("rule", "protection", "channel", "level", "protection_level")),
        "sampling.validity": Code(("rule", "validity_seconds", "interval_seconds")),
        "sampling.interval": Code(("interval_seconds",)),
        "sampling.max_gap": Code(("max_gap_seconds",)),
        "duration.rule": Code(("rule", "duration_seconds", "min_switch_seconds")),
        "duration.protection": Code(("protection", "duration_seconds")),
        "duration.run": Code(("duration_seconds",)),
        "wait": Code(("max_wait_seconds",)),
        "missing_tolerance": Code(("channel",)),
        "manual_task": Code(("task_kind", "task_id", "at_local")),
        "manual_task.irrigation": Code(("task_id", "at_local", "seconds")),
        "no_evidence": Code(("source_kind", "source")),
        "unverified_source": Code(("source_kind", "source", "card_id")),
        "uncalibrated": Code(("source_kind", "source", "card_id")),
        # an undefined treatment has no name: these two carry the ids where the others name it
        "unknown_treatment": Code(("treatments",)),
        "missing_control.undefined": Code(("control",)),
        "missing_control.unallocated": Code(("control", "control_id")),
        "no_replication": Code(("treatments", "treatment_ids")),
        "unbalanced_block": Code(("block",)),
        "confounded_with_time": Code(),
        "seed_mismatch.unreproducible": Code(),
        "seed_mismatch.differs": Code(),
        "treatment_not_applied": Code(("round", "treatment", "treatment_id", "problems")),
        "treatment_not_applied.none": Code(("round", "treatments", "treatment_ids")),
    },
    "receipt": {
        "not_sent": Code(),
        "device_rejected": Code(),
        "no_receipt": Code(),
        "link_broke": Code(),
        "readback_level": Code(("channel", "expected")),
        "readback_unavailable": Code(),
        "readback_mode": Code(("mode",)),
        "void_recovery_changed": Code(),
        "void_handover": Code(),
        "void_restart": Code(),
        "void_superseded": Code(("channel",)),
        # denied_code is a name for the technical details, not a placeholder
        "void_denied": Code(("denied_code",)),
        "internal_error": Code(),
        "lost_receipt": Code(),
        "pump_off_unconfirmed": Code(),
        "settled_applied": Code(("channel", "level"), action=False),
        "settled_not_applied": Code(("channel", "level", "mode")),
    },
    "task_end": {
        "handover": Code(action=False),
        "protection_write": Code(("channel",)),
        "pump_off_interlock": Code(),
        "pump_off_watchdog": Code(),
        "pump_off_unconfirmed": Code(),  # the pump may still be on; the interlock holds it
        "not_confirmed": Code(("action_state",)),
        "other": Code(),
    },
    "compute_error": {
        "submit_rejected": Code(),
        "submit_failed": Code(),
        "orphan_not_cancelled": Code(),
        "late_cancelled": Code(action=False),
        "backend_error": Code(),
        "cancelled_no_job": Code(action=False),
        "cancel_unknown": Code(),
        "outcome_unknown": Code(),
        "cancel_failed": Code(),
        "cleanup_failed": Code(),
        "settled_by_operator": Code(action=False),
        "output_limit": Code(("limit_kind", "bytes", "limit")),
        "too_many_files": Code(("file_count", "limit_count")),
        "artifact_missing": Code(("name",)),
        "artifact_mismatch": Code(("name",)),
        "no_artifacts": Code(),
    },
    "compute_stuck": {
        "reconcile_wait": Code(("age_seconds",)),
        "not_refreshed": Code(("age_seconds",)),
        "error": Code(action=False),
    },
    "chat_end": {
        "denied": Code(("denied_code",)),
        "model_unavailable": Code(),
        "model_stopped": Code(("stop_reason",)),
        "undelivered": Code(("role",)),
        "run_finished": Code(action=False),
    },
    "estimate": {
        "too_few_blocks": Code(("blocks", "min_blocks")),
        "sampled_p": Code(("flips", "blocks"), action=False),
    },
    "denial": DENIAL_CODES,
}


def checked(family: str, code: str, params: Mapping[str, object]) -> dict[str, object]:
    """The params as a dict, after logging any difference from the registry. Never raises."""
    declared = CODES.get(family, {}).get(code)
    if declared is None:
        logger.warning("unregistered message code %s.%s", family, code)
    elif set(params) != set(declared.params):
        logger.warning(
            "message %s.%s params %s differ from %s",
            family,
            code,
            sorted(params),
            list(declared.params),
        )
    return dict(params)


def checked_denial(code: str, reason: str, params: Mapping[str, object]) -> dict[str, object]:
    """Like ``checked("denial", reason, params)``, and logs a reason registered under another
    coarse code. Never raises."""
    declared = DENIAL_CODES.get(reason)
    if declared is not None and declared.of != code:
        logger.warning("denial reason %s is registered under %s, not %s", reason, declared.of, code)
    return checked("denial", reason, params)


def export() -> dict[str, dict[str, dict[str, object]]]:
    """The registry as plain data for the console: {family: {code: {params, action}}}; a
    denial reason also carries ``of``, its coarse code."""
    out: dict[str, dict[str, dict[str, object]]] = {}
    for family, entries in CODES.items():
        out[family] = {}
        for code, spec in entries.items():
            item: dict[str, object] = {"params": list(spec.params), "action": spec.action}
            if family == "denial":
                item["of"] = spec.of
            out[family][code] = item
    return out
