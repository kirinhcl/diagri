"""Gaps found in review, closed in the runtime: probes, backups, recovery bump, failure paths."""

import json

import pytest
from e2e_support import OPERATOR, STAGE

from growbridge.archive import snapshot as snapshots
from growbridge.archive.models import Channel, Entry
from growbridge.archive.source import SourceRewound
from growbridge.ports import ActionRequest, Denied
from growbridge.sim.fixtures import make_safety
from growbridge.workflow.states import StageState

SECRET = "correct horse battery"
EXPERIMENT = f"experiment-{STAGE}"
DATABASE_FILES = {
    f"{name}.sqlite3"
    for name in ("control", "workflow", "archive", "observer", "compute", "agents")
}


class Beat:
    """A dead-man's-switch endpoint that answers ``ok`` to every signal."""

    def __init__(self, ok: bool = True):
        self.ok = ok
        self.signals: list[str] = []

    async def ping(self) -> bool:
        self.signals.append("ping")
        return self.ok

    async def fail(self) -> bool:
        self.signals.append("fail")
        return self.ok


def kinds(runtime) -> list[str]:
    return [alert.kind for alert in runtime.book.open()]


def lines(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


# --- run-health probes and backups ----------------------------------------------------------------


async def test_capture_is_always_probed_and_missing_backups_are_a_standing_warning(world):
    runtime = await world.boot()
    await world.beat(runtime, 1)

    assert "capture" in runtime.health.probes and "capture" in runtime.health.limits
    assert "offsite_backup" not in runtime.health.limits
    standing = [a for a in runtime.book.open() if a.kind == "backup_unconfigured"]
    assert len(standing) == 1 and standing[0].severity == "warning"
    assert "offsite_backup" not in runtime.health.check().failures


async def test_capture_goes_stale_when_no_sample_arrives(world):
    runtime = await world.boot()
    await world.beat(runtime, 1)
    world.clock.advance(600)

    await runtime.tick()  # no fresh telemetry

    health = [a for a in runtime.book.open() if a.kind == "run_health"]
    assert len(health) == 1 and "capture" in health[0].message


async def test_capture_limit_follows_the_active_run_sheets_sampling_gap(world):
    runtime = await world.boot()
    await world.approved_stage(runtime)
    await world.beat(runtime, 1)

    assert runtime.health.limits["capture"] == 120  # sampling.max_gap_seconds of the sheet


async def test_backups_run_on_their_interval_and_feed_the_offsite_probe(world, tmp_path):
    target = tmp_path / "offsite"
    world.settings = world.settings.model_copy(
        update={"backup_dir": target, "backup_interval_seconds": 3600}
    )
    runtime = await world.boot()

    await world.beat(runtime, 1)
    first = runtime.backup_task
    await first
    assert {p.name for p in target.glob("*.sqlite3")} == DATABASE_FILES
    assert "backup_unconfigured" not in kinds(runtime)
    assert runtime.health.check().values["offsite_backup"] < 60

    await world.beat(runtime, 60)
    assert runtime.backup_task is first  # not due yet
    await world.beat(runtime, 3700)
    assert runtime.backup_task is not first
    await runtime.backup_task


async def test_a_failing_backup_raises_an_alert(world, tmp_path, monkeypatch):
    world.settings = world.settings.model_copy(update={"backup_dir": tmp_path / "offsite"})

    def broken(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("growbridge.runtime_backup.backup", broken)
    runtime = await world.boot()

    await world.beat(runtime, 1)
    await runtime.backup_task

    alerts = [a for a in runtime.book.open() if a.kind == "backup"]
    assert len(alerts) == 1 and "disk full" in alerts[0].message


async def test_failed_external_heartbeats_raise_alerts(world):
    host, run = Beat(ok=False), Beat(ok=True)
    runtime = await world.boot(heartbeats=(host, run))

    await world.beat(runtime, 1)

    assert [a.key for a in runtime.book.open() if a.kind == "external_monitor"] == ["host"]
    assert host.signals


async def test_external_heartbeats_are_sent_once_per_interval_not_on_every_tick(world):
    host, run = Beat(), Beat()
    runtime = await world.boot(heartbeats=(host, run), channels={})

    for _ in range(30):
        await world.beat(runtime, 1)  # thirty 1 Hz ticks: half of one heartbeat interval

    assert host.signals == ["ping"]
    assert run.signals == ["ping"]

    for _ in range(60):
        await world.beat(runtime, 1)

    assert host.signals == ["ping", "ping"]


async def test_run_failure_is_signalled_at_once_between_two_heartbeats(world):
    host, run = Beat(), Beat()
    runtime = await world.boot(heartbeats=(host, run), channels={})
    await world.beat(runtime, 1)
    assert run.signals == ["ping"]

    runtime.health.probes["capture"] = lambda: None  # the capture probe has no answer any more
    await world.beat(runtime, 1)

    assert run.signals == ["ping", "fail"]


# --- ingestion and reports ------------------------------------------------------------------------


async def test_samples_before_the_stage_started_are_not_attributed_to_it(world):
    runtime = await world.boot()
    await world.beat(runtime, 30)
    await world.beat(runtime, 30)  # received before any stage exists
    await world.approved_stage(runtime)
    started = runtime.workflow.stage(STAGE).started_at
    await world.beat(runtime, 30)
    await world.beat(runtime, 30)

    attributed = runtime.archive.samples(EXPERIMENT)
    assert attributed and all(sample.received_at >= started for sample in attributed)
    loose = runtime.archive.db.one("SELECT COUNT(*) AS n FROM samples WHERE experiment_id IS NULL")
    assert loose["n"] >= 2


async def test_a_rewound_sample_source_raises_an_alert_and_the_tick_goes_on(world, monkeypatch):
    runtime = await world.boot()

    def rewound(*_args, **_kwargs):
        raise SourceRewound("rowids were reused")

    monkeypatch.setattr(runtime.source, "read_after", rewound)
    await world.approved_stage(runtime)
    await world.beat(runtime, 30)

    assert "source_rewound" in kinds(runtime)
    assert "tick_step" not in kinds(runtime)
    assert (await runtime.control.read_state()).levels[Channel.LIGHT] == 60  # executor still ran


async def test_every_missed_daily_report_is_made_oldest_first(world):
    runtime = await world.boot()
    project, _round = await world.approved_stage(runtime)
    await world.beat(runtime, 30)
    assert runtime.reports.get(project, "2027-01-14") is not None

    await world.beat(runtime, 3 * 86400)  # three days of silence

    for day in ("2027-01-15", "2027-01-16", "2027-01-17"):
        assert runtime.reports.get(project, day) is not None, day


async def test_snapshot_holds_the_interventions_and_only_trusted_samples(world):
    runtime = await world.boot()
    await world.approved_stage(runtime)
    await world.beat(runtime, 30)
    await runtime.workflow.takeover(STAGE, world.operator)
    await world.beat(runtime, 5)
    await runtime.workflow.handback(STAGE, world.operator, accept_as_intervention=False)
    await world.run_until_ended(runtime)

    started = runtime.workflow.stage(STAGE).started_at
    shot = snapshots.freeze(
        runtime.archive, EXPERIMENT, world.clock, started, world.clock.now(), 60, 120
    )

    folder = runtime.archive.root / "snapshots" / shot.id
    rows = lines(folder / "samples.jsonl")
    assert rows and all(row["clock_synced"] for row in rows)
    assert [row["kind"] for row in lines(folder / "interventions.jsonl")] == ["takeover"]


# --- recovery bump --------------------------------------------------------------------------------


async def test_recovery_bump_voids_approvals_and_sessions_until_safety_is_reapproved(world):
    runtime = await world.boot()
    await world.approved_stage(runtime)
    await world.beat(runtime, 30)
    flow = runtime.workflow
    runtime.operators.add("alice", SECRET)
    token = runtime.operators.login(
        "alice", SECRET, Entry.LAN, recovery_number=runtime.control.recovery_number()
    )

    number = await runtime.bump_recovery("restored from backup")

    assert number == 2 == runtime.control.recovery_number()  # a new ledger starts at 1
    assert flow.stage(STAGE).state is StageState.RECOVERY_CHECK
    assert all(approval.voided_at is not None for approval in flow.approvals(STAGE))
    with pytest.raises(Denied):
        runtime.operators.actor(token, number)

    await world.beat(runtime, 1)  # the safety config of the old number is not valid
    assert flow.stage(STAGE).state is StageState.RECOVERY_CHECK
    runtime.control.approve_safety(make_safety(), OPERATOR)
    await world.beat(runtime, 1)
    assert flow.stage(STAGE).state is StageState.PENDING_REVIEW


# --- reviewed failure paths -----------------------------------------------------------------------


async def test_a_lost_write_reply_pauses_the_stage_and_resume_reconciles_it(world):
    world.sim.config["device"]["blower"]["mLevel"] = 30  # only the light is off its schedule
    runtime = await world.boot()
    await world.approved_stage(runtime)
    world.sim.lose_replies = True  # the write is applied but never answered

    await world.beat(runtime, 30)

    flow = runtime.workflow
    assert flow.stage(STAGE).state is StageState.PAUSED
    assert runtime.control.unsettled_actions()
    world.sim.lose_replies = False
    await world.beat(runtime, 5)  # fresh telemetry

    resumed = await flow.resume_stage(STAGE, world.operator)

    assert resumed.state is StageState.RUNNING
    assert runtime.control.unsettled_actions() == ()


async def test_restart_after_a_takeover_rewrites_the_scheduled_level(world):
    first = await world.boot()
    await world.approved_stage(first)
    await world.beat(first, 30)
    assert (await first.control.read_state()).levels[Channel.LIGHT] == 60
    taken = await first.workflow.takeover(STAGE, world.operator)
    manual = ActionRequest(
        request_id="manual-light",
        right_number=taken.manual_right,
        channel=Channel.LIGHT,
        level=20,
        trigger="operator dims the light",
        experiment_id=EXPERIMENT,
        stage_id=STAGE,
        operator=OPERATOR,
    )
    await first.control.submit(manual)
    await first.stop()

    world.clock.advance(5)
    second = await world.boot()
    assert second.workflow.stage(STAGE).state is StageState.RECOVERY_CHECK
    await world.beat(second, 1)
    assert second.workflow.stage(STAGE).state is StageState.MANUAL
    await second.workflow.handback(STAGE, world.operator, accept_as_intervention=True)
    before = len(world.sim.commands)

    await world.beat(second, 5)

    assert (await second.control.read_state()).levels[Channel.LIGHT] == 60
    assert len(world.sim.commands) > before  # a new write, not the old receipt
