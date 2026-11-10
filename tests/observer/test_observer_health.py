import logging

import pytest

from growbridge.observer.health import ExternalMonitor, RunHealth, RunHealthCheck

LIMITS = {
    "growbridge_response": 30.0,
    "executor_evaluation": 120.0,
    "capture": 300.0,
    "archive_write": 300.0,
    "oldest_undelivered_alert": 600.0,
    "offsite_backup": 90000.0,
}


class FakeBeat:
    def __init__(self, name, log):
        self.name = name
        self.log = log

    async def ping(self):
        self.log.append((self.name, "ping"))
        return True

    async def fail(self):
        self.log.append((self.name, "fail"))
        return True


def probes(**overrides):
    values = {name: 1.0 for name in LIMITS}
    values.update(overrides)
    return {name: (lambda v=value: v) for name, value in values.items()}


def check(clock, **overrides):
    return RunHealthCheck(probes(**overrides), LIMITS, clock).check()


def test_all_probes_within_limits_is_healthy(clock):
    health = check(clock)

    assert health.ok is True
    assert health.failures == ()


@pytest.mark.parametrize("name", list(LIMITS))
def test_each_stuck_probe_fails_the_run_health(clock, name):
    health = check(clock, **{name: LIMITS[name] + 1})

    assert health.ok is False
    assert health.failures == (name,)


def test_limit_boundary_is_still_healthy(clock):
    assert check(clock, capture=LIMITS["capture"]).ok is True


def test_a_probe_without_an_answer_or_that_raises_is_a_failure(clock):
    def broken():
        raise RuntimeError("db locked")

    all_probes = probes(capture=None)
    all_probes["archive_write"] = broken

    health = RunHealthCheck(all_probes, LIMITS, clock).check()

    assert health.failures == ("archive_write", "capture")


def test_a_limit_without_a_probe_is_a_failure(clock):
    partial = probes()
    del partial["offsite_backup"]

    assert RunHealthCheck(partial, LIMITS, clock).check().failures == ("offsite_backup",)


def test_health_records_the_check_time(clock):
    assert check(clock).checked_at == clock.now()


@pytest.fixture
def monitor_parts(clock):
    log: list[tuple[str, str]] = []
    monitor = ExternalMonitor(FakeBeat("host", log), FakeBeat("run", log), clock)
    return monitor, log


async def test_healthy_run_sends_both_heartbeats(monitor_parts, clock):
    monitor, log = monitor_parts

    await monitor.beat(check(clock))

    assert log == [("host", "ping"), ("run", "ping")]


async def test_host_online_but_capture_stuck_sends_failure_and_stops_run_heartbeat(
    monitor_parts, clock
):
    monitor, log = monitor_parts

    await monitor.beat(check(clock, capture=10_000.0))

    assert ("host", "ping") in log
    assert ("run", "fail") in log
    assert ("run", "ping") not in log
    assert ("host", "fail") not in log


async def test_maintenance_window_suppresses_the_failure_signal(monitor_parts, clock):
    monitor, log = monitor_parts
    stuck = check(clock, offsite_backup=10**6)

    await monitor.beat(stuck, maintenance_until=clock.now() + 3600)

    assert log == [("host", "ping")]


async def test_failure_signal_resumes_when_the_maintenance_grace_expires(monitor_parts, clock):
    monitor, log = monitor_parts
    until = clock.now() + 3600
    stuck = check(clock, offsite_backup=10**6)

    clock.advance(3601)
    await monitor.beat(stuck, maintenance_until=until)

    assert ("run", "fail") in log
    assert ("run", "ping") not in log


async def test_maintenance_does_not_hide_a_healthy_run_heartbeat(monitor_parts, clock):
    monitor, log = monitor_parts

    await monitor.beat(check(clock), maintenance_until=clock.now() + 3600)

    assert log == [("host", "ping"), ("run", "ping")]


async def test_a_hung_run_signal_does_not_block_the_host_heartbeat(clock):
    log: list[tuple[str, str]] = []

    class Down(FakeBeat):
        async def fail(self):
            raise ConnectionError("unreachable")

    monitor = ExternalMonitor(FakeBeat("host", log), Down("run", log), clock)

    await monitor.beat(check(clock, capture=10_000.0))

    assert ("host", "ping") in log


async def test_beat_status_reports_what_was_sent(monitor_parts, clock):
    monitor, _ = monitor_parts

    healthy = await monitor.beat(check(clock))
    failing = await monitor.beat(check(clock, capture=10_000.0))
    quiet = await monitor.beat(check(clock, capture=10_000.0), maintenance_until=clock.now() + 60)

    assert (healthy.host_ok, healthy.run_action, healthy.run_ok) == (True, "ping", True)
    assert (failing.host_ok, failing.run_action, failing.run_ok) == (True, "fail", True)
    assert (quiet.host_ok, quiet.run_action, quiet.run_ok) == (True, "suppressed", None)


async def test_a_ping_that_returns_false_is_logged_and_surfaced(clock, caplog):
    log: list[tuple[str, str]] = []

    class Refused(FakeBeat):
        async def ping(self):
            await super().ping()
            return False

    monitor = ExternalMonitor(Refused("host", log), FakeBeat("run", log), clock)

    with caplog.at_level(logging.WARNING, logger="growbridge.observer.health"):
        status = await monitor.beat(check(clock))

    assert status.host_ok is False
    assert status.run_ok is True
    assert "host" in caplog.text and "ping" in caplog.text


async def test_a_raising_signal_is_surfaced_as_not_ok(clock):
    class Down(FakeBeat):
        async def fail(self):
            raise ConnectionError("unreachable")

    monitor = ExternalMonitor(FakeBeat("host", []), Down("run", []), clock)

    status = await monitor.beat(check(clock, capture=10_000.0))

    assert (status.host_ok, status.run_action, status.run_ok) == (True, "fail", False)


def test_run_health_is_frozen():
    health = RunHealth(ok=True, failures=(), values={}, checked_at=0.0)
    assert health.ok is True
    with pytest.raises(Exception):  # noqa: B017
        health.ok = False
