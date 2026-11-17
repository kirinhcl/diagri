"""Compute submission service (architecture doc §9.4).

Sends registered job templates to a ``ComputeBackend`` after checking membership, parameters and
three quotas (task budget, service cap, last recorded project balance). The attempt id is stored
before submission and becomes the remote job name ``gb-<attempt_id>``, so a lost receipt can be
reconciled by name instead of resubmitting.

Accounting: compute (cpu hours) and storage (GB) are separate quotas. The project balance is a
compute balance only; the backend exposes no storage balance. A backend that cannot report a
balance (FirecREST) leaves it to an operator (``record_balance``); a missing balance is never read
as zero or as unlimited. Usage a backend does not report is charged as the whole reservation.

Inputs are references under ``input_root`` (``<snapshot id>/<path>``). The service resolves them to
local paths and hands those to the backend, but only after ``input_guard(task_id, ref)`` has
accepted each one; with a root and no guard, inputs are refused (fail closed).
"""

import asyncio
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from growbridge.archive.db import Database
from growbridge.archive.ids import file_digest, new_id
from growbridge.archive.models import Model
from growbridge.compute import refusals
from growbridge.compute.backend import (
    BackendError,
    BackendUnavailable,
    ComputeBackend,
    JobTemplate,
    OutputTooLarge,
    ParamSpec,
    RemoteJob,
    SubmitRejected,
)
from growbridge.compute.errors import CLEARED, Problem, coded, is_output_limit
from growbridge.compute.overview import build_overview
from growbridge.compute.phases import (
    FETCHABLE,
    LIVE,
    PHASE_STATE,
    POLL_AFTER_SECONDS,
    POLLED,
    RECONCILE_AFTER_SECONDS,
    TICK_BATCH,
    TICK_EVERY_SECONDS,
    Phase,
)
from growbridge.ports import Denied
from growbridge.workflow.states import TaskState

REMOTE_PHASE = {
    "queued": "queued", "running": "running", "completed": "fetching",
    "failed": "failed", "cancelled": "cancelled",
}  # fmt: skip
BYTES_PER_GB = 10**9  # storage is reserved in decimal gigabytes
MAX_TEXT_CHARS = 1000  # no text parameter is longer, whatever its template says
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
    "ALTER TABLE compute_balances ADD COLUMN entered_by TEXT NOT NULL DEFAULT 'backend'",
    "ALTER TABLE compute_balances ADD COLUMN note TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE compute_attempts ADD COLUMN settled_by TEXT",
    "ALTER TABLE compute_attempts ADD COLUMN settle_reason TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE compute_attempts ADD COLUMN storage_limit_gb REAL",
    "ALTER TABLE compute_attempts ADD COLUMN error_code TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE compute_attempts ADD COLUMN error_params TEXT NOT NULL DEFAULT '{}'",
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
    error_code: str = ""  # a compute_error code for ``error``; '' on an attempt from before codes
    error_params: dict[str, Any] = {}
    settled_by: str | None = None  # the operator who settled it by hand, if one did
    settle_reason: str = ""
    storage_limit_gb: float | None = None  # the template's max_storage_gb when it was reserved
    created_at: float
    updated_at: float

    @property
    def task_state(self) -> TaskState:
        return PHASE_STATE[self.phase]

    @property
    def job_name(self) -> str:
        return f"gb-{self.id}"


def _check_text(name: str, spec: ParamSpec, value: str) -> None:
    limit = min(spec.max_length or MAX_TEXT_CHARS, MAX_TEXT_CHARS)
    if len(value) > limit:
        raise refusals.param_too_long(name, limit)
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise refusals.param_bad_characters(name)
    if spec.pattern is not None and re.fullmatch(spec.pattern, value) is None:
        raise refusals.param_bad_format(name)
    if spec.choices is not None and value not in spec.choices:
        raise refusals.param_not_in_choices(name, spec.choices)


