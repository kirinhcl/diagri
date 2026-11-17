"""The refusals of the workflow store, the permission checks and the recovery check carry a
registered reason and params; the coarse code and the English message stay as they were."""

import pytest

from growbridge.ports import Actor, Denied
from growbridge.workflow.permissions import REAUTH_SECONDS, require_kind, require_operator


def refused_now(call, code: str) -> Denied:
    with pytest.raises(Denied) as exc:
        call()
    assert exc.value.code == code
    return exc.value


def test_record_not_found_carries_the_round_kind_and_id(world):
    exc = refused_now(lambda: world.svc.store.round("ghost"), "state")
    assert exc.reason == "record_not_found"
    assert exc.params == {"record_kind": "round", "record_id": "ghost"}


def test_record_not_found_carries_the_run_sheet_kind_and_id(world):
    exc = refused_now(lambda: world.svc.store.run_sheet("ghost", 3), "state")
    assert exc.reason == "record_not_found"
    assert exc.params == {"record_kind": "run_sheet", "record_id": "ghost"}


def test_record_not_found_carries_the_stage_kind_and_id(world):
    exc = refused_now(lambda: world.svc.store.stage("ghost"), "state")
    assert exc.reason == "record_not_found"
    assert exc.params == {"record_kind": "stage", "record_id": "ghost"}


async def test_stage_changed_concurrently_carries_the_stage_of_a_stale_update(world):
    await world.pending()
    stale = world.svc.store.stage("stage-1")
    world.svc.store.update_stage(stale, paused_at=1.0)
    exc = refused_now(lambda: world.svc.store.update_stage(stale, paused_at=2.0), "state")
    assert exc.reason == "stage_changed_concurrently" and exc.params == {"stage_id": "stage-1"}


def test_model_no_controls_carries_the_model_role(world):
    exc = refused_now(
        lambda: require_kind(Actor(kind="model", id="planner"), ("operator",)), "model_role"
    )
    assert exc.reason == "model_no_controls" and exc.params == {"role": "planner"}


def test_not_operator_carries_no_params_for_another_identity(world):
    exc = refused_now(
        lambda: require_kind(Actor(kind="probe", id="p"), ("operator",)), "not_operator"
    )
    assert exc.reason == "not_operator" and exc.params == {}


def test_reauth_required_carries_no_params(world):
    stale = Actor(kind="operator", id="op", reauth_at=0.0)
    exc = refused_now(
        lambda: require_operator(stale, REAUTH_SECONDS + 1, recent=True), "reauth_required"
    )
    assert exc.reason == "reauth_required" and exc.params == {}


async def test_onsite_check_not_open_carries_the_stage_and_its_state(world):
    await world.running()
    with pytest.raises(Denied) as exc:
        await world.svc.record_onsite_check("stage-1", world.op, "looked")
    assert exc.value.code == "state" and exc.value.reason == "onsite_check_not_open"
    assert exc.value.params == {"stage_id": "stage-1", "state": "running"}
