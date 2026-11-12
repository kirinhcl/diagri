"""Hashing a large input or artifact runs in a thread: the event loop (and the executor tick that
shares it) must keep going.

Safety never waits for a model or a transfer. ``serve`` runs the 1 Hz tick in the same event loop
as the compute service, so hashing a whole snapshot inline would stop the protection rules and
the pump interlock for as long as the hash takes (the same reason as the sandbox test in
``tests/e2e/test_e2e_sandbox_blocking.py``).
"""

import asyncio
import threading

from compute_support import GOOD_PARAMS, INPUTS

from growbridge.compute import service as service_module

TICKS_REQUIRED = 3
STUCK_SECONDS = 2.0  # a loop-blocking hash gives up after this long, so the test cannot hang
TEST_SECONDS = 20.0


class SlowWork:
    """Blocks the calling thread until released; records that it was entered and how often."""

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def block(self) -> None:
        self.calls += 1
        self.entered.set()
        self.release.wait(STUCK_SECONDS)


async def ticks_while(work: SlowWork, operation) -> tuple[int, object]:
    """Run ``operation`` while an event-loop ticker counts turns; release the work after a few."""
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while not work.entered.is_set():
            await asyncio.sleep(0.005)
        while not work.release.is_set():
            ticks += 1
            if ticks >= TICKS_REQUIRED:
                work.release.set()
            await asyncio.sleep(0.005)

    ticking = asyncio.create_task(ticker())
    try:
        result = await asyncio.wait_for(operation, TEST_SECONDS)
    finally:
        work.release.set()
        await ticking
    return ticks, result


async def test_compute_the_input_check_does_not_block_the_event_loop(env):
    work = SlowWork()
    env.service.input_guard = lambda task_id, ref: work.block()  # stands in for snapshots.verify

    ticks, attempt = await ticks_while(
        work, env.service.submit_compute_job("t1", "alice", "segment", GOOD_PARAMS, INPUTS)
    )

    assert ticks >= TICKS_REQUIRED, "the event loop was blocked by the input check"
    assert attempt.task_state.value == "remote_queued"


async def test_compute_artifact_hashing_does_not_block_the_event_loop(env, monkeypatch, tmp_path):
    attempt = await env.service.submit_compute_job("t1", "alice", "segment", GOOD_PARAMS, INPUTS)
    env.backend.finish(attempt.remote_job_id)
    await env.service.get_compute_job(attempt.id, "alice")
    work = SlowWork()
    real = service_module.file_digest

    def slow_digest(path):
        work.block()
        return real(path)

    monkeypatch.setattr(service_module, "file_digest", slow_digest)

    ticks, files = await ticks_while(
        work, env.service.fetch_compute_artifacts(attempt.id, "alice", tmp_path / "out")
    )

    assert ticks >= TICKS_REQUIRED, "the event loop was blocked while hashing the artifacts"
    assert set(files) == {"result.csv"}


async def test_compute_a_submit_checks_its_inputs_once(env):
    work = SlowWork()
    work.release.set()  # only counting
    env.service.input_guard = lambda task_id, ref: work.block()

    await env.service.submit_compute_job("t1", "alice", "segment", GOOD_PARAMS, INPUTS)

    assert work.calls == len(INPUTS)  # once per input, not again when the job is launched


async def test_compute_a_retry_checks_its_inputs_once(env):
    attempt = await env.service.submit_compute_job("t1", "alice", "segment", GOOD_PARAMS, INPUTS)
    env.backend.finish(attempt.remote_job_id, ok=False)
    await env.service.get_compute_job(attempt.id, "alice")
    work = SlowWork()
    work.release.set()
    env.service.input_guard = lambda task_id, ref: work.block()

    await env.service.retry(attempt.id, {})

    assert work.calls == len(INPUTS)
