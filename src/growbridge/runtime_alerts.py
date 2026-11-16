"""Alerts the runtime raises about stages and research tasks, each with the scope it belongs to.

Moved out of ``runtime.py`` (which stays within 800 lines). A stage that stopped by itself has one
open ``stage_waiting`` alert for as long as it waits; a research task past its deadline raises
``task_deadline``. Both carry their owner (the stage, the task's project) so the workbench shows
them only to whoever may see that stage or project.
"""

import json
from collections.abc import Mapping
from typing import Any

from growbridge.workflow.states import StageState

STAGE_ALERT = "stage_waiting"
OPERATOR_PAUSE = "pause"  # the history event of a pause that an operator asked for


def waiting_message(item: Mapping[str, Any]) -> str:
    """Why a stage waits: its state, the event that put it there and what the event carried."""
    detail = {
        name: value
        for name, value in item["detail"].items()
        if name != "right_number" and value != item["event"]
    }
    text = f"Stage {item['stage_id']} is {item['state']} after {item['event']}"
    return f"{text}: {json.dumps(detail, sort_keys=True)}" if detail else text


def stage_alerts(runtime: Any) -> None:
    """One open alert per stage that stopped by itself, for as long as it waits.

    The key names the history entry, so a new cause is a new alert and a new notification.
    A pause that an operator asked for raises none.
    """
    waiting = {
        f"{item['stage_id']}:{item['entry']}": item
        for item in runtime.workflow.waiting_stages()
        if item["event"] != OPERATOR_PAUSE
    }
    known = {alert.key: alert for alert in runtime.book.open() if alert.kind == STAGE_ALERT}
    for key in set(known) - set(waiting):
        runtime.book.resolve(STAGE_ALERT, key, known[key].scope)
    for key, item in waiting.items():
        if key not in known:
            checking = item["state"] == StageState.RECOVERY_CHECK.value
            severity = "critical" if checking else "warning"
            scope = ("stage", item["stage_id"])
            runtime.alert(STAGE_ALERT, key, waiting_message(item), severity, scope)


def expire_tasks(runtime: Any) -> None:
    for task in runtime.tasks.expire(runtime.clock.now()):
        message = f"Research task {task.id} is past its deadline and needs attention"
        runtime.alert("task_deadline", task.id, message, "warning", ("project", task.project_id))
