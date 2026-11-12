import pytest
from compute_support import GOOD_PARAMS, INPUTS

from growbridge.compute.service import ArtifactMismatch
from growbridge.ports import Denied
from growbridge.workflow.states import TaskState


async def submit(env, who="alice", params=None):
    return await env.service.submit_compute_job(
        "t1", who, "segment", GOOD_PARAMS if params is None else params, INPUTS
    )


def reserved(env):
    row = env.db.one(
        "SELECT SUM(reserved_cpu) AS c, SUM(reserved_storage) AS s FROM compute_attempts"
    )
    return row["c"] or 0.0, row["s"] or 0.0


async def test_compute_lost_receipt_goes_to_reconcile_and_keeps_reservation(env):
    env.backend.lose_receipt = True

    attempt = await submit(env)

    assert attempt.task_state is TaskState.RECONCILE
    assert reserved(env) == (10.0, 5.0)


async def test_compute_reconcile_finds_job_by_name_without_resubmitting(env):
    env.backend.lose_receipt = True
    attempt = await submit(env)

    found = await env.service.reconcile(attempt.id)

    assert found.task_state is TaskState.REMOTE_QUEUED
    assert found.remote_job_id is not None
    assert env.backend.submit_calls == [f"gb-{attempt.id}"]
    assert reserved(env) == (10.0, 5.0)


async def test_compute_reconcile_without_trace_releases_reservation(env):
    env.backend.lose_receipt = True
    attempt = await submit(env)
    env.backend.forget_jobs()

    result = await env.service.reconcile(attempt.id)

    assert result.task_state is TaskState.NEEDS_ATTENTION
    assert reserved(env) == (0.0, 0.0)


async def test_compute_rejected_submit_releases_reservation(env):
    env.backend.fail_submit = True

    attempt = await submit(env)

    assert attempt.task_state is TaskState.NEEDS_ATTENTION
    assert reserved(env) == (0.0, 0.0)


async def test_compute_get_settles_actual_usage_and_releases_the_rest(env):
    attempt = await submit(env)
    env.backend.set_usage(cpu=2.5, storage=1.0)
    env.backend.finish(attempt.remote_job_id)

    done = await env.service.get_compute_job(attempt.id, "alice")

    assert done.task_state is TaskState.FETCHING
    assert (done.used_cpu, done.used_storage) == (2.5, 1.0)
    assert reserved(env) == (0.0, 0.0)


async def test_compute_failed_job_settles_and_needs_attention(env):
    attempt = await submit(env)
    env.backend.set_usage(cpu=1.0, storage=0.5)
    env.backend.finish(attempt.remote_job_id, ok=False)

    failed = await env.service.get_compute_job(attempt.id, "alice")

    assert failed.task_state is TaskState.NEEDS_ATTENTION
    assert failed.used_cpu == 1.0


async def test_compute_settled_usage_frees_quota_for_next_job(env):
    service = await env.build(task_cpu=15.0)
    first = await service.submit_compute_job("t1", "alice", "segment", GOOD_PARAMS, INPUTS)
    env.backend.set_usage(cpu=1.0, storage=1.0)
    env.backend.finish(first.remote_job_id)
    await service.get_compute_job(first.id, "alice")

    second = await service.submit_compute_job("t1", "alice", "segment", GOOD_PARAMS, INPUTS)

    assert second.task_state is TaskState.REMOTE_QUEUED


async def test_compute_fetch_verifies_then_cleans_remote(env):
    attempt = await submit(env)
    env.backend.finish(attempt.remote_job_id)
    await env.service.get_compute_job(attempt.id, "alice")

    out = env.tmp / "out"
    checksums = await env.service.fetch_compute_artifacts(attempt.id, "alice", out)

    assert set(checksums) == {"result.csv"}
    assert (out / "result.csv").read_bytes() == b"a,b\n1,2\n"
    assert env.backend.cleaned == [attempt.remote_job_id]
    done = await env.service.get_compute_job(attempt.id, "alice")
    assert done.task_state is TaskState.DONE
    assert done.checksums == checksums


