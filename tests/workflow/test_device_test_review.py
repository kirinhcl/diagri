"""Regressions from the final review of device tests (2026-11-27)."""

import asyncio

import pytest
from device_test_support import calls, make_rig

from growbridge.archive.models import Channel, RightKind
from growbridge.ports import Denied
from growbridge.sim.control import WritingFakeControl
from growbridge.sim.fixtures import DEVICE


@pytest.fixture
def control(clock):
    return WritingFakeControl(clock)


@pytest.fixture
def rig(world):
    return make_rig(world)


async def until(predicate):
    for _ in range(200):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition not reached")


def refusal(reason: str) -> Denied:
    return Denied("state", reason, reason=reason)


# --- C1: a tick during the snapshot ----------------------------------------------------------


async def test_resume_during_the_snapshot_leaves_the_test_alone(rig):
    rig.control.snapshot_gate = asyncio.Event()
    first = asyncio.create_task(rig.tests.run("gh-01", Channel.LIGHT, rig.people.alice))
    await until(lambda: rig.tests.open_test(DEVICE) is not None)

    await rig.tests.resume()  # the runtime ticks while the device is being read

    assert rig.tests.open_test(DEVICE).state == "running"
    with pytest.raises(Denied) as second:
        await rig.tests.run("gh-01", Channel.FAN, rig.people.alice)
    assert second.value.reason == "device_test_running"
    rig.control.snapshot_gate.set()
    assert (await first)["result"] == "restored"
    assert [entry[1:3] for entry in calls(rig, "submit")] == [(Channel.LIGHT, 100)]


# --- I1 / M2: nothing reached the device -----------------------------------------------------


async def test_refused_switch_on_leaves_no_record_restore_or_alert(rig):
    rig.control.refuse["submit"] = refusal("controls_disabled")

    with pytest.raises(Denied) as refused:
        await rig.tests.run("gh-01", Channel.LIGHT, rig.people.alice)

    assert refused.value.reason == "controls_disabled"
    assert rig.tests.history("gh-01") == [] and rig.tests.open_test(DEVICE) is None
    assert calls(rig, "restore") == [] and rig.alerts == []
    assert rig.control.live(RightKind.TEST) == []


async def test_refused_pump_run_leaves_no_record(rig):
    rig.control.refuse["irrigate"] = refusal("irrigation_too_soon")

    with pytest.raises(Denied):
        await rig.tests.run("gh-01", Channel.PUMP, rig.people.alice)

    assert rig.tests.history("gh-01") == [] and calls(rig, "restore") == []


async def test_a_value_the_device_did_not_take_is_not_run(rig):
    rig.control.not_taken = True

    result = await rig.tests.run("gh-01", Channel.LIGHT, rig.people.alice)

    assert result["result"] == "not_run"
    assert rig.tests.history("gh-01")[0].state == "done"
    assert calls(rig, "restore") == [] and rig.alerts == [] and rig.sleeper.calls == []


async def test_refused_restore_after_the_value_was_written_is_restore_failed(rig):
    rig.control.refuse["restore"] = refusal("no_live_link")

    result = await rig.tests.run("gh-01", Channel.LIGHT, rig.people.alice)

    assert result["result"] == "restore_failed"
    assert rig.tests.unsettled(DEVICE) is not None and len(rig.alerts) == 1


# --- I2: a stage start handing over its rights -----------------------------------------------


async def test_test_refused_while_a_stage_start_hands_over(rig):
    rig.idle.restore()
    rig.people.pending()
    rig.world.svc.approve("stage-1", rig.people.alice)
    rig.control.handover_gate = asyncio.Event()
    start = asyncio.create_task(rig.world.svc.start_stage("stage-1", rig.people.alice))
    await until(lambda: calls(rig, "handover_waiting"))

    with pytest.raises(Denied) as refused:  # bounded: a test that waits here would hang
        await asyncio.wait_for(rig.tests.run("gh-01", Channel.LIGHT, rig.people.alice), 1)

    assert refused.value.reason == "device_test_not_idle"
    rig.control.handover_gate.set()
    await start
    assert rig.world.state() == "running"
    assert rig.control.granted(RightKind.TEST) == []


# --- I3: the restart retry waits out a refusal -----------------------------------------------


async def test_resume_leaves_a_refused_restore_running(rig):
    snapshot = await rig.control.snapshot(Channel.LIGHT)
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
    rig.control.refuse["restore"] = refusal("still_starting")

    await rig.tests.resume()

    assert rig.tests.record("devtest_cut").state == "running" and rig.alerts == []
    del rig.control.refuse["restore"]
    await rig.tests.resume()
    assert rig.tests.record("devtest_cut").state == "done"


async def test_resume_drops_a_row_cut_off_before_any_write(rig):
    rig.world.db.execute(
        "INSERT INTO device_tests(test_id, greenhouse_id, device_id, channel, operator, state,"
        " started_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("devtest_early", "gh-01", DEVICE, "light", "alice", "running", 1.0),
    )

    await rig.tests.resume()

    assert rig.tests.record("devtest_early") is None
    assert [e for e in rig.people.locks.events() if e["action"].startswith("test")] == []
