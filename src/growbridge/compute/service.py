"""Compute submission service (architecture doc §9.4).

Sends registered job templates to a ``ComputeBackend`` after checking membership, parameters and
three quotas (task budget, service cap, last recorded project balance). The attempt id is stored
before submission and becomes the remote job name ``gb-<attempt_id>``, so a lost receipt can be
reconciled by name instead of resubmitting.

Accounting: compute (cpu hours) and storage (GB) are separate quotas. The project balance is a
compute balance only; the backend exposes no storage balance.
"""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from growbridge.archive.db import Database
from growbridge.archive.ids import file_digest, new_id
from growbridge.archive.models import Model
from growbridge.compute.backend import (
    ComputeBackend,
    JobTemplate,
    ParamSpec,
    RemoteJob,
    SubmitRejected,
)
from growbridge.ports import Denied
from growbridge.workflow.states import TaskState

Phase = Literal[
    "prepared", "queued", "running", "reconcile", "fetching", "needs_review", "failed",
    "done", "cancelled",
]  # fmt: skip
PHASE_STATE: dict[str, TaskState] = {
    "prepared": TaskState.IN_PROGRESS,
    "queued": TaskState.REMOTE_QUEUED,
    "running": TaskState.COMPUTING,
    "reconcile": TaskState.RECONCILE,
    "fetching": TaskState.FETCHING,
    "needs_review": TaskState.NEEDS_REVIEW,
    "failed": TaskState.NEEDS_ATTENTION,
    "done": TaskState.DONE,
    "cancelled": TaskState.ENDED,
}
REMOTE_PHASE = {
    "queued": "queued", "running": "running", "completed": "fetching",
    "failed": "failed", "cancelled": "cancelled",
}  # fmt: skip
POLLED = ("queued", "running")
LIVE = ("prepared", "reconcile", "queued", "running")  # not yet settled
FETCHABLE = ("fetching", "needs_review", "failed")
STEPS = [
    "CREATE TABLE compute_attempts(id TEXT PRIMARY KEY, task_id TEXT NOT NULL,"
    " submitter TEXT NOT NULL, csc_user TEXT NOT NULL, template_id TEXT NOT NULL,"
    " template_version INTEGER NOT NULL, params TEXT NOT NULL, inputs TEXT NOT NULL,"
    " phase TEXT NOT NULL, remote_job_id TEXT, reserved_cpu REAL NOT NULL,"
    " reserved_storage REAL NOT NULL, used_cpu REAL NOT NULL DEFAULT 0,"
    " used_storage REAL NOT NULL DEFAULT 0, analysis_version INTEGER NOT NULL,"
    " parent_id TEXT, root_id TEXT NOT NULL, checksums TEXT NOT NULL DEFAULT '{}',"
    " error TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, updated_at REAL NOT NULL,"
    " settled_at REAL)",
    "CREATE TABLE compute_task_budgets(task_id TEXT PRIMARY KEY, cpu_hours REAL NOT NULL,"
    " storage_gb REAL NOT NULL)",
    "CREATE TABLE compute_balances(id INTEGER PRIMARY KEY AUTOINCREMENT, balance REAL NOT NULL,"
    " recorded_at REAL NOT NULL)",
]


class ArtifactMismatch(RuntimeError):
    """Fetched artifacts failed verification; the remote files were kept."""


class Attempt(Model):
    id: str
    task_id: str
    submitter: str
    csc_user: str
    template_id: str
    template_version: int
    params: dict[str, Any]
    inputs: dict[str, str]
    phase: Phase
    remote_job_id: str | None = None
    reserved_cpu: float
    reserved_storage: float
    used_cpu: float = 0.0
    used_storage: float = 0.0
    analysis_version: int = 1
    parent_id: str | None = None
    root_id: str
    checksums: dict[str, str] = {}
    error: str = ""
    created_at: float
    updated_at: float

    @property
    def task_state(self) -> TaskState:
        return PHASE_STATE[self.phase]

    @property
    def job_name(self) -> str:
        return f"gb-{self.id}"


