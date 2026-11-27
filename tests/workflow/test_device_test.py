"""Device tests: a holder's short on-site test of one channel on an idle greenhouse."""

import asyncio

import pytest
from device_test_support import build, calls, make_rig

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


async def refused(rig, channel=Channel.LIGHT, greenhouse="gh-01", actor=None) -> str:
    with pytest.raises(Denied) as error:
        await rig.tests.run(greenhouse, channel, actor or rig.people.alice)
    return error.value.reason


async def test_light_test_writes_100_waits_10_and_restores(rig):
    result = await rig.tests.run("gh-01", Channel.LIGHT, rig.people.alice)

    assert result["result"] == "restored"
    assert (result["channel"], result["test_level"], result["seconds"]) == ("light", 100, 10)
    assert [entry[1:3] for entry in calls(rig, "submit")] == [(Channel.LIGHT, 100)]
    assert [entry[1:3] for entry in calls(rig, "restore")] == [(Channel.LIGHT, 0)]
    assert rig.sleeper.calls == [10]
    granted = rig.control.granted(RightKind.TEST)
    assert len(granted) == 1 and rig.control.right(granted[0]) is None  # handed back
    assert rig.control.rights[granted[0]].operator == "alice"
    assert rig.tests.history("gh-01")[0].state == "done"


@pytest.mark.parametrize(("channel", "level"), [(Channel.EXHAUST, 100), (Channel.FAN, 10)])
async def test_level_channels_use_their_test_values(rig, channel, level):
    result = await rig.tests.run("gh-01", channel, rig.people.alice)

    assert [entry[1:3] for entry in calls(rig, "submit")] == [(channel, level)]
    assert result["test_level"] == level and result["seconds"] == 10


async def test_pump_test_irrigates_min_3_and_limit(rig):
    rig.tests = build(rig.world, rig.people, rig.idle, rig.sleeper, max_pump_seconds=2)

    result = await rig.tests.run("gh-01", Channel.PUMP, rig.people.alice)

    assert [entry[1] for entry in calls(rig, "irrigate")] == [2]
    assert rig.sleeper.calls == []
    assert [entry[1] for entry in calls(rig, "restore")] == [Channel.PUMP]
    assert result["seconds"] == 2 and result["result"] == "restored"


async def test_pump_test_runs_3_seconds_under_the_default_limit(rig):
    await rig.tests.run("gh-01", Channel.PUMP, rig.people.alice)

    assert [entry[1] for entry in calls(rig, "irrigate")] == [3]


async def test_refused_when_not_holder(rig):
    assert await refused(rig, actor=rig.people.bob) == "greenhouse_not_held"


async def test_refused_when_greenhouse_not_local(rig):
    assert await refused(rig, greenhouse="gh-02") == "device_test_not_local"


async def test_refused_when_a_stage_has_started(rig):
    await rig.people.running()

    assert await refused(rig) == "device_test_not_idle"
    assert calls(rig, "submit") == []


async def test_second_test_while_one_runs_is_refused(rig):
    rig.sleeper.gate = asyncio.Event()
    first = asyncio.create_task(rig.tests.run("gh-01", Channel.LIGHT, rig.people.alice))
    while not rig.sleeper.calls:
        await asyncio.sleep(0)

    assert await refused(rig, channel=Channel.FAN) == "device_test_running"
    rig.sleeper.gate.set()
    assert (await first)["result"] == "restored"
    assert rig.tests.running(DEVICE) is None


async def test_refused_on_a_protected_channel(rig):
    rig.tests.protected = lambda: frozenset({Channel.LIGHT})

    assert await refused(rig) == "device_test_protected"
    assert calls(rig, "submit") == [] and rig.control.granted(RightKind.TEST) == []


async def test_protection_during_the_wait_skips_restore(rig):
    held = set()
    rig.tests.protected = lambda: frozenset(held)
    rig.sleeper.during = lambda: held.add(Channel.LIGHT)

    result = await rig.tests.run("gh-01", Channel.LIGHT, rig.people.alice)

    assert result["result"] == "protected"
    assert calls(rig, "restore") == []
    assert rig.tests.history("gh-01")[0].state == "done"


async def test_idle_right_is_handed_back_and_regranted(rig):
    rig.idle.restore()
    held = rig.idle.right

    await rig.tests.run("gh-01", Channel.LIGHT, rig.people.alice)

    assert (held, "device test") in rig.control.handovers
    rig.idle.restore()
    assert rig.idle.right != held and rig.idle.runtime() is not None


async def test_restore_failure_raises_an_alert(rig):
    rig.control.fail_restore = True

    result = await rig.tests.run("gh-01", Channel.LIGHT, rig.people.alice)

    assert result["result"] == "restore_failed"
    record = rig.tests.unsettled(DEVICE)
    assert record is not None and record.state == "restore_failed"
    ((args, kwargs),) = rig.alerts
    assert args[0] == "device_test_restore_failed" and args[4] == ("device", DEVICE)
    assert kwargs["params"] == {
        "greenhouse_id": "gh-01",
        "channel": "light",
        "test_id": result["test_id"],
    }


async def test_unreadable_device_writes_nothing(rig):
    rig.control.unreadable = True

    with pytest.raises(ConnectionError):
        await rig.tests.run("gh-01", Channel.LIGHT, rig.people.alice)

    assert rig.tests.history("gh-01") == []
    assert rig.control.granted(RightKind.TEST) == [] and calls(rig, "submit") == []


async def test_lock_log_records_the_test(rig):
    await rig.tests.run("gh-01", Channel.LIGHT, rig.people.alice)

    event = rig.people.locks.events()[0]
    assert (event["action"], event["actor"], event["note"]) == ("test", "alice", "light: restored")


async def test_testable_only_for_own_local_idle_greenhouse(rig):
    rows = {row["id"]: row for row in rig.people.locks.overview()}

    assert rig.tests.testable(rows["gh-01"], rig.people.alice) is True
    assert rig.tests.testable(rows["gh-02"], rig.people.alice) is False
    assert rig.tests.testable(rows["gh-01"], rig.people.bob) is False
