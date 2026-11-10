"""Assembly of the Auto Research services into one process (architecture doc §12).

``build_runtime`` creates one SQLite file per owner under ``settings.data_dir`` and wires the
services together through their public surfaces. ``Runtime.tick`` is the once-a-second loop:
archive ingestion, executor, recovery follow-ups, observer, notifications, task deadlines, the
daily report and the run-health check. Every step runs on its own: a failing step raises an alert
and the later steps still run. ``tick`` never calls a model.
"""

import asyncio
import hashlib
import inspect
import json
import logging
import os
import secrets
import shutil
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from growbridge.agents.budget import CallBudget
from growbridge.agents.dispatch import Dispatcher
from growbridge.agents.llm import ModelClient
from growbridge.agents.tools import Tool
from growbridge.archive.clock import Clock, SystemClock
from growbridge.archive.db import Database
from growbridge.archive.models import Channel, RuleAction, SamplingPlan
from growbridge.archive.source import LegacySampleSource, SourceRewound, protect_history
from growbridge.archive.storage import StorageGuard
from growbridge.archive.store import Archive
from growbridge.compute.service import ComputeService
from growbridge.config import Settings
from growbridge.control.ledger import Ledger
from growbridge.control.service import ControlService
from growbridge.executor.engine import ExecutorEngine
from growbridge.observer.alerts import Alert, AlertBook, AlertRule
from growbridge.observer.channels import EmailChannel, NotifyChannel, TelegramChannel
from growbridge.observer.health import BeatStatus, ExternalMonitor, Heartbeat, RunHealthCheck
from growbridge.observer.metrics import compute_daily_metrics, day_bounds
from growbridge.observer.outbox import Outbox
from growbridge.observer.report import ReportContext, ReportStore, render_daily_report, reports_due
from growbridge.observer.service import DEFAULT_CHANNELS, Observer
from growbridge.planning.validate import validate_run_sheet
from growbridge.ports import Actor, Denied, StageRuntime
from growbridge.research.analysis import ConfirmatoryRunner
from growbridge.research.holdout import HoldoutRegistry
from growbridge.research.sandbox import SANDBOX_EXEC, RefusingSandbox, SeatbeltSandbox
from growbridge.runtime_agents import make_dispatcher, role_tools, run_agents
from growbridge.runtime_backup import Backups
from growbridge.service import Bridge
from growbridge.sim.clock import FakeClock
from growbridge.sim.device import SimulatedTransport
from growbridge.sim.fixtures import TIMEZONE, make_protocol, make_run_sheet, make_safety
from growbridge.transport import make_transport
from growbridge.workbench.api import create_workbench
from growbridge.workbench.auth import Operators
from growbridge.workflow.service import WorkflowService
from growbridge.workflow.states import StageState
from growbridge.workflow.tasks import TaskBoard

log = logging.getLogger(__name__)

DATABASES = ("control", "workflow", "archive", "observer", "compute", "agents")
HOST_ID_FILE = "host_id"
LINK_WAIT_SECONDS = 20.0  # real seconds start() waits for the device to identify itself
LINK_POLL_SECONDS = 0.05
INGEST_BATCH = 500
INGEST_BATCHES_PER_TICK = 10
OUTBOX_BASE_SECONDS = 30.0
OUTBOX_CAP_SECONDS = 1800.0
GIB = 1024**3
STORAGE_LOW_BYTES = 2 * GIB
STORAGE_CRITICAL_BYTES = GIB // 2
# Service-level ceilings until real CSC quotas are known (architecture doc §12.3).
COMPUTE_CPU_CAP_HOURS = 1000.0
COMPUTE_STORAGE_CAP_GB = 100.0
# Run-health limits: age in seconds of the thing each probe watches.
HEALTH_LIMITS = {
    "growbridge_response": 60.0,
    "executor_evaluation": 30.0,
    "archive_write": 600.0,
    "oldest_undelivered_alert": 900.0,
}
TELEGRAM_TOKEN_ENV = "GROWBRIDGE_TELEGRAM_TOKEN"
TELEGRAM_CHATS_ENV = "GROWBRIDGE_TELEGRAM_CHAT_IDS"
EMAIL_TO_ENV = "GROWBRIDGE_EMAIL_TO"
SMTP_HOST_ENV = "GROWBRIDGE_SMTP_HOST"
DEFAULT_ALERT_RULES: tuple[AlertRule, ...] = ()
SIM_STAGE = "stage-sim"
SIM_STAGE_SECONDS = 600
SIM_STEP_SECONDS = 60.0
SIM_MAX_BEATS = 40
Step = Callable[[], Awaitable[Any] | Any]


