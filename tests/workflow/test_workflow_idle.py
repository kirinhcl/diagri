"""The idle write right: held while a greenhouse has no current stage (design 2026-11-24, 5.3)."""

from growbridge.archive.models import Channel, RightKind, RuleAction
from growbridge.config import Greenhouse
from growbridge.ports import IdleRuntime
from growbridge.sim.fixtures import DEVICE
from growbridge.workflow.idle import IdleCare
from growbridge.workflow.locks import GreenhouseLocks

IDLE = (
    RuleAction(channel=Channel.LIGHT, level=0),
    RuleAction(channel=Channel.EXHAUST, level=10),
)


def attach(world, levels=IDLE) -> IdleCare:
    idle = IdleCare(world.svc.store, world.control, DEVICE, levels)
    world.svc.idle_care = idle
    return idle


def test_restore_grants_a_care_right_for_the_idle_levels(world):
    idle = attach(world)

    idle.restore()

    right = world.control.right(idle.right)
    assert right.kind is RightKind.CARE
    assert right.levels == IDLE and right.stage_id is None and right.device_id == DEVICE
    assert world.svc.idle_runtime() == IdleRuntime(right=idle.right, levels=IDLE)


def test_restore_keeps_a_valid_right(world):
    idle = attach(world)
    idle.restore()
    first = idle.right

    idle.restore()

    assert idle.right == first
    assert world.control.granted(RightKind.CARE) == [first]


def test_no_right_without_idle_levels(world):
    idle = attach(world, levels=())

    idle.restore()

    assert idle.right is None and world.svc.idle_runtime() is None


def test_no_idle_without_an_idle_care(world):
    assert world.svc.idle_runtime() is None


async def test_no_right_while_a_stage_is_current(world):
    await world.running("stage-1")
    idle = attach(world)

    idle.restore()

    assert idle.right is None and world.svc.idle_runtime() is None


def test_restore_waits_for_the_old_write_path(world):
    idle = attach(world)
    world.control.stopped = False

    idle.restore()

    assert idle.right is None


def test_restore_waits_for_the_pump_interlock(world):
    idle = attach(world)
    world.control.interlock = True

    idle.restore()

    assert idle.right is None


def test_restore_after_restart_grants_a_new_right(world):
    idle = attach(world)
    idle.restore()
    old = idle.right
    world.control.revoked.add(old)  # a restart revokes every right

    assert world.svc.idle_runtime() is None
    idle.restore()

    assert idle.right != old and world.svc.idle_runtime().right == idle.right


def test_a_right_from_an_earlier_recovery_is_replaced(world):
    idle = attach(world)
    idle.restore()
    old = idle.right
    world.control.recovery += 1

    assert world.svc.idle_runtime() is None
    idle.restore()

    assert idle.right != old


async def test_a_revoked_right_is_replaced(world):
    idle = attach(world)
    idle.restore()
    old = idle.right
    await world.control.handover(old, "a start that was then refused")

    idle.restore()

    assert idle.right != old


async def test_start_hands_the_idle_right_back(world):
    idle = attach(world)
    idle.restore()
    number = idle.right

    await world.running("stage-1")

    assert number in [handed for handed, _reason in world.control.handovers]
    assert world.svc.idle_runtime() is None


async def test_restore_care_also_restores_idle(world):
    idle = attach(world)

    await world.svc.restore_care()

    assert idle.right is not None


async def test_after_a_release_the_right_comes_back(world):
    idle = attach(world)
    stage = await world.running("stage-1")
    await world.svc.stop_stage(stage, world.op)
    houses = (Greenhouse(id="gh-01", name="One", device_id=DEVICE),)
    locks = GreenhouseLocks(world.db, world.clock, houses, world.svc.store, world.control)
    locks.lock("alice", ["gh-01"])
    await world.svc.restore_care()
    assert world.svc.idle_runtime() is None  # the ended stage is still current: care, not idle

    await locks.release("gh-01", "alice", plants_removed=True)
    await world.svc.restore_care()

    assert world.svc.idle_runtime() == IdleRuntime(right=idle.right, levels=IDLE)


async def test_no_idle_right_survives_a_start_that_a_tick_interleaves(world, monkeypatch):
    idle = attach(world)
    idle.restore()
    hand_over = world.control.handover

    async def tick_meanwhile(number, reason):
        await hand_over(number, reason)
        await world.svc.restore_care()  # the runtime ticks while the start awaits

    monkeypatch.setattr(world.control, "handover", tick_meanwhile)

    await world.running("stage-1")

    idle_rights = [n for n, r in world.control.rights.items() if r.levels == IDLE]
    assert idle_rights and all(n in world.control.revoked for n in idle_rights)


async def test_an_aborted_round_without_a_release_does_not_go_idle(world):
    idle = attach(world)
    await world.running("stage-1")

    await world.svc.abort_round(world.round_id, world.op)
    await world.svc.restore_care()

    assert idle.right is None and world.svc.idle_runtime() is None  # plants may still be inside


async def test_an_aborted_round_goes_idle_once_released(world):
    idle = attach(world)
    await world.running("stage-1")
    await world.svc.abort_round(world.round_id, world.op)
    houses = (Greenhouse(id="gh-01", name="One", device_id=DEVICE),)
    locks = GreenhouseLocks(world.db, world.clock, houses, world.svc.store, world.control)
    locks.lock("alice", ["gh-01"])

    await locks.release("gh-01", "alice", plants_removed=True)
    await world.svc.restore_care()

    assert world.svc.idle_runtime() == IdleRuntime(right=idle.right, levels=IDLE)
