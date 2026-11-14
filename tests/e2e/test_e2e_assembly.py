"""What ``build_runtime`` assembles: files per owner, host id, sandbox, tick order, daily report."""

import stat
import sys
from datetime import date
from pathlib import Path

import pytest
from e2e_support import RecordingChannel

from growbridge.observer.metrics import day_bounds
from growbridge.research.sandbox import SeatbeltSandbox
from growbridge.runtime import make_runtime_sandbox

ATTRIBUTES = (
    "settings clock bridge control workflow tasks budget archive storage executor book outbox "
    "observer reports runner holdout sandbox operators compute"
).split()


async def test_runtime_exposes_its_services_and_one_database_file_per_owner(world, settings):
    runtime = await world.boot()

    for name in ATTRIBUTES:
        assert hasattr(runtime, name), name
    assert runtime.compute is None  # no compute backend was given
    for owner in ("control", "workflow", "archive", "observer", "compute", "agents"):
        assert (settings.data_dir / f"{owner}.sqlite3").exists(), owner


async def test_host_id_is_created_once_with_private_permissions(world, settings):
    first = await world.boot()
    host_file = settings.data_dir / "host_id"
    created = host_file.read_text().strip()
    await first.stop()
    await world.boot()

    assert stat.S_IMODE(host_file.stat().st_mode) == 0o600
    assert len(created) >= 32
    assert host_file.read_text().strip() == created
    assert first.control.host_id == created


@pytest.mark.skipif(sys.platform != "darwin", reason="the Seatbelt sandbox exists on macOS only")
async def test_sandbox_denies_reading_the_home_directory_and_the_data_directory(world, settings):
    runtime = await world.boot()

    assert isinstance(runtime.sandbox, SeatbeltSandbox)
    assert Path.home().resolve() in runtime.sandbox.deny_read
    assert settings.data_dir.resolve() in runtime.sandbox.deny_read


def test_sandbox_without_seatbelt_refuses_to_run(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")

    assert not isinstance(make_runtime_sandbox([Path.home()]), SeatbeltSandbox)


async def test_tick_runs_its_steps_in_the_documented_order(world, monkeypatch):
    runtime = await world.boot()
    order: list[str] = []

    def record(owner, method, label, is_async):
        original = getattr(owner, method)

        async def wrapped_async(*args, **kwargs):
            order.append(label)
            return await original(*args, **kwargs)

        def wrapped_sync(*args, **kwargs):
            order.append(label)
            return original(*args, **kwargs)

        monkeypatch.setattr(owner, method, wrapped_async if is_async else wrapped_sync)

    record(runtime.archive, "ingest", "archive", False)
    record(runtime.executor, "tick", "executor", True)
    record(runtime.workflow, "restore_care", "recovery", True)
    record(runtime.observer, "tick", "observer", True)
    record(runtime.outbox, "deliver", "outbox", True)
    record(runtime.tasks, "expire", "tasks", False)
    record(runtime.health, "check", "health", False)

    await runtime.tick()

    assert order == ["archive", "executor", "recovery", "observer", "outbox", "tasks", "health"]


async def test_daily_report_is_made_once_per_day_and_queued_for_delivery(world):
    channel = RecordingChannel()
    runtime = await world.boot(channels={"telegram": channel})  # 08:00 UTC: past the report time
    project, _round = await world.approved_stage(runtime)

    await world.beat(runtime, 30)
    await world.beat(runtime, 30)

    text = runtime.reports.get(project, "2027-01-14")
    assert text is not None and "Daily report 2027-01-14" in text
    assert runtime.reports.get(project, "2027-01-15") is None
    event = f"report:{project}:2027-01-14"
    assert runtime.outbox.status(event, "telegram") == "accepted"
    assert channel.sent.count(text) == 1


async def test_daily_report_lists_frozen_readings_overlapping_the_day(world, settings):
    runtime = await world.boot(channels={})
    project, _round = await world.approved_stage(runtime)
    start, _end = day_bounds(date(2027, 1, 14), settings.report_timezone)
    period = runtime.archive.open_frozen("temp", 24.0, start + 3600)
    runtime.archive.close_frozen(period, "temp", start + 7200)
    runtime.archive.open_frozen("humi", 55.0, start + 10800)

    await world.beat(runtime, 30)

    text = runtime.reports.get(project, "2027-01-14")
    assert text is not None
    lines = text.splitlines()
    assert "- temp stuck at 24 from 01:00 to 02:00" in lines
    assert "- humi stuck at 55 from 03:00 (still frozen)" in lines


async def test_daily_report_shows_the_date_of_a_frozen_time_outside_the_day(world, settings):
    runtime = await world.boot(channels={})
    project, _round = await world.approved_stage(runtime)
    start, _end = day_bounds(date(2027, 1, 14), settings.report_timezone)
    period = runtime.archive.open_frozen("temp", 24.0, start - 7200)
    runtime.archive.close_frozen(period, "temp", start + 3600)
    runtime.archive.open_frozen("humi", 55.0, start - 3600)

    await world.beat(runtime, 30)

    lines = (runtime.reports.get(project, "2027-01-14") or "").splitlines()
    assert "- temp stuck at 24 from 2027-01-13 22:00 to 01:00" in lines
    assert "- humi stuck at 55 from 2027-01-13 23:00 (still frozen)" in lines


async def test_daily_report_without_a_channel_is_saved_and_nothing_is_queued(world):
    runtime = await world.boot(channels={})
    project, _round = await world.approved_stage(runtime)

    await world.beat(runtime, 30)

    assert runtime.reports.get(project, "2027-01-14") is not None
    assert runtime.outbox.oldest_undelivered() is None


async def test_legacy_samples_are_stamped_with_the_injected_clock(world):
    runtime = await world.boot()
    await world.beat(runtime, 30)

    received = [sample.received_at for sample in runtime.source.read_after(0, 10)]
    assert received and all(at == world.clock.now() or at < world.clock.now() for at in received)
    assert max(received) == world.clock.now()
