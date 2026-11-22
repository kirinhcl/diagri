"""How a model run ended, decided from its outcome alone (no database, no clock).

``Dispatcher.run_task`` ends a claimed task with the result; a replay of a recorded run reads the
same result without ending anything, so the decision lives here as pure functions.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from growbridge.agents.loop import AgentRun
from growbridge.archive.models import Model
from growbridge.ports import Denied
from growbridge.workflow.states import TaskState

REPORT_TOOL = "publish_research_report"
# What a run of the role must have done to count as finished: one of these tools without error
# and, where a field is named, with that result field true. (A frozen dataset or a compute job is
# real progress for the researcher: the next step comes in a later task.)
DELIVERABLES: dict[str, dict[str, str | None]] = {
    "planner": {"save_plan_draft": "saved"},
    "researcher": {
        "freeze_dataset": None,
        "submit_compute_job": None,
        "fetch_compute_artifacts": None,
        REPORT_TOOL: None,
    },
}
UNDELIVERED = {
    "planner": "ended without saving a run sheet draft",
    "researcher": "ended without freezing data, computing or publishing a report",
}
REASON_CHARS = 1500


class RunInterrupted(Exception):
    """Raised by a replay to stop a run; ``Dispatcher.replay_run`` lets it through."""


class RunEnd(Model):
    state: TaskState
    reason: str
    said: str = ""
    code: str
    params: dict[str, Any] = {}
    denied: dict[str, Any] | None = None


def end_of_run(
    run: AgentRun, owner_role: str, reviews: Sequence[bool], deliveries: Sequence[str]
) -> RunEnd:
    """The end of a run that came back from the model loop."""
    said = run.text.strip()
    if run.stop_reason != "end_turn":
        return RunEnd(
            state=TaskState.NEEDS_ATTENTION,
            reason=f"model stopped without finishing: {run.stop_reason}",
            code="model_stopped",
            params={"stop_reason": run.stop_reason},
        )
    if owner_role in DELIVERABLES and not deliveries:
        reason = f"{UNDELIVERED[owner_role]}: {said or '(no text)'}"
        return RunEnd(
            state=TaskState.NEEDS_ATTENTION,
            reason=reason[:REASON_CHARS],
            code="undelivered",
            params={"role": owner_role},
        )
    state = TaskState.NEEDS_REVIEW if reviews else TaskState.DONE
    return RunEnd(state=state, reason="run finished", said=said, code="run_finished")


def end_of_denied(exc: Denied) -> RunEnd:
    """The end of a run that a permission or budget check refused."""
    return RunEnd(
        state=TaskState.NEEDS_ATTENTION,
        reason=f"{exc.code}: {exc}",
        code="denied",
        params={"denied_code": exc.code},
        denied={
            "code": exc.code,
            "message": str(exc),
            "reason": exc.reason,
            "params": exc.params,
        },
    )


def end_of_error(exc: Exception) -> RunEnd:
    """The end of a run whose model or client failed."""
    return RunEnd(
        state=TaskState.NEEDS_ATTENTION,
        reason=f"model unavailable: {type(exc).__name__}: {exc}",
        code="model_unavailable",
    )