# --- small helpers -------------------------------------------------------------------------------


def private_dir(path: Path) -> Path:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def load_host_id(data_dir: Path) -> str:
    """The write-host id of this machine: read from ``data_dir/host_id`` or created (mode 0600)."""
    path = private_dir(data_dir) / HOST_ID_FILE
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        existing = path.read_text().strip()
        if not existing:
            raise ValueError(f"{path} is empty") from None
        return existing
    host_id = secrets.token_hex(16)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(host_id + "\n")
    return host_id


def register_write_host(settings: Settings, clock: Clock | None = None) -> str:
    """Claim the device for this machine without starting a runtime (no BLE, no services)."""
    clock = clock or SystemClock()
    host_id = load_host_id(settings.data_dir)
    db = Database(settings.data_dir / "control.sqlite3")
    try:
        if not Ledger(db).register_host(str(settings.device), host_id, clock.now()):
            raise Denied("host_unregistered", "another host is registered for this device")
    finally:
        db.close()
    return host_id


def make_runtime_sandbox(deny_read: list[Path]) -> RefusingSandbox | SeatbeltSandbox:
    if sys.platform == "darwin" and os.path.exists(SANDBOX_EXEC):
        return SeatbeltSandbox(deny_read)
    return RefusingSandbox()


def _listed(name: str) -> list[str]:
    return [item.strip() for item in os.environ.get(name, "").split(",") if item.strip()]


def default_channels() -> dict[str, NotifyChannel]:
    """Channels configured through the environment; none when nothing is configured."""
    found: dict[str, NotifyChannel] = {}
    chats, mails = _listed(TELEGRAM_CHATS_ENV), _listed(EMAIL_TO_ENV)
    if chats and os.environ.get(TELEGRAM_TOKEN_ENV):
        found["telegram"] = TelegramChannel(chats)
    if mails and os.environ.get(SMTP_HOST_ENV):
        found["email"] = EmailChannel(mails)
    return found


MIRROR_NAMESPACE = "runtime_mirror"
MIRROR_STEPS = ("CREATE TABLE intervention_mirror(key TEXT PRIMARY KEY, record_id TEXT NOT NULL)",)


class InterventionMirror:
    """Copies each workflow intervention into the archive exactly once.

    The key is a digest of the intervention's content, kept in a table of the archive database
    so the copy and its key are saved together; a repeat (restart, replay) finds the key.
    """

    def __init__(self, db: Database, archive: Archive):
        self.db = db
        self.archive = archive
        self.alert: Callable[[str, str, str], None] | None = None
        db.migrate(MIRROR_NAMESPACE, MIRROR_STEPS)

    def __call__(self, item: dict) -> None:
        try:
            self._mirror(item)
        except Exception as error:
            log.exception("intervention could not be copied to the archive")
            if self.alert is not None:
                message = f"{item.get('kind')} not copied to the archive: {error}"
                self.alert("intervention_mirror", "archive", message)

    def _mirror(self, item: dict) -> None:
        key = hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
        with self.db.transaction():
            if self.db.one("SELECT 1 FROM intervention_mirror WHERE key = ?", (key,)):
                return
            record_id = self.archive.record_intervention(
                item["experiment_id"],
                item["stage_id"],
                item["kind"],
                item["detail"],
                item["operator"],
            )
            self.db.execute("INSERT INTO intervention_mirror VALUES (?, ?)", (key, record_id))


class _GuardedBridge(Bridge):
    """The BLE connection opens only on the registered write host, whoever asks to start it."""

    def __init__(self, settings, transport_factory, clock):
        super().__init__(settings, transport_factory, clock)
        self.may_open: Callable[[], bool] = lambda: False

    async def start(self):
        if self.task is not None and not self.task.done():
            return  # already running (the HTTP lifespan starts it again)
        if not self.may_open():
            log.warning("not the registered write host: the BLE connection stays closed")
            return
        await super().start()


# --- the runtime ---------------------------------------------------------------------------------