def _check_value(name: str, spec: ParamSpec, value: Any) -> Any:
    ok = {
        "int": isinstance(value, int) and not isinstance(value, bool),
        "float": isinstance(value, int | float) and not isinstance(value, bool),
        "str": isinstance(value, str),
        "bool": isinstance(value, bool),
    }[spec.kind]
    if not ok:
        raise Denied("param", f"{name} must be {spec.kind}")
    if spec.kind in ("int", "float") and (
        (spec.minimum is not None and value < spec.minimum)
        or (spec.maximum is not None and value > spec.maximum)
    ):
        raise Denied("param", f"{name} outside {spec.minimum}..{spec.maximum}")
    if spec.choices is not None and value not in spec.choices:
        raise Denied("param", f"{name} must be one of {list(spec.choices)}")
    return value


def validate_params(template: JobTemplate, params: Mapping[str, Any]) -> dict[str, Any]:
    """Return the parameters with defaults filled in, or raise ``Denied("param")``."""
    unknown = sorted(set(params) - set(template.parameters))
    if unknown:
        raise Denied("param", f"unknown parameters {unknown}")
    result: dict[str, Any] = {}
    for name, spec in template.parameters.items():
        if name in params:
            result[name] = _check_value(name, spec, params[name])
        elif spec.default is None:
            raise Denied("param", f"{name} is required")
        else:
            result[name] = spec.default
    return result


def validate_inputs(inputs: Mapping[str, str]) -> dict[str, str]:
    for name, path in inputs.items():
        parts = Path(path).parts
        if not path or Path(path).is_absolute() or ".." in parts:
            raise Denied("param", f"input {name} must be a relative path inside the snapshot")
    return dict(inputs)


