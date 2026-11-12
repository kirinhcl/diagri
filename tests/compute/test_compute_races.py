import asyncio

from compute_support import GOOD_PARAMS, INPUTS

from growbridge.workflow.states import TaskState


def totals(env):
    row = env.db.one(
        "SELECT SUM(reserved_cpu) AS rc, SUM(reserved_storage) AS rs, SUM(used_cpu) AS uc,"
        " COUNT(settled_at) AS settled FROM compute_attempts"
    )
    return row["rc"] or 0.0, row["rs"] or 0.0, row["uc"] or 0.0, row["settled"]


async def start_submit(env):
    env.backend.hold("submit")
    task = asyncio.create_task(
        env.service.submit_compute_job("t1", "alice", "segment", GOOD_PARAMS, INPUTS)
    )
    await env.backend.entered["submit"].wait()
    row = env.db.one("SELECT id FROM compute_attempts")
    return task, row["id"]


async def running_attempt(env):
    attempt = await env.service.submit_compute_job("t1", "alice", "segment", GOOD_PARAMS, INPUTS)
    return attempt


async def test_compute_cancel_during_submit_is_not_resurrected(env):
    task, attempt_id = await start_submit(env)

    await env.service.cancel(attempt_id, "alice")
    env.backend.release("submit")
    await task

    final = await env.service.get_compute_job(attempt_id, "alice")
    assert final.task_state is TaskState.ENDED
    # no remote job was known when it was cancelled: the outcome is unknown, so it is charged
    assert totals(env) == (0.0, 0.0, 10.0, 1)
    # the job accepted after the cancel is cancelled remotely, not adopted
    assert [job.state for job in env.backend.jobs.values()] == ["cancelled"]


async def test_compute_cancel_during_poll_wins_over_stale_status(env):
    attempt = await running_attempt(env)
    env.backend.hold("status")
    poll = asyncio.create_task(env.service.get_compute_job(attempt.id, "alice"))
    await env.backend.entered["status"].wait()

    env.backend.finish(attempt.remote_job_id)  # the poll will see "completed" afterwards
    await env.service.cancel(attempt.id, "alice")
    env.backend.release("status")
    await poll

    final = await env.service.get_compute_job(attempt.id, "alice")
    assert final.task_state is TaskState.ENDED
    assert totals(env)[:2] == (0.0, 0.0)


async def test_compute_reconcile_during_poll_settles_once(env):
    attempt = await running_attempt(env)
    env.backend.set_usage(cpu=2.0, storage=1.0)
    env.backend.finish(attempt.remote_job_id)
    env.backend.hold("status")

    poll = asyncio.create_task(env.service.get_compute_job(attempt.id, "alice"))
    await env.backend.entered["status"].wait()
    reconcile = asyncio.create_task(env.service.reconcile(attempt.id))
    await asyncio.sleep(0)
    env.backend.release("status")
    await asyncio.gather(poll, reconcile)

    final = await env.service.get_compute_job(attempt.id, "alice")
    assert final.task_state is TaskState.FETCHING
    assert totals(env) == (0.0, 0.0, 2.0, 1)  # usage counted once


async def test_compute_double_cancel_releases_once(env):
    attempt = await running_attempt(env)

    await asyncio.gather(
        env.service.cancel(attempt.id, "alice"),
        env.service.cancel(attempt.id, "alice"),
        return_exceptions=True,
    )

    final = await env.service.get_compute_job(attempt.id, "alice")
    assert final.task_state is TaskState.ENDED
    assert totals(env) == (0.0, 0.0, 0.0, 1)


async def test_compute_reconcile_of_lost_receipt_during_late_submit_does_not_double_settle(env):
    task, attempt_id = await start_submit(env)

    during = await env.service.reconcile(attempt_id)  # submit still in flight: left alone
    env.backend.release("submit")
    done = await task

    assert during.task_state is TaskState.IN_PROGRESS
    assert done.task_state is TaskState.REMOTE_QUEUED
    assert totals(env)[:2] == (10.0, 5.0)
