import asyncio

import pytest
from compute_support import GOOD_PARAMS, INPUTS

from growbridge.ports import Denied
from growbridge.workflow.states import TaskState


async def submit(env, who="alice", params=None, inputs=None, task="t1"):
    return await env.service.submit_compute_job(
        task, who, "segment", GOOD_PARAMS if params is None else params, inputs or INPUTS
    )


async def test_compute_submit_records_attempt_and_names_job_after_it(env):
    attempt = await submit(env)

    assert attempt.task_state is TaskState.REMOTE_QUEUED
    assert attempt.csc_user == "csc_alice"
    assert attempt.params["batch_size"] == 32  # default filled in
    assert env.backend.submit_calls == [f"gb-{attempt.id}"]


async def test_compute_attempt_is_durable_before_submit(env):
    seen = []
    original = env.backend.submit

    async def spy(job_name, *args, **kwargs):
        row = env.db.one("SELECT phase FROM compute_attempts WHERE id = ?", (job_name[3:],))
        seen.append(row["phase"])
        return await original(job_name, *args, **kwargs)

    env.backend.submit = spy
    await submit(env)

    assert seen == ["prepared"]


@pytest.mark.parametrize("call", ["submit", "get", "fetch", "cancel"])
async def test_compute_non_member_is_denied_at_every_entry(env, call, tmp_path):
    attempt = await submit(env)
    service = env.service
    calls = {
        "submit": lambda: submit(env, who="mallory"),
        "get": lambda: service.get_compute_job(attempt.id, "mallory"),
        "fetch": lambda: service.fetch_compute_artifacts(attempt.id, "mallory", tmp_path),
        "cancel": lambda: service.cancel(attempt.id, "mallory"),
    }
    with pytest.raises(Denied) as info:
        await calls[call]()
    assert info.value.code == "member"


async def test_compute_other_member_cannot_touch_attempt(env):
    attempt = await submit(env)
    with pytest.raises(Denied) as info:
        await env.service.get_compute_job(attempt.id, "bob")
    assert info.value.code == "scope"


@pytest.mark.parametrize(
    "params",
    [
        {},  # required epochs missing
        {"epochs": 0},
        {"epochs": 101},
        {"epochs": "3"},
        {"epochs": True},
        {"epochs": 3, "model": "huge"},
        {"epochs": 3, "threshold": 1.5},
        {"epochs": 3, "extra": 1},
        {"epochs": 3, "verbose": "yes"},
    ],
)
async def test_compute_invalid_params_are_denied(env, params):
    with pytest.raises(Denied) as info:
        await submit(env, params=params)
    assert info.value.code == "param"
    assert env.backend.submit_calls == []


@pytest.mark.parametrize("path", ["/etc/passwd", "../secret", "a/../../b", ""])
async def test_compute_unsafe_input_path_is_denied(env, path):
    with pytest.raises(Denied) as info:
        await submit(env, inputs={"images": path})
    assert info.value.code == "param"


async def test_compute_unknown_template_is_denied(env):
    with pytest.raises(Denied) as info:
        await env.service.submit_compute_job("t1", "alice", "nope", GOOD_PARAMS, INPUTS)
    assert info.value.code == "param"


async def test_compute_unknown_attempt_is_denied(env):
    with pytest.raises(Denied) as info:
        await env.service.get_compute_job("missing", "alice")
    assert info.value.code == "state"


# Each template job reserves 10 cpu-hours and 5 GB.
CAPS = {
    "task_cpu": {"task_cpu": 15.0},
    "service_cpu": {"cpu_cap": 15.0},
    "task_storage": {"task_storage": 7.0},
    "service_storage": {"storage_cap": 7.0},
}


@pytest.mark.parametrize("name", list(CAPS))
async def test_compute_concurrent_reservations_never_oversell(env, name):
    service = await env.build(**CAPS[name])

    results = await asyncio.gather(
        service.submit_compute_job("t1", "alice", "segment", GOOD_PARAMS, INPUTS),
        service.submit_compute_job("t1", "bob", "segment", GOOD_PARAMS, INPUTS),
        return_exceptions=True,
    )

    denied = [r for r in results if isinstance(r, Denied)]
    assert len(denied) == 1 and denied[0].code == "quota"
    assert len(env.backend.submit_calls) == 1


async def test_compute_project_balance_is_the_third_cap(env):
    env.backend.balance_value = 15.0
    await env.service.refresh_balance()

    await submit(env)
    with pytest.raises(Denied) as info:
        await submit(env, who="bob")
    assert info.value.code == "quota"


async def test_compute_without_budget_or_balance_is_denied(env, tmp_path):
    with pytest.raises(Denied) as info:
        await submit(env, task="no-budget")
    assert info.value.code == "quota"


async def test_compute_storage_and_compute_are_separate_quotas(env):
    # compute is tight, storage is generous: the compute quota alone denies
    service = await env.build(cpu_cap=5.0)
    with pytest.raises(Denied) as info:
        await service.submit_compute_job("t1", "alice", "segment", GOOD_PARAMS, INPUTS)
    assert info.value.code == "quota"
    assert "cpu" in str(info.value)
