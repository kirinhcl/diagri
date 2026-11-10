import asyncio

import pytest

from growbridge.archive.models import ActionState, Channel
from growbridge.ports import Denied
from growbridge.sim.fixtures import make_safety

PUMP_ON = 0.6  # long enough to notice a gate held through the whole run


async def wait_for(predicate, attempts=200):
    for _ in range(attempts):
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition not reached")


def pump_on(rig):
    return rig.sim.config["outlet"]["O4"]["mOnOff"] == 1


async def start_irrigation(rig, request_id="irrigation-1", seconds=PUMP_ON):
    number = rig.manual_right()
    task = asyncio.create_task(
        rig.service.irrigate(rig.request(number, Channel.PUMP, 1, request_id), seconds)
    )
    await wait_for(lambda: pump_on(rig))
    await asyncio.sleep(0.05)
    return number, task


# --- reconcile_unsettled ----------------------------------------------------------------------


async def lose(rig, level=40, request_id="lost"):
    rig.sim.lose_replies = True
    number = rig.stage_right()
    record = await rig.service.submit(rig.request(number, Channel.LIGHT, level, request_id))
    rig.sim.lose_replies = False
    assert record.state is ActionState.UNKNOWN
    return number


async def test_control_reconcile_settles_applied_unknown_action_and_unblocks_writes(rig):
    number = await lose(rig)
    with pytest.raises(Denied) as error:
        await rig.service.submit(rig.request(number, Channel.LIGHT, 10))
    assert error.value.code == "unsettled"
    assert await rig.service.reconcile_unsettled() == ()
    settled = rig.service.receipt("lost")
    assert settled.state is ActionState.UNKNOWN  # history is kept; the settlement is added
    assert settled.settled_at == rig.clock.now() and "applied" in settled.error
    assert "not applied" not in settled.error
    assert rig.sink.actions[-1] == settled
    after = await rig.service.submit(rig.request(number, Channel.LIGHT, 10))
    assert after.state is ActionState.CONFIRMED


async def test_control_reconcile_records_not_applied_when_device_differs(rig):
    await lose(rig)
    rig.sim.external_change("device", "light", mLevel=10)
    assert await rig.service.reconcile_unsettled() == ()
    assert "not applied" in rig.service.receipt("lost").error


async def test_control_reconcile_waits_for_stopped_transport_and_fresh_data(rig):
    await lose(rig)
    rig.sim.halt_confirmed = False
    await rig.service.confirm_transport_stopped()
    assert [r.request_id for r in await rig.service.reconcile_unsettled()] == ["lost"]
    rig.sim.halt_confirmed = True
    await rig.service.confirm_transport_stopped()
    rig.clock.advance(100)  # telemetry is stale
    assert [r.request_id for r in await rig.service.reconcile_unsettled()] == ["lost"]
    await rig.refresh()
    assert await rig.service.reconcile_unsettled() == ()


async def test_control_reconcile_never_settles_pump_actions(rig):
    rig.sim.fail_off = True
    number = rig.manual_right()
    await rig.service.irrigate(rig.request(number, Channel.PUMP, 1, "pump-1"), 0.02)
    rig.sim.fail_off = False
    left = await rig.service.reconcile_unsettled()
    assert [r.request_id for r in left] == ["pump-1"]
    assert rig.service.interlocked()


# --- irrigation concurrency -------------------------------------------------------------------


async def test_control_concurrent_irrigations_respect_cooldown(rig, settings):
    rig.bridge.settings = settings.model_copy(update={"pump_cooldown_seconds": 60})
    number = rig.manual_right()
    calls = [
        rig.service.irrigate(rig.request(number, Channel.PUMP, 1, f"i{n}"), 0.02) for n in range(3)
    ]
    results = await asyncio.gather(*calls, return_exceptions=True)
    done = [r for r in results if not isinstance(r, Exception)]
    denied = [r for r in results if isinstance(r, Denied)]
    assert len(done) == 1 and len(denied) == 2
    assert {d.code for d in denied} == {"cooldown"}
    assert [c["params"]["O4"]["mOnOff"] for c in rig.writes()] == [1, 0]


