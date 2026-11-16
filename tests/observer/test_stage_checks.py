import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import DAY_START

from growbridge.archive.models import ManualMeasurement, ManualTask, TaskRecord
from growbridge.archive.store import Archive
from growbridge.observer.alerts import AlertBook
from growbridge.observer.stage_checks import (
    AUDIT_FINDING,
    CHECK_SECONDS,
    MEASUREMENT_GRACE_SECONDS,
    StageChecks,
)
from growbridge.planning.manual_tasks import EARLY_SECONDS, ON_TIME_SECONDS
from growbridge.planning.window import MEASUREMENT_GRACE_SECONDS as WINDOW_GRACE_SECONDS
from growbridge.planning.window import data_window
from growbridge.ports import StageRuntime
from growbridge.sim.fixtures import make_run_sheet
from growbridge.workflow.states import StageState

STAGE = "st1"
HOUR = 3600.0
WATER_DUE = DAY_START + 9 * HOUR
MEASURE_DUE = DAY_START + 10 * HOUR


class FakeStages:
    def __init__(
        self, started_at: float | None = DAY_START, state=StageState.RUNNING, stage_id=STAGE
    ):
        self.started_at = started_at
        self.state = state
        self.stage_id = stage_id
        self.ended_at: float | None = None
        self.active = True

    def active_stage(self):
        if not self.active:
            return None
        sheet = make_run_sheet(
            duration_seconds=3 * 86400,
            manual_tasks=(
                ManualTask(id="measure", kind="measurement", at="10:00"),
                ManualTask(id="water", kind="irrigation", at="09:00"),
            ),
        )
        return StageRuntime(
            stage_id=self.stage_id,
            experiment_id="e1",
            project_id="p1",
            state=self.state,
            run_sheet=sheet,
            started_at=self.started_at,
            ended_at=self.ended_at,
        )


class Rig:
    def __init__(self, db, clock, tmp_path, stages=None):
        self.archive = Archive(db, tmp_path / "archive", clock)
        self.book = AlertBook(db, clock)
        self.stages = stages or FakeStages()
        self.clock = clock
        self.checks = StageChecks(self.archive, self.book, self.stages, clock)
        clock.wall = DAY_START

    def at(self, wall: float) -> None:
        self.clock.wall = wall
        self.clock.mono += CHECK_SECONDS

    def record(self, task_id, kind, due, recorded_at, outcome="done"):
        self.archive.add_task_record(
            TaskRecord(
                id=f"r-{task_id}-{int(recorded_at)}",
                experiment_id="e1",
                stage_id=STAGE,
                task_id=task_id,
                kind=kind,
                due_at=due,
                outcome=outcome,
                done_at=recorded_at if outcome == "done" else None,
                operator="op",
                recorded_at=recorded_at,
            )
        )

    def measure(self, mid, measured_at, corrects=None):
        self.archive.add_measurement(
            ManualMeasurement(
                id=mid,
                experiment_id="e1",
                batch="b1",
                plant_id="p1",
                layout_version="L1",
                measured_at=measured_at,
                position="top",
                method="ruler",
                metric="height",
                value=3.0,
                unit="cm",
                operator="op",
                corrects=corrects,
            )
        )

    def open_alerts(self):
        return {(a.kind, a.key): a for a in self.book.open()}


@pytest.fixture
def rig(db, clock, tmp_path):
    return Rig(db, clock, tmp_path)


async def test_a_task_past_its_deadline_without_a_record_alerts(rig):
    rig.at(WATER_DUE + ON_TIME_SECONDS + 1)
    assert await rig.checks.tick() is True
    assert set(rig.open_alerts()) == {("task_missed", f"{STAGE}:water:{int(WATER_DUE)}")}
    assert rig.open_alerts()[("task_missed", f"{STAGE}:water:{int(WATER_DUE)}")].severity == (
        "warning"
    )


async def test_the_missed_alert_resolves_when_a_record_arrives(rig):
    rig.at(WATER_DUE + ON_TIME_SECONDS + 1)
    await rig.checks.tick()
    rig.record("water", "irrigation", WATER_DUE, rig.clock.now())
    rig.at(rig.clock.now() + 1)
    await rig.checks.tick()
    assert not [k for k in rig.open_alerts() if k[0] == "task_missed"]