async def test_compute_checksum_mismatch_keeps_remote_files(env):
    attempt = await submit(env)
    env.backend.finish(attempt.remote_job_id)
    await env.service.get_compute_job(attempt.id, "alice")
    env.backend.wrong_checksums = True

    with pytest.raises(ArtifactMismatch):
        await env.service.fetch_compute_artifacts(attempt.id, "alice", env.tmp / "out")

    assert env.backend.cleaned == []
    state = await env.service.get_compute_job(attempt.id, "alice")
    assert state.task_state is TaskState.NEEDS_REVIEW


async def test_compute_fetch_before_job_finished_is_denied(env):
    attempt = await submit(env)
    with pytest.raises(Denied) as info:
        await env.service.fetch_compute_artifacts(attempt.id, "alice", env.tmp / "out")
    assert info.value.code == "state"


async def test_compute_cancel_releases_reservation_and_cancels_remote(env):
    attempt = await submit(env)

    await env.service.cancel(attempt.id, "alice")

    assert env.backend.cancelled == [attempt.remote_job_id]
    state = await env.service.get_compute_job(attempt.id, "alice")
    assert state.task_state is TaskState.ENDED
    assert reserved(env) == (0.0, 0.0)


async def test_compute_cancel_finished_attempt_is_denied(env):
    attempt = await submit(env)
    env.backend.finish(attempt.remote_job_id)
    await env.service.get_compute_job(attempt.id, "alice")
    with pytest.raises(Denied) as info:
        await env.service.cancel(attempt.id, "alice")
    assert info.value.code == "state"


async def failed_attempt(env):
    attempt = await submit(env)
    env.backend.finish(attempt.remote_job_id, ok=False)
    return await env.service.get_compute_job(attempt.id, "alice")


async def test_compute_retry_with_neutral_change_keeps_analysis_version(env):
    failed = await failed_attempt(env)

    retried, new_version = await env.service.retry(failed.id, {"verbose": True})

    assert new_version is False
    assert retried.analysis_version == failed.analysis_version
    assert retried.parent_id == failed.id
    assert retried.params["verbose"] is True


async def test_compute_retry_changing_result_params_starts_new_analysis_version(env):
    failed = await failed_attempt(env)

    retried, new_version = await env.service.retry(failed.id, {"batch_size": 8})

    assert new_version is True
    assert retried.analysis_version == failed.analysis_version + 1
    original = await env.service.get_compute_job(failed.id, "alice")
    assert original.params["batch_size"] == 32  # the original is untouched


async def test_compute_retry_of_running_attempt_is_denied(env):
    attempt = await submit(env)
    with pytest.raises(Denied) as info:
        await env.service.retry(attempt.id, {})
    assert info.value.code == "state"


async def test_compute_retry_stops_at_the_template_limit(env):
    current = await failed_attempt(env)
    for _ in range(2):  # template default allows two retries
        current, _ = await env.service.retry(current.id, {})
        env.backend.finish(current.remote_job_id, ok=False)
        current = await env.service.get_compute_job(current.id, "alice")

    with pytest.raises(Denied) as info:
        await env.service.retry(current.id, {})
    assert info.value.code == "quota"


async def test_compute_retry_validates_adjusted_params(env):
    failed = await failed_attempt(env)
    with pytest.raises(Denied) as info:
        await env.service.retry(failed.id, {"batch_size": 9999})
    assert info.value.code == "param"


async def test_compute_unreported_usage_is_charged_at_the_full_reservation(env):
    attempt = await submit(env)
    env.backend.set_usage(cpu=None, storage=None)  # the backend cannot report usage
    env.backend.finish(attempt.remote_job_id)

    done = await env.service.get_compute_job(attempt.id, "alice")

    assert (done.used_cpu, done.used_storage) == (10.0, 5.0)  # the template's reservation
    assert reserved(env) == (0.0, 0.0)


async def test_compute_unreported_usage_still_counts_against_the_caps(env):
    service = await env.build(task_cpu=15.0)
    first = await service.submit_compute_job("t1", "alice", "segment", GOOD_PARAMS, INPUTS)
    env.backend.set_usage(cpu=None, storage=None)
    env.backend.finish(first.remote_job_id)
    await service.get_compute_job(first.id, "alice")

    with pytest.raises(Denied) as info:  # 10 h are spent, not 0: a second job does not fit
        await service.submit_compute_job("t1", "alice", "segment", GOOD_PARAMS, INPUTS)
    assert info.value.code == "quota"
