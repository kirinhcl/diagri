"""Greenhouse locks: all-or-nothing locking, and a release that hands over care first."""

import threading

import pytest

from growbridge.archive.db import Database
from growbridge.archive.models import RightKind
from growbridge.config import Greenhouse
from growbridge.ports import Denied
from growbridge.sim.control import FakeControl
from growbridge.sim.fixtures import DEVICE, make_protocol
from growbridge.workflow.locks import GreenhouseLocks
from growbridge.workflow.service import WorkflowService

REGISTRY = (
    Greenhouse(id="gh-01", name="One", device_id=DEVICE),
    Greenhouse(id="gh-02", name="Two", device_id="AC5-2"),
    Greenhouse(id="gh-03", name="Three", device_id="AC5-3"),
)


@pytest.fixture
def locks(world) -> GreenhouseLocks:
    return GreenhouseLocks(world.db, world.clock, REGISTRY, world.svc.store, world.control)


def test_lock_is_all_or_nothing(locks):
    locks.lock("bob", ["gh-02"])

    with pytest.raises(Denied) as denied:
        locks.lock("alice", ["gh-01", "gh-02"])

    assert denied.value.code == "lock_taken"
    assert "gh-02" in str(denied.value)
    assert locks.holder_of_device(DEVICE) is None
    assert locks.held_by("alice") == ()


@pytest.mark.parametrize("ids", [["gh-01", "gh-01"], ["gh-99"], []])
def test_lock_rejects_duplicates_and_unknown(locks, ids):
    with pytest.raises(Denied) as denied:
        locks.lock("alice", ids)

    assert denied.value.code == "state"
    assert locks.overview()[0]["holder"] is None


def test_lock_returns_ids_and_records_events(locks, world):
    assert locks.lock("alice", ["gh-02", "gh-01"]) == ("gh-02", "gh-01")

    assert locks.holder_of_device(DEVICE) == "alice"
    assert locks.locked_at(DEVICE) == world.clock.now()
    assert locks.held_by("alice") == ("gh-01", "gh-02")
    assert [event["action"] for event in locks.events()] == ["lock", "lock"]