def _check_value(name: str, spec: ParamSpec, value: Any) -> Any:
    ok = {
        "int": isinstance(value, int) and not isinstance(value, bool),
        "float": isinstance(value, int | float) and not isinstance(value, bool),
        "str": isinstance(value, str),
        "bool": isinstance(value, bool),
    }[spec.kind]
    if not ok:
        raise refusals.param_wrong_type(name, spec.kind)
    if spec.kind == "float" and not math.isfinite(value):
        raise refusals.param_not_finite(name)
    if spec.kind in ("int", "float") and (
        (spec.minimum is not None and value < spec.minimum)
        or (spec.maximum is not None and value > spec.maximum)
    ):
        raise refusals.param_out_of_range(name, spec.minimum, spec.maximum)
    if spec.kind == "str":
        _check_text(name, spec, value)
    return value


def template_problem(template: JobTemplate) -> str | None:
    """Rules every template must meet, whatever the backend; ``None`` when it meets them."""
    for name, spec in template.parameters.items():
        if spec.kind == "str" and spec.choices is None and spec.pattern is None:
            return f"parameter {name} is free text and must declare a pattern"
        if spec.default is not None:
            try:
                _check_value(name, spec, spec.default)
            except Denied as error:
                return f"the default of parameter {name} is not valid: {error}"
    return None


def validate_params(template: JobTemplate, params: Mapping[str, Any]) -> dict[str, Any]:
    """Return the parameters with defaults filled in, or raise ``Denied("param")``."""
    unknown = sorted(set(params) - set(template.parameters))
    if unknown:
        raise refusals.param_unknown_fields(unknown)
    result: dict[str, Any] = {}
    for name, spec in template.parameters.items():
        if name in params:
            result[name] = _check_value(name, spec, params[name])
        elif spec.default is None:
            raise refusals.param_required(name)
        else:
            result[name] = spec.default
    return result


def _require_amount(value: Any, what: str, field: str) -> None:
    ok = isinstance(value, int | float) and not isinstance(value, bool)
    if not ok or not math.isfinite(value) or value < 0:
        raise refusals.param_negative_amount(field, what)


def _limit_columns(error: OutputTooLarge) -> dict[str, str]:
    """The code and params of a refused fetch, from the numbers the backend measured: too many
    files is counted in files, every other limit in bytes."""
    if error.limit_kind == "files":
        counts = {"file_count": error.file_count, "limit_count": error.limit_count}
        return coded("too_many_files", counts)
    params = {"limit_kind": error.limit_kind, "bytes": error.size, "limit": error.limit}
    return coded("output_limit", params)


def _describe(error: BaseException) -> str:
    """For a record kept on an attempt. A backend's own errors never carry a credential."""
    return f"{type(error).__name__}: {error}"[:300]


