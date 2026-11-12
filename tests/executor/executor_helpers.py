"""Rig for the executor tests: real control service, bridge, simulated AC5 and workflow service."""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from growbridge.archive.db import Database
from growbridge.archive.models import (
    ActionRecord,
    CareRule,
    Channel,
    RightKind,
    RuleAction,
    RunSheet,
    SampleRecord,
    TimedAction,
)
from growbridge.control.service import ControlService
from growbridge.executor.engine import ExecutorEngine
from growbridge.ports import ActionRequest, Actor, RightScope
from growbridge.service import Bridge
from growbridge.sim.clock import FakeClock
from growbridge.sim.device import SimulatedTransport
from growbridge.sim.fixtures import TIMEZONE, make_protocol, make_run_sheet, make_safety
from growbridge.workflow.service import WorkflowService

HOST = "host-a"
STAGE = "stage-1"
DAY = "2027-01-15"


def local(hhmm: str, day: str = DAY) -> float:
    """UTC epoch seconds of a project-local wall time."""
    hours, minutes = hhmm.split(":")
    year, month, date = (int(part) for part in day.split("-"))
    moment = datetime(year, month, date, int(hours), int(minutes), tzinfo=ZoneInfo(TIMEZONE))
    return moment.timestamp()


def care_rules() -> tuple[CareRule, ...]:
    """Light 60 % from 06:00 to 22:00 while the stage is paused or has ended."""
    steps = (
        TimedAction(id="care-on", channel=Channel.LIGHT, at="06:00", level=60),
        TimedAction(id="care-off", channel=Channel.LIGHT, at="22:00", level=0),
    )
    return (CareRule(id="care-light", channel=Channel.LIGHT, schedule=steps),)


class ListSink:
    def __init__(self):
        self.actions: list[ActionRecord] = []
        self.samples: list[SampleRecord] = []

    def append_action(self, record):
        self.actions.append(record)

    def append_sample(self, record):
        self.samples.append(record)


class Rig:
    def __init__(self, clock, sim, bridge, control, workflow, dbs, allow=None):
        self.clock = clock
        self.sim = sim
        self.bridge = bridge
        self.control = control
        self.svc = workflow
        self.dbs = dbs
        self.engine = ExecutorEngine(control, workflow, clock, allow)
        self.round_id = ""
        self.project_id = ""

    # --- time ----------------------------------------------------------------------------------

    async def at(self, hhmm: str, day: str = DAY) -> None:
        """Move the wall clock to a project-local time; forward moves are real elapsed time."""
        delta = local(hhmm, day) - self.clock.now()
        if delta >= 0:
            self.clock.advance(delta)
        else:
            self.clock.wall += delta  # before anything has ticked: just set the date
        await self.refresh()

    async def refresh(self) -> None:
        await self.bridge.request("getDevSta")

    async def pass_time(self, seconds: float) -> None:
        """Time passes and fresh telemetry arrives."""
        self.clock.advance(seconds)
        await self.refresh()

    # --- stage ---------------------------------------------------------------------------------

    @property
    def op(self) -> Actor:
        return Actor(kind="operator", id="op-1", reauth_at=self.clock.now())

    def sheet(self, **fields) -> RunSheet:
        defaults = {
            "id": f"sheet-{STAGE}",
            "project_id": self.project_id,
            "experiment_id": f"experiment-{STAGE}",
            "stage_id": STAGE,
            "care_rules": care_rules(),
            "end_actions": (RuleAction(channel=Channel.LIGHT, level=0),),
        }
        return make_run_sheet(**{**defaults, **fields})

    async def start(self, safety=None, stages=None, **fields) -> str:
        """Design, approve and start the stage; the safety config is approved first."""
        self.control.approve_safety(safety or make_safety(), "op-1")
        self.project_id = self.svc.create_project("lettuce light series", self.op)
        extra = {} if stages is None else {"stages": stages}
        protocol = make_protocol(project_id=self.project_id, **extra)
        self.svc.save_protocol(protocol, self.op)
        self.round_id = self.svc.create_round(self.project_id, protocol.id, self.op)
        self.svc.submit_run_sheet(self.round_id, self.sheet(**fields), self.op)
        self.svc.approve(STAGE, self.op)
        await self.svc.start_stage(STAGE, self.op)
        return STAGE

    async def interlock(self) -> None:
        """Pause the stage (a manual right cannot coexist with a stage right), then leave the
        pump-off unconfirmed the way a failed irrigation does."""
        await self.svc.pause_stage(STAGE, self.op, "test")
        self.sim.fail_off = True
        scope = RightScope(device_id="SIMULATED", channels=(Channel.PUMP,))
        number = self.control.grant(RightKind.MANUAL, scope, operator="alice")
        request = ActionRequest(
            request_id="irrigation-1",
            right_number=number,
            channel=Channel.PUMP,
            level=1,
            trigger="test",
            operator="alice",
        )
        await self.control.irrigate(request, 0.02)
        assert self.control.interlocked()

    async def manual_write(self, channel, level) -> None:
        """An operator write under the stage's manual right (after a takeover)."""
        request = ActionRequest(
            request_id=f"manual-{channel.value}-{level}",
            right_number=self.svc.stage(STAGE).manual_right,
            channel=channel,
            level=level,
            trigger="operator",
            operator="op-1",
        )
        await self.control.submit(request)

    def state(self, stage_id: str = STAGE) -> str:
        return self.svc.stage(stage_id).state.value

    async def start_next_stage(self, stage_id: str = "stage-2", **fields) -> str:
        """Stop the current stage, move the round on and start another stage."""
        await self.svc.stop_stage(STAGE, self.op)
        await self.svc.choose_after_stop(self.round_id, "next", self.op)
        sheet = self.sheet(id=f"sheet-{stage_id}", stage_id=stage_id, **fields)
        self.svc.submit_run_sheet(self.round_id, sheet, self.op)
        self.svc.approve(stage_id, self.op)
        await self.svc.start_stage(stage_id, self.op)
        return stage_id

    # --- observing the device ------------------------------------------------------------------

    def writes(self) -> list[dict]:
        return [c for c in self.sim.commands if c["method"] == "setConfigField"]

    def written(self) -> list[tuple[str, int]]:
        """(key, level or on/off) of every write sent so far, in order."""
        found = []
        for command in self.writes():
            key = command["params"]["keyPath"][1]
            block = command["params"][key]
            found.append((key, block.get("mLevel", block["mOnOff"]) if block["mOnOff"] else 0))
        return found

    async def levels(self) -> dict[Channel, int]:
        return (await self.control.read_state()).levels

    async def tick(self):
        return await self.engine.tick()


async def build_rig(settings, tmp_path, allow=None, register=True) -> Rig:
    clock = FakeClock(now=local("10:00"))
    sim = SimulatedTransport()
    bridge = Bridge(settings, lambda _: sim, clock=clock)
    bridge.request_timeout = 0.2
    bridge.readback_interval = 0.01
    await bridge.start()
    for _ in range(100):
        if bridge.identity:
            break
        await asyncio.sleep(0.01)
    control_db = Database(tmp_path / "control.sqlite3")
    workflow_db = Database(tmp_path / "workflow.sqlite3")
    control = ControlService(bridge, control_db, clock, HOST, ListSink())
    if register:
        control.register_host()
    await control.startup()
    workflow = WorkflowService(workflow_db, clock, control)
    return Rig(clock, sim, bridge, control, workflow, (control_db, workflow_db), allow)
