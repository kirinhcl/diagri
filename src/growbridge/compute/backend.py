"""Compute backend contract: job templates, remote job records and the backend protocol."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, Protocol

from growbridge.archive.models import Model

ParamKind = Literal["int", "float", "str", "bool"]
RemoteState = Literal["queued", "running", "completed", "failed", "cancelled"]
REMOTE_TERMINAL = frozenset({"completed", "failed", "cancelled"})


class BackendError(RuntimeError):
    """The backend failed in a way that leaves the outcome of the call uncertain."""


class SubmitRejected(BackendError):
    """The backend definitely did not accept the job."""


class BackendUnavailable(RuntimeError):
    """The backend cannot be constructed (missing package or credentials)."""


class ParamSpec(Model):
    kind: ParamKind
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] | None = None
    default: Any = None  # None means the parameter is required


class JobTemplate(Model):
    id: str
    version: int
    script: str
    parameters: dict[str, ParamSpec]
    max_cpu_hours: float
    max_storage_gb: float
    result_changing: tuple[str, ...] = ()  # parameters whose change can alter scientific results
    max_retries: int = 2


class RemoteJob(Model):
    job_id: str
    name: str
    state: RemoteState
    cpu_hours_used: float = 0.0
    storage_gb_used: float = 0.0


class ComputeBackend(Protocol):
    async def submit(
        self,
        job_name: str,
        template: JobTemplate,
        params: Mapping[str, Any],
        inputs: Mapping[str, str],
    ) -> str: ...

    async def find_by_name(self, job_name: str) -> RemoteJob | None: ...

    async def status(self, job_id: str) -> RemoteJob: ...

    async def fetch(self, job_id: str, out_dir: Path) -> dict[str, str]:
        """Copy artifacts into ``out_dir``; return name -> sha256 as computed on the remote."""
        ...

    async def cleanup(self, job_id: str) -> None: ...

    async def cancel(self, job_id: str) -> None: ...

    async def balance(self) -> float: ...
