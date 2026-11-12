"""What the service hands to a backend as inputs: local paths under one root, scope-checked."""

import pytest
import pytest_asyncio
from compute_support import GOOD_PARAMS, MEMBERS, TEMPLATE

from growbridge.compute.service import ComputeService
from growbridge.ports import Denied


@pytest.fixture
def root(tmp_path):
    base = tmp_path / "snapshots"
    (base / "snap-1").mkdir(parents=True)
    (base / "snap-1" / "samples.jsonl").write_text("{}\n")
    return base


@pytest_asyncio.fixture
async def rooted(env, root):
    """A service whose inputs must be files under ``root``; the guard is set per test."""
    service = ComputeService(
        env.db,
        env.clock,
        env.backend,
        [TEMPLATE],
        MEMBERS,
        service_cpu_cap=100.0,
        service_storage_cap=100.0,
        input_root=root,
    )
    service.set_task_budget("t1", 100.0, 100.0)
    await service.refresh_balance()
    return service


async def submit(service, ref="snap-1/samples.jsonl"):
    return await service.submit_compute_job("t1", "alice", "segment", GOOD_PARAMS, {"data": ref})


async def test_compute_backend_receives_the_resolved_local_path(env, rooted, root):
    rooted.input_guard = lambda task_id, ref: None

    attempt = await submit(rooted)

    assert env.backend.submit_inputs == [{"data": str(root / "snap-1" / "samples.jsonl")}]
    assert attempt.inputs == {"data": "snap-1/samples.jsonl"}  # the audit keeps the reference


async def test_compute_inputs_are_refused_while_no_scope_guard_is_installed(env, rooted):
    with pytest.raises(Denied) as info:
        await submit(rooted)
    assert info.value.code == "param"
    assert env.backend.submit_calls == []


async def test_compute_guard_sees_the_task_and_every_reference_before_any_reservation(env, rooted):
    seen = []

    def guard(task_id, ref):
        seen.append((task_id, ref))
        raise Denied("scope", "not your snapshot")

    rooted.input_guard = guard
    with pytest.raises(Denied) as info:
        await submit(rooted)

    assert info.value.code == "scope"
    assert seen == [("t1", "snap-1/samples.jsonl")]
    assert env.db.one("SELECT COUNT(*) AS n FROM compute_attempts")["n"] == 0


@pytest.mark.parametrize("ref", ["snap-1/missing.jsonl", "snap-2/samples.jsonl"])
async def test_compute_missing_input_is_refused(env, rooted, ref):
    rooted.input_guard = lambda task_id, ref: None
    with pytest.raises(Denied) as info:
        await submit(rooted, ref)
    assert info.value.code == "param"
    assert env.backend.submit_calls == []


async def test_compute_symlink_leaving_the_root_is_refused(env, rooted, root, tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("x")
    (root / "snap-1" / "link").symlink_to(outside)
    rooted.input_guard = lambda task_id, ref: None
    with pytest.raises(Denied) as info:
        await submit(rooted, "snap-1/link")
    assert info.value.code == "param"


async def test_compute_without_a_root_refuses_every_input(env):
    rootless = ComputeService(
        env.db,
        env.clock,
        env.backend,
        [TEMPLATE],
        MEMBERS,
        service_cpu_cap=100.0,
        service_storage_cap=100.0,
    )
    rootless.input_guard = lambda task_id, ref: None  # even a guard does not open it
    with pytest.raises(Denied) as info:
        await rootless.submit_compute_job("t1", "alice", "segment", GOOD_PARAMS, {"data": "a/b"})
    assert info.value.code == "param"
    assert env.backend.submit_calls == []


async def test_compute_without_a_root_still_accepts_a_job_without_inputs(env):
    rootless = ComputeService(
        env.db,
        env.clock,
        env.backend,
        [TEMPLATE],
        MEMBERS,
        service_cpu_cap=100.0,
        service_storage_cap=100.0,
    )
    attempt = await rootless.submit_compute_job("t1", "alice", "segment", GOOD_PARAMS, {})
    assert attempt.task_state.value == "remote_queued"


async def test_compute_symlink_into_another_snapshot_is_refused(env, rooted, root):
    (root / "snap-2").mkdir()
    (root / "snap-2" / "other.jsonl").write_text("{}\n")
    (root / "snap-1" / "peek").symlink_to(root / "snap-2" / "other.jsonl")
    rooted.input_guard = lambda task_id, ref: None
    with pytest.raises(Denied) as info:
        await submit(rooted, "snap-1/peek")
    assert info.value.code == "param"
