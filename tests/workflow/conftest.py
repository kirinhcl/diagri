import pytest

from growbridge.archive.db import Database
from growbridge.archive.models import (
    CareRule,
    Channel,
    RuleAction,
    RunSheet,
    TimedAction,
)
from growbridge.ports import Actor, StageEvent, StageEventKind
from growbridge.sim.clock import FakeClock
from growbridge.sim.control import FakeControl
from growbridge.sim.fixtures import make_protocol, make_run_sheet
from growbridge.workflow.service import WorkflowService


def care_rules() -> tuple[CareRule, ...]:
    """Keep the light on a 06:00-22:00 schedule while the stage is paused or waiting."""
    steps = (
        TimedAction(id="care-on", channel=Channel.LIGHT, at="06:00", level=60),
        TimedAction(id="care-off", channel=Channel.LIGHT, at="22:00", level=0),
    )
    return (CareRule(id="care-light", channel=Channel.LIGHT, schedule=steps),)


class World:
    """One database, one fake clock, one fake control and a workflow service over them."""

    def __init__(self, db: Database, clock: FakeClock, control: FakeControl):
        self.db = db
        self.clock = clock
        self.control = control
        # fixture sheets run light 60, not the fixture protocol's 40/70 treatments
        self.svc = WorkflowService(db, clock, control, check_treatments=False)
        self.project_id = ""
        self.round_id = ""
        self.events = 0

    # --- actors --------------------------------------------------------------------------------

    @property
    def op(self) -> Actor:
        return Actor(kind="operator", id="op-1", reauth_at=self.clock.now())

    @staticmethod
    def actor(kind: str) -> Actor:
        return Actor(kind=kind, id=f"{kind}-1")

    # --- building ------------------------------------------------------------------------------

    def sheet(self, stage_id: str = "stage-1", version: int = 1, **fields) -> RunSheet:
        defaults = {
            "id": f"sheet-{stage_id}",
            "project_id": self.project_id,
            "experiment_id": f"experiment-{stage_id}",
            "stage_id": stage_id,
            "version": version,
            "care_rules": care_rules(),
            "end_actions": (RuleAction(channel=Channel.LIGHT, level=0),),
        }
        return make_run_sheet(**{**defaults, **fields})

    async def design(self, stages: tuple[str, ...] = ("vegetative",)) -> str:
        self.project_id = self.svc.create_project("lettuce light series", self.op)
        protocol = make_protocol(project_id=self.project_id, stages=stages)
        self.svc.save_protocol(protocol, self.op)
        self.round_id = self.svc.create_round(self.project_id, protocol.id, self.op)
        return self.round_id

    async def pending(self, stage_id: str = "stage-1", **fields) -> str:
        """Submit a run sheet; the stage waits for review. Designs the round on first use."""
        if not self.round_id:
            await self.design()
        findings = self.svc.submit_run_sheet(self.round_id, self.sheet(stage_id, **fields), self.op)
        assert not any(finding.blocking for finding in findings)
        return stage_id

    async def approved(self, stage_id: str = "stage-1", **fields) -> str:
        await self.pending(stage_id, **fields)
        self.svc.approve(stage_id, self.op)
        return stage_id

    async def running(self, stage_id: str = "stage-1", **fields) -> str:
        await self.approved(stage_id, **fields)
        await self.svc.start_stage(stage_id, self.op)
        return stage_id

    # --- events --------------------------------------------------------------------------------

    def event(self, kind: StageEventKind, stage_id: str = "stage-1", **fields) -> StageEvent:
        self.events += 1
        detail = fields.pop("detail", {})
        values = {"event_id": f"ev-{self.events}", "at": self.clock.now(), **fields}
        return StageEvent(kind=kind, stage_id=stage_id, detail=detail, **values)

    async def report(self, kind: StageEventKind, stage_id: str = "stage-1", **fields) -> None:
        await self.svc.report(self.event(kind, stage_id, **fields))

    # --- reading -------------------------------------------------------------------------------

    def state(self, stage_id: str = "stage-1") -> str:
        return self.svc.stage(stage_id).state.value

    def round_state(self) -> str:
        return self.svc.round_state(self.round_id).value


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def control(clock) -> FakeControl:
    return FakeControl(clock)


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "workflow.db")
    yield database
    database.close()


@pytest.fixture
def world(db, clock, control) -> World:
    return World(db, clock, control)
