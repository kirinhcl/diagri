"""The phases of a compute attempt and the intervals the service works to."""

from typing import Literal

from growbridge.workflow.states import TaskState

Phase = Literal[
    "prepared", "queued", "running", "reconcile", "fetching", "needs_review", "failed",
    "done", "cancelled",
]  # fmt: skip
PHASE_STATE: dict[str, TaskState] = {
    "prepared": TaskState.IN_PROGRESS,
    "queued": TaskState.REMOTE_QUEUED,
    "running": TaskState.COMPUTING,
    "reconcile": TaskState.RECONCILE,
    "fetching": TaskState.FETCHING,
    "needs_review": TaskState.NEEDS_REVIEW,
    "failed": TaskState.NEEDS_ATTENTION,
    "done": TaskState.DONE,
    "cancelled": TaskState.ENDED,
}
POLLED = ("queued", "running")
LIVE = ("prepared", "reconcile", "queued", "running")  # not yet settled
FETCHABLE = ("fetching", "needs_review", "failed")

POLL_AFTER_SECONDS = 60  # the tick looks at a live job again after this long
RECONCILE_AFTER_SECONDS = 300  # an unanswered submit is old enough to reconcile after this long
STUCK_AFTER_SECONDS = 3600  # a live job nobody has refreshed for this long is shown as stuck
TICK_EVERY_SECONDS = 60  # the tick does its work at most this often
TICK_BATCH = 10  # attempts looked at per tick
