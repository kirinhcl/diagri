import pytest

from growbridge.ports import Actor, Denied, StageEventKind
from growbridge.workflow.permissions import REAUTH_SECONDS, require_operator

NOW = 1_800_000_000.0


def actor(kind: str, reauth_at: float | None = None) -> Actor:
    return Actor(kind=kind, id=f"{kind}-1", reauth_at=reauth_at)


def test_permissions_reauth_window_is_five_minutes():
    assert REAUTH_SECONDS == 300


def test_permissions_operator_passes():
    require_operator(actor("operator"), NOW)


def test_permissions_model_identity_is_denied_as_model_role():
    with pytest.raises(Denied) as caught:
        require_operator(actor("model"), NOW)
    assert caught.value.code == "model_role"


@pytest.mark.parametrize("kind", ["workflow", "observer", "probe"])
def test_permissions_other_identities_are_not_operators(kind):
    with pytest.raises(Denied) as caught:
        require_operator(actor(kind), NOW)
    assert caught.value.code == "not_operator"


def test_permissions_recent_reauth_is_required_when_asked():
    with pytest.raises(Denied) as caught:
        require_operator(actor("operator"), NOW, recent=True)
    assert caught.value.code == "reauth_required"


def test_permissions_old_reauth_is_denied():
    with pytest.raises(Denied) as caught:
        require_operator(actor("operator", NOW - REAUTH_SECONDS - 1), NOW, recent=True)
    assert caught.value.code == "reauth_required"


def test_permissions_reauth_at_the_window_edge_passes():
    require_operator(actor("operator", NOW - REAUTH_SECONDS), NOW, recent=True)


def test_permissions_reauth_is_ignored_unless_asked():
    require_operator(actor("operator", NOW - 10_000), NOW)


def test_permissions_model_is_denied_before_reauth_is_looked_at():
    with pytest.raises(Denied) as caught:
        require_operator(actor("model", NOW), NOW, recent=True)
    assert caught.value.code == "model_role"


# --- through the service -----------------------------------------------------------------------


async def test_workflow_model_cannot_approve(world):
    await world.pending()
    with pytest.raises(Denied) as caught:
        world.svc.approve("stage-1", world.actor("model"))
    assert caught.value.code == "model_role"
    assert world.svc.approvals("stage-1") == ()


async def test_workflow_model_cannot_start_even_with_a_valid_approval(world):
    await world.approved()
    with pytest.raises(Denied) as caught:
        await world.svc.start_stage("stage-1", world.actor("model"))
    assert caught.value.code == "model_role"
    assert world.state() == "pending_review"


async def test_workflow_approve_needs_recent_reauth(world):
    await world.pending()
    stale = actor("operator", world.clock.now() - REAUTH_SECONDS - 1)
    with pytest.raises(Denied) as caught:
        world.svc.approve("stage-1", stale)
    assert caught.value.code == "reauth_required"


async def test_workflow_workflow_identity_cannot_approve(world):
    await world.pending()
    with pytest.raises(Denied) as caught:
        world.svc.approve("stage-1", world.actor("workflow"))
    assert caught.value.code == "not_operator"


async def test_workflow_observer_cannot_start(world):
    await world.approved()
    with pytest.raises(Denied) as caught:
        await world.svc.start_stage("stage-1", world.actor("observer"))
    assert caught.value.code == "not_operator"


async def test_workflow_workflow_identity_starts_only_with_a_valid_approval(world):
    await world.pending()
    with pytest.raises(Denied) as caught:
        await world.svc.start_stage("stage-1", world.actor("workflow"))
    assert caught.value.code == "approval_invalid"
    world.svc.approve("stage-1", world.op)
    runtime = await world.svc.start_stage("stage-1", world.actor("workflow"))
    assert runtime.state.value == "running"


async def test_workflow_observer_may_pause_but_model_and_workflow_may_not(world):
    await world.running()
    for kind, code in (("model", "model_role"), ("workflow", "not_operator")):
        with pytest.raises(Denied) as caught:
            await world.svc.pause_stage("stage-1", world.actor(kind), "x")
        assert caught.value.code == code
    runtime = await world.svc.pause_stage("stage-1", world.actor("observer"), "alert")
    assert runtime.state.value == "paused"


@pytest.mark.parametrize("kind", ["observer", "workflow", "model", "probe"])
async def test_workflow_only_operators_resume_stop_and_take_over(world, kind):
    await world.running()
    await world.svc.pause_stage("stage-1", world.op, "check")
    who = world.actor(kind)
    for method in (world.svc.resume_stage, world.svc.stop_stage, world.svc.takeover):
        with pytest.raises(Denied):
            await method("stage-1", who)
    assert world.state() == "paused"


async def test_the_planner_model_may_submit_a_draft_but_not_create_a_project(world):
    await world.design()
    model = Actor(kind="model", id="planner")
    findings = world.svc.submit_run_sheet(world.round_id, world.sheet(), model)
    assert findings == ()
    with pytest.raises(Denied) as caught:
        world.svc.create_project("x", model)
    assert caught.value.code == "model_role"


async def test_workflow_probe_cannot_submit_a_run_sheet(world):
    await world.design()
    with pytest.raises(Denied) as caught:
        world.svc.submit_run_sheet(world.round_id, world.sheet(), world.actor("probe"))
    assert caught.value.code == "not_operator"


async def test_workflow_events_need_no_actor_identity(world):
    await world.running()
    await world.report(StageEventKind.RULE_PAUSE)
    assert world.state() == "paused"
