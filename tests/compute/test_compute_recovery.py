"""No attempt stays stuck with its reservation held: the tick recovers it, or an operator does.

Common rule: when the outcome of a job is unknown, the attempt is charged its full reservation,
never zero.
"""

import asyncio

import pytest
from compute_support import GOOD_PARAMS, INPUTS

from growbridge.compute.phases import (
    POLL_AFTER_SECONDS,
    RECONCILE_AFTER_SECONDS,
    STUCK_AFTER_SECONDS,
    TICK_EVERY_SECONDS,
)
from growbridge.ports import Denied
from growbridge.workflow.states import TaskState


async def submit(env, who="alice"):
    return await env.service.submit_compute_job("t1", who, "segment", GOOD_PARAMS, INPUTS)


def usage(env, attempt_id):
    row = env.db.one(
        "SELECT reserved_cpu, reserved_storage, used_cpu, used_storage, phase, error,"
        " settled_by, settle_reason FROM compute_attempts WHERE id = ?",
        (attempt_id,),
    )
    return dict(row)


def mark(env):
    """Let the rate limit of the tick pass, and the attempts get old enough to be looked at."""
    env.clock.advance(RECONCILE_AFTER_SECONDS + 1)


# --- the tick ------------------------------------------------------------------------------------


async def test_compute_tick_reconciles_a_lost_receipt_without_any_model_action(env):
    env.backend.lose_receipt = True
    attempt = await submit(env)
    assert attempt.task_state is TaskState.RECONCILE

    await env.service.tick()  # too young: the submit may still be answering
    assert env.service._load(attempt.id).task_state is TaskState.RECONCILE

    mark(env)
    await env.service.tick()

    found = env.service._load(attempt.id)
    assert found.task_state is TaskState.REMOTE_QUEUED and found.remote_job_id is not None
    assert len(env.backend.submit_calls) == 1  # found by name, never resubmitted


async def test_compute_tick_settles_a_crashed_prepared_attempt_at_the_full_reservation(env):
    template = env.service.templates["segment"]
    crashed = env.service._reserve(  # reserved, then the process died before it submitted
        "t1", "alice", "csc_alice", template, {"epochs": 3}, {"images": "s1/images"}
    )
    mark(env)

    await env.service.tick()

    row = usage(env, crashed.id)
    assert row["phase"] == "failed" and row["reserved_cpu"] == 0.0
    assert (row["used_cpu"], row["used_storage"]) == (10.0, 5.0)  # unknown outcome: full charge
    assert "unknown" in row["error"]


async def test_compute_tick_settles_a_job_that_finished_while_nobody_asked(env):
    attempt = await submit(env)
    env.backend.set_usage(cpu=2.0, storage=1.0)
    env.backend.finish(attempt.remote_job_id)
    env.clock.advance(POLL_AFTER_SECONDS + 1)

    await env.service.tick()

    row = usage(env, attempt.id)
    assert row["phase"] == "fetching" and row["reserved_cpu"] == 0.0
    assert (row["used_cpu"], row["used_storage"]) == (2.0, 1.0)


async def test_compute_tick_is_rate_limited(env):
    env.backend.lose_receipt = True
    await submit(env)
    mark(env)
    calls = []
    original = env.backend.find_by_name

    async def counting(name):
        calls.append(name)
        return await original(name)

    env.backend.find_by_name = counting
    await env.service.tick()
    await env.service.tick()  # within the interval: nothing happens

    assert len(calls) == 1
    env.clock.advance(TICK_EVERY_SECONDS + 1)
    await env.service.tick()
    assert len(calls) == 1  # the attempt was already reconciled: nothing left to look at


async def test_compute_tick_skips_an_attempt_whose_submit_is_still_in_flight(env):
    env.backend.hold("submit")
    task = asyncio.create_task(submit(env))
    await env.backend.entered["submit"].wait()
    mark(env)

    await env.service.tick()  # the attempt is old, but the answer has not come back yet

    env.backend.release("submit")
    attempt = await task
    assert attempt.task_state is TaskState.REMOTE_QUEUED
    assert usage(env, attempt.id)["reserved_cpu"] == 10.0  # not settled behind its back


