"""Runtime behaviour on the simulated device: no model, restart, unregistered host, tick faults."""

import sys

import pytest
from e2e_support import STAGE

from growbridge.archive.models import Channel
from growbridge.ports import ActionRequest, Denied
from growbridge.workflow.states import RoundState, StageState


async def test_approved_stage_keeps_executing_without_any_model_client(world, monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)  # importing a model client would fail
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    runtime = await world.boot()
    _project, round_id = await world.approved_stage(runtime)

    await world.beat(runtime, 30)
    assert (await runtime.control.read_state()).levels[Channel.LIGHT] == 60
    assert runtime.workflow.stage(STAGE).state is StageState.RUNNING

    await world.run_until_ended(runtime)
    assert runtime.workflow.stage(STAGE).state is StageState.ENDED
    assert runtime.workflow.round_state(round_id) is RoundState.DATA_VERIFICATION
    assert (await runtime.control.read_state()).levels[Channel.LIGHT] == 0  # the end action


async def test_restart_enters_recovery_check_then_the_operator_resumes(world):
    first = await world.boot()
    await world.approved_stage(first)
    await world.beat(first, 30)
    assert first.workflow.stage(STAGE).state is StageState.RUNNING
    await first.stop()

    world.clock.advance(5)
    second = await world.boot()
    stage = second.workflow.stage(STAGE)
    assert stage.state is StageState.RECOVERY_CHECK
    assert stage.prior_state is StageState.RUNNING
    assert stage.right_number is None  # every write right of the old process is void

    await world.beat(second, 1)  # transport stop confirmed, read-back matches the run sheet
    assert second.control.transport_stopped()
    assert second.workflow.stage(STAGE).state is StageState.PAUSED

    resumed = await second.workflow.resume_stage(STAGE, world.operator)
    assert resumed.state is StageState.RUNNING
    assert resumed.right_number is not None


async def test_unconfirmed_transport_keeps_the_stage_in_recovery_check(world):
    first = await world.boot()
    await world.approved_stage(first)
    await first.stop()

    world.sim.halt_confirmed = False
    second = await world.boot()
    await world.beat(second, 1)
    assert not second.control.transport_stopped()
    assert second.workflow.stage(STAGE).state is StageState.RECOVERY_CHECK


async def test_unregistered_host_opens_no_ble_connection_and_writes_are_denied(world):
    runtime = await world.boot(register=False)

    assert world.sim.connected is False
    assert world.sim.commands == []
    assert runtime.bridge.task is None
    assert not runtime.control.host_registered()
    assert [a.key for a in runtime.book.open() if a.kind == "runtime"] == ["write_host"]

    await runtime.bridge.start()  # the HTTP lifespan starts the bridge too: still refused
    assert runtime.bridge.task is None and world.sim.connected is False

    request = ActionRequest(
        request_id="r-1", right_number=1, channel=Channel.LIGHT, level=50, trigger="test"
    )
    with pytest.raises(Denied):
        await runtime.control.submit(request)
    assert world.sim.commands == []


def spy(monkeypatch, owner, name, calls, is_async):
    original = getattr(owner, name)

    async def wrapped_async(*args, **kwargs):
        calls.append(name)
        return await original(*args, **kwargs)

    def wrapped_sync(*args, **kwargs):
        calls.append(name)
        return original(*args, **kwargs)

    monkeypatch.setattr(owner, name, wrapped_async if is_async else wrapped_sync)


@pytest.mark.parametrize("broken", ["archive", "observer"])
async def test_failing_tick_step_raises_an_alert_and_later_steps_still_run(
    world, monkeypatch, broken
):
    runtime = await world.boot()
    await world.approved_stage(runtime)
    calls: list[str] = []

    def failing(*_args, **_kwargs):
        raise RuntimeError("synthetic failure")

    async def failing_async(*_args, **_kwargs):
        raise RuntimeError("synthetic failure")

    if broken == "archive":
        monkeypatch.setattr(runtime.archive, "ingest", failing)
    else:
        monkeypatch.setattr(runtime.observer, "tick", failing_async)
    spy(monkeypatch, runtime.executor, "tick", calls, True)
    spy(monkeypatch, runtime.outbox, "deliver", calls, True)
    spy(monkeypatch, runtime.tasks, "expire", calls, False)

    await world.beat(runtime, 30)

    alerts = [a for a in runtime.book.open() if a.kind == "tick_step"]
    assert [a.key for a in alerts] == [broken]
    assert "synthetic failure" in alerts[0].message
    assert {"tick", "deliver", "expire"} <= set(calls)
    assert (await runtime.control.read_state()).levels[Channel.LIGHT] == 60
