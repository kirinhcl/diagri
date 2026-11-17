"""Compute backend contract: job templates, remote job records and the backend protocol."""

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import Field, field_validator

from growbridge.archive.models import Model

ParamKind = Literal["int", "float", "str", "bool"]
RemoteState = Literal["queued", "running", "completed", "failed", "cancelled"]
REMOTE_TERMINAL = frozenset({"completed", "failed", "cancelled"})


class BackendError(RuntimeError):
    """The backend failed in a way that leaves the outcome of the call uncertain."""


class SubmitRejected(BackendError):
    """The backend definitely did not accept the job."""


class OutputTooLarge(BackendError):
    """A job's outputs are over a limit; nothing of them was kept locally.

    ``limit_kind`` says which limit ("files": too many files, "total": the outputs together,
    "file": one listed file, "download": a transfer that grew past what was left). ``size`` and
    ``limit`` are byte counts, or None where the limit is not a byte count; for "files",
    ``file_count`` and ``limit_count`` are the number of output files and the most allowed.
    """

    def __init__(
        self,
        message: str,
        *,
        limit_kind: str = "total",
        size: int | None = None,
        limit: int | None = None,
        file_count: int | None = None,
        limit_count: int | None = None,
    ) -> None:
        super().__init__(message)
        self.limit_kind = limit_kind
        self.size = size
        self.limit = limit
        self.file_count = file_count
        self.limit_count = limit_count


class BackendUnavailable(RuntimeError):
    """The backend cannot be constructed (missing package or credentials)."""


class ParamSpec(Model):
    kind: ParamKind
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] | None = None
    # A text value must match ``pattern`` in full (re.fullmatch) and be at most ``max_length``
    # characters. A free text parameter (no ``choices``) has to declare a pattern: a template
    # without one is refused at start (see ``runtime_compute``).
    pattern: str | None = None
    max_length: int | None = Field(default=None, ge=1)
    default: Any = None  # None means the parameter is required

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                re.compile(value)
            except re.error as error:
                raise ValueError(f"not a valid regular expression: {error}") from None
        return value


class JobTemplate(Model):
    id: str
    version: int
    script: str
    parameters: dict[str, ParamSpec]
    max_cpu_hours: float = Field(ge=0, allow_inf_nan=False)
    max_storage_gb: float = Field(ge=0, allow_inf_nan=False)
    result_changing: tuple[str, ...] = ()  # parameters whose change can alter scientific results
    max_retries: int = 2


class RemoteJob(Model):
    job_id: str
    name: str
    state: RemoteState
    # None: the backend cannot report usage, so the service charges the attempt's whole
    # reservation (never less than was possible). A reported 0.0 is a real zero.
    cpu_hours_used: float | None = None
    storage_gb_used: float | None = None


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

    async def fetch(self, job_id: str, out_dir: Path, max_bytes: int) -> dict[str, str]:
        """Copy artifacts into ``out_dir``; return name -> sha256 as computed on the remote.

        At most ``max_bytes`` in total (the attempt's storage reservation, which the service
        passes because the backend does not know it). Over that, or over a file count the backend
        sets, raise ``OutputTooLarge`` and leave nothing of this fetch in ``out_dir``.
        """
        ...

    async def cleanup(self, job_id: str) -> None: ...

    async def cleanup_by_name(self, job_name: str) -> None:
        """Remove what the job of this name left behind, when its id is not known."""
        ...

    async def cancel(self, job_id: str) -> None: ...

    async def balance(self) -> float: ...
