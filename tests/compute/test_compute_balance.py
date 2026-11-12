"""The project balance comes from an operator when the backend cannot report one."""

import math

import pytest
import pytest_asyncio
from compute_support import GOOD_PARAMS, INPUTS, MEMBERS, TEMPLATE

from growbridge.archive.db import Database
from growbridge.compute.service import ComputeService
from growbridge.ports import Denied


@pytest_asyncio.fixture
async def bare(env):
    """A service that has no balance record yet, over a backend that has no balance."""
    env.backend.balance_unavailable = True
    db = Database(env.tmp / "bare.sqlite3")  # not the env fixture's database, which has a balance
    service = ComputeService(
        db,
        env.clock,
        env.backend,
        [TEMPLATE],
        MEMBERS,
        service_cpu_cap=1000.0,
        service_storage_cap=1000.0,
        input_root=env.tmp / "snapshots",
    )
    service.input_guard = lambda task_id, ref: None
    service.set_task_budget("t1", 100.0, 100.0)
    yield service
    db.close()


async def submit(service):
    return await service.submit_compute_job("t1", "alice", "segment", GOOD_PARAMS, INPUTS)


def balances(service):
    return service.db.query("SELECT * FROM compute_balances ORDER BY id")


async def test_compute_unavailable_backend_balance_is_not_zero_and_not_unlimited(env, bare):
    assert await bare.refresh_balance() is None  # nothing known
    with pytest.raises(Denied) as info:
        await submit(bare)
    assert info.value.code == "quota"


async def test_compute_operator_balance_allows_submission_and_is_attributed(env, bare):
    bare.record_balance(500.0, "alice", "MyCSC 2026-11-12")

    attempt = await submit(bare)

    assert attempt.task_state.value == "remote_queued"
    (row,) = balances(bare)
    assert (row["balance"], row["entered_by"], row["note"]) == (500.0, "alice", "MyCSC 2026-11-12")
    assert row["recorded_at"] == env.clock.now()


async def test_compute_refresh_keeps_the_operators_balance_when_the_backend_has_none(env, bare):
    bare.record_balance(500.0, "alice")

    assert await bare.refresh_balance() == 500.0

    assert len(balances(bare)) == 1  # nothing was appended, nothing was zeroed
    await submit(bare)


async def test_compute_balance_records_only_append_and_the_latest_counts(env, bare):
    bare.record_balance(500.0, "alice")
    bare.record_balance(5.0, "alice", "after a big job elsewhere")

    assert [row["balance"] for row in balances(bare)] == [500.0, 5.0]
    with pytest.raises(Denied) as info:  # 5 h are left: a 10 h reservation does not fit
        await submit(bare)
    assert info.value.code == "quota"


async def test_compute_backend_reported_balance_is_recorded_as_the_backend(env):
    env.backend.balance_value = 800.0  # the env fixture's service refreshes from the backend

    await env.service.refresh_balance()

    assert balances(env.service)[-1]["entered_by"] == "backend"


@pytest.mark.parametrize("value", [-1.0, math.nan, math.inf, "12", None, True])
async def test_compute_balance_must_be_a_finite_non_negative_number(env, bare, value):
    with pytest.raises(Denied) as info:
        bare.record_balance(value, "alice")
    assert info.value.code == "param"
    assert balances(bare) == []


@pytest.mark.parametrize(("cpu", "storage"), [(-1.0, 1.0), (1.0, math.nan), (math.inf, 1.0)])
async def test_compute_task_budget_must_be_finite_and_non_negative(env, cpu, storage):
    with pytest.raises(Denied) as info:
        env.service.set_task_budget("t9", cpu, storage)
    assert info.value.code == "param"


async def test_compute_overview_lists_balance_budgets_usage_and_open_jobs(env, bare):
    bare.record_balance(500.0, "alice", "note")
    attempt = await submit(bare)

    view = bare.overview()

    assert view["balance"] == {
        "cpu_hours": 500.0,
        "entered_by": "alice",
        "note": "note",
        "recorded_at": env.clock.now(),
    }
    (task,) = view["tasks"]
    assert task == {
        "task_id": "t1",
        "cpu_hours_budget": 100.0,
        "storage_gb_budget": 100.0,
        "cpu_hours_used": 0.0,
        "storage_gb_used": 0.0,
        "cpu_hours_reserved": 10.0,
        "storage_gb_reserved": 5.0,
    }
    (job,) = view["jobs"]
    assert (job["attempt_id"], job["task_id"], job["phase"]) == (attempt.id, "t1", "queued")
    assert view["service"] == {
        "cpu_hours_cap": 1000.0,
        "storage_gb_cap": 1000.0,
        "cpu_hours_committed": 10.0,
        "storage_gb_committed": 5.0,
    }


async def test_compute_overview_without_a_balance_says_so(bare):
    assert bare.overview()["balance"] is None
