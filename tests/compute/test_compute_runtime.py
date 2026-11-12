"""build_runtime hands the templates, the member map and the snapshot root to the service."""

import pytest
from compute_support import TEMPLATE

from growbridge.config import Settings
from growbridge.ports import Denied
from growbridge.runtime import build_runtime
from growbridge.sim.clock import FakeClock
from growbridge.sim.compute import FakeBackend
from growbridge.sim.device import SimulatedTransport


@pytest.fixture
def settings(tmp_path):
    return Settings(
        device="SIMULATED", token="x" * 32, data_dir=tmp_path / "data", auto_research=True
    )


def build(settings, **options):
    return build_runtime(settings, lambda _: SimulatedTransport(), FakeClock(), **options)


@pytest.fixture
def closing():
    runtimes = []
    yield runtimes
    for runtime in runtimes:
        for db in runtime.databases:
            db.close()


async def test_runtime_without_a_compute_backend_has_no_compute_service(settings, closing):
    runtime = build(settings)
    closing.append(runtime)
    assert runtime.compute is None


async def test_runtime_registers_templates_and_members_with_the_service(settings, closing):
    runtime = build(
        settings,
        compute_backend=FakeBackend(),
        compute_templates=[TEMPLATE],
        compute_members={"researcher": "csc_robot"},
    )
    closing.append(runtime)
    compute = runtime.compute

    assert set(compute.templates) == {TEMPLATE.id}
    assert compute.members == {"researcher": "csc_robot"}
    assert compute.input_root == runtime.archive.root / "snapshots"


async def test_runtime_compute_refuses_inputs_until_the_guard_is_installed(settings, closing):
    backend = FakeBackend()
    runtime = build(
        settings,
        compute_backend=backend,
        compute_templates=[TEMPLATE],
        compute_members={"researcher": "csc_robot"},
    )
    closing.append(runtime)
    runtime.compute.set_task_budget("t1", 100.0, 100.0)
    runtime.compute.record_balance(500.0, "alice")

    with pytest.raises(Denied) as info:
        await runtime.compute.submit_compute_job(
            "t1", "researcher", "segment", {"epochs": 3}, {"data": "snap-1/samples.jsonl"}
        )
    assert info.value.code == "param"
    assert backend.submit_calls == []

    attempt = await runtime.compute.submit_compute_job(  # no inputs: nothing to leak
        "t1", "researcher", "segment", {"epochs": 3}, {}
    )
    assert attempt.task_state.value == "remote_queued"


async def test_runtime_tick_recovers_a_lost_receipt_without_any_model_action(settings, closing):
    backend = FakeBackend()
    backend.lose_receipt = True
    runtime = build(
        settings,
        compute_backend=backend,
        compute_templates=[TEMPLATE],
        compute_members={"researcher": "csc_robot"},
    )
    closing.append(runtime)
    runtime.compute.set_task_budget("t1", 100.0, 100.0)
    runtime.compute.record_balance(500.0, "alice")
    attempt = await runtime.compute.submit_compute_job(
        "t1", "researcher", "segment", {"epochs": 3}, {}
    )
    assert attempt.task_state.value == "reconcile"
    runtime.clock.advance(600)

    await runtime.tick()

    found = runtime.compute._load(attempt.id)
    assert found.task_state.value == "remote_queued" and found.remote_job_id is not None
    assert len(backend.submit_calls) == 1


async def test_runtime_without_compute_ticks_as_before(settings, closing):
    runtime = build(settings)
    closing.append(runtime)
    await runtime.tick()  # nothing to reconcile, nothing raised
