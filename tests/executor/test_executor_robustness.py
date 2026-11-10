"""Restarts, event metadata, failed readbacks and end-action filtering."""

import pytest

from growbridge.archive.models import (
    Channel,
    ChannelPlan,
    Condition,
    Ownership,
    ProtectionRule,
    RuleAction,
    TimedAction,
)
from growbridge.executor.engine import ExecutorEngine
from growbridge.ports import StageEventKind
from growbridge.sim.fixtures import make_safety

KIND = StageEventKind


class RecordingPort:
    """The workflow service behind the StagePort protocol, recording what was reported."""

    def __init__(self, inner, fail_reports=0):
        self.inner = inner
        self.events = []
        self.fail_reports = fail_reports

    def active_stage(self):
        return self.inner.active_stage()

    async def report(self, event):
        self.events.append(event)
        if self.fail_reports:
            self.fail_reports -= 1
            raise ConnectionError("workflow unavailable")
        await self.inner.report(event)


def exhaust_safety():
    rule = ProtectionRule(
        id="overheat-exhaust-up",
        sensor="temp",
        unit="C",
        validity_seconds=20,
        trigger=Condition(op=">", value=35),
        duration_seconds=30,
        action=RuleAction(channel=Channel.EXHAUST, level=100),
    )
    return make_safety(rules=(rule,))


async def test_executor_restart_writes_again_instead_of_trusting_an_old_receipt(rig):
    await rig.start()
    await rig.tick()  # light-on is confirmed under the first process
    await rig.svc.takeover("stage-1", rig.op)
    await rig.manual_write(Channel.LIGHT, 20)
    await rig.svc.handback("stage-1", rig.op, accept_as_intervention=True)
    restarted = ExecutorEngine(rig.control, rig.svc, rig.clock)  # a new process, same databases

    report = await restarted.tick()

    assert KIND.EXTERNAL_CHANGE not in report.reported
    assert any("light" in request_id for request_id in report.writes)
    assert (await rig.levels())[Channel.LIGHT] == 60
    assert rig.state() == "running"
    again = await restarted.tick()
    assert again.writes == () and again.reported == ()


async def test_executor_reports_carry_the_write_right_they_were_decided_under(rig):
    port = RecordingPort(rig.svc)
    rig.engine = ExecutorEngine(rig.control, port, rig.clock)
    await rig.start()
    await rig.tick()
    right = rig.svc.stage("stage-1").right_number
    rig.sim.external_change("device", "light", mLevel=10)

    await rig.tick()

    assert [e.kind for e in port.events] == [KIND.EXTERNAL_CHANGE]
    assert port.events[0].detail["right_number"] == right


async def test_executor_report_that_raised_is_sent_again_on_the_next_tick(rig):
    port = RecordingPort(rig.svc, fail_reports=1)
    rig.engine = ExecutorEngine(rig.control, port, rig.clock)
    await rig.start()
    await rig.tick()
    rig.sim.external_change("device", "light", mLevel=10)

    with pytest.raises(ConnectionError):
        await rig.tick()
    report = await rig.tick()

    assert report.reported == (KIND.EXTERNAL_CHANGE,)
    assert port.events[0].event_id == port.events[1].event_id
    assert rig.state() == "paused"


async def test_executor_stops_retrying_a_readback_that_keeps_failing(rig):
    port = RecordingPort(rig.svc)
    rig.engine = ExecutorEngine(rig.control, port, rig.clock)
    await rig.start()
    rig.sim.ignore_writes = True  # acknowledged, never applied: every readback differs

    for _ in range(5):
        await rig.tick()
        await rig.pass_time(1)
        if rig.state() != "running":
            break

    keys = [key for key, _ in rig.written()]
    assert keys.count("light") == 3  # a small fixed number of attempts, then it stops
    assert keys.count("blower") <= 3  # the stage was paused before its last attempt
    assert [e.kind for e in port.events] == [KIND.EXTERNAL_CHANGE]  # reported once
    assert rig.state() == "paused"


async def test_executor_end_actions_only_touch_host_controlled_channels_and_never_the_pump(rig):
    channels = (
        ChannelPlan(channel=Channel.LIGHT, ownership=Ownership.DEVICE),
        ChannelPlan(channel=Channel.EXHAUST, ownership=Ownership.HOST, retained_level=30),
        ChannelPlan(channel=Channel.PUMP, ownership=Ownership.HOST, retained_level=0),
    )
    end = (
        RuleAction(channel=Channel.LIGHT, level=0),
        RuleAction(channel=Channel.PUMP, level=0),
        RuleAction(channel=Channel.EXHAUST, level=10),
    )
    timed = (TimedAction(id="exhaust-base", channel=Channel.EXHAUST, at="00:00", level=30),)
    await rig.start(
        safety=exhaust_safety(),
        channels=channels,
        timed_actions=timed,
        end_actions=end,
        duration_seconds=3600,
    )
    await rig.tick()
    await rig.pass_time(3601)

    report = await rig.tick()

    assert KIND.END_ACTIONS in report.reported and rig.state() == "ended"
    assert {key for key, _ in rig.written()} == {"blower"}
    assert rig.written()[-1] == ("blower", 10)