class ComputeService:
    def __init__(
        self,
        db: Database,
        clock: Any,
        backend: ComputeBackend,
        templates: Sequence[JobTemplate],
        members: Mapping[str, str],
        service_cpu_cap: float,
        service_storage_cap: float,
    ) -> None:
        self.db, self.clock, self.backend = db, clock, backend
        self.members = dict(members)
        self.service_cpu_cap, self.service_storage_cap = service_cpu_cap, service_storage_cap
        self.templates: dict[str, JobTemplate] = {}
        for template in sorted(templates, key=lambda t: t.version):
            self.templates[template.id] = template  # newest version wins
        self._inflight: set[str] = set()
        db.migrate("compute", STEPS)

    # -- budgets --------------------------------------------------------------------------
    def set_task_budget(self, task_id: str, cpu_hours: float, storage_gb: float) -> None:
        self.db.execute(
            "INSERT INTO compute_task_budgets VALUES (?, ?, ?) ON CONFLICT(task_id)"
            " DO UPDATE SET cpu_hours = excluded.cpu_hours, storage_gb = excluded.storage_gb",
            (task_id, cpu_hours, storage_gb),
        )

    async def refresh_balance(self) -> float:
        value = await self.backend.balance()
        self.db.execute(
            "INSERT INTO compute_balances(balance, recorded_at) VALUES (?, ?)",
            (value, self.clock.now()),
        )
        return value

    def _check_caps(self, task_id: str, template: JobTemplate) -> None:
        budget = self.db.one("SELECT * FROM compute_task_budgets WHERE task_id = ?", (task_id,))
        balance = self.db.one("SELECT * FROM compute_balances ORDER BY id DESC LIMIT 1")
        if budget is None or balance is None:
            raise Denied("quota", "no task budget or project balance recorded")
        sums = "SUM(reserved_cpu + used_cpu) AS c, SUM(reserved_storage + used_storage) AS s"
        task = self.db.one(f"SELECT {sums} FROM compute_attempts WHERE task_id = ?", (task_id,))
        every = self.db.one(f"SELECT {sums} FROM compute_attempts")
        exposure = self.db.one(
            "SELECT SUM(reserved_cpu) + SUM(CASE WHEN settled_at >= ? THEN used_cpu ELSE 0 END)"
            " AS c FROM compute_attempts",
            (balance["recorded_at"],),
        )
        cpu, gb = template.max_cpu_hours, template.max_storage_gb
        checks = [
            ("cpu hours over task budget", cpu, budget["cpu_hours"] - (task["c"] or 0)),
            ("storage over task budget", gb, budget["storage_gb"] - (task["s"] or 0)),
            ("cpu hours over service cap", cpu, self.service_cpu_cap - (every["c"] or 0)),
            ("storage over service cap", gb, self.service_storage_cap - (every["s"] or 0)),
            ("cpu hours over project balance", cpu, balance["balance"] - (exposure["c"] or 0)),
        ]
        for label, need, available in checks:
            if need > available:
                raise Denied("quota", f"{label}: need {need}, available {available}")

    # -- lookup helpers -------------------------------------------------------------------
    def _member(self, submitter: str) -> str:
        if submitter not in self.members:
            raise Denied("member", f"{submitter} is not mapped to a CSC project member")
        return self.members[submitter]

    def _load(self, attempt_id: str) -> Attempt:
        row = self.db.one("SELECT * FROM compute_attempts WHERE id = ?", (attempt_id,))
        if row is None:
            raise Denied("state", f"unknown attempt {attempt_id}")
        data = dict(row)
        data.pop("settled_at")
        for key in ("params", "inputs", "checksums"):
            data[key] = json.loads(data[key])
        return Attempt(**data)

    def _owned(self, attempt_id: str, submitter: str) -> Attempt:
        self._member(submitter)
        attempt = self._load(attempt_id)
        if attempt.submitter != submitter:
            raise Denied("scope", "the attempt belongs to another submitter")
        return attempt

    def _update(
        self,
        attempt_id: str,
        allowed: Sequence[str] | None = None,
        unsettled: bool = False,
        **columns: Any,
    ) -> bool:
        """Write columns; with ``allowed``/``unsettled`` the write is a guarded transition.

        A late writer (a poll or submit that raced a cancel or reconcile) matches no row and
        returns False, so it cannot resurrect a settled attempt or settle it twice.
        """
        columns["updated_at"] = self.clock.now()
        assignments = ", ".join(f"{name} = ?" for name in columns)
        sql, params = f"UPDATE compute_attempts SET {assignments} WHERE id = ?", [*columns.values()]
        params.append(attempt_id)
        if allowed is not None:
            sql += f" AND phase IN ({', '.join('?' * len(allowed))})"
            params.extend(allowed)
        if unsettled:
            sql += " AND settled_at IS NULL"
        return self.db.execute(sql, params).rowcount == 1

    def _settle(
        self,
        attempt_id: str,
        phase: str,
        job: RemoteJob | None,
        error: str = "",
        allowed: Sequence[str] = LIVE,
    ) -> bool:
        """Record actual usage (none when ``job`` is None) and release the reservation once."""
        return self._update(
            attempt_id,
            allowed=allowed,
            unsettled=True,
            phase=phase,
            reserved_cpu=0.0,
            reserved_storage=0.0,
            used_cpu=job.cpu_hours_used if job else 0.0,
            used_storage=job.storage_gb_used if job else 0.0,
            settled_at=self.clock.now(),
            error=error,
            remote_job_id=job.job_id if job else None,
        )

    def _apply_remote(self, attempt_id: str, job: RemoteJob) -> bool:
        phase = REMOTE_PHASE[job.state]
        if phase in POLLED:
            return self._update(
                attempt_id, LIVE, unsettled=True, phase=phase, remote_job_id=job.job_id
            )
        return self._settle(attempt_id, phase, job)

    # -- submission -----------------------------------------------------------------------
    async def submit_compute_job(
        self,
        task_id: str,
        submitter: str,
        template_id: str,
        params: Mapping[str, Any],
        inputs: Mapping[str, str],
    ) -> Attempt:
        csc_user = self._member(submitter)
        template = self.templates.get(template_id)
        if template is None:
            raise Denied("param", f"unknown template {template_id}")
        clean = validate_params(template, params)
        attempt = self._reserve(
            task_id, submitter, csc_user, template, clean, validate_inputs(inputs)
        )
        return await self._launch(attempt, template)

    def _reserve(
        self,
        task_id: str,
        submitter: str,
        csc_user: str,
        template: JobTemplate,
        params: dict[str, Any],
        inputs: dict[str, str],
        parent: Attempt | None = None,
        analysis_version: int = 1,
    ) -> Attempt:
        """Check the three caps and insert the reservation in one transaction."""
        attempt_id, now = new_id("att"), self.clock.now()
        root_id = parent.root_id if parent else attempt_id
        with self.db.transaction():
            if parent is not None:
                self._check_retry_limit(root_id, template)
            self._check_caps(task_id, template)
            self.db.execute(
                "INSERT INTO compute_attempts(id, task_id, submitter, csc_user, template_id,"
                " template_version, params, inputs, phase, reserved_cpu, reserved_storage,"
                " analysis_version, parent_id, root_id, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'prepared', ?, ?, ?, ?, ?, ?, ?)",
                (
                    attempt_id, task_id, submitter, csc_user, template.id, template.version,
                    json.dumps(params), json.dumps(inputs), template.max_cpu_hours,
                    template.max_storage_gb, analysis_version, parent.id if parent else None,
                    root_id, now, now,
                ),
            )  # fmt: skip
        return self._load(attempt_id)

    def _check_retry_limit(self, root_id: str, template: JobTemplate) -> None:
        row = self.db.one(
            "SELECT COUNT(*) AS n FROM compute_attempts WHERE root_id = ? AND id != ?",
            (root_id, root_id),
        )
        if row["n"] >= template.max_retries:
            raise Denied("quota", f"retry limit of {template.max_retries} reached")

    async def _launch(self, attempt: Attempt, template: JobTemplate) -> Attempt:
        self._inflight.add(attempt.id)
        try:
            job_id = await self.backend.submit(
                attempt.job_name, template, attempt.params, attempt.inputs
            )
        except SubmitRejected as error:
            self._settle(attempt.id, "failed", None, error=str(error), allowed=("prepared",))
        except Exception as error:  # noqa: BLE001  receipt lost: the job may exist remotely
            if not self._update(attempt.id, ("prepared",), phase="reconcile", error=repr(error)):
                await self._cancel_orphan(attempt, None)
        else:
            adopted = self._update(
                attempt.id, ("prepared",), unsettled=True, phase="queued", remote_job_id=job_id
            )
            if not adopted:
                await self._cancel_orphan(attempt, job_id)
        finally:
            self._inflight.discard(attempt.id)
        return self._load(attempt.id)

    async def _cancel_orphan(self, attempt: Attempt, job_id: str | None) -> None:
        """The attempt was cancelled while its submit was in flight: stop the late remote job."""
        try:
            if job_id is None:
                found = await self.backend.find_by_name(attempt.job_name)
                job_id = found.job_id if found else None
            if job_id is not None:
                await self.backend.cancel(job_id)
        except Exception as error:  # noqa: BLE001  keep the evidence on the cancelled attempt
            self._update(attempt.id, error=f"orphan remote job not cancelled: {error!r}")
            return
        if job_id is not None:
            self._update(attempt.id, remote_job_id=job_id, error="late remote job cancelled")

    # -- query and reconcile --------------------------------------------------------------
    async def get_compute_job(self, attempt_id: str, submitter: str) -> Attempt:
        attempt = self._owned(attempt_id, submitter)
        if attempt.phase in POLLED and attempt.remote_job_id:
            self._apply_remote(attempt_id, await self.backend.status(attempt.remote_job_id))
            return self._load(attempt_id)
        return attempt

    async def reconcile(self, attempt_id: str) -> Attempt:
        attempt = self._load(attempt_id)
        if attempt_id in self._inflight:
            return attempt
        if attempt.phase in ("prepared", "reconcile"):
            job = await self.backend.find_by_name(attempt.job_name)
            if job is None:
                self._settle(attempt_id, "failed", None, error="no remote job found by name")
            else:
                self._apply_remote(attempt_id, job)
        elif attempt.phase in POLLED and attempt.remote_job_id:
            self._apply_remote(attempt_id, await self.backend.status(attempt.remote_job_id))
        return self._load(attempt_id)

    async def cancel(self, attempt_id: str, submitter: str) -> None:
        attempt = self._owned(attempt_id, submitter)
        if attempt.phase not in ("prepared", "reconcile", *POLLED):
            raise Denied("state", f"cannot cancel an attempt in phase {attempt.phase}")
        job_id = attempt.remote_job_id
        if job_id is None:
            found = await self.backend.find_by_name(attempt.job_name)
            job_id = found.job_id if found else None
        job = None
        if job_id is not None:
            await self.backend.cancel(job_id)
            job = await self.backend.status(job_id)
        self._settle(attempt_id, "cancelled", job)

    # -- artifacts and retry --------------------------------------------------------------
    async def fetch_compute_artifacts(
        self, attempt_id: str, submitter: str, out_dir: Path
    ) -> dict[str, str]:
        attempt = self._owned(attempt_id, submitter)
        if attempt.phase not in FETCHABLE or not attempt.remote_job_id:
            raise Denied("state", f"nothing to fetch in phase {attempt.phase}")
        reported = await self.backend.fetch(attempt.remote_job_id, out_dir)
        problems = self._verify(out_dir, reported)
        if problems:
            phase = "failed" if attempt.phase == "failed" else "needs_review"
            self._update(attempt_id, FETCHABLE, phase=phase, error="; ".join(problems))
            raise ArtifactMismatch("; ".join(problems))
        await self.backend.cleanup(attempt.remote_job_id)
        phase = "failed" if attempt.phase == "failed" else "done"
        self._update(attempt_id, FETCHABLE, phase=phase, checksums=json.dumps(reported), error="")
        return reported

    @staticmethod
    def _verify(out_dir: Path, reported: Mapping[str, str]) -> list[str]:
        if not reported:
            return ["no artifacts returned"]
        root, problems = out_dir.resolve(), []
        for name, expected in reported.items():
            path = (out_dir / name).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                problems.append(f"{name}: missing or outside the output directory")
            elif file_digest(path) != expected:
                problems.append(f"{name}: checksum mismatch")
        return problems

    async def retry(self, attempt_id: str, adjustments: dict[str, Any]) -> tuple[Attempt, bool]:
        """Resubmit a failed attempt; returns (new attempt, new analysis version?)."""
        attempt = self._load(attempt_id)
        csc_user = self._member(attempt.submitter)
        if attempt.phase != "failed":
            raise Denied("state", f"only a failed attempt can be retried, not {attempt.phase}")
        template = self.templates.get(attempt.template_id)
        if template is None or template.version != attempt.template_version:
            raise Denied("param", "the template version of the attempt is no longer registered")
        params = validate_params(template, {**attempt.params, **adjustments})
        changed = any(
            name in template.result_changing and params[name] != attempt.params.get(name)
            for name in adjustments
        )
        version = attempt.analysis_version + (1 if changed else 0)
        new = self._reserve(
            attempt.task_id, attempt.submitter, csc_user, template, params, attempt.inputs,
            parent=attempt, analysis_version=version,
        )  # fmt: skip
        return await self._launch(new, template), changed
