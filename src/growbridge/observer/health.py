"""Run-health check and external monitoring (architecture doc section 8.2).

External signals go straight to the monitoring service, never through the local outbox. The host
heartbeat is sent every beat. The run heartbeat is sent only while the run health is good; when it
is not, a failure signal is sent and the heartbeat stops, so a lost failure signal still alerts.
"""

import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Literal, Protocol

from growbridge.archive.clock import Clock
from growbridge.archive.models import Model

log = logging.getLogger(__name__)

PROBE_NAMES = (
    "growbridge_response",
    "executor_evaluation",
    "capture",
    "archive_write",
    "oldest_undelivered_alert",
    "offsite_backup",
)


class RunHealth(Model):
    ok: bool
    failures: tuple[str, ...]  # names of the probes that are over their limit or silent
    values: dict[str, float | None]  # probe name -> age in seconds
    checked_at: float


class RunHealthCheck:
    """Each probe returns the age in seconds of the thing it watches; ``None`` means unknown."""

    def __init__(
        self,
        probes: Mapping[str, Callable[[], float | None]],
        limits: Mapping[str, float],
        clock: Clock,
    ):
        self.probes = dict(probes)
        self.limits = dict(limits)
        self.clock = clock

    def _read(self, name: str) -> float | None:
        probe = self.probes.get(name)
        if probe is None:
            return None
        try:
            return probe()
        except Exception:
            log.exception("run-health probe %s failed", name)
            return None

    def check(self) -> RunHealth:
        values = {name: self._read(name) for name in sorted(self.limits)}
        failures = tuple(
            name for name, age in values.items() if age is None or age > self.limits[name]
        )
        return RunHealth(
            ok=not failures, failures=failures, values=values, checked_at=self.clock.now()
        )


class Heartbeat(Protocol):
    async def ping(self) -> bool: ...

    async def fail(self) -> bool: ...


class BeatStatus(Model):
    host_ok: bool  # the host heartbeat was delivered
    run_action: Literal["ping", "fail", "suppressed"]
    run_ok: bool | None  # whether that run signal was delivered; None when none was sent


class ExternalMonitor:
    def __init__(self, host: Heartbeat, run: Heartbeat, clock: Clock):
        self.host = host
        self.run = run
        self.clock = clock

    async def _signal(self, target: str, action: Callable[[], Awaitable[bool]]) -> bool:
        """Send one signal; a refused or failed delivery is logged and returned as ``False``."""
        name = getattr(action, "__name__", "signal")
        try:
            delivered = await action()
        except Exception as error:
            log.warning("%s %s signal raised %s", target, name, type(error).__name__)
            return False
        if not delivered:
            log.warning("%s %s signal was not delivered", target, name)
        return bool(delivered)

    async def beat(self, health: RunHealth, maintenance_until: float | None = None) -> BeatStatus:
        host_ok = await self._signal("host", self.host.ping)
        if health.ok:
            return BeatStatus(
                host_ok=host_ok, run_action="ping", run_ok=await self._signal("run", self.run.ping)
            )
        if maintenance_until is not None and self.clock.now() < maintenance_until:
            # planned maintenance: the external grace period was extended to the deadline
            return BeatStatus(host_ok=host_ok, run_action="suppressed", run_ok=None)
        run_ok = await self._signal("run", self.run.fail)
        return BeatStatus(host_ok=host_ok, run_action="fail", run_ok=run_ok)
