"""Each receipt and early-end site carries a message code and params (registry families
``receipt`` and ``task_end``); the English ``error`` and ``ended_early`` texts stay as they were."""

import asyncio

import pytest
from test_control_planned_irrigation import HOSTED, _cut_short
from test_control_priority import hang_first_field_write, hold_a, wait_for

from growbridge.archive.models import ActionRecord, ActionState, Channel
from growbridge.control.device import changed_nothing
from growbridge.sim.fixtures import make_safety

# --- DeviceIO outcomes ------------------------------------------------------------------------


async def light(rig, level=40, request_id="w"):
    number = rig.stage_right()
    return await rig.service.submit(rig.request(number, Channel.LIGHT, level, request_id))


def failing(rig, method, error):
    original = rig.bridge.request

    async def request(name, *args, **kwargs):
        if name == method:
            raise error
        return await original(name, *args, **kwargs)

    rig.bridge.request = request


async def test_a_write_that_could_not_be_built_is_not_sent(rig):
    async def offline():
        raise ConnectionError("offline")

    rig.bridge.configuration = offline
    record = await light(rig)
    assert record.state is ActionState.FAILED and record.error.startswith("not sent: ")
    assert (record.error_code, record.error_params) == ("not_sent", {})


async def test_a_rejected_write_says_the_device_rejected_it(rig):
    original = rig.sim.send

    async def reject(command):
        if command["method"] == "setConfigField":
            rig.sim.emit({"method": "setConfigField", "msgId": command["msgId"], "code": 500})
            return
        await original(command)

    rig.sim.send = reject
    record = await light(rig)
    assert record.error.startswith("Device rejected")
    assert (record.error_code, record.error_params) == ("device_rejected", {})


async def test_a_write_without_a_receipt_says_so(rig):
    rig.sim.lose_replies = True
    record = await light(rig)
    assert record.error.startswith("no receipt")
    assert (record.error_code, record.error_params) == ("no_receipt", {})


async def test_a_link_that_broke_while_sending_says_so(rig):
    failing(rig, "setConfigField", ConnectionError("gone"))
    record = await light(rig)
    assert record.error == "link broke while sending: gone"
    assert (record.error_code, record.error_params) == ("link_broke", {})


async def test_a_wrong_level_on_read_back_names_the_channel_and_the_level(rig):
    rig.sim.ignore_writes = True
    record = await light(rig, level=40)
    assert record.error == "read-back level differs from 40"
    assert record.error_code == "readback_level"
    assert record.error_params == {"channel": "light", "expected": 40}


async def test_a_read_back_that_cannot_be_read_says_so(rig):
    failing(rig, "getDevSta", ConnectionError("gone"))
    record = await light(rig)
    assert record.error.startswith("read-back unavailable")
    assert (record.error_code, record.error_params) == ("readback_unavailable", {})


async def test_a_wrong_mode_on_read_back_carries_the_mode_as_a_number(rig):
    rig.service.device.modes_from = lambda config: {Channel.LIGHT: 1}
    record = await light(rig)
    assert record.error == "read-back mode is 1, expected 0"
    assert (record.error_code, record.error_params) == ("readback_mode", {"mode": 1})


async def test_an_unexpected_exception_is_an_internal_error_with_english_text_only(rig):
    async def boom(channel, level):
        raise RuntimeError("bad")

    rig.service.device.write = boom
    record = await light(rig)
    assert record.state is ActionState.UNKNOWN and record.error == "RuntimeError: bad"
    assert (record.error_code, record.error_params) == ("internal_error", {})


async def test_a_confirmed_write_has_no_code(rig):
    record = await light(rig)
    assert (record.error, record.error_code, record.error_params) == (None, None, {})


# --- voided and unsettled actions -------------------------------------------------------------


async def queued_behind_a_hung_write(rig, number):
    release = hang_first_field_write(rig)
    first = await hold_a(rig, number)
    second = asyncio.create_task(rig.service.submit(rig.request(number, Channel.EXHAUST, 40, "b")))
    await wait_for(lambda: rig.service.receipt("b") is not None)
    return release, first, second