def validate_inputs(inputs: Mapping[str, str]) -> dict[str, str]:
    for name, path in inputs.items():
        parts = Path(path).parts
        if not path or Path(path).is_absolute() or ".." in parts:
            raise refusals.param_bad_input_path(name)
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
        input_root: Path | None = None,
    ) -> None:
        self.db, self.clock, self.backend = db, clock, backend
        self.input_root = input_root
        self.input_guard: Callable[[str, str], None] | None = None  # (task_id, input reference)
        self.members = dict(members)
        self.service_cpu_cap, self.service_storage_cap = service_cpu_cap, service_storage_cap
        self.templates: dict[str, JobTemplate] = {}
        for template in sorted(templates, key=lambda t: t.version):
            self.templates[template.id] = template  # newest version wins
        self._inflight: set[str] = set()
        self._last_tick: float | None = None
        db.migrate("compute", STEPS)

    # -- budgets --------------------------------------------------------------------------
    def set_task_budget(self, task_id: str, cpu_hours: float, storage_gb: float) -> None:
        for field, value in (("cpu_hours", cpu_hours), ("storage_gb", storage_gb)):
            _require_amount(value, "a task budget", field)
        self.db.execute(
            "INSERT INTO compute_task_budgets VALUES (?, ?, ?) ON CONFLICT(task_id)"
            " DO UPDATE SET cpu_hours = excluded.cpu_hours, storage_gb = excluded.storage_gb",
            (task_id, cpu_hours, storage_gb),
        )

    def record_balance(self, cpu_hours: float, entered_by: str, note: str = "") -> None:
        """An operator's reading of the project's remaining cpu hours (appended, never edited)."""
        _require_amount(cpu_hours, "a balance", "cpu_hours")
        self.db.execute(
            "INSERT INTO compute_balances(balance, recorded_at, entered_by, note)"
            " VALUES (?, ?, ?, ?)",
            (cpu_hours, self.clock.now(), entered_by, note),
        )

    async def refresh_balance(self) -> float | None:
        """Ask the backend; if it has no balance, keep the latest recorded one (or ``None``)."""
        try:
            value = await self.backend.balance()
        except BackendUnavailable:
            row = self.db.one("SELECT balance FROM compute_balances ORDER BY id DESC LIMIT 1")
            return None if row is None else row["balance"]
        self.record_balance(value, "backend")
        return value

    def _check_caps(self, task_id: str, template: JobTemplate) -> None:
        budget = self.db.one("SELECT * FROM compute_task_budgets WHERE task_id = ?", (task_id,))
        balance = self.db.one("SELECT * FROM compute_balances ORDER BY id DESC LIMIT 1")
        if budget is None or balance is None:
            raise refusals.quota_not_recorded(task_id)
        sums = "SUM(reserved_cpu + used_cpu) AS c, SUM(reserved_storage + used_storage) AS s"
        task = self.db.one(f"SELECT {sums} FROM compute_attempts WHERE task_id = ?", (task_id,))
        every = self.db.one(f"SELECT {sums} FROM compute_attempts")
        exposure = self.db.one(
            "SELECT SUM(reserved_cpu) + SUM(CASE WHEN settled_at >= ? THEN used_cpu ELSE 0 END)"
            " AS c FROM compute_attempts",
            (balance["recorded_at"],),
        )
        cpu, gb = template.max_cpu_hours, template.max_storage_gb
        left = {  # what each limit still allows, per resource
            "task": (budget["cpu_hours"] - (task["c"] or 0),
                     budget["storage_gb"] - (task["s"] or 0)),
            "cap": (self.service_cpu_cap - (every["c"] or 0),
                    self.service_storage_cap - (every["s"] or 0)),
            "balance": balance["balance"] - (exposure["c"] or 0),
        }  # fmt: skip
        over_task, over_cap = refusals.quota_over_task_budget, refusals.quota_over_service_cap
        checks = [
            (over_task, "cpu_hours", cpu, left["task"][0]),
            (over_task, "storage_gb", gb, left["task"][1]),
            (over_cap, "cpu_hours", cpu, left["cap"][0]),
            (over_cap, "storage_gb", gb, left["cap"][1]),
            (refusals.quota_over_balance, "cpu_hours", cpu, left["balance"]),
        ]  # fmt: skip
        for refuse, resource, need, available in checks:
            if need > available:
                raise refuse(resource, need, available)

    # -- lookup helpers -------------------------------------------------------------------
    def _member(self, submitter: str) -> str:
        if submitter not in self.members:
            raise refusals.member_unmapped(submitter)
        return self.members[submitter]

    def _load(self, attempt_id: str) -> Attempt:
        row = self.db.one("SELECT * FROM compute_attempts WHERE id = ?", (attempt_id,))
        if row is None:
            raise refusals.attempt_not_found(attempt_id)
        data = dict(row)
        data.pop("settled_at")
        for key in ("params", "inputs", "checksums", "error_params"):
            data[key] = json.loads(data[key])
        return Attempt(**data)

    def _owned(self, attempt_id: str, submitter: str) -> Attempt:
        self._member(submitter)
        attempt = self._load(attempt_id)
        if attempt.submitter != submitter:
            raise refusals.attempt_other_submitter(attempt_id)
        return attempt

    def _update(
        self,
        attempt_id: str,
        allowed: Sequence[str] | None = None,
        unsettled: bool = False,
        unsettled_by_hand: bool = False,
        **columns: Any,
    ) -> bool:
        """Write columns; with ``allowed``/``unsettled`` the write is a guarded transition.

        A late writer (a poll or submit that raced a cancel or reconcile) matches no row and
        returns False, so it cannot resurrect a settled attempt or settle it twice. With
        ``unsettled_by_hand`` an attempt an operator has settled is left as they left it.
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
        if unsettled_by_hand:
            sql += " AND settled_by IS NULL"
        return self.db.execute(sql, params).rowcount == 1

    def _settle(
        self,
        attempt_id: str,
        phase: str,
        job: RemoteJob | None,
        error: str = "",
        allowed: Sequence[str] = LIVE,
        unknown: bool = False,
        **more: Any,
    ) -> bool:
        """Charge the attempt and release its reservation, once.

        The charge is the reported usage of ``job``, or the whole reservation where the backend
        reports none, or where the outcome is ``unknown`` (never zero then). Only an attempt that
        certainly never reached the scheduler (``job`` None, not ``unknown``) is charged nothing.
        """
        used_cpu, used_storage = self._usage(attempt_id, job, unknown)
        columns: dict[str, Any] = {
            "phase": phase,
            "reserved_cpu": 0.0,
            "reserved_storage": 0.0,
            "used_cpu": used_cpu,
            "used_storage": used_storage,
            "settled_at": self.clock.now(),
            "error": error,
            "error_code": "",
            "error_params": "{}",
            **more,
        }
        if job is not None:
            columns["remote_job_id"] = job.job_id
        return self._update(attempt_id, allowed=allowed, unsettled=True, **columns)

    def _usage(
        self, attempt_id: str, job: RemoteJob | None, unknown: bool = False
    ) -> tuple[float, float]:
        """What to charge: the reported usage, or the whole reservation where none is reported.

        The reservation only changes when the attempt is settled (a guarded write), so reading it
        here and writing the charge afterwards is safe.
        """
        if job is None and not unknown:
            return 0.0, 0.0
        row = self.db.one(
            "SELECT reserved_cpu, reserved_storage FROM compute_attempts WHERE id = ?",
            (attempt_id,),
        )
        cpu = None if job is None else job.cpu_hours_used
        storage = None if job is None else job.storage_gb_used
        return (
            row["reserved_cpu"] if cpu is None else cpu,
            row["reserved_storage"] if storage is None else storage,
        )

    def _apply_remote(self, attempt_id: str, job: RemoteJob) -> bool:
        phase = REMOTE_PHASE[job.state]
        if phase in POLLED:
            return self._update(  # a poll that works clears an error an earlier one left
                attempt_id, LIVE, unsettled=True, phase=phase, remote_job_id=job.job_id, **CLEARED
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
            raise refusals.template_not_found(template_id)
        clean = validate_params(template, params)
        refs = validate_inputs(inputs)
        local = await self._check_inputs(task_id, refs)  # before anything is reserved
        attempt = self._reserve(task_id, submitter, csc_user, template, clean, refs)
        return await self._launch(attempt, template, local)

    async def _check_inputs(self, task_id: str, refs: Mapping[str, str]) -> dict[str, str]:
        """The local paths of ``refs``; the guard must have accepted each reference first.

        Once per submit or retry, not again at launch: a snapshot is immutable once frozen, so
        the check right before the reservation is as good as one right before the upload, and a
        second check would hash the whole snapshot again. The guard hashes, so it runs in a
        thread; the event loop (and the executor tick) keeps going meanwhile.
        """
        if not refs:
            return {}
        guard = self.input_guard
        if self.input_root is None or guard is None:
            raise refusals.inputs_unavailable()
        root, found = self.input_root.resolve(), {}
        for name, ref in refs.items():
            await asyncio.to_thread(guard, task_id, ref)
            path = (root / ref).resolve()  # follows links: one that leaves the snapshot is refused
            scope = (root / ref.partition("/")[0]).resolve()  # the snapshot the guard accepted
            if not path.is_relative_to(scope) or not path.exists():
                raise refusals.param_input_missing(name)
            found[name] = str(path)
        return found

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
                " analysis_version, parent_id, root_id, created_at, updated_at, storage_limit_gb)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'prepared', ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    attempt_id, task_id, submitter, csc_user, template.id, template.version,
                    json.dumps(params), json.dumps(inputs), template.max_cpu_hours,
                    template.max_storage_gb, analysis_version, parent.id if parent else None,
                    root_id, now, now, template.max_storage_gb,
                ),
            )  # fmt: skip
        return self._load(attempt_id)

    def _check_retry_limit(self, root_id: str, template: JobTemplate) -> None:
        row = self.db.one(
            "SELECT COUNT(*) AS n FROM compute_attempts WHERE root_id = ? AND id != ?",
            (root_id, root_id),
        )
        if row["n"] >= template.max_retries:
            raise refusals.quota_retry_limit(template.max_retries)

    async def _launch(
        self, attempt: Attempt, template: JobTemplate, local: Mapping[str, str]
    ) -> Attempt:
        self._inflight.add(attempt.id)
        try:
            job_id = await self.backend.submit(attempt.job_name, template, attempt.params, local)
        except SubmitRejected as error:
            self._settle(attempt.id, "failed", None, error=str(error), allowed=("prepared",),
                         **coded("submit_rejected"))  # fmt: skip
        except Exception as error:  # noqa: BLE001  receipt lost: the job may exist remotely
            lost = self._update(
                attempt.id, ("prepared",), phase="reconcile", error=repr(error),
                **coded("submit_failed"),
            )  # fmt: skip
            if not lost:
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
            self._update(attempt.id, error=f"orphan remote job not cancelled: {error!r}",
                         **coded("orphan_not_cancelled"))  # fmt: skip
            return
        if job_id is not None:
            self._update(attempt.id, remote_job_id=job_id, error="late remote job cancelled",
                         **coded("late_cancelled"))  # fmt: skip

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
                await self._settle_unknown(attempt, "no remote job found by name")
            else:
                self._apply_remote(attempt_id, job)
        elif attempt.phase in POLLED and attempt.remote_job_id:
            self._apply_remote(attempt_id, await self.backend.status(attempt.remote_job_id))
        return self._load(attempt_id)

    async def cancel(self, attempt_id: str, submitter: str) -> None:
        attempt = self._owned(attempt_id, submitter)
        if attempt.phase not in ("prepared", "reconcile", *POLLED):
            raise refusals.attempt_not_cancellable(attempt_id, attempt.phase)
        job_id = attempt.remote_job_id
        if job_id is None:
            found = await self.backend.find_by_name(attempt.job_name)
            job_id = found.job_id if found else None
        if job_id is None:  # nothing to cancel was found: it may yet have run, so it is charged
            self._settle(attempt_id, "cancelled", None, "cancelled; no remote job was found",
                         unknown=True, **coded("cancelled_no_job"))  # fmt: skip
            return
        await self.backend.cancel(job_id)
        try:
            job = await self.backend.status(job_id)
        except Exception as error:  # noqa: BLE001  gone from the listing: the state is unknown
            note = f"cancel requested; the remote state is unknown ({_describe(error)})"
            self._settle(attempt_id, "failed", None, note, unknown=True, remote_job_id=job_id,
                         **coded("cancel_unknown"))  # fmt: skip
            return
        self._settle(attempt_id, "cancelled", job)

    # -- recovery: the tick and the operator ----------------------------------------------
    async def tick(self) -> None:
        """Look again at attempts nobody has answered for, so none stays stuck with a held
        reservation: an unanswered submit is reconciled by name, a live job is polled.

        Rate-limited, a few attempts at a time, and an attempt that fails is recorded and skipped.
        The backend is asynchronous, so waiting for it does not block the event loop.
        """
        mono = self.clock.monotonic()
        if self._last_tick is not None and mono - self._last_tick < TICK_EVERY_SECONDS:
            return
        self._last_tick = mono
        for attempt_id in self._due():
            try:
                await self.reconcile(attempt_id)
            except Exception as error:  # noqa: BLE001  one bad attempt must not stop the rest
                self._update(attempt_id, error=_describe(error), **coded("backend_error"))

    def _due(self) -> list[str]:
        now = self.clock.now()
        rows = self.db.query(
            "SELECT id FROM compute_attempts WHERE (phase IN ('prepared', 'reconcile')"
            " AND updated_at <= ?) OR (phase IN ('queued', 'running') AND updated_at <= ?)"
            " ORDER BY updated_at, id LIMIT ?",
            (now - RECONCILE_AFTER_SECONDS, now - POLL_AFTER_SECONDS, TICK_BATCH),
        )
        return [row["id"] for row in rows]

    async def _settle_unknown(self, attempt: Attempt, why: str) -> None:
        """No job was found for an attempt that was submitted (or may have been): it may have
        run, so it is charged its whole reservation; its files are cleaned up if possible."""
        note = f"outcome unknown: {why}; charged the full reservation"
        if self._settle(attempt.id, "failed", None, note, unknown=True,
                        **coded("outcome_unknown")):  # fmt: skip
            await self._remote_cleanup(attempt, cancel=False)

    async def _remote_cleanup(self, attempt: Attempt, cancel: bool) -> None:
        """Best effort: stop the job and remove its directory; what fails is written down."""
        notes: list[str] = []
        columns: list[dict[str, str]] = []
        if cancel and attempt.remote_job_id:
            try:
                await self.backend.cancel(attempt.remote_job_id)
            except Exception as error:  # noqa: BLE001
                notes.append(f"remote cancel failed ({_describe(error)})")
                columns.append(coded("cancel_failed"))
        try:
            await self.backend.cleanup_by_name(attempt.job_name)
        except Exception as error:  # noqa: BLE001
            notes.append(f"cleanup failed ({_describe(error)})")
            columns.append(coded("cleanup_failed"))
        if notes:  # what needs an administrator wins over the code the attempt had
            self.db.execute(
                "UPDATE compute_attempts SET error = CASE WHEN error = '' THEN ?"
                " ELSE error || '; ' || ? END, error_code = ?, error_params = '{}' WHERE id = ?",
                ("; ".join(notes), "; ".join(notes), columns[0]["error_code"], attempt.id),
            )

    async def settle_attempt(self, attempt_id: str, actor: str, reason: str) -> Attempt:
        """An operator ends an attempt nobody can recover (a job that is gone, a fetch that can
        never finish). A live attempt is charged its whole reservation, as its outcome is not
        known; one whose usage is already charged keeps that charge. Who and why are recorded."""
        reason = reason.strip()
        if not reason:
            raise refusals.param_required("reason", "a reason is required")
        attempt = self._load(attempt_id)
        who = {"settled_by": actor, "settle_reason": reason}
        note = f"settled by an operator: {reason}"
        settled_code = coded("settled_by_operator")
        if attempt.phase in LIVE:
            done = self._settle(
                attempt_id,
                "failed",
                None,
                note,
                unknown=True,
                **who,
                **coded("settled_by_operator"),
            )
        elif attempt.phase in ("fetching", "needs_review"):
            done = self._update(
                attempt_id, ("fetching", "needs_review"), phase="failed", error=note, **who,
                **settled_code,
            )  # fmt: skip
        else:
            raise refusals.attempt_already_final(attempt_id, attempt.phase)
        if not done:
            message = "the attempt was settled by someone else meanwhile"
            raise refusals.attempt_settled_by_operator(attempt_id, message)
        await self._remote_cleanup(attempt, cancel=attempt.phase in LIVE)
        return self._load(attempt_id)

    # -- artifacts and retry --------------------------------------------------------------
    async def fetch_compute_artifacts(
        self, attempt_id: str, submitter: str, out_dir: Path
    ) -> dict[str, str]:
        attempt = self._owned(attempt_id, submitter)
        if attempt.phase not in FETCHABLE or not attempt.remote_job_id:
            raise refusals.attempt_nothing_to_fetch(attempt_id, attempt.phase)
        if attempt.settled_by:  # the operator's decision is final; a submitter cannot reopen it
            message = "an operator settled this attempt: it is final"
            raise refusals.attempt_settled_by_operator(attempt_id, message)
        limit = self._output_limit(attempt)
        try:
            reported = await self.backend.fetch(attempt.remote_job_id, out_dir, limit)
        except OutputTooLarge as error:  # visible (stuck) and final until an operator settles it
            self._record_fetch(
                attempt_id, phase="needs_review", error=str(error), **_limit_columns(error)
            )
            raise
        except BackendError as error:  # visible too, but a retry may work
            self._record_fetch(attempt_id, error=_describe(error), **coded("backend_error"))
            raise
        problems = await asyncio.to_thread(self._verify, out_dir, reported)  # hashes the files
        if problems:
            phase = "failed" if attempt.phase == "failed" else "needs_review"
            said = "; ".join(problem.text for problem in problems)
            self._record_fetch(
                attempt_id, phase=phase, error=said, **coded(problems[0].code, problems[0].params)
            )
            raise ArtifactMismatch(said)
        await self.backend.cleanup(attempt.remote_job_id)
        phase = "failed" if attempt.phase == "failed" else "done"
        recorded = self._record_fetch(
            attempt_id, phase=phase, checksums=json.dumps(reported), **CLEARED
        )
        if not recorded and self._load(attempt_id).settled_by:  # not a parallel fetch's win
            await self._discard(
                attempt_id, out_dir, reported
            )  # unrecorded files are not left behind
            message = "an operator settled this attempt during the fetch"
            raise refusals.attempt_settled_by_operator(attempt_id, message)
        return reported

    @staticmethod
    async def _discard(attempt_id: str, out_dir: Path, reported: Mapping[str, str]) -> None:
        """Remove exactly the files a fetch brought home; ``_verify`` has already confined
        every name to ``out_dir``, and anything else in the directory is left alone."""

        def remove() -> None:
            for name in reported:
                (out_dir / name).unlink(missing_ok=True)

        try:
            await asyncio.to_thread(remove)
        except OSError as error:
            message = f"settled during the fetch; the downloaded files remain ({error})"
            raise refusals.attempt_settled_by_operator(attempt_id, message) from error

    def _record_fetch(self, attempt_id: str, **columns: Any) -> bool:
        """Write a fetch's outcome, unless an operator settled the attempt meanwhile."""
        return self._update(attempt_id, FETCHABLE, unsettled_by_hand=True, **columns)

    def _output_limit(self, attempt: Attempt) -> int:
        """The most bytes a fetch may bring home: the storage the attempt reserved."""
        if is_output_limit(attempt.error, attempt.error_code) and attempt.phase == "needs_review":
            raise refusals.attempt_outputs_over_limit(attempt.id)
        gigabytes = attempt.storage_limit_gb
        if gigabytes is None:  # an attempt from before the limit was stored
            template = self.templates.get(attempt.template_id)
            if template is None:
                raise refusals.attempt_no_storage_limit(attempt.id, attempt.template_id)
            gigabytes = template.max_storage_gb
        return int(gigabytes * BYTES_PER_GB)

    @staticmethod
    def _verify(out_dir: Path, reported: Mapping[str, str]) -> list[Problem]:
        if not reported:
            return [Problem("no artifacts returned", "no_artifacts", {})]
        root, problems = out_dir.resolve(), []
        for name, expected in reported.items():
            path = (out_dir / name).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                text = f"{name}: missing or outside the output directory"
                problems.append(Problem(text, "artifact_missing", {"name": name}))
            elif file_digest(path) != expected:
                problems.append(Problem(f"{name}: checksum mismatch", "artifact_mismatch",
                                        {"name": name}))  # fmt: skip
        return problems

    async def retry(self, attempt_id: str, adjustments: dict[str, Any]) -> tuple[Attempt, bool]:
        """Resubmit a failed attempt; returns (new attempt, new analysis version?)."""
        attempt = self._load(attempt_id)
        csc_user = self._member(attempt.submitter)
        if attempt.phase != "failed":
            raise refusals.attempt_not_retryable(attempt_id, attempt.phase)
        template = self.templates.get(attempt.template_id)
        if template is None or template.version != attempt.template_version:
            raise refusals.template_version_unregistered(
                attempt.template_id, attempt.template_version
            )
        params = validate_params(template, {**attempt.params, **adjustments})
        local = await self._check_inputs(attempt.task_id, attempt.inputs)  # still in scope?
        changed = any(
            name in template.result_changing and params[name] != attempt.params.get(name)
            for name in adjustments
        )
        version = attempt.analysis_version + (1 if changed else 0)
        new = self._reserve(
            attempt.task_id, attempt.submitter, csc_user, template, params, attempt.inputs,
            parent=attempt, analysis_version=version,
        )  # fmt: skip
        return await self._launch(new, template, local), changed

    # -- what the workbench shows ---------------------------------------------------------
    def overview(self) -> dict[str, Any]:
        """Balance, per-task budgets and usage, the service totals, open and stuck jobs."""
        caps = (self.service_cpu_cap, self.service_storage_cap)
        return build_overview(self.db, self.clock, *caps)
