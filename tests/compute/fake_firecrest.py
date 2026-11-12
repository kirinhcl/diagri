"""An in-memory stand-in for ``firecrest.v2.AsyncFirecrest``.

The methods take exactly the keyword names documented at
https://pyfirecrest.readthedocs.io/en/stable/reference_async_v2.html, so a call with a wrong
keyword fails here. It keeps a small remote file system and a job table.
"""

import hashlib
import re
from typing import Any

JOB_NAME = re.compile(r"^#SBATCH --job-name=(\S+)$", re.MULTILINE)


class FakeFirecrest:
    def __init__(self) -> None:
        self.dirs: set[str] = set()
        self.files: dict[str, bytes] = {}
        self.jobs: list[dict[str, Any]] = []
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.submitted: list[dict[str, Any]] = []
        self.checksum_shape = "plain"  # "plain" or "wrapped" (under an "output" key)
        self.checksum_algorithm = "SHA-256"
        self.checksum_override: str | None = None
        self.listing_override: list[Any] | None = None
        self.reply_override: Any = None  # replaces the submit reply
        self.fail: dict[str, Exception] = {}  # method name -> error to raise
        self.next_id = 1001

    # -- test controls --------------------------------------------------------------------
    def set_state(self, jobid: str, state: Any) -> None:
        for job in self.jobs:
            if str(job["jobId"]) == str(jobid):
                job["status"]["state"] = state

    def put_output(self, jobid: str, name: str, content: bytes) -> None:
        job = next(j for j in self.jobs if str(j["jobId"]) == str(jobid))
        self.files[f"{job['workingDirectory']}/out/{name}"] = content

    def _record(self, method: str, **kwargs: Any) -> None:
        self.calls.append((method, kwargs))
        if method in self.fail:
            raise self.fail[method]

    def called(self, method: str) -> list[dict[str, Any]]:
        return [kwargs for name, kwargs in self.calls if name == method]

    # -- documented API -------------------------------------------------------------------
    async def mkdir(self, system_name: str, path: str, create_parents: bool = False) -> dict:
        self._record("mkdir", system_name=system_name, path=path, create_parents=create_parents)
        self.dirs.add(path)
        return {}

    async def upload(
        self,
        system_name: str,
        local_file: Any,
        directory: str,
        filename: str,
        account: str | None = None,
        blocking: bool = True,
        transfer_method: str = "s3",
    ) -> None:
        self._record(
            "upload",
            system_name=system_name,
            local_file=local_file,
            directory=directory,
            filename=filename,
            account=account,
        )
        with open(local_file, "rb") as stream:
            self.files[f"{directory}/{filename}"] = stream.read()

    async def submit(
        self,
        system_name: str,
        working_dir: str,
        script_str: str | None = None,
        script_local_path: str | None = None,
        script_remote_path: str | None = None,
        env_vars: dict[str, str] | None = None,
        account: str | None = None,
        partition: str | None = None,
        reservation: str | None = None,
    ) -> Any:
        record = {
            "system_name": system_name,
            "working_dir": working_dir,
            "script_str": script_str,
            "env_vars": env_vars,
            "account": account,
        }
        self._record("submit", **record)
        self.submitted.append(record)
        if self.reply_override is not None:
            return self.reply_override
        match = JOB_NAME.search(script_str or "")
        jobid = str(self.next_id)
        self.next_id += 1
        self.jobs.append(
            {
                "jobId": int(jobid),
                "name": match.group(1) if match else "submit",
                "status": {"state": "PENDING", "stateReason": "None", "exitCode": 0},
                "workingDirectory": working_dir,
            }
        )
        return {"jobId": int(jobid)}

    async def job_info(
        self,
        system_name: str,
        jobid: Any = None,
        allusers: bool = False,
        account: str | None = None,
        name: str | None = None,
        time_window: Any = None,
    ) -> list[dict[str, Any]]:
        self._record("job_info", system_name=system_name, jobid=jobid, name=name)
        found = [j for j in self.jobs if jobid is None or str(j["jobId"]) == str(jobid)]
        if name is not None:  # the real filter may be a prefix or pattern match: be generous
            found = [j for j in self.jobs if j["name"].startswith(name)]
        return [dict(job) for job in found]

    async def cancel_job(self, system_name: str, jobid: Any) -> dict:
        self._record("cancel_job", system_name=system_name, jobid=jobid)
        self.set_state(jobid, "CANCELLED")
        return {}

    async def list_files(
        self, system_name: str, path: str, show_hidden: bool = False, recursive: bool = False
    ) -> list[Any]:
        self._record("list_files", system_name=system_name, path=path)
        if self.listing_override is not None:
            return self.listing_override
        prefix = path.rstrip("/") + "/"
        names = sorted(p[len(prefix) :] for p in self.files if p.startswith(prefix))
        return [
            {"name": n, "type": "-", "size": len(self.files[prefix + n])}
            for n in names
            if "/" not in n
        ]

    async def download(
        self,
        system_name: str,
        source_path: str,
        target_path: Any,
        account: str | None = None,
        blocking: bool = True,
        transfer_method: str = "s3",
    ) -> None:
        self._record(
            "download", system_name=system_name, source_path=source_path, target_path=target_path
        )
        with open(target_path, "wb") as stream:
            stream.write(self.files[source_path])

    async def checksum(self, system_name: str, path: str) -> dict:
        self._record("checksum", system_name=system_name, path=path)
        digest = self.checksum_override or hashlib.sha256(self.files[path]).hexdigest()
        body = {"algorithm": self.checksum_algorithm, "checksum": digest}
        return {"output": body} if self.checksum_shape == "wrapped" else body

    async def rm(
        self,
        system_name: str,
        path: str,
        account: str | None = None,
        blocking: bool = True,
        timeout: Any = None,
    ) -> None:
        self._record("rm", system_name=system_name, path=path)
        self.files = {
            p: c for p, c in self.files.items() if p != path and not p.startswith(path + "/")
        }
        self.dirs = {d for d in self.dirs if d != path and not d.startswith(path + "/")}