@dataclass
class Runtime:
    settings: Settings
    clock: Clock
    bridge: Bridge
    control: ControlService
    workflow: WorkflowService
    tasks: TaskBoard
    budget: CallBudget
    archive: Archive
    storage: StorageGuard
    executor: ExecutorEngine
    book: AlertBook
    outbox: Outbox
    observer: Observer
    reports: ReportStore
    runner: ConfirmatoryRunner
    holdout: HoldoutRegistry
    sandbox: Any
    operators: Operators
    compute: ComputeService | None
    channels: Mapping[str, NotifyChannel]
    health: RunHealthCheck
    monitor: ExternalMonitor | None
    source: LegacySampleSource
    agents_db: Database
    backups: Backups
    databases: tuple[Database, ...] = ()
    failing: set[str] = field(default_factory=set)
    stopped: bool = False

    # --- life cycle ----------------------------------------------------------------------------

    async def start(self) -> None:
        protect_history(self.bridge.store, lambda: self.archive.cursor(self._device), self.clock)
        if self.backups.directory is None:
            message = "No backup_dir is configured: the databases are not being backed up"
            self._alert("backup_unconfigured", "backups", message, "warning")
        if not self.control.host_registered():
            self._alert("runtime", "write_host", "This host is not the registered write host")
            return
        await self.bridge.start()
        await self._await_link()
        await self.control.startup()
        await self.workflow.on_restart()

    async def stop(self) -> None:
        if self.stopped:
            return
        self.stopped = True
        await self.backups.close()
        await self.bridge.stop()
        for db in self.databases:
            db.close()

    def workbench(self, role_tokens: Mapping[str, str] | None = None) -> APIRouter:
        args = (self.workflow, self.control, self.archive, self.operators, self.settings)
        return create_workbench(*args, role_tokens or {}, self.book)

    @property
    def _device(self) -> str:
        return str(self.settings.device)

    async def _await_link(self) -> None:
        deadline = time.monotonic() + LINK_WAIT_SECONDS
        while time.monotonic() < deadline:
            if self.bridge.identity and self.bridge.connected:
                return
            await asyncio.sleep(LINK_POLL_SECONDS)
        log.warning("the device did not identify itself within %s s", LINK_WAIT_SECONDS)

    # --- model roles (never called from tick) --------------------------------------------------

    def alert(self, kind: str, key: str, message: str) -> None:
        """Raise a critical alert (and queue its notification); never raises."""
        self._alert(kind, key, message)

    def role_tools(self) -> dict[str, list[Tool]]:
        return role_tools(self, private_dir(self.settings.data_dir / "agent_work"))

    def dispatcher(self, client: ModelClient) -> Dispatcher:
        return make_dispatcher(self, client, private_dir(self.settings.data_dir / "agent_work"))

    async def run_agents(self, client: ModelClient) -> int:
        """Run every open task owned by a model role once; returns how many runs finished.

        A failing task raises an alert and the others still run. ``tick`` never calls this.
        """
        return await run_agents(self, self.dispatcher(client))

    # --- recovery ------------------------------------------------------------------------------

    async def bump_recovery(self, reason: str) -> int:
        """After a restore or a host change: new recovery number, then every live stage into
        恢复待核对 (approvals void), with no stage write in between; then halt the old transport."""
        number = self.control.bump_recovery(reason)
        await self.workflow.on_recovery_bump()
        await self.control.confirm_transport_stopped()
        return number

    @property
    def backup_task(self):
        return self.backups.task

    # --- the tick ------------------------------------------------------------------------------

    async def tick(self) -> None:
        steps: tuple[tuple[str, Step], ...] = (
            ("archive", self._ingest),
            ("executor", self.executor.tick),
            ("recovery", self._follow_up),
            ("observer", self.observer.tick),
            ("outbox", self._deliver),
            ("tasks", self._expire),
            ("report", self._daily_report),
            ("backup", self.backups.step),
            ("health", self._check_health),
        )
        for name, step in steps:
            await self._guarded(name, step)

    async def _guarded(self, name: str, step: Step) -> None:
        try:
            outcome = step()
            if inspect.isawaitable(outcome):
                await outcome
        except Exception as error:
            log.exception("tick step %s failed", name)
            self.failing.add(name)
            self._alert("tick_step", name, f"{name}: {type(error).__name__}: {error}")
            return
        if name in self.failing:
            self.failing.discard(name)
            self._safely(lambda: self.book.resolve("tick_step", name))

    @staticmethod
    def _safely(action: Callable[[], Any]) -> None:
        try:
            action()
        except Exception:
            log.exception("could not record a runtime alert")

    def _alert(self, kind: str, key: str, message: str, severity: Any = "critical") -> None:
        def raise_it() -> None:
            self._announce(self.book.raise_alert(kind, key, severity, message))

        self._safely(raise_it)

    def _announce(self, alert: Alert) -> None:
        if alert.count != 1:
            return
        text = f"[{alert.severity}] {alert.message}"
        for channel in self.observer.notify_channels:
            self.outbox.queue_notification(alert.event_id, channel, text)

    # --- the steps -----------------------------------------------------------------------------

    def _ingest(self) -> None:
        stage = self.workflow.active_stage()

        def context(received_at: float) -> tuple[str | None, str | None]:
            """A sample belongs to the stage only if it arrived once the stage had started."""
            if stage is None or stage.started_at is None or received_at < stage.started_at:
                return None, None
            return stage.experiment_id, stage.stage_id

        try:
            for _ in range(INGEST_BATCHES_PER_TICK):
                stored = self.archive.ingest(self.source, self._device, context, INGEST_BATCH)
                if stored < INGEST_BATCH:
                    return
        except SourceRewound as error:
            self._alert("source_rewound", "legacy_samples", str(error))

    async def _follow_up(self) -> None:
        stage = self.workflow.active_stage()
        if stage is not None and stage.state is StageState.RECOVERY_CHECK:
            await self.workflow.try_exit_recovery(stage.stage_id)
        await self.workflow.restore_care()

    async def _deliver(self) -> None:
        await self.outbox.deliver(self.channels)

    def _expire(self) -> None:
        for task in self.tasks.expire(self.clock.now()):
            message = f"Research task {task.id} is past its deadline and needs attention"
            self._alert("task_deadline", task.id, message, "warning")

    async def _daily_report(self) -> None:
        stage = self.workflow.active_stage()
        if stage is None:
            return
        settings = self.settings
        row = self.reports.db.one(
            "SELECT MAX(report_date) AS latest FROM observer_reports WHERE project_id = ?",
            (stage.project_id,),
        )
        last = row["latest"] if row else None
        for target in reports_due(
            self.clock.now(), settings.report_time, settings.report_timezone, last
        ):
            text = self._report_text(stage, date.fromisoformat(target))
            if self.reports.save(stage.project_id, target, text):
                event = f"report:{stage.project_id}:{target}"
                for channel in self.observer.notify_channels:
                    self.outbox.queue_notification(event, channel, text)

    def _report_text(self, stage: StageRuntime, day: date) -> str:
        zone = self.settings.report_timezone
        start, end = day_bounds(day, zone)
        samples = self.archive.samples(stage.experiment_id, start, end)
        gap = stage.run_sheet.sampling.max_gap_seconds
        metrics = compute_daily_metrics(samples, day, zone, gap, {})
        actions = self.archive.actions(stage.experiment_id)
        protective = tuple(
            f"{a.trigger}: {a.channel.value} -> {a.planned_level}"
            for a in actions
            if start <= a.created_at < end and a.trigger.startswith("protect:")
        )
        interventions = tuple(
            f"{item['kind']} ({item['operator'] or 'system'}) at "
            f"{datetime.fromtimestamp(item['at'], ZoneInfo(zone)):%H:%M}"
            for item in self.workflow.interventions(stage.experiment_id)
            if start <= item["at"] < end
        )
        row = self.workflow.db.one("SELECT name FROM wf_projects WHERE id = ?", (stage.project_id,))
        context = ReportContext(
            project_id=stage.project_id,
            project_name=row["name"] if row else stage.project_id,
            protective_actions=protective,
            manual_interventions=interventions,
        )
        return render_daily_report(metrics, context)

    def _capture_limit(self) -> float:
        stage = self.workflow.active_stage()
        if stage is None:
            return self.settings.stale_seconds
        return stage.run_sheet.sampling.max_gap_seconds

    async def _check_health(self) -> None:
        self.health.limits["capture"] = self._capture_limit()
        health = self.health.check()
        if health.ok:
            self.book.resolve("run_health", "run")
        else:
            self._alert("run_health", "run", "Run health failing: " + ", ".join(health.failures))
        if self.monitor is not None:
            self._monitor_alerts(await self.monitor.beat(health))

    def _monitor_alerts(self, status: BeatStatus) -> None:
        signals = {"host": status.host_ok, "run": status.run_ok}
        for name, delivered in signals.items():
            if delivered is False:
                message = f"The external {name} heartbeat could not be delivered"
                self._alert("external_monitor", name, message, "warning")
            elif delivered:
                self._safely(lambda n=name: self.book.resolve("external_monitor", n))


