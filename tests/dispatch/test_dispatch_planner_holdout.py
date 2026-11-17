"""``find_prior_runs`` must not tell a planner how many held-out outcome rows exist."""

import json

from vocab_support import TEST_CATALOG

from growbridge.archive.models import ManualMeasurement
from growbridge.research.holdout import HoldoutRegistry
from growbridge.sim.clock import START

EXPERIMENT = "experiment-1"


def _measurement(ident: str, batch: str) -> ManualMeasurement:
    return ManualMeasurement(
        id=ident,
        experiment_id=EXPERIMENT,
        batch=batch,
        plant_id="p1",
        layout_version="v1",
        measured_at=START + 1,
        position="tent-1",
        method="ruler",
        metric="canopy_area_growth",
        value=1.0,
        unit="cm2",
        operator="op-1",
    )


def _seed(env) -> HoldoutRegistry:
    registry = HoldoutRegistry(env.db, env.clock, catalog=TEST_CATALOG)
    registry.register(env.project_id, "hold-1", ["batch-h"], ["canopy_area_growth"], ["d-1", "d-2"])
    env.stage_for(EXPERIMENT)
    for ident, batch in (
        ("m-d1", "d-1"),
        ("m-d2", "d-2"),
        ("m-h1", "batch-h"),
        ("m-h2", "batch-h"),
    ):
        env.archive.add_measurement(_measurement(ident, batch))
    return registry


async def _count(env, deps=None) -> int:
    outcome = await env.invoke("planner", "find_prior_runs", deps, experiment_id=EXPERIMENT)
    assert not outcome.is_error, outcome.content
    return json.loads(outcome.content)["measurements"]


async def test_held_out_outcomes_are_not_counted(env):
    registry = _seed(env)

    assert await _count(env, env.make_deps(holdout=registry)) == 2


async def test_without_a_registry_every_measurement_is_counted(env):
    _seed(env)

    assert await _count(env) == 4