async def finish(release, first, second):
    release.set()
    await asyncio.gather(first, second, return_exceptions=True)


async def test_a_recovery_bump_voids_with_its_code(rig):
    number = rig.stage_right()
    parts = await queued_behind_a_hung_write(rig, number)
    rig.service.bump_recovery("restore")
    record = rig.service.receipt("b")
    assert record.state is ActionState.VOID and record.error == "recovery number changed"
    assert (record.error_code, record.error_params) == ("void_recovery_changed", {})
    await finish(*parts)


async def test_a_hand_over_voids_with_its_code(rig):
    number = rig.stage_right()
    parts = await queued_behind_a_hung_write(rig, number)
    handover = asyncio.create_task(rig.service.handover(number, "ended"))
    await wait_for(lambda: rig.service.receipt("b").state is ActionState.VOID)
    record = rig.service.receipt("b")
    assert record.error == "hand-over: ended"
    assert (record.error_code, record.error_params) == ("void_handover", {})
    await finish(*parts)
    await handover


async def test_a_protection_write_supersedes_a_queued_write_with_the_channel(rig):
    number = rig.stage_right()
    rig.service.approve_safety(make_safety(), "alice")
    protection = rig.service.protection_right()
    release = hang_first_field_write(rig)
    first = await hold_a(rig, number)
    queued = asyncio.create_task(rig.service.submit(rig.request(number, Channel.LIGHT, 3, "b")))
    await wait_for(lambda: rig.service.receipt("b") is not None)
    urgent = asyncio.create_task(rig.service.submit(rig.request(protection, Channel.LIGHT, 0, "p")))
    await wait_for(lambda: rig.service.receipt("p") is not None)
    record = rig.service.receipt("b")
    assert record.error == "superseded by a protection write on light"
    assert record.error_code == "void_superseded"
    assert record.error_params == {"channel": "light"}
    release.set()
    await asyncio.gather(first, urgent, queued, return_exceptions=True)


async def test_a_queued_write_refused_at_the_gate_is_voided_with_the_denied_code(rig):
    number = rig.stage_right()
    release, first, second = await queued_behind_a_hung_write(rig, number)
    rig.service.ledger.revoke(number, rig.clock.now())  # no void: the re-check refuses it
    release.set()
    await asyncio.gather(first, second, return_exceptions=True)
    record = rig.service.receipt("b")
    assert record.state is ActionState.VOID
    assert record.error_code == "void_denied"
    assert record.error_params == {"denied_code": "right_invalid"}


async def test_a_restart_voids_queued_and_loses_the_receipt_of_the_sent(rig, restart):
    number = rig.stage_right()
    release, first, second = await queued_behind_a_hung_write(rig, number)
    for task in (first, second):
        task.cancel()
    await asyncio.gather(first, second, return_exceptions=True)
    fresh = restart()
    await fresh.startup()
    lost, queued = fresh.receipt("a"), fresh.receipt("b")
    assert lost.error == "process stopped before the receipt was stored; not replayed"
    assert (lost.error_code, lost.error_params) == ("lost_receipt", {})
    assert queued.error == "process stopped before the action was sent"
    assert (queued.error_code, queued.error_params) == ("void_restart", {})
    release.set()


async def settle_after_losing(rig, change=None):
    rig.sim.lose_replies = True
    number = rig.stage_right()
    await rig.service.submit(rig.request(number, Channel.LIGHT, 40, "lost"))
    rig.sim.lose_replies = False
    if change:
        rig.sim.external_change("device", "light", mLevel=10)
    await rig.service.reconcile_unsettled()
    return rig.service.receipt("lost")


async def test_a_reconcile_that_finds_the_write_applied_says_so(rig):
    record = await settle_after_losing(rig)
    assert "applied" in record.error
    assert record.error_code == "settled_applied"
    assert record.error_params == {"channel": "light", "level": 40}


async def test_a_reconcile_that_finds_it_not_applied_names_the_level_and_mode(rig):
    record = await settle_after_losing(rig, change=True)
    assert "not applied" in record.error
    assert record.error_code == "settled_not_applied"
    assert record.error_params == {"channel": "light", "level": 10, "mode": 0}


