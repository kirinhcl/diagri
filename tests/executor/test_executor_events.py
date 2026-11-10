"""What the executor reports to the workflow service (spec 7.7, 7.8)."""

import pytest

from growbridge.archive.models import Channel
from growbridge.ports import StageEventKind
from growbridge.sim.fixtures import humidity_rule

KIND = StageEventKind


async def drop_link(rig):
    rig.sim.connected = False
    report = await rig.tick()
    assert report.writes == ()


async def restore_link(rig):
    rig.sim.connected = True
    await rig.refresh()


# --- disconnects (7.7) ----------------------------------------------------------------------


async def test_executor_disconnect_with_a_due_action_pauses_the_stage(rig):
    await rig.at("05:59")
    await rig.start()
    await rig.tick()
    await drop_link(rig)
    rig.clock.advance(90)  # inside the allowed gap, but 06:00 passes
    writes = len(rig.writes())

    await restore_link(rig)
    report = await rig.tick()

    assert KIND.DISCONNECT_AFFECTS in report.reported
    assert rig.state() == "paused"
    assert len(rig.writes()) == writes  # nothing of the stage is written after the outage


async def test_executor_short_disconnect_without_due_action_only_records_the_gap(rig):
    await rig.start()
    await rig.tick()
    await drop_link(rig)
    rig.clock.advance(60)
    await restore_link(rig)

    report = await rig.tick()

    assert report.reported == ()
    assert rig.state() == "running"
    assert report.gap_seconds == pytest.approx(60, abs=1)
    assert rig.engine.gaps == (report.gap_seconds,)


async def test_executor_disconnect_longer_than_the_allowed_gap_pauses_the_stage(rig):
    await rig.start()
    await rig.tick()
    await drop_link(rig)
    rig.clock.advance(300)  # the run sheet allows 120 s without data
    await restore_link(rig)

    report = await rig.tick()

    assert KIND.DISCONNECT_AFFECTS in report.reported
    assert rig.state() == "paused"


async def test_executor_disconnect_with_a_changed_device_pauses_the_stage(rig):
    await rig.start()
    await rig.tick()
    await drop_link(rig)
    rig.sim.external_change("device", "light", mLevel=5)
    rig.clock.advance(30)
    await restore_link(rig)

    report = await rig.tick()

    assert KIND.DISCONNECT_AFFECTS in report.reported
    assert rig.state() == "paused"


# --- reports ------------------------------------------------------------------------------


@pytest.mark.parametrize("change", [{"mLevel": 10}, {"modeType": 1}], ids=["level", "mode"])
async def test_executor_panel_change_is_reported_and_pauses(rig, change):
    await rig.start()
    await rig.tick()
    rig.sim.external_change("device", "light", **change)

    report = await rig.tick()

    assert KIND.EXTERNAL_CHANGE in report.reported
    assert rig.state() == "paused"


async def test_executor_unknown_result_is_reported_and_blocks_further_writes(rig):
    await rig.start()
    rig.sim.lose_replies = True

    report = await rig.tick()

    assert KIND.RESULT_UNKNOWN in report.reported
    assert rig.state() == "paused"
    assert rig.control.unsettled_actions()
    count = len(rig.writes())
    await rig.tick()
    # care rules may still write the light; the stage's own writes stay blocked
    assert {key for key, _ in rig.written()[count:]} <= {"light"}


async def test_executor_missing_sensor_pauses_when_the_rule_says_so(rig):
    rig.sim.set_sensor("humi", None)
    await rig.start(feedback_rules=(humidity_rule(on_missing="pause"),))
    await rig.refresh()

    report = await rig.tick()

    assert KIND.RULE_PAUSE in report.reported
    assert rig.state() == "paused"


async def test_executor_missing_sensor_holds_when_the_rule_says_hold(rig):
    rig.sim.set_sensor("humi", None)
    await rig.start(feedback_rules=(humidity_rule(),))
    await rig.refresh()

    report = await rig.tick()

    assert report.reported == () and rig.state() == "running"


# --- pause expiry -------------------------------------------------------------------------


async def pause_with_limit(rig, **fields):
    await rig.start(max_wait_seconds=600, **fields)
    await rig.svc.pause_stage("stage-1", rig.op, "test")
    await rig.tick()


async def test_executor_reports_the_longest_wait_once_it_has_passed(rig):
    await pause_with_limit(rig)
    await rig.pass_time(300)
    assert (await rig.tick()).reported == ()

    await rig.pass_time(301)
    report = await rig.tick()

    assert report.reported == (KIND.MAX_WAIT_EXPIRED,)
    assert rig.state() == "paused"  # on_expiry defaults to staying paused
    await rig.pass_time(10)
    assert (await rig.tick()).reported == ()  # reported once


