"""A fetch is bounded by the attempt's storage reservation, and a refusal is visible and final."""

import pytest
from compute_support import GOOD_PARAMS, INPUTS

from growbridge.compute import service as service_module
from growbridge.compute.backend import BackendError, OutputTooLarge
from growbridge.compute.errors import OUTPUT_LIMIT_MARK
from growbridge.ports import Denied
from growbridge.workflow.states import TaskState


@pytest.fixture(autouse=True)
def tiny_gigabyte(monkeypatch):
    """The template reserves 5 GB: with 100 bytes to the GB the limit is 500 bytes."""
    monkeypatch.setattr(service_module, "BYTES_PER_GB", 100)


async def finished(env):
    attempt = await env.service.submit_compute_job("t1", "alice", "segment", GOOD_PARAMS, INPUTS)
    env.backend.finish(attempt.remote_job_id)
    await env.service.get_compute_job(attempt.id, "alice")
    return attempt


def row(env, attempt_id):
    return dict(env.db.one("SELECT * FROM compute_attempts WHERE id = ?", (attempt_id,)))


async def test_compute_fetch_is_given_the_storage_reservation_as_its_byte_limit(env, tmp_path):
    attempt = await finished(env)

    await env.service.fetch_compute_artifacts(attempt.id, "alice", tmp_path / "out")

    assert env.backend.fetch_limits == [500]  # max_storage_gb 5 x 100 bytes


async def test_compute_outputs_over_the_limit_stop_the_fetch_and_show_as_stuck(env, tmp_path):
    attempt = await finished(env)
    env.backend.artifacts = {"big.bin": b"x" * 2000}

    with pytest.raises(OutputTooLarge):
        await env.service.fetch_compute_artifacts(attempt.id, "alice", tmp_path / "out")

    stored = row(env, attempt.id)
    assert stored["phase"] == "needs_review" and stored["error"].startswith(OUTPUT_LIMIT_MARK)
    assert env.backend.cleaned == []  # the remote files stay until the operator decides
    (stuck,) = env.service.overview()["stuck"]
    assert stuck["attempt_id"] == attempt.id and OUTPUT_LIMIT_MARK in stuck["reason"]


async def test_compute_a_refused_fetch_is_not_retried_in_a_loop(env, tmp_path):
    attempt = await finished(env)
    env.backend.artifacts = {"big.bin": b"x" * 2000}
    with pytest.raises(OutputTooLarge):
        await env.service.fetch_compute_artifacts(attempt.id, "alice", tmp_path / "out")
    env.backend.fetch_limits.clear()

    with pytest.raises(Denied) as info:
        await env.service.fetch_compute_artifacts(attempt.id, "alice", tmp_path / "out")

    assert info.value.code == "state" and "operator" in str(info.value)
    assert env.backend.fetch_limits == []  # the backend was not asked again


async def test_compute_the_operator_can_settle_an_attempt_whose_outputs_are_too_large(
    env, tmp_path
):
    attempt = await finished(env)
    env.backend.set_usage(cpu=2.0, storage=1.0)
    env.backend.artifacts = {"big.bin": b"x" * 2000}
    with pytest.raises(OutputTooLarge):
        await env.service.fetch_compute_artifacts(attempt.id, "alice", tmp_path / "out")

    settled = await env.service.settle_attempt(attempt.id, "carol", "outputs far too large")

    assert settled.task_state is TaskState.NEEDS_ATTENTION
    assert env.service.overview()["stuck"] == []
    assert env.backend.cleaned_names == [attempt.job_name]  # the remote files go with it


async def test_compute_a_failed_attempt_with_oversized_outputs_goes_to_review_too(env, tmp_path):
    attempt = await env.service.submit_compute_job("t1", "alice", "segment", GOOD_PARAMS, INPUTS)
    env.backend.finish(attempt.remote_job_id, ok=False)
    await env.service.get_compute_job(attempt.id, "alice")
    env.backend.artifacts = {"big.bin": b"x" * 2000}

    with pytest.raises(OutputTooLarge):
        await env.service.fetch_compute_artifacts(attempt.id, "alice", tmp_path / "out")

    assert row(env, attempt.id)["phase"] == "needs_review"  # visible, and not retried as failed


async def test_compute_another_backend_error_is_recorded_and_the_fetch_may_be_retried(
    env, tmp_path
):
    attempt = await finished(env)
    original = env.backend.fetch

    async def broken(job_id, out_dir, max_bytes):
        raise BackendError("FirecREST download failed (TimeoutError)")

    env.backend.fetch = broken
    with pytest.raises(BackendError):
        await env.service.fetch_compute_artifacts(attempt.id, "alice", tmp_path / "out")
    stored = row(env, attempt.id)
    assert stored["phase"] == "fetching" and "download failed" in stored["error"]
    assert len(env.service.overview()["stuck"]) == 1  # shown, but not final

    env.backend.fetch = original  # the network is back
    files = await env.service.fetch_compute_artifacts(attempt.id, "alice", tmp_path / "out")
    assert set(files) == {"result.csv"} and row(env, attempt.id)["error"] == ""


