"""FirecREST adapter for CSC Roihu (Slurm), over pyfirecrest's v2 asynchronous client.

NOT VERIFIED AGAINST REAL CSC: everything here follows CSC's and pyfirecrest's documentation and
the Roihu OpenAPI specification, and is tested against a fake client only. What is assumed where
the documentation is silent (each one fails closed with a ``BackendError`` when it is wrong):

* Slurm state names (the specification does not list them): only the states in ``SLURM_STATES``
  are mapped; any other state is an error that names it, never "completed". An attempt that
  cannot be polled to a result is not left stuck: the operator settles it (``/wb/compute``).
* ``list_files`` entries are dicts with a ``name``, a ``type`` ("-" for a regular file) and a
  ``size`` in bytes (an integer or digits); anything else, including a sub-directory or an entry
  without a usable size, is refused rather than skipped or downloaded blind. A fetch is bounded
  by ``MAX_OUTPUT_FILES`` and by the byte limit the service passes (the attempt's storage
  reservation). The listed sizes are checked first; each download is then watched and
  cancelled as soon as its file on disk passes what is left of the limit.
* ``checksum`` may return the checksum object itself or wrapped under ``output``; both are read,
  and only SHA-256 is accepted.
* Slurm takes the job name from ``#SBATCH --job-name`` (``submit`` has no name argument), so the
  generated name is inserted after the interpreter line; a template that sets its own is refused.
* ``job_info(name=...)`` is filtered again here for an exact match. Whether it also finds a job
  that has already finished is not documented: a finished job it cannot find reads as absent.
  The same goes for a finished job whose id ``job_info`` no longer lists: ``status``, ``fetch``
  and ``cleanup`` then fail with "not listed" instead of guessing.

The API reports no CPU or storage usage and has no billing balance: ``status`` returns no usage
(the service then charges the attempt's whole reservation) and ``balance`` is unavailable.

Parameters reach the job only as environment variables (``DIAGRI_PARAM_<NAME>``, input locations
as ``DIAGRI_INPUT_<NAME>``, results go to ``DIAGRI_OUTPUT_DIR``); they are never put into the
script text. Credentials come from environment variables only and are never kept on the object,
logged, or put in an error: a failing client call is reported by its exception class alone.
"""

import asyncio
import os
import re
from collections.abc import Awaitable, Mapping
from pathlib import Path
from typing import Any

from growbridge.compute.backend import (
    BackendError,
    BackendUnavailable,
    JobTemplate,
    OutputTooLarge,
    RemoteJob,
    SubmitRejected,
)

JOB_SETTINGS = ("FIRECREST_SYSTEM", "FIRECREST_ACCOUNT", "FIRECREST_WORKDIR")
CREDENTIALS = (
    "FIRECREST_URL",
    "FIRECREST_TOKEN_URL",
    "FIRECREST_CLIENT_ID",
    "FIRECREST_CLIENT_SECRET",
)
ENV_VARIABLES = (*CREDENTIALS, *JOB_SETTINGS)
SYSTEMS = ("cpu", "gpu")
ACCOUNT = re.compile(r"^[A-Za-z0-9_]{1,64}$")
WORKDIR = re.compile(r"^/[A-Za-z0-9_./-]*$")
JOB_NAME = re.compile(r"^gb-[A-Za-z0-9_-]{1,100}$")
ENV_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,59}$")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
SCRIPT_NAMES_ITSELF = re.compile(r"^[ \t]*#SBATCH\b.*(--job-name|(?:\s|^)-J)", re.MULTILINE)
SCRIPT_SETS_TIME = re.compile(
    r"^[ \t]*#SBATCH\b.*(?:--time(?:[= \t]|$)|\s-t(?:[= \t]|\d|$))", re.MULTILINE
)
# One output file costs a download and a checksum call; this keeps a runaway job (or a template
# that writes one file per sample) from turning a fetch into an unbounded number of API calls.
MAX_OUTPUT_FILES = 1000
# While a file downloads, its size on disk is looked at this often. The most that can be written
# past the byte limit before the watchdog reacts is what the link carries in one interval (about
# 31 MB at 1 Gbit/s) plus what the client writes between two of its own awaits.
WATCH_INTERVAL_SECONDS = 0.25
FILE_TYPES = ("-", "f", "file")
DIRECTORY_TYPES = ("d", "directory")
# Why each: a terminal state ends the attempt (otherwise ``status`` would raise for ever and the
# reservation never be released); a non-terminal one keeps the job live and polled. Nothing that
# is not certain is mapped to "completed".
SLURM_STATES = {
    "PENDING": "queued",
    "CONFIGURING": "queued",
    "RUNNING": "running",
    "COMPLETING": "running",
    "COMPLETED": "completed",
    "FAILED": "failed",
    "TIMEOUT": "failed",
    "OUT_OF_MEMORY": "failed",
    "NODE_FAIL": "failed",
    "CANCELLED": "cancelled",  # sacct may append "by <uid>"; only the first word counts
    # terminal, and not a success: the job will not produce a result
    "DEADLINE": "failed",  # ran past its deadline and was ended
    "PREEMPTED": "failed",  # taken off the nodes by a higher-priority job and not requeued
    "BOOT_FAIL": "failed",  # the node failed to start the job
    "REVOKED": "failed",  # a federated sibling ran it instead, so this one never will
    # not terminal: the scheduler still holds the job and may run it, so it keeps being polled
    "REQUEUED": "queued",  # back in the queue after a node failure or a preemption
    "REQUEUE_HOLD": "queued",  # requeued and held until released
    "SUSPENDED": "running",  # stopped on its nodes, still allocated, may resume
    "STOPPED": "running",  # SIGSTOPped on its nodes, still allocated, may resume
}