async def test_compute_tick_goes_on_after_one_attempt_fails_and_records_why(env):
    first, second = await submit(env), await submit(env, "bob")
    env.backend.finish(second.remote_job_id)
    original = env.backend.status

    async def flaky(job_id):
        if job_id == first.remote_job_id:
            raise RuntimeError("scheduler unreachable")
        return await original(job_id)

    env.backend.status = flaky
    env.clock.advance(POLL_AFTER_SECONDS + 1)

    await env.service.tick()

    assert usage(env, second.id)["phase"] == "fetching"  # the other one was not held up
    failing = usage(env, first.id)
    assert failing["phase"] == "queued" and "scheduler unreachable" in failing["error"]


# --- reconcile of a job that is not there -----------------------------------------------------


async def test_compute_reconcile_without_a_trace_charges_the_full_reservation_and_cleans_up(env):
    env.backend.lose_receipt = True
    attempt = await submit(env)
    env.backend.forget_jobs()  # it finished and dropped out of the listing, or never existed

    result = await env.service.reconcile(attempt.id)

    row = usage(env, attempt.id)
    assert result.task_state is TaskState.NEEDS_ATTENTION
    assert (row["used_cpu"], row["used_storage"]) == (10.0, 5.0)
    assert row["reserved_cpu"] == 0.0 and "unknown" in row["error"]
    assert env.backend.cleaned_names == [attempt.job_name]


async def test_compute_reconcile_survives_a_cleanup_that_fails(env):
    env.backend.lose_receipt = True
    attempt = await submit(env)
    env.backend.forget_jobs()
    env.backend.fail_cleanup = True

    await env.service.reconcile(attempt.id)

    row = usage(env, attempt.id)
    assert row["phase"] == "failed" and "cleanup" in row["error"]  # said, not raised


# --- cancel --------------------------------------------------------------------------------------


async def test_compute_cancel_of_a_vanished_job_settles_at_the_full_reservation(env):
    attempt = await submit(env)
    env.backend.forget_jobs()  # status will fail after the cancel

    await env.service.cancel(attempt.id, "alice")

    row = usage(env, attempt.id)
    assert row["phase"] == "failed" and row["reserved_cpu"] == 0.0
    assert (row["used_cpu"], row["used_storage"]) == (10.0, 5.0)
    assert env.backend.cancelled == [attempt.remote_job_id]


# --- the operator --------------------------------------------------------------------------------


async def test_compute_operator_settles_a_stuck_attempt_and_is_recorded(env):
    attempt = await submit(env)
    env.backend.finish(attempt.remote_job_id)
    env.backend.forget_jobs()  # completed, but FirecREST no longer lists it
    with pytest.raises(Exception, match="unknown job"):
        await env.service.get_compute_job(attempt.id, "alice")

    settled = await env.service.settle_attempt(attempt.id, "carol", "job no longer listed")

    row = usage(env, attempt.id)
    assert settled.task_state is TaskState.NEEDS_ATTENTION
    assert row["phase"] == "failed" and row["reserved_cpu"] == 0.0
    assert (row["used_cpu"], row["used_storage"]) == (10.0, 5.0)
    assert (row["settled_by"], row["settle_reason"]) == ("carol", "job no longer listed")
    assert env.backend.cancelled == [attempt.remote_job_id]  # best effort
    assert env.backend.cleaned_names == [attempt.job_name]


async def test_compute_operator_settle_goes_on_when_the_remote_steps_fail(env):
    attempt = await submit(env)
    env.backend.fail_cleanup = True

    async def broken(job_id):
        raise RuntimeError("cannot reach the scheduler")

    env.backend.cancel = broken

    await env.service.settle_attempt(attempt.id, "carol", "scheduler gone")

    row = usage(env, attempt.id)
    assert row["phase"] == "failed" and row["reserved_cpu"] == 0.0
    assert "cannot reach the scheduler" in row["error"] and "cleanup" in row["error"]


