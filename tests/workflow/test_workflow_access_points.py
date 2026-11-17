"""Owner and lock-holder checks at every workflow entry that acts on a project or a stage."""

import pytest
from access_support import People

from growbridge.ports import Actor, Denied
from growbridge.sim.fixtures import make_protocol


@pytest.fixture
def people(world) -> People:
    return People(world)


def _hidden(error: Denied, what: str) -> None:
    assert error.code == "state" and str(error).startswith(f"unknown {what}")


# --- design --------------------------------------------------------------------------------------


def test_owner_designs_and_others_do_not_see_the_project(world, people):
    round_id = people.design()

    with pytest.raises(Denied) as denied:
        world.svc.create_round(world.project_id, "protocol-1", people.bob)
    _hidden(denied.value, "project")
    with pytest.raises(Denied) as denied:
        protocol = make_protocol(project_id=world.project_id, id="protocol-x")
        world.svc.save_protocol(protocol, people.bob)
    _hidden(denied.value, "project")
    with pytest.raises(Denied) as denied:
        world.svc.create_round(world.project_id, "protocol-1", people.root)
    assert denied.value.code == "not_owner"
    assert round_id


async def test_round_choice_and_abort_need_the_owner(world, people):
    await people.running()
    await world.svc.stop_stage("stage-1", people.alice)

    for call in (
        lambda: world.svc.choose_after_stop(world.round_id, "redo", people.bob),
        lambda: world.svc.abort_round(world.round_id, people.bob),
    ):
        with pytest.raises(Denied) as denied:
            await call()
        _hidden(denied.value, "round")
    assert await world.svc.choose_after_stop(world.round_id, "redo", people.alice)


# --- run sheets ----------------------------------------------------------------------------------


def test_a_draft_needs_the_owner_to_hold_the_sheets_greenhouse(world, people):
    people.design()

    with pytest.raises(Denied) as denied:  # alice has not locked gh-01 yet
        world.svc.submit_run_sheet(world.round_id, world.sheet("stage-1"), people.alice)
    assert denied.value.code == "not_lock_holder"
    assert world.svc.store.find_stage("stage-1") is None

    people.locks.lock("alice", ["gh-01"])
    world.svc.submit_run_sheet(world.round_id, world.sheet("stage-1"), people.alice)


def test_model_draft_needs_owner_lock(world, people):
    people.design()
    planner = Actor(kind="model", id="planner")

    with pytest.raises(Denied) as denied:
        world.svc.submit_run_sheet(world.round_id, world.sheet("stage-1"), planner)
    assert denied.value.code == "not_lock_holder"

    people.locks.lock("alice", ["gh-01"])
    world.svc.submit_run_sheet(world.round_id, world.sheet("stage-1"), planner)


def test_another_user_cannot_draft_into_the_project(world, people):
    people.design()
    people.locks.lock("bob", ["gh-01"])

    with pytest.raises(Denied) as denied:
        world.svc.submit_run_sheet(world.round_id, world.sheet("stage-1"), people.bob)
    _hidden(denied.value, "round")


# --- stage actions -------------------------------------------------------------------------------


async def test_owner_with_the_lock_drives_the_stage(world, people):
    await people.running()
    alice = people.alice

    await world.svc.pause_stage("stage-1", alice, "look")
    await world.svc.resume_stage("stage-1", alice)
    await world.svc.takeover("stage-1", alice)
    await world.svc.handback("stage-1", alice, False)
    await world.svc.stop_stage("stage-1", alice)

    assert world.state("stage-1") == "stopped"


STAGE_CALLS = {
    "approve": lambda svc, who: svc.approve("stage-1", who),
    "revoke": lambda svc, who: svc.revoke_approval("stage-1", who),
    "start": lambda svc, who: svc.start_stage("stage-1", who),
}
LIVE_CALLS = {
    "pause": lambda svc, who: svc.pause_stage("stage-1", who, "x"),
    "resume": lambda svc, who: svc.resume_stage("stage-1", who),
    "takeover": lambda svc, who: svc.takeover("stage-1", who),
    "stop": lambda svc, who: svc.stop_stage("stage-1", who),
    "onsite": lambda svc, who: svc.record_onsite_check("stage-1", who, "checked"),
}


async def _call(call, svc, who):
    result = call(svc, who)
    if hasattr(result, "__await__"):
        await result


