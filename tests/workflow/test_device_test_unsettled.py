"""Unsettled device tests: retry, on-site settling, the restart retry, release and stage start."""

import asyncio

import pytest
from device_test_support import calls, make_rig

from growbridge.archive.models import Channel
from growbridge.ports import Denied
from growbridge.sim.control import WritingFakeControl
from growbridge.sim.fixtures import DEVICE


@pytest.fixture
def control(clock):
    return WritingFakeControl(clock)


@pytest.fixture
def rig(world):
    return make_rig(world)


async def failed_test(rig) -> str:
    rig.control.fail_restore = True
    result = await rig.tests.run("gh-01", Channel.LIGHT, rig.people.alice)
    rig.control.fail_restore = False
    return result["test_id"]


async def test_restore_failure_blocks_stage_start_until_settled(rig):
    test_id = await failed_test(rig)

    with pytest.raises(Denied) as refused:
        await rig.people.running()
    assert refused.value.reason == "device_test_unsettled"

    rig.tests.settle("gh-01", test_id, rig.people.alice, "checked the light on site")
    await rig.world.svc.start_stage("stage-1", rig.people.alice)
    assert rig.world.state() == "running"


async def test_retry_restores_and_resolves_the_alert(rig):
    test_id = await failed_test(rig)

    result = await rig.tests.retry("gh-01", test_id, rig.people.alice)

    assert result["result"] == "restored"
    assert rig.tests.record(test_id).state == "done"
    assert rig.tests.unsettled(DEVICE) is None
    assert rig.resolved == [("device_test_restore_failed", test_id, ("device", DEVICE))]


async def test_retry_that_fails_again_stays_unsettled(rig):
    test_id = await failed_test(rig)
    rig.control.fail_restore = True

    result = await rig.tests.retry("gh-01", test_id, rig.people.alice)

    assert result["result"] == "restore_failed"
    assert rig.tests.record(test_id).state == "restore_failed"


async def test_settle_needs_a_note(rig):
    test_id = await failed_test(rig)

    with pytest.raises(ValueError):
        rig.tests.settle("gh-01", test_id, rig.people.alice, "   ")
    assert rig.tests.record(test_id).state == "restore_failed"


async def test_settle_only_by_holder(rig):
    test_id = await failed_test(rig)

    with pytest.raises(Denied) as refused:
        rig.tests.settle("gh-01", test_id, rig.people.bob, "checked")
    assert refused.value.reason == "greenhouse_not_held"


async def test_settle_records_the_note_and_resolves(rig):
    test_id = await failed_test(rig)

    rig.tests.settle("gh-01", test_id, rig.people.alice, "light back on its timer")

    record = rig.tests.record(test_id)
    assert (record.state, record.note) == ("settled_onsite", "light back on its timer")
    event = rig.people.locks.events()[0]
    assert (event["action"], event["note"]) == ("test_settled", "light back on its timer")
    assert rig.resolved == [("device_test_restore_failed", test_id, ("device", DEVICE))]


async def test_release_refused_while_test_running(rig):
    rig.sleeper.gate = asyncio.Event()
    running = asyncio.create_task(rig.tests.run("gh-01", Channel.LIGHT, rig.people.alice))
    while not rig.sleeper.calls:
        await asyncio.sleep(0)

    with pytest.raises(Denied) as refused:
        await rig.people.locks.release("gh-01", "alice", plants_removed=True)
    assert refused.value.reason == "device_test_unsettled"

    rig.sleeper.gate.set()
    assert (await running)["result"] == "restored"
    assert rig.people.locks.held_by("alice") == ("gh-01", "gh-02")


async def test_release_refused_while_unsettled(rig):
    await failed_test(rig)

    with pytest.raises(Denied) as refused:
        await rig.people.locks.release("gh-01", "alice", plants_removed=True)
    assert refused.value.reason == "device_test_unsettled"


async def test_forced_release_settles_unsettled_tests(rig):
    test_id = await failed_test(rig)

    await rig.people.locks.release("gh-01", "root", force=True, note="alice left the lab")

    record = rig.tests.record(test_id)
    assert (record.state, record.note) == ("settled_onsite", "alice left the lab")
    assert rig.people.locks.held_by("alice") == ("gh-02",)


async def left_running(rig) -> str:
    """What a restart leaves of a test cut off after its value was written: a ``running`` row
    with its snapshot, and the device at the test value."""
    snapshot = await rig.control.snapshot(Channel.LIGHT)
    rig.control.levels[Channel.LIGHT] = 100
    rig.world.db.execute(
        "INSERT INTO device_tests(test_id, greenhouse_id, device_id, channel, operator, state,"
        " snapshot, started_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "devtest_cut",
            "gh-01",
            DEVICE,
            "light",
            "alice",
            "running",
            snapshot.model_dump_json(),
            1.0,
        ),
    )
    return "devtest_cut"


async def test_resume_restores_a_test_left_running(rig):
    test_id = await left_running(rig)
    assert rig.tests.unsettled(DEVICE).test_id == test_id

    await rig.tests.resume()

    assert rig.tests.record(test_id).state == "done"
    assert [entry[1:3] for entry in calls(rig, "restore")] == [(Channel.LIGHT, 0)]


async def test_resume_waits_for_the_link(rig):
    test_id = await left_running(rig)
    rig.control.is_connected = False

    await rig.tests.resume()

    assert rig.tests.record(test_id).state == "running"
    assert calls(rig, "restore") == []
