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
    "finding": {},
    "receipt": {},
    "task_end": {},
    "compute_error": {},
    "compute_stuck": {},
    "chat_end": {},
    "estimate": {},
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


def export() -> dict[str, dict[str, dict[str, object]]]:
    """The registry as plain data for the console: {family: {code: {params, action}}}."""
    return {
        family: {
            code: {"params": list(spec.params), "action": spec.action}
            for code, spec in entries.items()
        }
        for family, entries in CODES.items()
    }