def _import_package() -> Any:
    try:
        import firecrest  # the PyPI package ``pyfirecrest``; imported only when it is needed
    except ImportError as error:
        raise BackendUnavailable(
            "the optional package 'pyfirecrest' is not installed (pip install pyfirecrest)"
        ) from error
    return firecrest


def _require(source: Mapping[str, str], names: tuple[str, ...]) -> None:
    missing = [name for name in names if not source.get(name)]
    if missing:
        raise BackendUnavailable(f"missing environment variables: {', '.join(missing)}")


def _job_settings(source: Mapping[str, str]) -> tuple[str, str, str]:
    _require(source, JOB_SETTINGS)
    system, account, workdir = (source[name] for name in JOB_SETTINGS)
    if system not in SYSTEMS:
        raise BackendUnavailable(f"FIRECREST_SYSTEM must be one of {', '.join(SYSTEMS)}")
    if not ACCOUNT.fullmatch(account):
        raise BackendUnavailable("FIRECREST_ACCOUNT is not a valid CSC project name")
    root = workdir.rstrip("/")
    if not WORKDIR.fullmatch(workdir) or not root or ".." in root.split("/"):
        raise BackendUnavailable("FIRECREST_WORKDIR must be an absolute path without '..'")
    return system, account, root


def _default_client(module: Any, source: Mapping[str, str]) -> Any:
    _require(source, CREDENTIALS)
    try:
        auth = module.ClientCredentialsAuth(
            client_id=source["FIRECREST_CLIENT_ID"],
            client_secret=source["FIRECREST_CLIENT_SECRET"],
            token_uri=source["FIRECREST_TOKEN_URL"],
        )
        return module.v2.AsyncFirecrest(firecrest_url=source["FIRECREST_URL"], authorization=auth)
    except Exception as error:  # the message could carry a credential: name the class only
        raise BackendUnavailable(
            f"could not build the FirecREST client ({type(error).__name__}); "
            "this needs pyfirecrest with the v2 API"
        ) from None


def _text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float | str) and "\x00" not in str(value):
        return str(value)
    raise SubmitRejected("a parameter value cannot be passed as an environment variable")


def _job_id(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, int | str) or str(value) == "":
        raise BackendError(f"FirecREST returned no usable job id ({value!r})")
    return str(value)


def _state(raw: Any) -> str:
    words = raw.replace("+", " ").split() if isinstance(raw, str) else []
    mapped = SLURM_STATES.get(words[0].upper()) if words else None
    if mapped is None:
        raise BackendError(f"unrecognised Slurm state {raw!r}; it is not treated as finished")
    return mapped


def _remote_job(entry: Any) -> RemoteJob:
    """One ``JobModel``; usage is left unreported because the API has none."""
    status = entry.get("status") if isinstance(entry, dict) else None
    name = entry.get("name") if isinstance(entry, dict) else None
    if not isinstance(status, dict) or not isinstance(name, str) or not name:
        raise BackendError("FirecREST returned a job record without a name and status")
    return RemoteJob(
        job_id=_job_id(entry.get("jobId")), name=name, state=_state(status.get("state"))
    )