async def test_executor_stops_the_stage_when_the_run_sheet_says_stop_on_expiry(rig):
    await pause_with_limit(rig, on_expiry="stop")
    await rig.pass_time(601)

    await rig.tick()

    assert rig.state() == "stopped"


# --- interlock (7.8) ----------------------------------------------------------------------


async def test_executor_tries_pump_off_before_any_other_write(rig):
    await rig.start()
    await rig.interlock()
    rig.sim.fail_off = False
    sent = len(rig.sim.commands)

    await rig.tick()

    first = next(c for c in rig.sim.commands[sent:] if c["method"] == "setConfigField")
    assert first["params"]["keyPath"][1] == "O4" and first["params"]["O4"]["mOnOff"] == 0
    assert not rig.control.interlocked()
    assert rig.state() == "paused"


async def test_executor_reports_an_unconfirmed_pump_off(rig):
    await rig.start()
    await rig.interlock()

    report = await rig.tick()

    assert KIND.PUMP_OFF_UNCONFIRMED in report.reported
    assert rig.state() == "recovery_check"


# --- bookkeeping --------------------------------------------------------------------------


async def test_executor_heartbeat_follows_completed_ticks(rig):
    assert rig.engine.heartbeat() is None

    await rig.tick()
    first = rig.engine.heartbeat()
    await rig.pass_time(5)
    await rig.tick()

    assert first == pytest.approx(rig.clock.monotonic() - 5)
    assert rig.engine.heartbeat() == pytest.approx(rig.clock.monotonic())


# --- stale readings and unconfirmed transport (Appendix B) ----------------------------------


async def test_executor_stale_readings_while_connected_pause_the_stage_once(rig):
    await rig.start()
    await rig.tick()
    rig.clock.advance(200)  # connected, but no telemetry for longer than the run sheet allows

    report = await rig.tick()

    assert KIND.READINGS_STALE in report.reported
    assert report.writes == ()
    assert rig.state() == "paused"
    assert KIND.READINGS_STALE not in (await rig.tick()).reported


async def test_executor_fresh_readings_rearm_the_stale_report(rig):
    await rig.start()
    await rig.tick()
    rig.clock.advance(200)
    await rig.tick()
    await rig.refresh()
    await rig.svc.resume_stage("stage-1", rig.op)
    assert rig.state() == "running"
    await rig.tick()
    rig.clock.advance(200)

    report = await rig.tick()

    assert KIND.READINGS_STALE in report.reported
    assert rig.state() == "paused"


@pytest.mark.parametrize("situation", ["running", "paused", "manual"])
async def test_executor_unconfirmed_transport_sends_no_stage_or_care_writes(rig, situation):
    await rig.start()
    if situation == "paused":
        await rig.svc.pause_stage("stage-1", rig.op, "test")
    elif situation == "manual":
        await rig.svc.takeover("stage-1", rig.op)
    rig.sim.halt_confirmed = False
    assert not await rig.control.confirm_transport_stopped()

    report = await rig.tick()

    assert KIND.TRANSPORT_UNCONFIRMED in report.reported
    assert report.writes == () and rig.writes() == []
    assert rig.state() == "recovery_check"


# --- the external-change baseline belongs to the stage write right ----------------------------


async def test_executor_handback_without_a_tick_in_manual_is_not_an_external_change(rig):
    await rig.start()
    await rig.tick()
    await rig.svc.takeover("stage-1", rig.op)
    await rig.manual_write(Channel.LIGHT, 20)
    await rig.svc.handback("stage-1", rig.op, accept_as_intervention=True)

    report = await rig.tick()

    assert KIND.EXTERNAL_CHANGE not in report.reported
    assert rig.state() == "running"
    assert (await rig.levels())[Channel.LIGHT] == 60  # realigned to the schedule
    rig.sim.external_change("device", "light", mLevel=10)  # a real panel change still counts
    assert KIND.EXTERNAL_CHANGE in (await rig.tick()).reported
    assert rig.state() == "paused"


async def test_executor_resume_without_a_tick_in_pause_keeps_the_stage_running(rig):
    await rig.start()
    await rig.tick()
    await rig.svc.pause_stage("stage-1", rig.op, "test")
    await rig.svc.resume_stage("stage-1", rig.op)

    report = await rig.tick()

    assert report.reported == () and rig.state() == "running"