async def test_control_concurrent_irrigations_without_cooldown_do_not_overlap(rig):
    number = rig.manual_right()
    calls = [
        rig.service.irrigate(rig.request(number, Channel.PUMP, 1, f"i{n}"), 0.02) for n in range(3)
    ]
    await asyncio.gather(*calls, return_exceptions=True)
    switches = [c["params"]["O4"]["mOnOff"] for c in rig.writes()]
    assert switches == [1, 0] * (len(switches) // 2)  # runs never overlap
    assert switches[-1] == 0 and not pump_on(rig)


async def test_control_second_pump_start_is_refused_while_a_cycle_runs(rig):
    number, task = await start_irrigation(rig)
    with pytest.raises(Denied) as error:
        await rig.service.irrigate(rig.request(number, Channel.PUMP, 1, "second"), 0.02)
    assert error.value.code == "cooldown"
    assert [c["params"]["O4"]["mOnOff"] for c in rig.writes()] == [1]
    await rig.service.pump_off()
    assert (await task).state is ActionState.CONFIRMED


async def test_control_irrigation_does_not_hold_the_gate_while_pump_runs(rig):
    protection = rig.service.approve_safety(make_safety(), "alice")
    loop = asyncio.get_running_loop()
    _, task = await start_irrigation(rig)
    began = loop.time()
    dimmed = await asyncio.wait_for(
        rig.service.submit(rig.request(protection, Channel.LIGHT, 0)), timeout=0.3
    )
    assert dimmed.state is ActionState.CONFIRMED
    record = await asyncio.wait_for(task, timeout=0.5)
    assert loop.time() - began < PUMP_ON - 0.1  # the protection write ended the run early
    assert record.state is ActionState.CONFIRMED
    assert not pump_on(rig) and rig.service.interlocked() is False


async def test_control_handover_ends_a_pump_run_early(rig):
    number, task = await start_irrigation(rig)
    loop = asyncio.get_running_loop()
    began = loop.time()
    await asyncio.wait_for(rig.service.handover(number, "takeover ended"), timeout=0.3)
    record = await asyncio.wait_for(task, timeout=0.5)
    assert loop.time() - began < PUMP_ON - 0.1
    assert record.state is ActionState.CONFIRMED and not pump_on(rig)


async def test_control_pump_off_ends_a_run_early(rig):
    _, task = await start_irrigation(rig)
    assert await rig.service.pump_off() is True
    assert (await asyncio.wait_for(task, timeout=0.5)).state is ActionState.CONFIRMED
    assert not pump_on(rig)


# --- recovery number --------------------------------------------------------------------------


async def test_control_recovery_bump_unconfirms_transport_and_rechecks_in_gate(rig):
    number = rig.stage_right()
    release = asyncio.Event()
    original = rig.sim.send

    async def slow(command):
        if command["method"] == "setConfigField":
            await release.wait()
        await original(command)

    rig.sim.send = slow
    first = asyncio.create_task(rig.service.submit(rig.request(number, Channel.LIGHT, 50, "a")))
    await wait_for(lambda: rig.service.receipt("a") is not None)
    await wait_for(lambda: rig.service.receipt("a").state is ActionState.MAYBE_SENT)
    second = asyncio.create_task(rig.service.submit(rig.request(number, Channel.EXHAUST, 40, "b")))
    await wait_for(lambda: rig.service.receipt("b") is not None)
    rig.service.bump_recovery("restore")
    assert rig.service.transport_stopped() is False
    release.set()
    assert (await first).state is ActionState.CONFIRMED  # already on its way
    with pytest.raises(Denied) as error:
        await second
    assert error.value.code == "right_invalid"
    assert rig.service.receipt("b").state is ActionState.VOID
    new = rig.stage_right(stage_id="stage-2")
    with pytest.raises(Denied) as error:
        await rig.service.submit(rig.request(new, Channel.LIGHT, 10))
    assert error.value.code == "unsettled"  # until the old transport is confirmed again
    await rig.service.confirm_transport_stopped()
    record = await rig.service.submit(rig.request(new, Channel.LIGHT, 10))
    assert record.state is ActionState.CONFIRMED


# --- pump_off ledger record -------------------------------------------------------------------


async def test_control_pump_off_leaves_an_audit_record_linked_to_the_pump_action(rig):
    rig.sim.fail_off = True
    number = rig.manual_right()
    await rig.service.irrigate(rig.request(number, Channel.PUMP, 1, "pump-1"), 0.02)
    rig.sim.fail_off = False
    assert await rig.service.pump_off() is True
    record = [r for r in rig.sink.actions if r.trigger == "interlock"][-1]
    assert record.trigger == "interlock" and record.channel is Channel.PUMP
    assert record.planned_level == 0 and record.state is ActionState.CONFIRMED
    assert record.supersedes == "pump-1"
    assert rig.service.receipt(record.request_id) == record


async def test_control_failed_pump_off_is_recorded_too(rig):
    rig.sim.fail_off = True
    number = rig.manual_right()
    await rig.service.irrigate(rig.request(number, Channel.PUMP, 1, "pump-1"), 0.02)
    assert await rig.service.pump_off() is False
    record = [r for r in rig.sink.actions if r.trigger == "interlock"][-1]
    assert record.trigger == "interlock" and record.state is ActionState.UNKNOWN
    assert record.supersedes == "pump-1"