def test_two_threads_one_winner(world, tmp_path):
    winners: list[str] = []
    errors: list[str] = []

    def attempt(name: str) -> None:
        db = Database(tmp_path / "workflow.db")  # the same file, its own connection
        svc = WorkflowService(db, world.clock, FakeControl(world.clock))
        mine = GreenhouseLocks(db, world.clock, REGISTRY, svc.store, svc.control)
        try:
            mine.lock(name, ["gh-01"])
            winners.append(name)
        except Denied as error:
            errors.append(error.code)
        finally:
            db.close()

    GreenhouseLocks(world.db, world.clock, REGISTRY, world.svc.store, world.control)
    threads = [threading.Thread(target=attempt, args=(n,)) for n in ("alice", "bob")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(winners) == 1
    assert errors == ["lock_taken"]


async def _ended_with_care(world) -> str:
    """A stage that ran and stopped: it keeps its care right, as terminal stages do."""
    stage = await world.running("stage-1")
    await world.svc.stop_stage(stage, world.op)
    assert world.svc.store.stage(stage).care_right is not None
    return stage


async def test_release_hands_over_care_and_frees(world, locks):
    stage = await _ended_with_care(world)
    care = world.svc.store.stage(stage).care_right
    locks.lock("alice", ["gh-01"])

    await locks.release("gh-01", "alice")

    row = world.svc.store.stage(stage)
    assert (care, "release") in world.control.handovers
    assert row.care_right is None and row.care_released is True
    assert locks.holder_of_device(DEVICE) is None
    assert locks.events()[0]["action"] == "release"


async def test_a_released_greenhouse_has_no_current_stage(world, locks):
    await _ended_with_care(world)
    locks.lock("alice", ["gh-01"])

    await locks.release("gh-01", "alice")

    assert world.svc.active_stage() is None


async def test_ended_stage_without_release_is_still_current(world, locks):
    stage = await _ended_with_care(world)

    assert world.svc.active_stage().stage_id == stage


async def test_the_released_stage_is_still_found_when_asked_for(world, locks):
    stage = await _ended_with_care(world)
    locks.lock("alice", ["gh-01"])

    await locks.release("gh-01", "alice")

    assert world.svc.active_stage(include_released=True).stage_id == stage


async def test_release_without_care_holder_only_deletes_lock(world, locks):
    locks.lock("alice", ["gh-02"])

    await locks.release("gh-02", "alice")

    assert locks.held_by("alice") == ()
    assert world.control.handovers == []


async def test_release_refused_while_stage_unfinished(world, locks):
    await world.pending("stage-1")
    locks.lock("alice", ["gh-01"])

    for force in (False, True):
        with pytest.raises(Denied) as denied:
            await locks.release("gh-01", "alice", force=force, note="x")
        assert denied.value.code == "greenhouse_busy"
    assert locks.holder_of_device(DEVICE) == "alice"


async def test_release_only_own_unless_forced(locks):
    locks.lock("alice", ["gh-02"])

    with pytest.raises(Denied) as denied:
        await locks.release("gh-02", "bob")
    assert denied.value.code == "not_lock_holder"

    await locks.release("gh-02", "root", force=True, note="alice left the lab")
    event = locks.events()[0]
    assert (event["action"], event["actor"], event["note"]) == (
        "force_release",
        "root",
        "alice left the lab",
    )


def _file_in_new_round(world, stage_id: str) -> None:
    """The stopped round waits for a choice, so the new stage goes into a new project's round."""
    project = world.svc.create_project("next", world.op)
    protocol = make_protocol(project_id=project, id="protocol-2")
    world.svc.save_protocol(protocol, world.op)
    round_id = world.svc.create_round(project, protocol.id, world.op)
    sheet = world.sheet(stage_id, project_id=project, protocol_id=protocol.id)
    world.svc.submit_run_sheet(round_id, sheet, world.op)


async def test_release_loses_to_concurrent_submission(world, locks):
    stage = await _ended_with_care(world)
    locks.lock("alice", ["gh-01"])
    original = world.control.handover

    async def racing(number, reason):
        world.control.handover = original
        await original(number, reason)
        _file_in_new_round(world, "stage-2")  # the owner files another stage meanwhile

    world.control.handover = racing

    with pytest.raises(Denied) as denied:
        await locks.release("gh-01", "alice")

    assert denied.value.code == "greenhouse_busy"
    assert locks.holder_of_device(DEVICE) == "alice"
    assert world.svc.store.stage(stage).care_released is False
    world.svc.approve("stage-2", world.op)  # the new stage goes on as if nothing happened
    assert world.state("stage-2") == "pending_review"


async def test_released_care_not_restored(world, locks):
    stage = await _ended_with_care(world)
    locks.lock("alice", ["gh-01"])
    await locks.release("gh-01", "alice")

    await world.svc.on_restart()

    assert world.svc.store.stage(stage).care_right is None


async def test_crash_between_handover_and_commit_restores_care(world, locks, monkeypatch):
    stage = await _ended_with_care(world)
    locks.lock("alice", ["gh-01"])

    def crash(*_args, **_kwargs):
        raise RuntimeError("process died")

    monkeypatch.setattr(locks, "_finish_release", crash)
    with pytest.raises(RuntimeError):
        await locks.release("gh-01", "alice")
    monkeypatch.undo()

    # what start-up does: the control service voids every right, then the workflow recovers
    world.control.revoked.update(world.control.rights)
    await world.svc.on_restart()

    row = world.svc.store.stage(stage)
    assert locks.holder_of_device(DEVICE) == "alice"
    assert row.care_released is False
    assert row.care_right is not None and row.care_right in world.control.live(RightKind.CARE)


async def test_release_during_recovery_keeps_care_away(world, locks):
    """After a restart the stopped stage has no care yet (the old writes are not confirmed gone);
    releasing then must still keep a later restore from giving that greenhouse care again."""
    stage = await _ended_with_care(world)
    locks.lock("alice", ["gh-01"])
    world.control.stopped = False  # restore_care declines until the transport is confirmed stopped
    await world.svc.on_restart()
    assert world.svc.store.stage(stage).care_right is None

    await locks.release("gh-01", "alice")
    world.control.stopped = True
    await world.svc.on_restart()

    assert world.svc.store.stage(stage).care_right is None


async def test_a_refused_release_gets_its_care_back(world, locks):
    # the release handed care back, then lost to a new stage: it changed nothing, so care
    # comes back on the next restore instead of waiting for a stage that may never start
    stage = await _ended_with_care(world)
    old = world.svc.store.stage(stage).care_right
    locks.lock("alice", ["gh-01"])
    original = world.control.handover

    async def racing(number, reason):
        world.control.handover = original
        await original(number, reason)
        _file_in_new_round(world, "stage-2")

    world.control.handover = racing
    with pytest.raises(Denied):
        await locks.release("gh-01", "alice")

    await world.svc.restore_care()  # what the runtime does on every tick

    row = world.svc.store.stage(stage)
    assert row.care_right is not None and row.care_right != old
    assert row.care_released is False


async def test_a_release_that_fails_after_the_hand_back_gets_its_care_back(
    world, locks, monkeypatch
):
    # not only a refusal: any failure after care was handed back leaves no dead right behind
    stage = await _ended_with_care(world)
    old = world.svc.store.stage(stage).care_right
    locks.lock("alice", ["gh-01"])

    def broken(*_args):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(locks, "_finish_release", broken)
    with pytest.raises(RuntimeError):
        await locks.release("gh-01", "alice")

    await world.svc.restore_care()

    row = world.svc.store.stage(stage)
    assert row.care_right is not None and row.care_right != old