# --- assembly ------------------------------------------------------------------------------------


def _probes(
    clock: Clock,
    bridge: Bridge,
    executor: ExecutorEngine,
    archive: Archive,
    outbox: Outbox,
    backups: Backups,
) -> dict[str, Callable[[], float | None]]:
    def response() -> float | None:
        seen = bridge.received_monotonic
        return clock.monotonic() - seen if seen else None

    def evaluation() -> float | None:
        beat = executor.heartbeat()
        return None if beat is None else clock.monotonic() - beat

    def archived() -> float | None:
        written = archive.last_write_at()
        return None if written is None else clock.now() - written

    def undelivered() -> float | None:
        oldest = outbox.oldest_undelivered()
        return 0.0 if oldest is None else clock.now() - oldest

    def capture() -> float | None:
        received = bridge.received_at
        return clock.now() - received if received else None

    return {
        "growbridge_response": response,
        "executor_evaluation": evaluation,
        "capture": capture,
        "archive_write": archived,
        "oldest_undelivered_alert": undelivered,
        "offsite_backup": backups.age,
    }


def _compute(backend: Any, db: Database, clock: Clock) -> ComputeService | None:
    if backend is None:
        return None
    args = (db, clock, backend, (), {}, COMPUTE_CPU_CAP_HOURS, COMPUTE_STORAGE_CAP_GB)
    return ComputeService(*args)


