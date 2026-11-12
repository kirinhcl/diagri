"""Whether any stage under a protocol version has started: the analysis script of that version
may only be frozen before it has (architecture doc §6.5), and a snapshot's experiment must belong
to a round that runs the protocol."""

from growbridge.sim.fixtures import make_protocol


async def test_nothing_has_started_while_the_stage_waits_for_review_or_approval(world):
    await world.approved("stage-1")

    assert world.svc.store.protocol_started("protocol-1", 1) is False


async def test_a_started_stage_marks_the_protocol_version_as_started(world):
    await world.running("stage-1")

    assert world.svc.store.protocol_started("protocol-1", 1) is True


async def test_a_stage_that_was_started_and_stopped_still_counts(world):
    await world.running("stage-1")
    await world.svc.stop_stage("stage-1", world.op)

    assert world.svc.store.protocol_started("protocol-1", 1) is True


async def test_another_version_or_another_protocol_is_not_affected(world):
    await world.running("stage-1")
    world.svc.save_protocol(make_protocol(project_id=world.project_id, version=2), world.op)

    assert world.svc.store.protocol_started("protocol-1", 2) is False
    assert world.svc.store.protocol_started("protocol-other", 1) is False


async def test_experiments_under_a_protocol_version_are_listed_once_each(world):
    await world.approved("stage-1")
    await world.pending("stage-2")

    found = world.svc.store.experiments_under("protocol-1", 1)

    assert sorted(found) == ["experiment-stage-1", "experiment-stage-2"]
    assert world.svc.store.experiments_under("protocol-1", 2) == ()
    assert world.svc.store.experiments_under("protocol-other", 1) == ()


async def test_the_start_times_of_an_experiments_stages_are_listed(world):
    await world.approved("stage-1")
    assert world.svc.store.stage_starts("experiment-stage-1") == (None,)

    await world.svc.start_stage("stage-1", world.op)

    assert world.svc.store.stage_starts("experiment-stage-1") == (world.clock.now(),)
    assert world.svc.store.stage_starts("experiment-unknown") == ()


async def test_the_protocol_versions_an_experiment_ran_under_are_listed(world):
    await world.approved("stage-1")

    assert world.svc.store.protocol_versions_of("experiment-stage-1") == (("protocol-1", 1),)
    assert world.svc.store.protocol_versions_of("experiment-unknown") == ()
