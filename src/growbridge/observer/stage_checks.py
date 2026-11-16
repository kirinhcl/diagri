"""Alerts on process errors in a started stage: a manual task past its deadline with no record,
a measurement task recorded done with no measurement behind it, a measurement outside the data
window. Closes those alerts, the auditor's findings and the warning of its failed runs once
their stage is no longer the active one. Reads stored records only; never reports a stage event
or pauses anything."""

from datetime import datetime
from zoneinfo import ZoneInfo

from growbridge.archive.clock import Clock
from growbridge.archive.snapshot import outside_window
from growbridge.archive.store import Archive
from growbridge.observer.alerts import AlertBook
from growbridge.planning import manual_tasks
from growbridge.planning.window import MEASUREMENT_GRACE_SECONDS as WINDOW_GRACE_SECONDS
from growbridge.planning.window import data_window
from growbridge.ports import StagePort, StageRuntime

CHECK_SECONDS = 300.0
MEASUREMENT_GRACE_SECONDS = 2 * 3600.0  # after a measurement task is recorded done
TASK_MISSED = "task_missed"
MEASUREMENT_MISSING = "measurement_missing"
OUTSIDE_WINDOW = "measurement_outside_window"
AUDIT_FINDING = "audit_finding"  # raised by the auditor role; kept here so this module closes it
# alerts keyed "<stage id>:..." that only mean something while that stage is the active one
STAGE_KINDS = frozenset({TASK_MISSED, MEASUREMENT_MISSING, OUTSIDE_WINDOW, AUDIT_FINDING})
AUDIT_TASK = "audit_task"  # the runtime's warning that an auditor run failed, one per stage
SEVERITY = "warning"
TIME_FORMAT = "%Y-%m-%d %H:%M"  # in the run sheet's time zone


class StageChecks:
    def __init__(self, archive: Archive, book: AlertBook, stages: StagePort, clock: Clock):
        self.archive = archive
        self.book = book
        self.stages = stages
        self.clock = clock
        self._checked_at: float | None = None

    async def tick(self) -> bool:
        """True when a check ran; False when skipped because one ran recently."""
        mono = self.clock.monotonic()
        if self._checked_at is not None and mono - self._checked_at < CHECK_SECONDS:
            return False
        self._checked_at = mono
        stage = self.stages.active_stage()
        self._close_other_stages(None if stage is None else stage.stage_id)
        if stage is None or stage.started_at is None:
            return True
        start, end = data_window(stage)
        self._check_tasks(stage, start, end)
        self._check_window(stage, start, end)
        return True

    def _close_other_stages(self, active_id: str | None) -> None:
        """Resolve the stage alerts of every stage but the active one: nothing re-evaluates them
        once their stage is no longer active, so they would stay open for ever."""
        own_audit = None if active_id is None else audit_task_key(active_id)
        for alert in self.book.open():
            if alert.kind in STAGE_KINDS:
                stale = not _of_stage(alert.key, active_id)
            else:
                stale = alert.kind == AUDIT_TASK and alert.key != own_audit
            if stale:
                self.book.resolve(alert.kind, alert.key)

    def _check_tasks(self, stage: StageRuntime, start: float, end: float) -> None:
        now = self.clock.now()
        experiment = stage.experiment_id
        items = manual_tasks.occurrences(stage.run_sheet, start, min(end, now + 1))
        records = self.archive.task_records(experiment, start, end)
        current = self.archive.measurements(experiment)
        for item, record, state in manual_tasks.statuses(items, records, now, end):
            if item.due_at > now:
                continue
            slot = f"{stage.stage_id}:{item.task_id}:{int(item.due_at)}"
            self._set(state == "missed", TASK_MISSED, slot, self._missed_text(item))
            gap = self._unmeasured(item, record, current, now, end)
            text = "" if gap is None else self._lacks_text(item, gap, stage.run_sheet.timezone)
            self._set(gap is not None, MEASUREMENT_MISSING, slot, text)

    @staticmethod
    def _unmeasured(item, record, current, now: float, end: float) -> tuple[float, float] | None:
        """The window ``(first, last)`` of a measurement task recorded done in which no
        measurement is timed, or None when nothing is wrong (yet). The window runs from an hour
        before the task was due to its on-time deadline, or to when it was done if that is later:
        a task done late and measured then has its measurement."""
        if item.kind != "measurement" or record is None or record.outcome != "done":
            return None
        if now < record.recorded_at + MEASUREMENT_GRACE_SECONDS:
            return None
        first = item.due_at - manual_tasks.EARLY_SECONDS
        done = record.recorded_at if record.done_at is None else record.done_at
        last = max(manual_tasks.deadline(item, end), done)
        if any(first <= m.measured_at <= last for m in current):
            return None
        return first, last

    def _check_window(self, stage: StageRuntime, start: float, end: float) -> None:
        experiment = stage.experiment_id
        grace = WINDOW_GRACE_SECONDS
        current = {m.id for m in self.archive.measurements(experiment)}
        outside = {
            row["id"]: row
            for row in outside_window(self.archive, experiment, start, end, grace)
            # an earlier stage of the round shares the experiment; its measurements are not
            # this stage's to judge
            if row["id"] in current and row["measured_at"] >= start
        }
        for mid, row in outside.items():
            text = (
                f"Measurement {mid} ({row['metric']}) is dated outside the stage's data window "
                "and will not be in its snapshot. Enter it again with the time it was taken, "
                "or record a correction."
            )
            self.book.raise_alert(OUTSIDE_WINDOW, f"{stage.stage_id}:{mid}", SEVERITY, text)
        prefix = f"{stage.stage_id}:"
        for alert in self.book.open():
            if alert.kind == OUTSIDE_WINDOW and alert.key.startswith(prefix):
                if alert.key[len(prefix) :] not in outside:
                    self.book.resolve(OUTSIDE_WINDOW, alert.key)

    def _set(self, active: bool, kind: str, key: str, message: str) -> None:
        if active:
            self.book.raise_alert(kind, key, SEVERITY, message)
        else:
            self.book.resolve(kind, key)

    @staticmethod
    def _missed_text(item) -> str:
        return (
            f"Task {item.task_id} ({item.kind}) was due and its time has passed with no record. "
            "Record it as done or skipped."
        )

    @staticmethod
    def _lacks_text(item, window: tuple[float, float], timezone: str) -> str:
        zone = ZoneInfo(timezone)
        first, last = (datetime.fromtimestamp(t, zone).strftime(TIME_FORMAT) for t in window)
        return (
            f"Task {item.task_id} was recorded done but no measurement is timed within the "
            f"task's window (from {first} to {last}). Enter the measurement with the time it "
            "was taken."
        )


def audit_task_key(stage_id: str) -> str:
    """The key of a stage's failed-audit warning; one per stage, however many runs failed."""
    return f"audit:{stage_id}"


def _of_stage(key: str, stage_id: str | None) -> bool:
    """Whether a stage alert's key names this stage. Matches the whole id, not the part before
    the first colon: a stage id may itself contain one."""
    return stage_id is not None and (key == stage_id or key.startswith(f"{stage_id}:"))
