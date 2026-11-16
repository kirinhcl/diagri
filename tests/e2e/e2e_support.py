"""Shared pieces of the end-to-end tests: one simulated device, one fake clock, real services."""

from datetime import datetime
from zoneinfo import ZoneInfo

from growbridge.archive.models import Channel, RuleAction, RunSheet, SamplingPlan, TimedAction
from growbridge.ports import Actor
from growbridge.runtime import Runtime, build_runtime
from growbridge.sim.clock import FakeClock
from growbridge.sim.device import SimulatedTransport
from growbridge.sim.fixtures import TIMEZONE, make_protocol, make_run_sheet, make_safety

DAY = "2027-01-15"
STAGE = "stage-e2e"


def light_schedule(level: int) -> tuple[TimedAction, ...]:
    """Light at ``level`` from 06:00 to 22:00, exhaust 30 % all day."""
    return (
        TimedAction(id="light-on", channel=Channel.LIGHT, at="06:00", level=level),
        TimedAction(id="light-off", channel=Channel.LIGHT, at="22:00", level=0),
        TimedAction(id="exhaust-base", channel=Channel.EXHAUST, at="00:00", level=30),
    )


# make_protocol's rounds 1-4: high, control, control, high
ROUND_LIGHT = {1: 70, 2: 40, 3: 40, 4: 70}
HIGH_LIGHT = light_schedule(ROUND_LIGHT[1])
STAGE_SECONDS = 600
OPERATOR = "op-1"


def local(hhmm: str, day: str = DAY) -> float:
    """UTC epoch seconds of a project-local wall time."""
    hours, minutes = hhmm.split(":")
    year, month, date = (int(part) for part in day.split("-"))
    moment = datetime(year, month, date, int(hours), int(minutes), tzinfo=ZoneInfo(TIMEZONE))
    return moment.timestamp()


class RecordingChannel:
    """A notification channel that accepts everything and keeps the texts it was given."""

    def __init__(self):
        self.sent: list[str] = []

    async def send(self, text: str) -> str:
        self.sent.append(text)
        return "accepted"


class World:
    """A device, a clock and the runtimes built on them; ``boot`` may be called again to restart."""

    def __init__(self, settings, clock: FakeClock):
        self.settings = settings
        self.clock = clock
        self.sim = SimulatedTransport()
        self.runtimes: list[Runtime] = []

    @property
    def operator(self) -> Actor:
        return Actor(kind="operator", id=OPERATOR, reauth_at=self.clock.now())

    async def boot(self, register: bool = True, **options) -> Runtime:
        runtime = build_runtime(self.settings, lambda _: self.sim, self.clock, **options)
        runtime.bridge.request_timeout = 0.2
        runtime.bridge.readback_interval = 0.01
        if register:
            runtime.control.register_host()
        self.runtimes.append(runtime)
        await runtime.start()
        return runtime

    async def beat(self, runtime: Runtime, seconds: float = 1.0) -> None:
        """Time passes, fresh telemetry arrives, the runtime ticks once."""
        self.clock.advance(seconds)
        await runtime.bridge.request("getDevSta")
        await runtime.tick()

    async def shutdown(self) -> None:
        for runtime in reversed(self.runtimes):
            await runtime.stop()

    def sheet(self, project_id: str, **fields) -> RunSheet:
        """A short stage: light at round 1's 70 % from 06:00 (the workflow checks the round's
        treatment), the light off when the stage ends."""
        defaults = {
            "timed_actions": HIGH_LIGHT,
            "id": f"sheet-{STAGE}",
            "project_id": project_id,
            "experiment_id": f"experiment-{STAGE}",
            "stage_id": STAGE,
            "duration_seconds": STAGE_SECONDS,
            "sampling": SamplingPlan(interval_seconds=60, max_gap_seconds=120),
            "end_actions": (RuleAction(channel=Channel.LIGHT, level=0),),
        }
        return make_run_sheet(**{**defaults, **fields})

    def model_sheet(self, project_id: str, protocol, **fields) -> RunSheet:
        """The sheet a model files for protocol round 1: it applies the round's treatment
        ("high", light 70 %), which the agent checks require."""
        owner = {"protocol_id": protocol.id, "protocol_version": protocol.version}
        return self.sheet(project_id, **{"timed_actions": HIGH_LIGHT, **owner, **fields})

    def designed_stage(self, runtime: Runtime) -> tuple[str, str]:
        """Design the stage and leave it waiting for review; returns (project_id, round_id)."""
        flow, operator = runtime.workflow, self.operator
        runtime.control.approve_safety(make_safety(), OPERATOR)
        project = flow.create_project("lettuce light series", operator)
        protocol = make_protocol(project_id=project)
        flow.save_protocol(protocol, operator)
        round_id = flow.create_round(project, protocol.id, operator)
        sheet = self.sheet(project, protocol_id=protocol.id, protocol_version=protocol.version)
        findings = flow.submit_run_sheet(round_id, sheet, Actor(kind="model", id="planner"))
        assert not [f for f in findings if f.blocking], findings
        return project, round_id

    async def approved_stage(self, runtime: Runtime) -> tuple[str, str]:
        """Design, approve and start the stage; returns (project_id, round_id)."""
        project, round_id = self.designed_stage(runtime)
        runtime.workflow.approve(STAGE, self.operator)
        await runtime.workflow.start_stage(STAGE, self.operator)
        return project, round_id

    async def run_until_ended(self, runtime: Runtime, step: float = 60.0, limit: int = 40) -> int:
        for beats in range(1, limit + 1):
            await self.beat(runtime, step)
            if runtime.workflow.stage(STAGE).state.value == "ended":
                return beats
        raise AssertionError("the stage did not end")