def _size(entry: dict[str, Any], name: str) -> int:
    """The remote size in bytes, or an error: a fetch never downloads blind."""
    size = entry.get("size")
    if isinstance(size, str) and size.isascii() and size.isdigit():
        return int(size)
    if isinstance(size, int) and not isinstance(size, bool) and size >= 0:
        return size
    raise BackendError(f"output {name!r} has no usable size in the listing")


def _file_name(entry: Any) -> str:
    kind = entry.get("type") if isinstance(entry, dict) else None
    name = entry.get("name") if isinstance(entry, dict) else None
    if not isinstance(name, str) or name in ("", ".", "..") or "/" in name or "\x00" in name:
        raise BackendError("FirecREST listed an output file with an unusable name")
    if kind in DIRECTORY_TYPES:
        raise BackendError(f"output {name!r} is a directory; nested outputs are not fetched")
    if kind not in FILE_TYPES:
        raise BackendError(f"output {name!r} has an unrecognised type {kind!r}")
    return name


def _on_disk(path: Path, missing_ok: bool = False) -> int:
    """The size of a downloaded file; a file that is not there after a download that said it
    worked is an error of the backend, not an ``OSError``."""
    try:
        return path.stat().st_size
    except FileNotFoundError:
        if missing_ok:  # the client has not created it yet
            return 0
        raise BackendError("a downloaded output is missing locally") from None
    except OSError as error:
        raise BackendError(f"a downloaded output cannot be read ({type(error).__name__})") from None


def _listed(entry: Any) -> tuple[str, int]:
    name = _file_name(entry)
    return name, _size(entry, name)


def _digest(reply: Any) -> str:
    body = reply.get("output", reply) if isinstance(reply, dict) else None
    algorithm = body.get("algorithm") if isinstance(body, dict) else None
    value = body.get("checksum") if isinstance(body, dict) else None
    plain = re.sub(r"[-_]", "", algorithm).lower() if isinstance(algorithm, str) else ""
    if plain != "sha256":
        raise BackendError("FirecREST returned a checksum that is not SHA-256")
    if not isinstance(value, str) or not SHA256_HEX.fullmatch(value.lower()):
        raise BackendError("FirecREST returned a malformed SHA-256 checksum")
    return value.lower()


