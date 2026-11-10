"""FirecREST adapter for CSC Roihu (Slurm).

UNVERIFIED against real CSC: this module has never talked to Roihu. It only validates that the
optional ``pyfirecrest`` package and the credentials are present, and keeps the configuration.
The remote operations are deliberately not implemented, because the ``pyfirecrest`` call
signatures and the Roihu job-script conventions have not been confirmed; each raises
``NotImplementedError`` rather than guessing. Credentials come from environment variables only.
"""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from growbridge.compute.backend import BackendUnavailable, JobTemplate, RemoteJob

ENV_VARIABLES = (
    "FIRECREST_URL",
    "FIRECREST_TOKEN_URL",
    "FIRECREST_CLIENT_ID",
    "FIRECREST_CLIENT_SECRET",
    "FIRECREST_SYSTEM",
)
UNVERIFIED = "FirecrestBackend.{} is not implemented: unverified against real CSC Roihu"


class FirecrestBackend:
    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        try:
            import firecrest  # noqa: F401  (the PyPI package ``pyfirecrest``; imported lazily)
        except ImportError as error:
            raise BackendUnavailable(
                "the optional package 'pyfirecrest' is not installed (pip install pyfirecrest)"
            ) from error
        source = os.environ if environ is None else environ
        missing = [name for name in ENV_VARIABLES if not source.get(name)]
        if missing:
            raise BackendUnavailable(f"missing environment variables: {', '.join(missing)}")
        self.system = source["FIRECREST_SYSTEM"]
        self._url = source["FIRECREST_URL"]
        self._token_url = source["FIRECREST_TOKEN_URL"]
        self._client_id = source["FIRECREST_CLIENT_ID"]
        self._client_secret = source["FIRECREST_CLIENT_SECRET"]

    def __repr__(self) -> str:
        return f"FirecrestBackend(system={self.system!r}, url={self._url!r})"

    async def submit(
        self,
        job_name: str,
        template: JobTemplate,
        params: Mapping[str, Any],
        inputs: Mapping[str, str],
    ) -> str:
        raise NotImplementedError(UNVERIFIED.format("submit"))

    async def find_by_name(self, job_name: str) -> RemoteJob | None:
        raise NotImplementedError(UNVERIFIED.format("find_by_name"))

    async def status(self, job_id: str) -> RemoteJob:
        raise NotImplementedError(UNVERIFIED.format("status"))

    async def fetch(self, job_id: str, out_dir: Path) -> dict[str, str]:
        raise NotImplementedError(UNVERIFIED.format("fetch"))

    async def cleanup(self, job_id: str) -> None:
        raise NotImplementedError(UNVERIFIED.format("cleanup"))

    async def cancel(self, job_id: str) -> None:
        raise NotImplementedError(UNVERIFIED.format("cancel"))

    async def balance(self) -> float:
        raise NotImplementedError(UNVERIFIED.format("balance"))
