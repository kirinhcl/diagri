"""Every error an attempt records carries a code and params beside its English text."""

import asyncio
import json

import pytest
from compute_support import GOOD_PARAMS, INPUTS

from growbridge.compute import service as service_module
from growbridge.compute.backend import BackendError, OutputTooLarge
from growbridge.compute.errors import OUTPUT_LIMIT_MARK
from growbridge.compute.phases import POLL_AFTER_SECONDS, STUCK_AFTER_SECONDS
from growbridge.compute.phases import RECONCILE_AFTER_SECONDS as RECONCILE_AFTER


@pytest.fixture(autouse=True)
def tiny_gigabyte(monkeypatch):
    monkeypatch.setattr(service_module, "BYTES_PER_GB", 100)  # a 5 GB reservation is 500 bytes


async def submit(env):
    return await env.service.submit_compute_job("t1", "alice", "segment", GOOD_PARAMS, INPUTS)


async def finished(env):
    attempt = await submit(env)
    env.backend.finish(attempt.remote_job_id)
    await env.service.get_compute_job(attempt.id, "alice")
    return attempt


def coded(env, attempt_id):
    row = env.db.one("SELECT error_code, error_params FROM compute_attempts WHERE id = ?",
                     (attempt_id,))  # fmt: skip
    return row["error_code"], json.loads(row["error_params"])


async def test_a_rejected_submit_says_submit_rejected(env):
    env.backend.fail_submit = True
    attempt = await submit(env)
    assert coded(env, attempt.id) == ("submit_rejected", {})


async def test_a_lost_receipt_says_submit_failed(env):
    env.backend.lose_receipt = True
    attempt = await submit(env)
    assert coded(env, attempt.id) == ("submit_failed", {})


async def test_a_late_remote_job_that_was_cancelled_says_so(env):
    env.backend.hold("submit")
    task = asyncio.create_task(submit(env))
    await env.backend.entered["submit"].wait()
    attempt_id = env.db.one("SELECT id FROM compute_attempts")["id"]
    await env.service.cancel(attempt_id, "alice")
    env.backend.release("submit")
    await task
    assert coded(env, attempt_id) == ("late_cancelled", {})


async def test_a_late_remote_job_that_could_not_be_cancelled_says_so(env):
    env.backend.hold("submit")
    task = asyncio.create_task(submit(env))
    await env.backend.entered["submit"].wait()
    attempt_id = env.db.one("SELECT id FROM compute_attempts")["id"]
    await env.service.cancel(attempt_id, "alice")

    async def broken(job_id):
        raise BackendError("scheduler gone")

    env.backend.cancel = broken
    env.backend.release("submit")
    await task
    assert coded(env, attempt_id) == ("orphan_not_cancelled", {})


async def test_a_cancel_that_found_no_job_says_cancelled_no_job(env):
    env.backend.lose_receipt = True
    attempt = await submit(env)
    env.backend.forget_jobs()
    await env.service.cancel(attempt.id, "alice")
    assert coded(env, attempt.id) == ("cancelled_no_job", {})


async def test_a_cancel_whose_remote_state_is_unknown_says_cancel_unknown(env):
    attempt = await submit(env)
    env.backend.forget_jobs()
    await env.service.cancel(attempt.id, "alice")
    assert coded(env, attempt.id) == ("cancel_unknown", {})


async def test_a_job_nobody_can_find_says_outcome_unknown(env):
    env.backend.lose_receipt = True
    attempt = await submit(env)
    env.backend.forget_jobs()
    await env.service.reconcile(attempt.id)
    assert coded(env, attempt.id) == ("outcome_unknown", {})


async def test_a_cleanup_that_fails_says_cleanup_failed(env):
    env.backend.lose_receipt = True
    attempt = await submit(env)
    env.backend.forget_jobs()
    env.backend.fail_cleanup = True
    await env.service.reconcile(attempt.id)
    assert coded(env, attempt.id) == ("cleanup_failed", {})


