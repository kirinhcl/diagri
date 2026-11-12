"""ComputeService over FirecrestBackend over a fake client: the whole path, no network."""

import pytest
import pytest_asyncio
from fake_firecrest import FakeFirecrest

from growbridge.archive.db import Database
from growbridge.compute.backend import BackendError, JobTemplate, ParamSpec
from growbridge.compute.firecrest import FirecrestBackend
from growbridge.compute.service import ComputeService
from growbridge.ports import Denied
from growbridge.sim.clock import FakeClock
from growbridge.workflow.states import TaskState

ENV = {
    "FIRECREST_SYSTEM": "cpu",
    "FIRECREST_ACCOUNT": "project_2001234",
    "FIRECREST_WORKDIR": "/scratch/project_2001234/diagri",
}
TEMPLATE = JobTemplate(
    id="segment",
    version=1,
    script='#!/bin/bash\n#SBATCH --time=00:10:00\npython run.py "$DIAGRI_INPUT_DATA"\n',
    parameters={"epochs": ParamSpec(kind="int", minimum=1, maximum=100)},
    max_cpu_hours=10.0,
    max_storage_gb=5.0,
)


@pytest_asyncio.fixture
async def stack(tmp_path):
    snapshots = tmp_path / "snapshots"
    (snapshots / "snap-1").mkdir(parents=True)
    (snapshots / "snap-1" / "samples.jsonl").write_text('{"a": 1}\n')
    client = FakeFirecrest()
    db = Database(tmp_path / "compute.sqlite3")
    service = ComputeService(
        db,
        FakeClock(),
        FirecrestBackend(client=client, environ=ENV),
        [TEMPLATE],
        {"researcher": "csc_robot"},
        service_cpu_cap=100.0,
        service_storage_cap=100.0,
        input_root=snapshots,
    )
    service.input_guard = lambda task_id, ref: None
    service.set_task_budget("t1", 50.0, 50.0)
    service.record_balance(500.0, "alice")
    yield service, client, tmp_path
    db.close()


async def submit(service):
    return await service.submit_compute_job(
        "t1", "researcher", "segment", {"epochs": 3}, {"data": "snap-1/samples.jsonl"}
    )


async def test_firecrest_through_the_service_runs_a_job_to_a_verified_fetch(stack):
    service, client, tmp_path = stack

    attempt = await submit(service)
    assert attempt.task_state is TaskState.REMOTE_QUEUED
    assert attempt.remote_job_id == "1001"
    assert client.submitted[0]["working_dir"].endswith(f"/{attempt.job_name}")

    client.set_state("1001", "RUNNING")
    running = await service.get_compute_job(attempt.id, "researcher")
    assert running.task_state is TaskState.COMPUTING
    client.set_state("1001", "COMPLETED")
    client.put_output("1001", "result.csv", b"a,b\n1,2\n")
    done = await service.get_compute_job(attempt.id, "researcher")
    assert done.task_state is TaskState.FETCHING
    assert (done.used_cpu, done.used_storage) == (10.0, 5.0)  # the API reports none: full charge

    files = await service.fetch_compute_artifacts(attempt.id, "researcher", tmp_path / "out")
    assert set(files) == {"result.csv"}
    final = await service.get_compute_job(attempt.id, "researcher")
    assert final.task_state is TaskState.DONE
    assert [c["path"] for c in client.called("rm")] == [client.submitted[0]["working_dir"]]


async def test_firecrest_lost_submit_reply_is_reconciled_by_the_job_name(stack):
    service, client, _ = stack
    original = client.submit

    async def lose_the_reply(**kwargs):
        await original(**kwargs)  # the scheduler accepted the job
        raise TimeoutError("reply lost")

    client.submit = lose_the_reply
    attempt = await submit(service)
    assert attempt.task_state is TaskState.RECONCILE

    found = await service.reconcile(attempt.id)

    assert found.task_state is TaskState.REMOTE_QUEUED
    assert found.remote_job_id == "1001"
    assert len(client.submitted) == 1  # nothing was submitted twice


async def test_firecrest_unknown_state_is_an_error_and_the_job_stays_reserved(stack):
    service, client, _ = stack
    attempt = await submit(service)
    client.set_state("1001", "WEIRD")

    with pytest.raises(BackendError, match="WEIRD"):
        await service.get_compute_job(attempt.id, "researcher")

    held = service._load(attempt.id)
    assert held.task_state is TaskState.REMOTE_QUEUED and held.reserved_cpu == 10.0


async def test_firecrest_a_second_job_does_not_fit_after_a_full_charge(stack):
    service, client, _ = stack
    service.set_task_budget("t1", 15.0, 50.0)
    first = await submit(service)
    client.set_state(first.remote_job_id, "COMPLETED")
    await service.get_compute_job(first.id, "researcher")

    with pytest.raises(Denied) as info:
        await submit(service)
    assert info.value.code == "quota"