class FirecrestBackend:
    """``client`` is an ``AsyncFirecrest``-like object; without one the real client is built from
    the environment (and ``pyfirecrest`` imported) here, not at module import."""

    def __init__(self, client: Any = None, environ: Mapping[str, str] | None = None) -> None:
        source = os.environ if environ is None else environ
        module = _import_package() if client is None else None
        self.system, self.account, self.workdir = _job_settings(source)
        self._client = client if client is not None else _default_client(module, source)

    def __repr__(self) -> str:
        return f"FirecrestBackend(system={self.system!r}, account={self.account!r})"

    # -- helpers --------------------------------------------------------------------------
    async def _call(
        self, operation: str, call: Awaitable[Any], failure: type[BackendError] = BackendError
    ) -> Any:
        try:
            return await call
        except BackendError:
            raise
        except Exception as error:  # never echo the message: it may carry a token or a URL
            raise failure(f"FirecREST {operation} failed ({type(error).__name__})") from None

    def _job_dir(self, job_name: str, failure: type[BackendError] = BackendError) -> str:
        if not JOB_NAME.fullmatch(job_name):
            raise failure(f"{job_name!r} is not a job name of this service")
        return f"{self.workdir}/{job_name}"

    async def _job(self, job_id: str) -> RemoteJob:
        reply = await self._call(
            "job_info", self._client.job_info(system_name=self.system, jobid=str(job_id))
        )
        jobs = [job for job in self._jobs(reply) if job.job_id == str(job_id)]
        if len(jobs) != 1:
            raise BackendError(f"job {job_id} is not listed by FirecREST (found {len(jobs)})")
        return jobs[0]

    @staticmethod
    def _jobs(reply: Any) -> list[RemoteJob]:
        if not isinstance(reply, list):
            raise BackendError("FirecREST returned a job list that is not a list")
        return [_remote_job(entry) for entry in reply]

    # -- submit ---------------------------------------------------------------------------
    @classmethod
    def check_template(cls, template: JobTemplate) -> None:
        """Refuse at start-up what ``submit`` would refuse for every job of this template."""
        cls._script("gb-check", template.script)
        cls._environment("/check", dict.fromkeys(template.parameters, ""), [])

    @staticmethod
    def _script(job_name: str, script: str) -> str:
        if not script.startswith("#!"):
            raise SubmitRejected("the template script must start with an interpreter line (#!)")
        if SCRIPT_NAMES_ITSELF.search(script):
            raise SubmitRejected("the template script must not set its own job name")
        if not SCRIPT_SETS_TIME.search(script):
            raise SubmitRejected("the template script must set a time limit (#SBATCH --time)")
        first, _, rest = script.partition("\n")
        return f"{first}\n#SBATCH --job-name={job_name}\n{rest}"

    @staticmethod
    def _environment(job_dir: str, params: Mapping[str, Any], inputs: list[str]) -> dict[str, str]:
        env = {"DIAGRI_OUTPUT_DIR": f"{job_dir}/out"}
        pairs = [("DIAGRI_PARAM_", n, v) for n, v in params.items()]
        pairs += [("DIAGRI_INPUT_", n, f"{job_dir}/inputs/{n}") for n in inputs]
        for prefix, name, value in pairs:
            key = prefix + name.upper()
            if not ENV_NAME.fullmatch(name) or key in env:
                raise SubmitRejected(f"{name!r} cannot be a unique environment variable name")
            env[key] = _text(value)
        return env

    @staticmethod
    def _uploads(job_dir: str, inputs: Mapping[str, str]) -> list[tuple[Path, str]]:
        """(local file, remote directory) pairs; every input is checked before anything is sent."""
        found: list[tuple[Path, str]] = []
        for name, local in inputs.items():
            root = Path(local)
            if not ENV_NAME.fullmatch(name) or root.is_symlink() or not root.exists():
                raise SubmitRejected(f"input {name!r} is not a usable local file or directory")
            base = f"{job_dir}/inputs/{name}"
            files = [root] if root.is_file() else sorted(root.rglob("*"))
            for path in files:
                if path.is_symlink() or not (path.is_file() or path.is_dir()):
                    raise SubmitRejected(f"input {name!r} holds a link or special file")
                if path.is_file():
                    parent = "." if root.is_file() else path.relative_to(root).parent.as_posix()
                    found.append((path, base if parent == "." else f"{base}/{parent}"))
        return found

    async def _send(self, job_dir: str, inputs: Mapping[str, str]) -> None:
        uploads = self._uploads(job_dir, inputs)
        folders = {f"{job_dir}/out", *(f"{job_dir}/inputs/{name}" for name in inputs)}
        folders |= {directory for _, directory in uploads}
        for folder in sorted(folders):
            reply = self._client.mkdir(system_name=self.system, path=folder, create_parents=True)
            await self._call("mkdir", reply, SubmitRejected)
        for path, directory in uploads:
            upload = self._client.upload(
                system_name=self.system,
                local_file=str(path),
                directory=directory,
                filename=path.name,
                account=self.account,
            )
            await self._call("upload", upload, SubmitRejected)

    async def submit(
        self,
        job_name: str,
        template: JobTemplate,
        params: Mapping[str, Any],
        inputs: Mapping[str, str],
    ) -> str:
        """Rejections before the final call are ``SubmitRejected`` (nothing was submitted); a
        failed final call is a plain ``BackendError`` (the job may exist: reconcile by name)."""
        job_dir = self._job_dir(job_name, SubmitRejected)
        script = self._script(job_name, template.script)
        env = self._environment(job_dir, params, list(inputs))
        await self._send(job_dir, inputs)
        reply = await self._call(
            "submit",
            self._client.submit(
                system_name=self.system,
                working_dir=job_dir,
                script_str=script,
                env_vars=env,
                account=self.account,
            ),
        )
        return _job_id(reply.get("jobId") if isinstance(reply, dict) else None)

    # -- query ----------------------------------------------------------------------------
    async def find_by_name(self, job_name: str) -> RemoteJob | None:
        reply = await self._call(
            "job_info", self._client.job_info(system_name=self.system, name=job_name)
        )
        jobs = [job for job in self._jobs(reply) if job.name == job_name]
        if len(jobs) > 1:
            raise BackendError(f"more than one job is named {job_name}")
        return jobs[0] if jobs else None

    async def status(self, job_id: str) -> RemoteJob:
        return await self._job(job_id)

    # -- results --------------------------------------------------------------------------
    async def fetch(self, job_id: str, out_dir: Path, max_bytes: int) -> dict[str, str]:
        job = await self._job(job_id)
        remote = f"{self._job_dir(job.name)}/out"
        listing = await self._call(
            "list_files", self._client.list_files(system_name=self.system, path=remote)
        )
        if not isinstance(listing, list):
            raise BackendError("FirecREST returned an output listing that is not a list")
        listed = [_listed(entry) for entry in listing]  # all of them, before any download
        self._check_listing(listed, max_bytes)
        out_dir.mkdir(parents=True, exist_ok=True)
        downloaded: list[Path] = []
        try:
            return await self._download_all(remote, listed, out_dir, downloaded, max_bytes)
        except BaseException:  # a refusal, a failure or a cancel leaves none of this fetch behind
            for path in downloaded:
                path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _check_listing(listed: list[tuple[str, int]], max_bytes: int) -> None:
        if len(listed) > MAX_OUTPUT_FILES:
            raise OutputTooLarge(
                f"output limit: {len(listed)} output files, over the limit of {MAX_OUTPUT_FILES}",
                limit_kind="files",
            )
        total = sum(size for _, size in listed)
        if total > max_bytes:
            raise OutputTooLarge(
                f"output limit: the outputs total {total} bytes, over the limit of {max_bytes}",
                limit_kind="total",
                size=total,
                limit=max_bytes,
            )

    async def _download_all(
        self,
        remote: str,
        listed: list[tuple[str, int]],
        out_dir: Path,
        downloaded: list[Path],
        max_bytes: int,
    ) -> dict[str, str]:
        """The listed sizes can be wrong and a file can change, so each transfer is bounded by
        what is left of the limit, and the bytes that actually arrive are what counts."""
        sums: dict[str, str] = {}
        total = 0
        for name, size in listed:
            remaining = max_bytes - total
            if size > remaining:
                raise OutputTooLarge(
                    f"output limit: a file listed at {size} bytes does not fit in the {remaining}"
                    f" bytes left of the limit of {max_bytes}",
                    limit_kind="file",
                    size=size,
                    limit=remaining,
                )
            target = out_dir / name
            downloaded.append(target)  # before the download: a partial file is removed as well
            total += await self._transfer(remote, name, target, remaining)
            reply = self._client.checksum(system_name=self.system, path=f"{remote}/{name}")
            sums[name] = _digest(await self._call("checksum", reply))
        return sums

    async def _transfer(self, remote: str, name: str, target: Path, remaining: int) -> int:
        """Download one file and return its size; cancel the transfer the moment the file on disk
        passes ``remaining`` (the client cannot be asked to stop at a size)."""
        download = self._client.download(
            system_name=self.system, source_path=f"{remote}/{name}", target_path=str(target)
        )
        task = asyncio.ensure_future(self._call("download", download))
        try:
            while not task.done():
                await asyncio.wait({task}, timeout=WATCH_INTERVAL_SECONDS)
                if not task.done() and _on_disk(target, missing_ok=True) > remaining:
                    raise OutputTooLarge(
                        f"output limit: a download passed the {remaining} bytes left of the limit",
                        limit_kind="download",
                        size=_on_disk(target, missing_ok=True),
                        limit=remaining,
                    )
            task.result()  # a failed download raises here
        finally:
            if not task.done():  # the limit was hit, or the fetch itself was cancelled
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        size = _on_disk(target)  # a fast transfer can finish between two looks
        if size > remaining:
            raise OutputTooLarge(
                f"output limit: a download of {size} bytes passed the {remaining} bytes left"
                " of the limit",
                limit_kind="download",
                size=size,
                limit=remaining,
            )
        return size

    async def cleanup(self, job_id: str) -> None:
        job = await self._job(job_id)
        path = self._job_dir(job.name)  # only a directory of this service is ever removed
        await self._call("rm", self._client.rm(system_name=self.system, path=path))

    async def cleanup_by_name(self, job_name: str) -> None:
        """For a job whose id is not known: its directory is named after the job."""
        path = self._job_dir(job_name)
        await self._call("rm", self._client.rm(system_name=self.system, path=path))

    async def cancel(self, job_id: str) -> None:
        reply = self._client.cancel_job(system_name=self.system, jobid=str(job_id))
        await self._call("cancel_job", reply)

    async def balance(self) -> float:
        raise BackendUnavailable(
            "FirecREST provides no billing balance; an operator enters the project balance"
        )