async def test_a_done_measurement_task_without_a_measurement_alerts_after_the_grace(rig):
    recorded = MEASURE_DUE + 300
    rig.record("measure", "measurement", MEASURE_DUE, recorded)
    rig.record("water", "irrigation", WATER_DUE, WATER_DUE + 60)
    rig.at(recorded + MEASUREMENT_GRACE_SECONDS - 1)
    await rig.checks.tick()
    assert not [k for k in rig.open_alerts() if k[0] == "measurement_missing"]
    rig.at(recorded + MEASUREMENT_GRACE_SECONDS)
    await rig.checks.tick()
    key = ("measurement_missing", f"{STAGE}:measure:{int(MEASURE_DUE)}")
    assert key in rig.open_alerts()
    assert rig.open_alerts()[key].severity == "warning"


async def test_a_measurement_stored_before_the_task_record_counts(rig):
    recorded = MEASURE_DUE + 300
    rig.measure("m1", MEASURE_DUE + 60)
    rig.record("measure", "measurement", MEASURE_DUE, recorded)
    rig.record("water", "irrigation", WATER_DUE, WATER_DUE + 60)
    rig.at(recorded + MEASUREMENT_GRACE_SECONDS + 1)
    await rig.checks.tick()
    assert not [k for k in rig.open_alerts() if k[0] == "measurement_missing"]


async def test_a_measurement_outside_the_window_alerts(rig):
    _, end = data_window(rig.stages.active_stage())
    late = end + WINDOW_GRACE_SECONDS + 128
    rig.measure("m9", late)
    rig.at(DAY_START + 60)
    await rig.checks.tick()
    assert ("measurement_outside_window", f"{STAGE}:m9") in rig.open_alerts()


async def test_a_corrected_measurement_resolves_its_outside_window_alert(rig):
    _, end = data_window(rig.stages.active_stage())
    rig.measure("m9", end + WINDOW_GRACE_SECONDS + 128)
    rig.at(DAY_START + 60)
    await rig.checks.tick()
    rig.measure("m9b", DAY_START + 2 * HOUR, corrects="m9")
    rig.at(DAY_START + 120)
    await rig.checks.tick()
    assert not [k for k in rig.open_alerts() if k[0] == "measurement_outside_window"]


async def test_a_stage_not_started_is_not_checked(db, clock, tmp_path):
    stages = FakeStages(started_at=None, state=StageState.PENDING_REVIEW)
    rig = Rig(db, clock, tmp_path, stages)
    rig.at(WATER_DUE + 10 * HOUR)
    await rig.checks.tick()
    assert rig.open_alerts() == {}


async def test_checks_run_at_most_every_check_seconds(rig):
    rig.at(DAY_START + 60)
    assert await rig.checks.tick() is True
    rig.clock.mono += CHECK_SECONDS - 1
    assert await rig.checks.tick() is False
    rig.clock.mono += 1
    assert await rig.checks.tick() is True


async def test_a_measurement_dated_before_the_stage_start_is_not_judged(rig):
    # every stage of a round shares one experiment: an earlier stage's measurement is not this
    # stage's to judge
    rig.measure("m-earlier", DAY_START - 5 * HOUR)
    rig.at(DAY_START + 60)
    await rig.checks.tick()
    assert not [k for k in rig.open_alerts() if k[0] == "measurement_outside_window"]


def test_the_observer_does_not_import_the_agents_package():
    code = (
        "import sys, growbridge.observer.service\n"
        "found = sorted(m for m in sys.modules if m.startswith('growbridge.agents'))\n"
        "assert not found, found"
    )
    src = Path(__file__).resolve().parents[2] / "src"
    result = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "PYTHONPATH": str(src)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


STAGE_KINDS = ("task_missed", "measurement_missing", "measurement_outside_window", AUDIT_FINDING)


def _raise_for(rig, stage_id: str) -> None:
    for kind in STAGE_KINDS:
        rig.book.raise_alert(kind, f"{stage_id}:x", "warning", "left over")


async def test_alerts_of_a_stage_that_is_no_longer_active_are_resolved(rig):
    _raise_for(rig, "st0")
    _raise_for(rig, "st10")  # shares the active stage's prefix, is another stage
    rig.book.raise_alert(AUDIT_FINDING, f"{STAGE}:abc", "warning", "this stage's finding")
    rig.book.raise_alert("stage_gap", "st0:x", "warning", "another kind is left alone")
    rig.at(DAY_START + 60)

    await rig.checks.tick()

    assert set(rig.open_alerts()) == {(AUDIT_FINDING, f"{STAGE}:abc"), ("stage_gap", "st0:x")}