# --- the pump ---------------------------------------------------------------------------------


async def test_a_pump_off_that_never_confirmed_says_so(rig):
    number = rig.manual_right()
    rig.sim.fail_off = True
    record = await rig.service.irrigate(rig.request(number, Channel.PUMP, 1, "i"), 0.02)
    assert record.state is ActionState.UNKNOWN
    assert record.error == "pump off unconfirmed; interlock set"
    assert (record.error_code, record.error_params) == ("pump_off_unconfirmed", {})


# --- early ends -------------------------------------------------------------------------------


async def test_a_hand_over_ends_a_run_with_the_handover_code(rig):
    stage = rig.stage_right(channels=HOSTED)
    record = await _cut_short(rig, stage, lambda: rig.service.handover(stage, "paused"))
    assert record.ended_early == "hand-over: paused"
    assert (record.ended_early_code, record.ended_early_params) == ("handover", {})


async def test_a_protection_write_ends_a_run_with_its_channel(rig):
    stage = rig.stage_right(channels=HOSTED)
    rig.service.approve_safety(make_safety(), "alice")
    protection = rig.service.protection_right()
    record = await _cut_short(
        rig,
        stage,
        lambda: rig.service.submit(rig.request(protection, Channel.LIGHT, 0, "p")),
    )
    assert record.ended_early == "protection write: test"
    assert record.ended_early_code == "protection_write"
    assert record.ended_early_params == {"channel": "light"}


@pytest.mark.parametrize(
    ("trigger", "code"), [("interlock", "pump_off_interlock"), ("watchdog", "pump_off_watchdog")]
)
async def test_the_pump_off_path_ends_a_run_with_its_trigger_code(rig, trigger, code):
    stage = rig.stage_right(channels=HOSTED)
    record = await _cut_short(rig, stage, lambda: rig.service.pump_off(trigger=trigger))
    assert record.ended_early == f"pump switched off ({trigger})"
    assert (record.ended_early_code, record.ended_early_params) == (code, {})


async def test_a_cycle_ended_without_a_reason_is_other(rig):
    event = asyncio.Event()
    event.set()
    update = await rig.service._hold(event, 1.0)
    assert update["ended_early"] == "ended early"
    assert update["ended_early_code"] == "other" and update["ended_early_params"] == {}


async def test_a_full_run_has_no_early_end_code(rig):
    number = rig.manual_right()
    record = await rig.service.irrigate(rig.request(number, Channel.PUMP, 1, "i"), 0.02)
    assert record.ended_early is None and record.ended_early_code is None


# --- old data ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("state", "error", "code", "nothing"),
    [
        (ActionState.FAILED, "not sent: x", "not_sent", True),
        (ActionState.FAILED, "anything", "not_sent", True),
        (ActionState.FAILED, "anything", "device_rejected", True),
        (ActionState.FAILED, "not sent: x", "readback_level", False),
        (ActionState.UNKNOWN, "no receipt", "no_receipt", False),
        (ActionState.VOID, None, "void_handover", True),
        (ActionState.FAILED, "not sent: offline", None, True),
        (ActionState.FAILED, "Device rejected: code 500", None, True),
        (ActionState.FAILED, "read-back level differs from 1", None, False),
    ],
)
def test_changed_nothing_reads_the_code_and_still_knows_old_records(state, error, code, nothing):
    assert changed_nothing(state, error, code) is nothing


OLD_ACTION = (
    '{"request_id": "old", "state": "failed", "channel": "light", "planned_level": 40,'
    ' "right_number": 1, "right_kind": "stage", "trigger": "t", "created_at": 1.0,'
    ' "error": "not sent: offline"}'
)


def test_an_action_record_without_the_new_fields_still_reads():
    record = ActionRecord.model_validate_json(OLD_ACTION)
    assert record.error == "not sent: offline"
    assert record.error_code is None and record.error_params == {}
    assert record.ended_early_code is None and record.ended_early_params == {}