def build_runtime(
    settings: Settings,
    transport_factory: Callable[[Settings], Any] = make_transport,
    clock: Clock | None = None,
    compute_backend: Any = None,
    channels: Mapping[str, NotifyChannel] | None = None,
    heartbeats: tuple[Heartbeat, Heartbeat] | None = None,
) -> Runtime:
    """``heartbeats`` is the (host, run) pair of external dead-man's-switch endpoints."""
    clock = clock or SystemClock()
    data_dir = private_dir(settings.data_dir)
    host_id = load_host_id(data_dir)
    dbs = {name: Database(data_dir / f"{name}.sqlite3") for name in DATABASES}
    bridge = _GuardedBridge(settings, transport_factory, clock)
    archive = Archive(dbs["archive"], data_dir / "archive", clock)
    control = ControlService(bridge, dbs["control"], clock, host_id, archive)
    mirror = InterventionMirror(dbs["archive"], archive)
    bridge.may_open = control.host_registered
    flow = WorkflowService(
        dbs["workflow"],
        clock,
        control,
        validate=lambda sheet: validate_run_sheet(sheet, control.capabilities(), control.safety()),
        on_intervention=mirror,
    )
    storage = StorageGuard(data_dir, STORAGE_LOW_BYTES, STORAGE_CRITICAL_BYTES, shutil.disk_usage)
    executor = ExecutorEngine(control, flow, clock, storage.allows)
    book = AlertBook(dbs["observer"], clock)
    outbox = Outbox(dbs["observer"], clock, OUTBOX_BASE_SECONDS, OUTBOX_CAP_SECONDS)
    selected = default_channels() if channels is None else dict(channels)
    notify = tuple(selected) or DEFAULT_CHANNELS
    observer = Observer(flow, control.readings, book, outbox, DEFAULT_ALERT_RULES, clock, notify)
    sandbox = make_runtime_sandbox([Path.home(), data_dir])
    backups = Backups(
        dict(zip(DATABASES, dbs.values(), strict=True)),
        settings.backup_dir,
        settings.backup_interval_seconds,
        clock,
        lambda *_args: None,  # replaced by the runtime's alert once it exists
        book.resolve,
    )
    limits = {**HEALTH_LIMITS, "capture": settings.stale_seconds}
    if settings.backup_dir is not None:
        limits["offsite_backup"] = backups.limit_seconds
    runtime = Runtime(
        settings=settings,
        clock=clock,
        bridge=bridge,
        control=control,
        workflow=flow,
        tasks=TaskBoard(dbs["workflow"], clock),
        budget=CallBudget(dbs["agents"], clock),
        archive=archive,
        storage=storage,
        executor=executor,
        book=book,
        outbox=outbox,
        observer=observer,
        reports=ReportStore(dbs["observer"]),
        runner=ConfirmatoryRunner(dbs["agents"], clock, sandbox, data_dir / "analysis"),
        holdout=HoldoutRegistry(dbs["agents"], clock),
        sandbox=sandbox,
        operators=Operators(dbs["workflow"], clock),
        compute=_compute(compute_backend, dbs["compute"], clock),
        channels=selected,
        health=RunHealthCheck(
            _probes(clock, bridge, executor, archive, outbox, backups), limits, clock
        ),
        monitor=None if heartbeats is None else ExternalMonitor(*heartbeats, clock),
        source=LegacySampleSource(bridge.store, clock),
        agents_db=dbs["agents"],
        backups=backups,
        databases=tuple(dbs.values()),
    )
    mirror.alert = runtime._alert
    backups.alert = runtime.alert
    return runtime