@pytest.mark.parametrize("name", sorted(STAGE_CALLS))
async def test_another_user_cannot_act_on_a_pending_stage(world, people, name):
    people.pending()
    if name in ("revoke", "start"):
        world.svc.approve("stage-1", people.alice)

    with pytest.raises(Denied) as denied:
        await _call(STAGE_CALLS[name], world.svc, people.bob)
    _hidden(denied.value, "stage")


@pytest.mark.parametrize("name", sorted(LIVE_CALLS))
async def test_another_user_cannot_act_on_a_running_stage(world, people, name):
    await people.running()
    if name == "resume":
        await world.svc.pause_stage("stage-1", people.alice, "x")

    with pytest.raises(Denied) as denied:
        await _call(LIVE_CALLS[name], world.svc, people.bob)
    _hidden(denied.value, "stage")
    assert ("reconcile",) not in world.control.log[-1:]


async def test_onsite_check_by_other_has_no_control_effects(world, people):
    await people.running()
    before = list(world.control.log)

    with pytest.raises(Denied):
        await world.svc.record_onsite_check("stage-1", people.bob, "x")

    assert world.control.log == before


async def test_owner_without_the_lock_is_told_so(world, people):
    people.pending()
    world.svc.store.db.execute("DELETE FROM greenhouse_locks")  # the lock is gone

    with pytest.raises(Denied) as denied:
        world.svc.approve("stage-1", people.alice)
    assert denied.value.code == "not_lock_holder"


async def test_admin_can_stop_but_not_approve(world, people):
    people.pending()

    with pytest.raises(Denied) as denied:
        world.svc.approve("stage-1", people.root)
    assert denied.value.code == "not_owner"

    world.svc.approve("stage-1", people.alice)
    await world.svc.start_stage("stage-1", people.alice)
    await world.svc.pause_stage("stage-1", people.root, "emergency")
    await world.svc.stop_stage("stage-1", people.root)
    assert world.state("stage-1") == "stopped"


async def test_refusal_not_swallowed_by_apply_once(world, people):
    people.pending()
    world.svc.approve("stage-1", people.alice)
    await world.svc.start_stage("stage-1", people.alice)  # the stage is already RUNNING

    with pytest.raises(Denied):  # start of a running stage returns it, but not to bob
        await world.svc.start_stage("stage-1", people.bob)


async def test_abort_after_disable_and_transfer_is_refused(world, people):
    await people.running()
    await world.svc.stop_stage("stage-1", people.alice)  # stopped: keeps its care right
    original = world.control.handover

    async def transfer_meanwhile(number, reason):
        world.control.handover = original
        await original(number, reason)
        store = world.svc.store
        store.set_project_owner(
            world.project_id, "carol", "root", "alice left", world.clock.now(), lambda: None
        )

    world.control.handover = transfer_meanwhile

    with pytest.raises(Denied) as denied:
        await world.svc.abort_round(world.round_id, people.alice)

    assert denied.value.code in ("state", "not_owner")
    assert world.round_state() != "aborted"


async def test_access_none_unchanged(world):
    await world.running("stage-1")  # no access: operators act as before

    assert world.state("stage-1") == "running"


async def test_a_stage_id_used_in_another_round_does_not_tell_its_state(world, people):
    await people.running()  # alice's stage-1 is running
    world.round_id = ""
    people.locks.lock("bob", ["gh-02"])
    round_b = people.design(people.bob, protocol_id="protocol-bob")
    sheet = world.sheet(
        "stage-1", protocol_id="protocol-bob", device_id="AC5-2", experiment_id="experiment-bob"
    )

    with pytest.raises(Denied) as denied:
        world.svc.submit_run_sheet(round_b, sheet, people.bob)

    assert denied.value.code == "state"
    assert "running" not in str(denied.value) and "already used" in str(denied.value)


async def test_a_refused_abort_gets_the_finished_stages_care_back(world, people):
    await people.running()
    await world.svc.stop_stage("stage-1", people.alice)
    old = world.svc.store.stage("stage-1").care_right
    original = world.control.handover

    async def transfer_meanwhile(number, reason):
        world.control.handover = original
        await original(number, reason)
        store = world.svc.store
        store.set_project_owner(
            world.project_id, "carol", "root", "alice left", world.clock.now(), lambda: None
        )

    world.control.handover = transfer_meanwhile
    with pytest.raises(Denied):
        await world.svc.abort_round(world.round_id, people.alice)

    await world.svc.restore_care()  # what the runtime does on every tick

    care = world.svc.store.stage("stage-1").care_right
    assert care is not None and care != old