async def test_a_remote_cancel_that_fails_while_settling_says_cancel_failed(env):
    attempt = await submit(env)

    async def broken(job_id):
        raise RuntimeError("cannot reach the scheduler")

    env.backend.cancel = broken
    env.backend.fail_cleanup = True
    await env.service.settle_attempt(attempt.id, "carol", "gone")
    assert coded(env, attempt.id) == ("cancel_failed", {})


async def test_an_operator_settle_says_settled_by_operator(env):
    attempt = await submit(env)
    await env.service.settle_attempt(attempt.id, "carol", "gone")
    assert coded(env, attempt.id) == ("settled_by_operator", {})


async def test_a_failed_poll_in_the_tick_says_backend_error(env):
    attempt = await submit(env)

    async def broken(job_id):
        raise RuntimeError("scheduler unreachable")

    env.backend.status = broken
    env.clock.advance(POLL_AFTER_SECONDS + 1)
    await env.service.tick()
    assert coded(env, attempt.id) == ("backend_error", {})


async def test_a_failed_fetch_says_backend_error_and_a_good_one_clears_it(env, tmp_path):
    attempt = await finished(env)
    original = env.backend.fetch

    async def broken(job_id, out_dir, max_bytes):
        raise BackendError("download failed")

    env.backend.fetch = broken
    with pytest.raises(BackendError):
        await env.service.fetch_compute_artifacts(attempt.id, "alice", tmp_path / "out")
    assert coded(env, attempt.id) == ("backend_error", {})

    env.backend.fetch = original
    await env.service.fetch_compute_artifacts(attempt.id, "alice", tmp_path / "out")
    assert coded(env, attempt.id) == ("", {})


async def test_outputs_over_the_limit_carry_bytes_limit_and_kind(env, tmp_path):
    attempt = await finished(env)
    env.backend.artifacts = {"big.bin": b"x" * 2000}
    with pytest.raises(OutputTooLarge):
        await env.service.fetch_compute_artifacts(attempt.id, "alice", tmp_path / "out")
    assert coded(env, attempt.id) == (
        "output_limit",
        {"limit_kind": "total", "bytes": 2000, "limit": 500},
    )


async def test_too_many_output_files_carry_the_counts_and_are_final(env, tmp_path):
    attempt = await finished(env)

    async def crowded(job_id, out_dir, max_bytes):
        raise OutputTooLarge(
            "output limit: 1001 output files, over the limit of 1000",
            limit_kind="files",
            file_count=1001,
            limit_count=1000,
        )

    env.backend.fetch = crowded
    with pytest.raises(OutputTooLarge):
        await env.service.fetch_compute_artifacts(attempt.id, "alice", tmp_path / "out")
    assert coded(env, attempt.id) == ("too_many_files", {"file_count": 1001, "limit_count": 1000})
    with pytest.raises(Exception, match="over the limit"):  # only an operator can settle it
        await env.service.fetch_compute_artifacts(attempt.id, "alice", tmp_path / "out")


async def test_a_missing_or_wrong_artifact_names_the_file(env, tmp_path):
    attempt = await finished(env)
    env.backend.wrong_checksums = True
    with pytest.raises(service_module.ArtifactMismatch):
        await env.service.fetch_compute_artifacts(attempt.id, "alice", tmp_path / "out")
    assert coded(env, attempt.id) == ("artifact_mismatch", {"name": "result.csv"})


async def test_no_artifacts_returned_says_no_artifacts(env, tmp_path):
    attempt = await finished(env)
    env.backend.artifacts = {}
    with pytest.raises(service_module.ArtifactMismatch):
        await env.service.fetch_compute_artifacts(attempt.id, "alice", tmp_path / "out")
    assert coded(env, attempt.id) == ("no_artifacts", {})


async def test_an_attempt_stored_before_codes_still_counts_as_over_the_output_limit(env, tmp_path):
    attempt = await finished(env)
    env.service._update(  # as an older version wrote it: no code, only the English prefix
        attempt.id, phase="needs_review", error=f"{OUTPUT_LIMIT_MARK} the outputs total 9 bytes",
        error_code="", error_params="{}",
    )  # fmt: skip
    with pytest.raises(Exception, match="over the limit"):
        await env.service.fetch_compute_artifacts(attempt.id, "alice", tmp_path / "out")