# --- simulated run (no radio, no network) --------------------------------------------------------


async def _design_and_start(runtime: Runtime, clock: FakeClock) -> str:
    flow = runtime.workflow
    operator = Actor(kind="operator", id="simulator", reauth_at=clock.now())
    runtime.control.approve_safety(make_safety(), operator.id)
    project = flow.create_project("simulated light stage", operator)
    protocol = make_protocol(project_id=project)
    flow.save_protocol(protocol, operator)
    round_id = flow.create_round(project, protocol.id, operator)
    sheet = make_run_sheet(
        id="sheet-sim",
        project_id=project,
        experiment_id="experiment-sim",
        stage_id=SIM_STAGE,
        protocol_id=protocol.id,
        protocol_version=protocol.version,
        duration_seconds=SIM_STAGE_SECONDS,
        sampling=SamplingPlan(interval_seconds=60, max_gap_seconds=120),
        end_actions=(RuleAction(channel=Channel.LIGHT, level=0),),
    )
    findings = flow.submit_run_sheet(round_id, sheet, Actor(kind="model", id="planner"))
    blocking = [item.message for item in findings if item.blocking]
    if blocking:
        raise RuntimeError("the simulated run sheet was refused: " + "; ".join(blocking))
    flow.approve(SIM_STAGE, operator)
    await flow.start_stage(SIM_STAGE, operator)
    return round_id


async def simulate_stage() -> dict[str, Any]:
    """Approve, run and end one short stage on the simulated device; returns a summary."""
    start = datetime(2027, 1, 15, 10, 0, tzinfo=ZoneInfo(TIMEZONE)).timestamp()
    with tempfile.TemporaryDirectory() as directory:
        settings = Settings(
            device="SIMULATED",
            token=secrets.token_urlsafe(32),
            data_dir=Path(directory) / "data",
            controls_enabled=True,
            pump_cooldown_seconds=0,
            auto_research=True,
        )
        clock, device = FakeClock(now=start), SimulatedTransport()
        runtime = build_runtime(settings, lambda _: device, clock, channels={})
        runtime.bridge.request_timeout = 0.2
        runtime.bridge.readback_interval = 0.01
        try:
            runtime.control.register_host()
            await runtime.start()
            round_id = await _design_and_start(runtime, clock)
            beats = 0
            while beats < SIM_MAX_BEATS:
                beats += 1
                clock.advance(SIM_STEP_SECONDS)
                await runtime.bridge.request("getDevSta")
                await runtime.tick()
                if runtime.workflow.stage(SIM_STAGE).state is StageState.ENDED:
                    break
            writes = [c for c in device.commands if c["method"] == "setConfigField"]
            return {
                "stage": runtime.workflow.stage(SIM_STAGE).state.value,
                "round": runtime.workflow.round_state(round_id).value,
                "beats": beats,
                "samples": len(runtime.archive.samples("experiment-sim")),
                "writes": len(writes),
            }
        finally:
            await runtime.stop()
