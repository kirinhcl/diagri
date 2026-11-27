"""A device-test rig over the workflow world: locks, access, idle care, a recording sleep."""

import asyncio
from types import SimpleNamespace

from access_support import People

from growbridge.archive.models import Channel, RuleAction
from growbridge.sim.fixtures import DEVICE
from growbridge.workflow.device_test import DeviceTests
from growbridge.workflow.idle import IdleCare

IDLE = (RuleAction(channel=Channel.LIGHT, level=0), RuleAction(channel=Channel.EXHAUST, level=10))


class Sleeper:
    """Records each wait; when ``gate`` is set, a wait blocks until the gate opens."""

    def __init__(self):
        self.calls: list[float] = []
        self.gate: asyncio.Event | None = None
        self.during = None  # called inside the wait

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        if self.during is not None:
            self.during()
        if self.gate is not None:
            await self.gate.wait()


def build(world, people, idle, sleeper, **extra):
    tests = DeviceTests(
        world.db,
        world.clock,
        world.control,
        people.locks,
        people.access,
        world.svc.store,
        idle,
        sleep=sleeper,
        **extra,
    )
    return tests


def make_rig(world):
    people = People(world)
    people.locks.lock("alice", ["gh-01", "gh-02"])
    idle = IdleCare(world.svc.store, world.control, DEVICE, IDLE)
    world.svc.idle_care = idle
    sleeper = Sleeper()
    tests = build(world, people, idle, sleeper)
    world.svc.device_tests = tests
    people.locks.tests = tests
    alerts, resolved = [], []
    tests.alert = lambda *args, **kwargs: alerts.append((args, kwargs))
    tests.resolve = lambda *args: resolved.append(args)
    world.control.levels[Channel.LIGHT] = 0
    return SimpleNamespace(
        world=world,
        people=people,
        idle=idle,
        sleeper=sleeper,
        tests=tests,
        alerts=alerts,
        resolved=resolved,
        control=world.control,
    )


def calls(rig, name):
    return [entry for entry in rig.control.log if entry[0] == name]
