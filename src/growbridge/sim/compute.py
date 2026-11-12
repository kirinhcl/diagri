"""In-memory compute backend for tests and simulated runs; never touches the network."""

import asyncio
import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from growbridge.compute.backend import (
    BackendError,
    BackendUnavailable,
    JobTemplate,
    RemoteJob,
    SubmitRejected,
)

WRONG_CHECKSUM = "0" * 64


class FakeBackend:
    def __init__(self) -> None:
        self.jobs: dict[str, RemoteJob] = {}
        self.submit_calls: list[str] = []
        self.submit_inputs: list[dict[str, str]] = []
        self.cleaned: list[str] = []
        self.cleaned_names: list[str] = []
        self.fail_cleanup = False
        self.cancelled: list[str] = []
        self.artifacts: dict[str, bytes] = {"result.csv": b"a,b\n1,2\n"}
        self.lose_receipt = False  # accept the job, then fail the call (receipt lost)
        self.fail_submit = False  # refuse the job outright
        self.wrong_checksums = False  # report checksums that do not match the files
        self.balance_value = 0.0
        self.balance_unavailable = False  # like FirecREST: there is no balance to read
        self.cpu_used: float | None = 0.0  # None: usage is not reported
        self.storage_used: float | None = 0.0
        self.gates: dict[str, asyncio.Event] = {}  # operation -> event the call waits on
        self.released: dict[str, asyncio.Event] = {}
        self.entered: dict[str, asyncio.Event] = {}  # operation -> set when a call arrives

    def hold(self, operation: str) -> None:
        """Make ``submit`` or ``status`` wait (on arrival) until ``release`` is called."""
        self.released[operation] = self.gates[operation] = asyncio.Event()
        self.entered[operation] = asyncio.Event()

    def release(self, operation: str) -> None:
        self.released[operation].set()

    async def _pause(self, operation: str) -> None:
        gate = self.gates.pop(operation, None)  # only the first call is held
        if gate is not None:
            self.entered[operation].set()
            await gate.wait()

    def set_usage(self, cpu: float | None, storage: float | None) -> None:
        self.cpu_used, self.storage_used = cpu, storage

    def set_balance(self, value: float) -> None:
        self.balance_value = value

    def finish(self, job_id: str, ok: bool = True) -> None:
        """Move a job to its terminal state, stamping the configured usage."""
        job = self.jobs[job_id]
        self.jobs[job_id] = job.model_copy(
            update={
                "state": "completed" if ok else "failed",
                "cpu_hours_used": self.cpu_used,
                "storage_gb_used": self.storage_used,
            }
        )

    def forget_jobs(self) -> None:
        self.jobs.clear()

    async def submit(
        self,
        job_name: str,
        template: JobTemplate,
        params: Mapping[str, Any],
        inputs: Mapping[str, str],
    ) -> str:
        self.submit_calls.append(job_name)
        self.submit_inputs.append(dict(inputs))
        await self._pause("submit")
        await asyncio.sleep(0)  # let concurrent callers interleave
        if self.fail_submit:
            raise SubmitRejected("scheduler refused the job")
        job_id = f"job-{len(self.jobs) + 1}"
        self.jobs[job_id] = RemoteJob(
            job_id=job_id,
            name=job_name,
            state="queued",
            cpu_hours_used=0.0,
            storage_gb_used=0.0,
        )
        if self.lose_receipt:
            raise TimeoutError("receipt lost")
        return job_id

    async def find_by_name(self, job_name: str) -> RemoteJob | None:
        return next((job for job in self.jobs.values() if job.name == job_name), None)

    async def status(self, job_id: str) -> RemoteJob:
        snapshot = self.jobs.get(job_id)
        await self._pause("status")
        if snapshot is not None:
            return snapshot
        if job_id not in self.jobs:
            raise BackendError(f"unknown job {job_id}")
        return self.jobs[job_id]

    async def fetch(self, job_id: str, out_dir: Path) -> dict[str, str]:
        out_dir.mkdir(parents=True, exist_ok=True)
        sums: dict[str, str] = {}
        for name, content in self.artifacts.items():
            (out_dir / name).write_bytes(content)
            real = hashlib.sha256(content).hexdigest()
            sums[name] = WRONG_CHECKSUM if self.wrong_checksums else real
        return sums

    async def cleanup(self, job_id: str) -> None:
        self.cleaned.append(job_id)

    async def cleanup_by_name(self, job_name: str) -> None:
        if self.fail_cleanup:
            raise BackendError("cleanup failed")
        self.cleaned_names.append(job_name)

    async def cancel(self, job_id: str) -> None:
        self.cancelled.append(job_id)
        if job_id in self.jobs:  # a job that is no longer listed is accepted and ignored
            self.jobs[job_id] = self.jobs[job_id].model_copy(update={"state": "cancelled"})

    async def balance(self) -> float:
        if self.balance_unavailable:
            raise BackendUnavailable("this backend reports no balance")
        return self.balance_value
