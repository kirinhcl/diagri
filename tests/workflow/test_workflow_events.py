import pytest

from growbridge.ports import StageEventKind as Kind

PAUSING = [
    Kind.DISCONNECT_AFFECTS,
    Kind.READINGS_STALE,
    Kind.EXTERNAL_CHANGE,
    Kind.CLOCK_ANOMALY,
    Kind.RESULT_UNKNOWN,
    Kind.ALERT_PAUSE,
    Kind.RULE_PAUSE,
]
UNCONFIRMED = [Kind.PUMP_OFF_UNCONFIRMED, Kind.TRANSPORT_UNCONFIRMED]


def handed(world) -> list[int]:
    return [number for number, _ in world.control.handovers]


@pytest.mark.parametrize("kind", PAUSING)
async def test_stage_running_to_paused_on_events_that_affect_execution(world, kind):
    await world.running()
    old = world.svc.stage("stage-1")
    await world.report(kind)
    runtime = world.svc.stage("stage-1")
    assert runtime.state.value == "paused"
    assert runtime.right_number is None
    assert old.right_number in handed(world)
    assert runtime.care_right == old.care_right


@pytest.mark.parametrize("kind", PAUSING)
async def test_stage_pausing_events_are_ignored_outside_running(world, kind):
    await world.running()
    await world.svc.takeover("stage-1", world.op)
    await world.report(kind)
    assert world.state() == "manual"


@pytest.mark.parametrize("kind", UNCONFIRMED)
@pytest.mark.parametrize("start", ["running", "paused", "manual"])
async def test_stage_unconfirmed_transport_or_pump_goes_to_recovery_check(world, kind, start):
    await world.running()
    if start == "paused":
        await world.svc.pause_stage("stage-1", world.op, "x")
    if start == "manual":
        await world.svc.takeover("stage-1", world.op)
    before = world.svc.stage("stage-1")
    await world.report(kind)
    runtime = world.svc.stage("stage-1")
    assert runtime.state.value == "recovery_check"
    assert runtime.prior_state.value == start
    assert runtime.right_number is None and runtime.manual_right is None
    for number in (before.right_number, before.manual_right):
        if number is not None:
            assert number in handed(world)


@pytest.mark.parametrize("kind", UNCONFIRMED)
async def test_stage_unconfirmed_events_are_ignored_for_a_stage_waiting_for_review(world, kind):
    await world.pending()
    await world.report(kind)
    assert world.state() == "pending_review"


async def test_stage_same_event_id_advances_only_once(world):
    await world.running()
    event = world.event(Kind.RULE_PAUSE)
    await world.svc.report(event)
    await world.svc.resume_stage("stage-1", world.op)
    await world.svc.report(event)
    assert world.state() == "running"
    assert len([row for row in world.svc.history("stage-1") if row["event"] == "rule_pause"]) == 1


async def test_stage_event_for_an_old_stage_right_is_dropped(world):
    await world.running()
    old = world.svc.stage("stage-1").right_number
    await world.svc.pause_stage("stage-1", world.op, "x")
    await world.svc.resume_stage("stage-1", world.op)
    await world.report(Kind.RULE_PAUSE, detail={"right_number": old})
    assert world.state() == "running"


async def test_stage_event_for_an_unknown_stage_is_ignored(world):
    await world.report(Kind.RULE_PAUSE, stage_id="ghost")


async def test_stage_end_condition_sets_end_pending_and_keeps_running(world):
    await world.running()
    old = world.svc.stage("stage-1")
    await world.report(Kind.END_CONDITION_MET)
    runtime = world.svc.stage("stage-1")
    assert runtime.state.value == "running"
    assert runtime.end_pending is True
    assert runtime.right_number == old.right_number
    assert world.control.handovers == []


async def test_stage_end_actions_confirmed_ends_the_stage_and_hands_over_the_stage_right(world):
    await world.running()
    old = world.svc.stage("stage-1")
    await world.report(Kind.END_CONDITION_MET)
    await world.report(Kind.END_ACTIONS, detail={"confirmed": True})
    runtime = world.svc.stage("stage-1")
    assert runtime.state.value == "ended"
    assert runtime.right_number is None
    assert runtime.end_pending is False
    assert old.right_number in handed(world)
    assert runtime.care_right == old.care_right


async def test_stage_end_actions_unconfirmed_keeps_the_stage_for_checking(world):
    await world.running()
    old = world.svc.stage("stage-1")
    await world.report(Kind.END_CONDITION_MET)
    await world.report(Kind.END_ACTIONS, detail={"confirmed": False})
    runtime = world.svc.stage("stage-1")
    assert runtime.state.value == "recovery_check"
    assert runtime.prior_state.value == "running"
    assert runtime.end_pending is True
    assert old.right_number in handed(world)
    assert world.round_state() == "stage_running"


async def test_stage_end_actions_without_an_end_condition_are_dropped(world):
    await world.running()
    await world.report(Kind.END_ACTIONS, detail={"confirmed": True})
    assert world.state() == "running"


async def test_stage_end_condition_is_ignored_while_paused(world):
    await world.running()
    await world.svc.pause_stage("stage-1", world.op, "x")
    await world.report(Kind.END_CONDITION_MET)
    assert world.svc.stage("stage-1").end_pending is False


async def test_stage_max_wait_expired_stays_paused_when_the_sheet_says_so(world):
    await world.running(on_expiry="stay_paused")
    await world.svc.pause_stage("stage-1", world.op, "x")
    await world.report(Kind.MAX_WAIT_EXPIRED)
    assert world.state() == "paused"
    expired = [row for row in world.svc.history("stage-1") if row["event"] == "max_wait_expired"]
    assert len(expired) == 1


async def test_stage_max_wait_expired_stops_the_stage_when_the_sheet_says_so(world):
    await world.running(on_expiry="stop")
    await world.svc.pause_stage("stage-1", world.op, "x")
    await world.report(Kind.MAX_WAIT_EXPIRED)
    assert world.state() == "stopped"


async def test_stage_max_wait_expired_is_ignored_while_running(world):
    await world.running(on_expiry="stop")
    await world.report(Kind.MAX_WAIT_EXPIRED)
    assert world.state() == "running"


async def test_stage_events_after_the_stage_ended_are_dropped(world):
    await world.running()
    await world.report(Kind.END_CONDITION_MET)
    await world.report(Kind.END_ACTIONS, detail={"confirmed": True})
    await world.report(Kind.RULE_PAUSE)
    assert world.state() == "ended"
