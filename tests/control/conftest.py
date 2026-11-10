"""Shared rig for the control service tests: simulated AC5, fake clock, temporary database."""

import asyncio
from dataclasses import dataclass, field

import pytest
import pytest_asyncio

from growbridge.archive.db import Database
from growbridge.archive.models import ActionRecord, Channel, RightKind, SampleRecord
from growbridge.control.service import ControlService
from growbridge.ports import ActionRequest, RightScope
from growbridge.service import Bridge
from growbridge.sim.clock import FakeClock
from growbridge.sim.device import SimulatedTransport

DEVICE = "SIMULATED"
HOST = "host-a"
ALL_CHANNELS = (Channel.LIGHT, Channel.EXHAUST, Channel.FAN)


class ListSink:
    def __init__(self):
        self.actions: list[ActionRecord] = []
        self.samples: list[SampleRecord] = []

    def append_action(self, record):
        self.actions.append(record)

    def append_sample(self, record):
        self.samples.append(record)


@dataclass
class Rig:
    service: ControlService
    bridge: Bridge
    sim: SimulatedTransport
    clock: FakeClock
    db: Database
    sink: ListSink
    counter: int = field(default=0)

    def stage_right(self, channels=ALL_CHANNELS, stage_id="stage-1"):
        scope = RightScope(
            device_id=DEVICE,
            experiment_id="experiment-1",
            stage_id=stage_id,
            run_sheet_digest="digest-1",
            channels=tuple(channels),
        )
        return self.service.grant(RightKind.STAGE, scope)

    def manual_right(self, channels=(Channel.PUMP,), operator="alice"):
        scope = RightScope(device_id=DEVICE, channels=tuple(channels))
        return self.service.grant(RightKind.MANUAL, scope, operator=operator)

    def request(self, right, channel, level, request_id=None, **extra):
        self.counter += 1
        return ActionRequest(
            request_id=request_id or f"req-{self.counter}",
            right_number=right,
            channel=channel,
            level=level,
            trigger="test",
            **extra,
        )

    def writes(self):
        return [c for c in self.sim.commands if c["method"] == "setConfigField"]

    async def refresh(self):
        await self.bridge.request("getDevSta")


@pytest_asyncio.fixture
async def build(settings, tmp_path):
    made = []

    async def factory(register=True, start=True):
        clock = FakeClock()
        sim = SimulatedTransport()
        bridge = Bridge(settings, lambda _: sim, clock=clock)
        bridge.request_timeout = 0.2
        bridge.readback_interval = 0.01
        await bridge.start()
        for _ in range(100):
            if bridge.identity:
                break
            await asyncio.sleep(0.01)
        db = Database(tmp_path / "control.sqlite3")
        sink = ListSink()
        service = ControlService(bridge, db, clock, HOST, sink)
        if register:
            service.register_host()
        if start:
            await service.startup()
        rig = Rig(service, bridge, sim, clock, db, sink)
        made.append(rig)
        return rig

    yield factory
    for rig in made:
        await rig.bridge.stop()
        rig.db.close()


@pytest_asyncio.fixture
async def rig(build):
    return await build()


@pytest.fixture
def restart(rig):
    """A second control service on the same database, bridge and device: a new process."""

    def make(host_id=HOST):
        return ControlService(rig.bridge, rig.db, rig.clock, host_id, rig.sink)

    return make