async def test_a_coded_output_limit_is_final_even_if_the_english_text_changed(env, tmp_path):
    attempt = await finished(env)
    env.service._update(
        attempt.id, phase="needs_review", error="too big", error_code="output_limit"
    )
    with pytest.raises(Exception, match="over the limit"):
        await env.service.fetch_compute_artifacts(attempt.id, "alice", tmp_path / "out")


def test_after_the_migration_an_old_row_reads_with_no_code(tmp_path):
    from growbridge.archive.db import Database

    path = tmp_path / "old.db"
    db = Database(path)
    db.migrate("compute", service_module.STEPS[:-2])  # the schema before this change
    db.execute(
        "INSERT INTO compute_attempts(id, task_id, submitter, csc_user, template_id,"
        " template_version, params, inputs, phase, reserved_cpu, reserved_storage,"
        " analysis_version, root_id, error, created_at, updated_at)"
        " VALUES('a1','t1','alice','u','segment',1,'{}','{}','queued',1,1,1,'a1','old words',1,1)"
    )
    db.migrate("compute", service_module.STEPS)
    row = db.one("SELECT error, error_code, error_params FROM compute_attempts")
    assert (row["error"], row["error_code"], row["error_params"]) == ("old words", "", "{}")
    db.close()


# --- what the overview says about a stuck attempt ------------------------------------------------


async def test_a_stuck_attempt_waiting_for_reconciliation_says_reconcile_wait(env):
    env.backend.lose_receipt = True
    await submit(env)
    env.clock.advance(RECONCILE_AFTER + 1)
    (stuck,) = env.service.overview()["stuck"]
    assert stuck["reason_code"] == "reconcile_wait"
    assert stuck["reason_params"] == {"age_seconds": int(RECONCILE_AFTER + 1)}
    assert "reconciliation" in stuck["reason"]


async def test_a_stuck_attempt_nobody_refreshed_says_not_refreshed(env):
    await submit(env)
    env.clock.advance(STUCK_AFTER_SECONDS + 1)
    (stuck,) = env.service.overview()["stuck"]
    assert stuck["reason_code"] == "not_refreshed"
    assert stuck["reason_params"] == {"age_seconds": int(STUCK_AFTER_SECONDS + 1)}
    assert stuck["reason"].startswith("not refreshed for ")


async def test_a_stuck_attempt_with_an_error_carries_the_errors_code_and_params(env, tmp_path):
    attempt = await finished(env)
    env.backend.artifacts = {"big.bin": b"x" * 2000}
    with pytest.raises(OutputTooLarge):
        await env.service.fetch_compute_artifacts(attempt.id, "alice", tmp_path / "out")
    (stuck,) = env.service.overview()["stuck"]
    assert stuck["reason_code"] == "error" and stuck["reason_params"] == {}
    assert stuck["error_code"] == "output_limit"
    assert stuck["error_params"] == {"limit_kind": "total", "bytes": 2000, "limit": 500}
    assert stuck["reason"].startswith("error: output limit:")


async def test_a_stuck_attempt_with_an_old_error_has_an_empty_error_code(env):
    attempt = await submit(env)
    env.service._update(attempt.id, error="scheduler unreachable")
    (stuck,) = env.service.overview()["stuck"]
    assert stuck["reason_code"] == "error" and stuck["error_code"] == ""
    assert stuck["error_params"] == {}


async def test_the_settle_response_carries_the_code(env):
    from growbridge.compute.errors import coded as coded_columns

    attempt = await submit(env)
    settled = await env.service.settle_attempt(attempt.id, "carol", "gone")
    assert (settled.error_code, settled.error_params) == ("settled_by_operator", {})
    assert coded_columns("settled_by_operator")["error_code"] == "settled_by_operator"
