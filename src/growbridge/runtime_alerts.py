"""Alerts the runtime raises about stages and research tasks, each with the scope it belongs to.

Moved out of ``runtime.py`` (which stays within 800 lines). A stage that stopped by itself has one
open ``stage_waiting`` alert for as long as it waits; a research task past its deadline raises
``task_deadline``. Both carry their owner (the stage, the task's project) so the workbench shows
them only to whoever may see that stage or project.
"""

from typing import Any

from growbridge.runtime_waiting import waiting_message, waiting_params
from growbridge.workflow.states import StageState

STAGE_ALERT = "stage_waiting"
OPERATOR_PAUSE = "pause"  # the history event of a pause that an operator asked for


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
            message, params = waiting_message(item), waiting_params(item)
            runtime.alert(
                STAGE_ALERT, key, message, severity, scope, code="stage_waiting", params=params
            )


def expire_tasks(runtime: Any) -> None:
    for task in runtime.tasks.expire(runtime.clock.now()):
        message = f"Research task {task.id} is past its deadline and needs attention"
        params = {"task_id": task.id, "project_id": task.project_id, "role": task.owner_role}
        scope = ("project", task.project_id)
        runtime.alert(
            "task_deadline", task.id, message, "warning", scope, code="task_deadline", params=params
        )
