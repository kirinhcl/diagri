"""A stage that stops by itself tells the operator why: an alert, and a notification."""

from e2e_support import ROUND_LIGHT, STAGE, RecordingChannel

from growbridge.workflow.states import StageState

KIND = "stage_waiting"


def stage_alerts(runtime):
    return [alert for alert in runtime.book.open() if alert.kind == KIND]


async def running_stage(world, **options):
    runtime = await world.boot(**options)
    await world.approved_stage(runtime)
    await world.beat(runtime, 30)  # the stage has applied its levels: light 60
    assert runtime.workflow.stage(STAGE).state is StageState.RUNNING
    assert stage_alerts(runtime) == []
    return runtime


async def test_stage_paused_by_a_panel_change_raises_an_alert_that_says_why(world):
    channel = RecordingChannel()
    runtime = await running_stage(world, channels={"telegram": channel})

    world.sim.external_change("device", "light", mLevel=5)
    await world.beat(runtime, 1)

    assert runtime.workflow.stage(STAGE).state is StageState.PAUSED
    (alert,) = stage_alerts(runtime)
    assert alert.severity == "warning"
    assert STAGE in alert.message and "external_change" in alert.message
    assert '"channel": "light"' in alert.message and '"actual": 5' in alert.message
    (waiting,) = runtime.workflow.waiting_stages()
    assert alert.code == "stage_waiting"
    assert set(alert.params) == {"stage_id", "entry_id", "state", "event", "detail"}
    assert alert.params["stage_id"] == STAGE
    assert alert.params["entry_id"] == waiting["entry"]
    assert (alert.params["state"], alert.params["event"]) == ("paused", "external_change")
    assert alert.params["detail"] == waiting["detail"]
    assert alert.params["detail"] and "external_change" not in alert.params["detail"]
    await world.beat(runtime, 1)  # the outbox delivers on the next tick
    assert [text for text in channel.sent if "external_change" in text] == [
        f"[warning] {alert.message}"
    ]


async def test_stage_alert_is_resolved_when_the_operator_resumes_the_stage(world):
    runtime = await running_stage(world, channels={})
    world.sim.external_change("device", "light", mLevel=5)
    await world.beat(runtime, 1)
    assert len(stage_alerts(runtime)) == 1

    world.sim.external_change("device", "light", mLevel=ROUND_LIGHT[1])  # set back
    await world.beat(runtime, 1)
    await runtime.workflow.resume_stage(STAGE, world.operator)
    await world.beat(runtime, 1)

    assert runtime.workflow.stage(STAGE).state is StageState.RUNNING
    assert stage_alerts(runtime) == []


async def test_stage_paused_by_a_clock_step_raises_an_alert_naming_the_clock(world):
    runtime = await running_stage(world, channels={})

    world.clock.jump(30)
    await world.beat(runtime, 1)

    (alert,) = stage_alerts(runtime)
    assert "clock_anomaly" in alert.message


async def test_stage_paused_by_the_operator_raises_no_stage_alert(world):
    runtime = await running_stage(world, channels={})

    await runtime.workflow.pause_stage(STAGE, world.operator, "checking the tent")
    await world.beat(runtime, 1)

    assert runtime.workflow.stage(STAGE).state is StageState.PAUSED
    assert stage_alerts(runtime) == []


async def test_stage_held_in_recovery_check_after_a_restart_raises_a_critical_alert(world):
    first = await running_stage(world, channels={})
    await first.stop()

    world.sim.halt_confirmed = False  # the old write path cannot be confirmed stopped
    second = await world.boot(channels={})
    await world.beat(second, 1)

    assert second.workflow.stage(STAGE).state is StageState.RECOVERY_CHECK
    (alert,) = stage_alerts(second)
    assert alert.severity == "critical"
    assert "recovery_check" in alert.message and "restart" in alert.message


async def test_stage_paused_after_the_recovery_check_keeps_an_alert_until_it_is_resumed(world):
    first = await running_stage(world, channels={})
    await first.stop()

    second = await world.boot(channels={})
    await world.beat(second, 1)

    assert second.workflow.stage(STAGE).state is StageState.PAUSED
    (alert,) = stage_alerts(second)
    assert alert.severity == "warning" and "recovery_exit" in alert.message

    await second.workflow.resume_stage(STAGE, world.operator)
    await world.beat(second, 1)
    assert stage_alerts(second) == []


async def test_runtime_alert_passes_code_and_params_through(world):
    runtime = await world.boot(channels={})

    runtime.alert("probe", "k", "m", code="probe_code", params={"n": 1})
    assert runtime._alert("probe2", "k", "m", code="c2", params={"n": 2}) is True

    found = {a.kind: (a.code, a.params) for a in runtime.book.open()}
    assert found["probe"] == ("probe_code", {"n": 1})
    assert found["probe2"] == ("c2", {"n": 2})