async def test_compute_fetch_with_no_known_limit_is_refused_not_unlimited(env, tmp_path):
    attempt = await finished(env)
    env.db.execute("UPDATE compute_attempts SET storage_limit_gb = NULL")  # an old record
    env.service.templates.clear()  # and its template was withdrawn

    with pytest.raises(Denied) as info:
        await env.service.fetch_compute_artifacts(attempt.id, "alice", tmp_path / "out")

    assert info.value.code == "state" and env.backend.fetch_limits == []


async def test_compute_an_old_record_without_a_stored_limit_uses_its_template(env, tmp_path):
    attempt = await finished(env)
    env.db.execute("UPDATE compute_attempts SET storage_limit_gb = NULL")

    await env.service.fetch_compute_artifacts(attempt.id, "alice", tmp_path / "out")

    assert env.backend.fetch_limits == [500]


def assert_left_as_the_operator_settled_it(env, attempt_id, reason):
    stored = row(env, attempt_id)
    assert stored["phase"] == "failed" and stored["settled_by"] == "carol"
    assert stored["error"].startswith(f"settled by an operator: {reason}")
    assert stored["checksums"] == "{}"


async def test_compute_a_fetch_cannot_reopen_an_attempt_the_operator_settled(env, tmp_path):
    attempt = await finished(env)
    env.backend.artifacts = {"big.bin": b"x" * 2000}
    with pytest.raises(OutputTooLarge):
        await env.service.fetch_compute_artifacts(attempt.id, "alice", tmp_path / "out")
    await env.service.settle_attempt(attempt.id, "carol", "outputs far too large")
    env.backend.fetch_limits.clear()

    with pytest.raises(Denied) as info:
        await env.service.fetch_compute_artifacts(attempt.id, "alice", tmp_path / "out")

    assert info.value.code == "state" and "operator" in str(info.value)
    assert env.backend.fetch_limits == []  # nothing is downloaded again
    assert_left_as_the_operator_settled_it(env, attempt.id, "outputs far too large")


async def broken_download(job_id, out_dir, max_bytes):
    raise BackendError("FirecREST download failed (TimeoutError)")


@pytest.mark.parametrize(
    ("artifacts", "broken", "expected"),
    [
        ({"big.bin": b"x" * 2000}, False, OutputTooLarge),
        ({"result.csv": b"a,b\n1,2\n"}, True, BackendError),
        ({"result.csv": b"a,b\n1,2\n"}, False, Denied),
    ],
    ids=["too-large", "backend-error", "complete"],
)
async def test_compute_an_operator_who_settles_during_a_fetch_keeps_the_last_word(
    env, tmp_path, artifacts, broken, expected
):
    attempt = await finished(env)
    env.backend.artifacts = artifacts
    download = broken_download if broken else env.backend.fetch

    async def settled_meanwhile(job_id, out_dir, max_bytes):
        await env.service.settle_attempt(attempt.id, "carol", "giving up on it")
        return await download(job_id, out_dir, max_bytes)

    env.backend.fetch = settled_meanwhile
    with pytest.raises(expected):
        await env.service.fetch_compute_artifacts(attempt.id, "alice", tmp_path / "out")

    assert_left_as_the_operator_settled_it(env, attempt.id, "giving up on it")
    kept = [path for path in (tmp_path / "out").rglob("*") if path.is_file()]
    assert kept == []  # files whose fetch was not recorded are not left behind


async def test_compute_discarding_a_refused_fetch_leaves_other_files_alone(env, tmp_path):
    attempt = await finished(env)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "notes.txt").write_text("written by someone else")
    original = env.backend.fetch

    async def settled_meanwhile(job_id, out_dir, max_bytes):
        await env.service.settle_attempt(attempt.id, "carol", "giving up on it")
        return await original(job_id, out_dir, max_bytes)

    env.backend.fetch = settled_meanwhile
    with pytest.raises(Denied):
        await env.service.fetch_compute_artifacts(attempt.id, "alice", out_dir)

    assert sorted(path.name for path in out_dir.iterdir()) == ["notes.txt"]


async def test_compute_a_fetch_that_a_parallel_fetch_beat_still_returns_its_files(env, tmp_path):
    attempt = await finished(env)
    original = env.backend.fetch

    async def beaten(job_id, out_dir, max_bytes):
        env.db.execute("UPDATE compute_attempts SET phase = 'done' WHERE id = ?", (attempt.id,))
        return await original(job_id, out_dir, max_bytes)

    env.backend.fetch = beaten
    files = await env.service.fetch_compute_artifacts(attempt.id, "alice", tmp_path / "out")

    assert set(files) == {"result.csv"} and row(env, attempt.id)["phase"] == "done"
