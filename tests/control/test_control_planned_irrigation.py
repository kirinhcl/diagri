"""A planned irrigation: a run sheet's irrigation task, started by the operator under the stage
right while the stage keeps running. Every other irrigation check still applies."""

import pytest
from test_control_interlock import PUMP_SECONDS

from growbridge.archive.models import ActionState, Channel
from growbridge.ports import Denied

HOSTED = (Channel.LIGHT, Channel.PUMP)  # the workflow grants every host-controlled channel


def planned(rig, number, stage_id="stage-1", request_id=None):
    return rig.request(number, Channel.PUMP, 1, request_id, stage_id=stage_id, operator="alice")


async def test_a_planned_irrigation_runs_under_the_stage_right_and_switches_off(rig):
    stage = rig.stage_right(channels=HOSTED)

    record = await rig.service.irrigate(planned(rig, stage), PUMP_SECONDS, planned=True)

    assert record.state is ActionState.CONFIRMED and record.right_number == stage
    assert [c["params"]["O4"]["mOnOff"] for c in rig.writes()] == [1, 0]
    assert rig.service.interlocked() is False and rig.service.irrigating() is False


async def test_the_stage_right_still_cannot_irrigate_unless_it_is_planned(rig):
    stage = rig.stage_right(channels=HOSTED)

    with pytest.raises(Denied) as error:
        await rig.service.irrigate(planned(rig, stage), PUMP_SECONDS)

    assert error.value.code == "right_invalid" and rig.writes() == []


async def test_a_planned_irrigation_must_name_the_rights_own_stage(rig):
    stage = rig.stage_right(channels=HOSTED)

    for request in (planned(rig, stage, stage_id="stage-2"), planned(rig, stage, stage_id=None)):
        with pytest.raises(Denied):
            await rig.service.irrigate(request, PUMP_SECONDS, planned=True)

    assert rig.writes() == []


async def test_a_planned_irrigation_keeps_the_time_limit_and_the_cooldown(rig, settings):
    stage = rig.stage_right(channels=HOSTED)
    too_long = settings.max_pump_seconds + 1

    with pytest.raises(Denied) as error:
        await rig.service.irrigate(planned(rig, stage), too_long, planned=True)
    assert error.value.code == "scope"

    await rig.service.irrigate(planned(rig, stage), PUMP_SECONDS, planned=True)
    if settings.pump_cooldown_seconds > 0:
        with pytest.raises(Denied) as error:
            await rig.service.irrigate(planned(rig, stage), PUMP_SECONDS, planned=True)
        assert error.value.code == "cooldown"


async def test_a_planned_request_id_cannot_be_replayed_as_another_kind_of_run(rig):
    stage = rig.stage_right(channels=HOSTED)
    request = planned(rig, stage, request_id="planned-1")
    await rig.service.irrigate(request, PUMP_SECONDS, planned=True)

    with pytest.raises(Denied) as error:
        await rig.service.irrigate(request, PUMP_SECONDS)

    assert error.value.code == "request_id_reused"
