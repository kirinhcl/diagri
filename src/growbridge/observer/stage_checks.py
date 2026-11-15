"""Alerts on process errors in a started stage: a manual task past its deadline with no record,
a measurement task recorded done with no measurement behind it, a measurement outside the data
window. Reads stored records only; never reports a stage event or pauses anything."""

from growbridge.agents import handlers_researcher
from growbridge.archive.clock import Clock
from growbridge.archive.snapshot import outside_window
from growbridge.archive.store import Archive
from growbridge.observer.alerts import AlertBook
from growbridge.planning import manual_tasks
from growbridge.planning.window import data_window
from growbridge.ports import StagePort, StageRuntime

CHECK_SECONDS = 300.0
MEASUREMENT_GRACE_SECONDS = 2 * 3600.0  # after a measurement task is recorded done
TASK_MISSED = "task_missed"
MEASUREMENT_MISSING = "measurement_missing"
OUTSIDE_WINDOW = "measurement_outside_window"
SEVERITY = "warning"


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
        if stage is None or stage.started_at is None:
            return True
        start, end = data_window(stage)
        self._check_tasks(stage, start, end)
        self._check_window(stage, start, end)
        return True

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
            self._set(
                self._lacks_measurement(item, record, current, now, end),
                MEASUREMENT_MISSING,
                slot,
                self._lacks_text(item),
            )

    def _lacks_measurement(self, item, record, current, now: float, end: float) -> bool:
        if item.kind != "measurement" or record is None or record.outcome != "done":
            return False
        if now < record.recorded_at + MEASUREMENT_GRACE_SECONDS:
            return False
        first = item.due_at - manual_tasks.EARLY_SECONDS
        last = manual_tasks.deadline(item, end)
        return not any(first <= m.measured_at <= last for m in current)

    def _check_window(self, stage: StageRuntime, start: float, end: float) -> None:
        experiment = stage.experiment_id
        grace = handlers_researcher.MEASUREMENT_GRACE_SECONDS
        current = {m.id for m in self.archive.measurements(experiment)}
        outside = {
            row["id"]: row
            for row in outside_window(self.archive, experiment, start, end, grace)
            if row["id"] in current
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
    def _lacks_text(item) -> str:
        return (
            f"Task {item.task_id} was recorded done but no measurement was entered for it. "
            "Enter the measurement with the time it was taken."
        )