async def test_compute_operator_settles_a_fetch_that_can_never_finish(env):
    attempt = await submit(env)
    env.backend.set_usage(cpu=2.0, storage=1.0)
    env.backend.finish(attempt.remote_job_id)
    await env.service.get_compute_job(attempt.id, "alice")  # now in fetching, usage settled

    settled = await env.service.settle_attempt(attempt.id, "carol", "outputs are gone")

    row = usage(env, attempt.id)
    assert settled.task_state is TaskState.NEEDS_ATTENTION
    assert (row["used_cpu"], row["used_storage"]) == (2.0, 1.0)  # already charged: not again


@pytest.mark.parametrize("phase_setup", ["done", "cancelled", "failed"])
async def test_compute_operator_cannot_settle_what_is_already_final(env, phase_setup, tmp_path):
    attempt = await submit(env)
    if phase_setup == "done":
        env.backend.finish(attempt.remote_job_id)
        await env.service.get_compute_job(attempt.id, "alice")
        await env.service.fetch_compute_artifacts(attempt.id, "alice", tmp_path / "out")
    elif phase_setup == "cancelled":
        await env.service.cancel(attempt.id, "alice")
    else:
        env.backend.finish(attempt.remote_job_id, ok=False)
        await env.service.get_compute_job(attempt.id, "alice")

    with pytest.raises(Denied) as info:
        await env.service.settle_attempt(attempt.id, "carol", "why not")
    assert info.value.code == "state"


async def test_compute_settling_twice_charges_once(env):
    attempt = await submit(env)
    await env.service.settle_attempt(attempt.id, "carol", "first")

    with pytest.raises(Denied):
        await env.service.settle_attempt(attempt.id, "dave", "second")

    row = usage(env, attempt.id)
    assert (row["used_cpu"], row["settled_by"]) == (10.0, "carol")


@pytest.mark.parametrize("reason", ["", "   "])
async def test_compute_settling_needs_a_reason(env, reason):
    attempt = await submit(env)
    with pytest.raises(Denied) as info:
        await env.service.settle_attempt(attempt.id, "carol", reason)
    assert info.value.code == "param"
    assert usage(env, attempt.id)["reserved_cpu"] == 10.0


async def test_compute_settling_an_unknown_attempt_is_refused(env):
    with pytest.raises(Denied) as info:
        await env.service.settle_attempt("att_nope", "carol", "why")
    assert info.value.code == "state"


async def test_compute_settled_attempt_frees_its_quota(env):
    service = await env.build(task_cpu=15.0)
    first = await service.submit_compute_job("t1", "alice", "segment", GOOD_PARAMS, INPUTS)
    await service.settle_attempt(first.id, "carol", "stuck")

    with pytest.raises(Denied):  # 10 h were charged as unknown: 5 h left, a new job needs 10
        await service.submit_compute_job("t1", "alice", "segment", GOOD_PARAMS, INPUTS)


# --- what is shown as stuck ---------------------------------------------------------------------


async def test_compute_overview_lists_attempts_that_wait_for_reconciliation(env):
    env.backend.lose_receipt = True
    attempt = await submit(env)
    assert env.service.overview()["stuck"] == []  # young: still being answered

    mark(env)

    (stuck,) = env.service.overview()["stuck"]
    assert stuck["attempt_id"] == attempt.id and stuck["phase"] == "reconcile"
    assert "reconcil" in stuck["reason"]

    await env.service.tick()
    assert env.service.overview()["stuck"] == []


async def test_compute_overview_lists_a_job_nobody_has_been_able_to_poll(env):
    attempt = await submit(env)
    env.clock.advance(STUCK_AFTER_SECONDS + 1)  # no tick ran, nothing refreshed it

    (stuck,) = env.service.overview()["stuck"]

    assert stuck["attempt_id"] == attempt.id and stuck["phase"] == "queued"


async def test_compute_overview_lists_an_attempt_with_a_recorded_error(env):
    attempt = await submit(env)
    env.service._update(attempt.id, error="scheduler unreachable")

    (stuck,) = env.service.overview()["stuck"]

    assert stuck["reason"].startswith("error") and "scheduler unreachable" in stuck["reason"]


async def test_compute_a_healthy_queued_job_is_not_stuck(env):
    await submit(env)
    assert env.service.overview()["stuck"] == []