async def test_with_no_active_stage_every_stage_alert_is_resolved(rig):
    _raise_for(rig, STAGE)
    rig.book.raise_alert("stage_gap", f"{STAGE}:x", "warning", "another kind is left alone")
    rig.stages.active = False
    rig.at(DAY_START + 60)

    await rig.checks.tick()

    assert set(rig.open_alerts()) == {("stage_gap", f"{STAGE}:x")}


async def test_a_stage_not_yet_started_keeps_its_own_alerts_and_closes_older_ones(
    db, clock, tmp_path
):
    rig = Rig(db, clock, tmp_path, FakeStages(started_at=None, state=StageState.PENDING_REVIEW))
    _raise_for(rig, "st0")
    rig.book.raise_alert(AUDIT_FINDING, f"{STAGE}:abc", "info", "this stage's finding")
    rig.at(DAY_START + 60)

    await rig.checks.tick()

    assert set(rig.open_alerts()) == {(AUDIT_FINDING, f"{STAGE}:abc")}


async def test_a_stage_id_with_a_colon_keeps_its_own_alerts(db, clock, tmp_path):
    # not started, so only the sweep runs and no check re-evaluates the stage's own alerts
    stages = FakeStages(started_at=None, state=StageState.PENDING_REVIEW, stage_id="round:1")
    rig = Rig(db, clock, tmp_path, stages)
    _raise_for(rig, "round:1")
    _raise_for(rig, "round")  # the part before the colon is another stage
    rig.at(DAY_START + 60)

    await rig.checks.tick()

    assert set(rig.open_alerts()) == {(kind, "round:1:x") for kind in STAGE_KINDS}


async def test_a_failed_audit_warning_closes_once_its_stage_is_no_longer_active(rig):
    # raised by the runtime when an auditor run fails, keyed "audit:<stage id>"
    rig.book.raise_alert("audit_task", "audit:st0", "warning", "an older stage's audit failed")
    rig.book.raise_alert("audit_task", "audit:st10", "warning", "shares the prefix, other stage")
    rig.book.raise_alert("audit_task", f"audit:{STAGE}", "warning", "this stage's audit failed")
    rig.at(DAY_START + 60)

    await rig.checks.tick()

    assert set(rig.open_alerts()) == {("audit_task", f"audit:{STAGE}")}


async def test_with_no_active_stage_a_failed_audit_warning_is_resolved(rig):
    rig.book.raise_alert("audit_task", f"audit:{STAGE}", "warning", "this stage's audit failed")
    rig.stages.active = False
    rig.at(DAY_START + 60)

    await rig.checks.tick()

    assert rig.open_alerts() == {}


def _missing(rig):
    return [a for k, a in rig.open_alerts().items() if k[0] == "measurement_missing"]


async def test_a_task_done_and_measured_late_is_not_missing_its_measurement(rig):
    late = MEASURE_DUE + 3 * HOUR  # past the on-time deadline of due + 2 h
    rig.record("measure", "measurement", MEASURE_DUE, late)
    rig.measure("m-late", late)
    rig.at(late + MEASUREMENT_GRACE_SECONDS + 1)
    await rig.checks.tick()
    assert _missing(rig) == []


async def test_a_measurement_timed_after_a_late_task_was_done_does_not_count(rig):
    late = MEASURE_DUE + 3 * HOUR
    rig.record("measure", "measurement", MEASURE_DUE, late)
    rig.measure("m-later", late + 1)
    rig.at(late + MEASUREMENT_GRACE_SECONDS + 1)
    await rig.checks.tick()
    (alert,) = _missing(rig)
    assert "no measurement is timed within the task's window (from " in alert.message
    assert "(from 2026-11-10 09:00 to 2026-11-10 13:00)" in alert.message  # sheet time


async def test_a_measurement_outside_an_on_time_tasks_window_does_not_count(rig):
    recorded = MEASURE_DUE + 300
    rig.record("measure", "measurement", MEASURE_DUE, recorded)
    rig.measure("m-early", MEASURE_DUE - EARLY_SECONDS - 1)
    rig.measure("m-after", MEASURE_DUE + ON_TIME_SECONDS + 1)
    rig.at(recorded + MEASUREMENT_GRACE_SECONDS + 1)
    await rig.checks.tick()
    (alert,) = _missing(rig)
    assert alert.key == f"{STAGE}:measure:{int(MEASURE_DUE)}"
