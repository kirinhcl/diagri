"""The ``on_intervention`` hook: interventions are handed on after the workflow's own write."""

from growbridge.workflow.service import WorkflowService


def with_hook(world, hook):
    world.svc = WorkflowService(
        world.db, world.clock, world.control, on_intervention=hook, check_treatments=False
    )


async def test_takeover_hands_the_intervention_on_after_the_transaction(world):
    seen = []

    def hook(item):
        assert world.db.depth == 0  # never inside db.transaction()
        seen.append(item)

    with_hook(world, hook)
    await world.running()
    await world.svc.takeover("stage-1", world.op)

    assert len(seen) == 1
    assert seen[0] == {
        "experiment_id": "experiment-stage-1",
        "stage_id": "stage-1",
        "at": world.clock.now(),
        "kind": "takeover",
        "operator": "op-1",
        "detail": {},
    }


async def test_a_failing_hook_does_not_break_the_stage_transition(world):
    def hook(_item):
        raise RuntimeError("archive is down")

    with_hook(world, hook)
    await world.running()
    await world.svc.takeover("stage-1", world.op)

    assert world.state() == "manual"
    assert [row["kind"] for row in world.svc.interventions("experiment-stage-1")] == ["takeover"]


async def test_no_hook_means_no_change(world):
    await world.running()
    await world.svc.takeover("stage-1", world.op)

    assert world.state() == "manual"
