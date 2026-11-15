import pytest
from conftest import DAY_START

from growbridge.agents import handlers_researcher
from growbridge.archive.models import ManualMeasurement, ManualTask, TaskRecord
from growbridge.archive.store import Archive
from growbridge.observer.alerts import AlertBook
from growbridge.observer.stage_checks import (
    CHECK_SECONDS,
    MEASUREMENT_GRACE_SECONDS,
    StageChecks,
)
from growbridge.planning.manual_tasks import ON_TIME_SECONDS
from growbridge.planning.window import data_window
from growbridge.ports import StageRuntime
from growbridge.sim.fixtures import make_run_sheet
from growbridge.workflow.states import StageState

STAGE = "st1"
HOUR = 3600.0
WATER_DUE = DAY_START + 9 * HOUR
MEASURE_DUE = DAY_START + 10 * HOUR


class FakeStages:
    def __init__(self, started_at: float | None = DAY_START, state=StageState.RUNNING):
        self.started_at = started_at
        self.state = state
        self.ended_at: float | None = None

    def active_stage(self):
        sheet = make_run_sheet(
            duration_seconds=3 * 86400,
            manual_tasks=(
                ManualTask(id="measure", kind="measurement", at="10:00"),
                ManualTask(id="water", kind="irrigation", at="09:00"),
            ),
        )
        return StageRuntime(
            stage_id=STAGE,
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
    late = end + handlers_researcher.MEASUREMENT_GRACE_SECONDS + 128
    rig.measure("m9", late)
    rig.at(DAY_START + 60)
    await rig.checks.tick()
    assert ("measurement_outside_window", f"{STAGE}:m9") in rig.open_alerts()


async def test_a_corrected_measurement_resolves_its_outside_window_alert(rig):
    _, end = data_window(rig.stages.active_stage())
    rig.measure("m9", end + handlers_researcher.MEASUREMENT_GRACE_SECONDS + 128)
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
