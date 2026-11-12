"""The confirmatory entry on the runner side: the frozen script text, who froze it, the state of
each snapshot's one run and a run that leaves the event loop free."""

import asyncio
import threading

import pytest

from growbridge.archive.db import Database
from growbridge.archive.ids import file_digest
from growbridge.archive.models import AnalysisPlan, Snapshot
from growbridge.ports import Denied
from growbridge.research import analysis as analysis_module
from growbridge.research.analysis import MAX_SCRIPT_CHARS, STEPS, ConfirmatoryRunner
from growbridge.research.sandbox import SandboxResult
from growbridge.sim.clock import FakeClock
from growbridge.sim.fixtures import make_protocol

SCRIPT = b"print('frozen analysis')\n"
GATE_SECONDS = 5.0  # a sandbox that is never released must not hang the suite


class ScriptedSandbox:
    """Records what it was given; optionally blocks until released, like a long analysis."""

    def __init__(self, exit_code: int = 0, timed_out: bool = False, error: Exception | None = None):
        self.result = SandboxResult(exit_code, "out", "", timed_out)
        self.error = error
        self.calls: list[dict] = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block = False
        self.during = None  # called inside run (in the sandbox thread)

    def run(self, script, snapshot_dir, out_dir, timeout):
        self.calls.append(
            {"text": script.read_bytes(), "thread": threading.get_ident(), "out": out_dir}
        )
        self.entered.set()
        if self.during is not None:
            self.during()
        if self.block:
            assert self.release.wait(GATE_SECONDS), "the sandbox was never released"
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "research.db")
    yield database
    database.close()


@pytest.fixture
def snapshot_dir(tmp_path):
    directory = tmp_path / "snapshot"
    directory.mkdir()
    (directory / "samples.jsonl").write_text('{"v": 1}\n')
    (directory / "manifest.json").write_text('{"files": "samples.jsonl"}')
    return directory


def snapshot_of(directory, **overrides) -> Snapshot:
    fields = {
        "id": "snap-1",
        "experiment_id": "experiment-1",
        "version": 1,
        "created_at": 1_800_000_000.0,
        "manifest_sha256": file_digest(directory / "manifest.json"),
        "complete": True,
        "coverage": 0.99,
        "files": {"samples.jsonl": file_digest(directory / "samples.jsonl")},
    }
    return Snapshot(**{**fields, **overrides})


@pytest.fixture
def sandbox():
    return ScriptedSandbox()


@pytest.fixture
def runner(db, sandbox, tmp_path):
    return ConfirmatoryRunner(db, FakeClock(), sandbox, tmp_path / "work")


# --- freezing keeps the text and the person ----------------------------------------------------


def test_freeze_keeps_the_script_text_and_who_froze_it(runner):
    protocol = make_protocol()

    sha = runner.freeze_analysis(protocol, SCRIPT, "alice")

    assert runner.frozen_script(protocol) == (sha, SCRIPT)
    info = runner.frozen_info(protocol)
    assert (info.sha256, info.frozen_by, info.frozen_at) == (sha, "alice", FakeClock().now())


def test_nothing_is_frozen_before_a_freeze_and_for_another_version(runner):
    protocol = make_protocol()
    assert runner.frozen_script(protocol) is None
    assert runner.frozen_info(protocol) is None

    runner.freeze_analysis(protocol, SCRIPT, "alice")

    assert runner.frozen_script(make_protocol(version=2)) is None


def test_freezing_the_same_text_again_keeps_the_first_freezer(runner):
    protocol = make_protocol()
    first = runner.freeze_analysis(protocol, SCRIPT, "alice")

    second = runner.freeze_analysis(protocol, SCRIPT, "bob")

    assert first == second
    assert runner.frozen_info(protocol).frozen_by == "alice"


def test_a_different_text_for_a_frozen_version_is_refused(runner):
    protocol = make_protocol()
    runner.freeze_analysis(protocol, SCRIPT, "alice")

    with pytest.raises(Denied) as caught:
        runner.freeze_analysis(protocol, b"print('other')\n", "alice")

    assert caught.value.code == "script_hash"
    assert runner.frozen_script(protocol)[1] == SCRIPT


def test_a_text_that_differs_from_the_hash_in_the_protocol_is_refused(runner):
    plan = AnalysisPlan(
        primary_endpoint="canopy_area_growth",
        target_effect=0.15,
        method="paired_block",
        script_sha256="0" * 64,
    )

    with pytest.raises(Denied) as caught:
        runner.freeze_analysis(make_protocol(analysis=plan), SCRIPT, "alice")

    assert caught.value.code == "script_hash"


@pytest.mark.parametrize("bad", [b"\xff\xfe\x00", b"", b"x" * (MAX_SCRIPT_CHARS + 1)])
def test_scripts_that_are_not_text_or_empty_or_too_long_are_refused(runner, bad):
    with pytest.raises(Denied) as caught:
        runner.freeze_analysis(make_protocol(), bad, "alice")

    assert caught.value.code == "param"
    assert runner.frozen_script(make_protocol()) is None


def test_the_limit_counts_characters_not_bytes(runner):
    text = ("é" * MAX_SCRIPT_CHARS).encode()  # twice as many bytes as characters

    sha = runner.freeze_analysis(make_protocol(), text, "alice")

    assert runner.frozen_script(make_protocol()) == (sha, text)


def test_a_script_file_is_still_accepted(runner, tmp_path):
    path = tmp_path / "analysis.py"
    path.write_bytes(SCRIPT)

    sha = runner.freeze_analysis(make_protocol(), path)

    assert sha == file_digest(path)
    assert runner.frozen_script(make_protocol()) == (sha, SCRIPT)


# --- the state of a snapshot's run -------------------------------------------------------------


async def test_status_goes_from_none_to_running_to_succeeded(runner, sandbox, snapshot_dir):
    protocol, snapshot = make_protocol(), snapshot_of(snapshot_dir)
    runner.freeze_analysis(protocol, SCRIPT, "alice")
    seen = []
    sandbox.during = lambda: seen.append(runner.status("snap-1", protocol))
    assert runner.status("snap-1", protocol) == "none"

    run = await runner.run_frozen(protocol, snapshot, snapshot_dir, "alice")

    assert seen == ["running"]
    assert runner.status("snap-1", protocol) == "succeeded"
    assert (run.status, run.label, run.exit_code) == ("succeeded", "confirmatory", 0)


@pytest.mark.parametrize("fields", [{"exit_code": 1}, {"timed_out": True}])
async def test_a_failed_or_timed_out_run_has_status_failed(db, tmp_path, snapshot_dir, fields):
    runner = ConfirmatoryRunner(db, FakeClock(), ScriptedSandbox(**fields), tmp_path / "work")
    protocol = make_protocol()
    runner.freeze_analysis(protocol, SCRIPT, "alice")

    run = await runner.run_frozen(protocol, snapshot_of(snapshot_dir), snapshot_dir, "alice")

    assert runner.status("snap-1", protocol) == "failed"
    assert (run.status, run.label) == ("failed", "exploratory")


async def test_status_is_per_protocol_version_and_per_snapshot(runner, snapshot_dir):
    protocol = make_protocol()
    runner.freeze_analysis(protocol, SCRIPT, "alice")
    await runner.run_frozen(protocol, snapshot_of(snapshot_dir), snapshot_dir, "alice")

    assert runner.status("snap-1", protocol) == "succeeded"
    assert runner.status("snap-2", protocol) == "none"
    assert runner.status("snap-1", make_protocol(version=2)) == "none"
    assert runner.status("snap-1", make_protocol(id="protocol-2")) == "none"


# --- run_frozen --------------------------------------------------------------------------------


async def test_run_frozen_runs_the_stored_text_and_records_who_started_it(
    runner, sandbox, db, snapshot_dir
):
    protocol = make_protocol()
    sha = runner.freeze_analysis(protocol, SCRIPT, "alice")

    run = await runner.run_frozen(protocol, snapshot_of(snapshot_dir), snapshot_dir, "bob")

    assert sandbox.calls[0]["text"] == SCRIPT
    assert run.script_sha256 == sha
    row = db.one("SELECT started_by FROM research_runs WHERE id = ?", (run.id,))
    assert row["started_by"] == "bob"
    assert runner.completed("snap-1", protocol) is True


async def test_run_frozen_without_a_frozen_script_is_refused(runner, sandbox, snapshot_dir):
    with pytest.raises(Denied) as caught:
        await runner.run_frozen(make_protocol(), snapshot_of(snapshot_dir), snapshot_dir, "bob")

    assert caught.value.code == "state"
    assert sandbox.calls == []


async def test_a_second_run_of_the_same_snapshot_is_refused(runner, sandbox, snapshot_dir):
    protocol, snapshot = make_protocol(), snapshot_of(snapshot_dir)
    runner.freeze_analysis(protocol, SCRIPT, "alice")
    await runner.run_frozen(protocol, snapshot, snapshot_dir, "bob")

    with pytest.raises(Denied) as caught:
        await runner.run_frozen(protocol, snapshot, snapshot_dir, "bob")

    assert caught.value.code == "already_run"
    assert len(sandbox.calls) == 1


async def test_a_snapshot_that_no_longer_matches_is_refused_before_the_sandbox(
    runner, sandbox, snapshot_dir
):
    protocol, snapshot = make_protocol(), snapshot_of(snapshot_dir)
    runner.freeze_analysis(protocol, SCRIPT, "alice")
    (snapshot_dir / "samples.jsonl").write_text("tampered\n")

    with pytest.raises(Denied) as caught:
        await runner.run_frozen(protocol, snapshot, snapshot_dir, "bob")

    assert caught.value.code == "snapshot_incomplete"
    assert sandbox.calls == [] and runner.status("snap-1", protocol) == "none"


async def test_a_refusal_from_the_admit_check_leaves_no_run_behind(runner, sandbox, snapshot_dir):
    protocol, snapshot = make_protocol(), snapshot_of(snapshot_dir)
    runner.freeze_analysis(protocol, SCRIPT, "alice")

    def refuse():
        raise Denied("scope", "not for analysis")

    with pytest.raises(Denied) as caught:
        await runner.run_frozen(protocol, snapshot, snapshot_dir, "bob", admit=refuse)

    assert caught.value.code == "scope"
    assert sandbox.calls == [] and runner.status("snap-1", protocol) == "none"
    run = await runner.run_frozen(protocol, snapshot, snapshot_dir, "bob")  # still available
    assert run.status == "succeeded"


async def test_a_sandbox_that_refuses_to_run_releases_the_attempt(db, tmp_path, snapshot_dir):
    refusing = ScriptedSandbox(error=Denied("sandbox_unavailable"))
    runner = ConfirmatoryRunner(db, FakeClock(), refusing, tmp_path / "work")
    protocol = make_protocol()
    runner.freeze_analysis(protocol, SCRIPT, "alice")

    with pytest.raises(Denied) as caught:
        await runner.run_frozen(protocol, snapshot_of(snapshot_dir), snapshot_dir, "bob")

    assert caught.value.code == "sandbox_unavailable"
    assert runner.status("snap-1", protocol) == "none"


async def test_a_sandbox_that_crashes_is_recorded_as_a_failed_attempt(db, tmp_path, snapshot_dir):
    crashing = ScriptedSandbox(error=RuntimeError("secret detail"))
    runner = ConfirmatoryRunner(db, FakeClock(), crashing, tmp_path / "work")
    protocol = make_protocol()
    runner.freeze_analysis(protocol, SCRIPT, "alice")

    run = await runner.run_frozen(protocol, snapshot_of(snapshot_dir), snapshot_dir, "bob")

    assert run.status == "failed" and run.exit_code != 0
    assert "secret detail" not in run.stderr
    assert runner.status("snap-1", protocol) == "failed"  # never left "running" forever


async def test_the_event_loop_keeps_running_while_the_sandbox_works(runner, sandbox, snapshot_dir):
    protocol, snapshot = make_protocol(), snapshot_of(snapshot_dir)
    runner.freeze_analysis(protocol, SCRIPT, "alice")
    sandbox.block = True
    loop_thread = threading.get_ident()
    ticks = 0

    task = asyncio.create_task(runner.run_frozen(protocol, snapshot, snapshot_dir, "bob"))
    try:
        assert await asyncio.to_thread(sandbox.entered.wait, GATE_SECONDS)
        for _ in range(3):
            await asyncio.sleep(0.01)
            ticks += 1
        assert not task.done()
        assert runner.status("snap-1", protocol) == "running"  # written before the sandbox ran
    finally:
        sandbox.release.set()
    run = await asyncio.wait_for(task, GATE_SECONDS)

    assert ticks == 3
    assert sandbox.calls[0]["thread"] != loop_thread
    assert run.status == "succeeded"


async def test_two_runs_started_together_let_only_one_through(runner, sandbox, snapshot_dir):
    protocol, snapshot = make_protocol(), snapshot_of(snapshot_dir)
    runner.freeze_analysis(protocol, SCRIPT, "alice")
    sandbox.block = True

    first = asyncio.create_task(runner.run_frozen(protocol, snapshot, snapshot_dir, "bob"))
    second = asyncio.create_task(runner.run_frozen(protocol, snapshot, snapshot_dir, "carol"))
    try:
        assert await asyncio.to_thread(sandbox.entered.wait, GATE_SECONDS)
        await asyncio.sleep(0.01)  # the second request has met the claim of the first
    finally:
        sandbox.release.set()
    outcomes = await asyncio.wait_for(
        asyncio.gather(first, second, return_exceptions=True), GATE_SECONDS
    )

    # Snapshot checks run in worker threads, so either request may reach the claim first.
    runs = [outcome for outcome in outcomes if not isinstance(outcome, BaseException)]
    refusals = [outcome for outcome in outcomes if isinstance(outcome, Denied)]
    assert [run.status for run in runs] == ["succeeded"]
    assert [refusal.code for refusal in refusals] == ["already_run"]
    assert len(sandbox.calls) == 1


# --- older databases ---------------------------------------------------------------------------


def test_an_older_database_is_migrated_and_its_scripts_have_no_stored_text(tmp_path):
    database = Database(tmp_path / "old.db")
    database.migrate("research_analysis", STEPS[:2])  # the schema before the entry existed
    legacy = ("protocol-1", 1, "a" * 64, 1.0)
    database.execute("INSERT INTO research_scripts VALUES (?, ?, ?, ?)", legacy)
    try:
        runner = ConfirmatoryRunner(database, FakeClock(), ScriptedSandbox(), tmp_path / "work")

        assert runner.frozen_script(make_protocol()) is None  # only the hash is known
        info = runner.frozen_info(make_protocol())
        assert (info.sha256, info.frozen_by) == ("a" * 64, None)
    finally:
        database.close()


# --- runs that a dead process left unfinished --------------------------------------------------


def leave_running(db, runner, protocol, snapshot_id: str = "snap-1") -> None:
    """What a process that died mid-run leaves: a claimed run with no end."""
    db.execute(
        "INSERT INTO research_runs(id, protocol_id, protocol_version, snapshot_id, "
        "script_sha256, started_at, started_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("run-live", protocol.id, protocol.version, snapshot_id, "a" * 64, 1.0, "bob"),
    )


def test_an_unfinished_run_is_settled_as_failed_and_marked_interrupted(runner, db, caplog):
    protocol = make_protocol()
    runner.freeze_analysis(protocol, SCRIPT, "alice")
    leave_running(db, runner, protocol)
    assert runner.status("snap-1", protocol) == "running"

    with caplog.at_level("WARNING"):
        settled = runner.settle_interrupted()

    assert settled == ("run-live",)
    assert runner.status("snap-1", protocol) == "failed"
    assert runner.completed("snap-1", protocol) is False
    row = db.one("SELECT * FROM research_runs WHERE id = 'run-live'")
    assert row["finished_at"] == FakeClock().now() and row["exit_code"] == -1
    assert row["timed_out"] == 0 and row["interrupted"] == 1
    assert [r.message for r in caplog.records if "run-live" in r.message]


def test_a_settled_run_still_uses_up_the_attempt(runner, db, snapshot_dir):
    protocol = make_protocol()
    runner.freeze_analysis(protocol, SCRIPT, "alice")
    leave_running(db, runner, protocol)
    runner.settle_interrupted()

    with pytest.raises(Denied) as caught:
        asyncio.run(runner.run_frozen(protocol, snapshot_of(snapshot_dir), snapshot_dir, "bob"))

    assert caught.value.code == "already_run"


async def test_finished_runs_are_left_alone_and_settling_twice_changes_nothing(
    runner, db, snapshot_dir
):
    protocol = make_protocol()
    runner.freeze_analysis(protocol, SCRIPT, "alice")
    done = await runner.run_frozen(protocol, snapshot_of(snapshot_dir), snapshot_dir, "bob")
    leave_running(db, runner, protocol, snapshot_id="snap-2")

    first = runner.settle_interrupted()
    second = runner.settle_interrupted()

    assert first == ("run-live",) and second == ()
    row = db.one("SELECT * FROM research_runs WHERE id = ?", (done.id,))
    assert row["exit_code"] == 0 and row["interrupted"] == 0
    assert runner.status("snap-1", protocol) == "succeeded"


def test_a_database_from_before_the_marker_is_migrated(tmp_path):
    database = Database(tmp_path / "old.db")
    database.migrate("research_analysis", STEPS[:5])  # up to the freezing entry
    try:
        runner = ConfirmatoryRunner(database, FakeClock(), ScriptedSandbox(), tmp_path / "work")

        assert runner.settle_interrupted() == ()
    finally:
        database.close()


# --- no path leaves a run "running" once nothing executes it -----------------------------------


async def test_an_unwritable_work_folder_leaves_no_run_and_keeps_the_attempt(
    db, sandbox, tmp_path, snapshot_dir
):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, so nothing can be created below it")
    runner = ConfirmatoryRunner(db, FakeClock(), sandbox, blocker / "work")
    protocol, snapshot = make_protocol(), snapshot_of(snapshot_dir)
    runner.freeze_analysis(protocol, SCRIPT, "alice")

    for _ in range(2):  # the second try is not "already_run": the first left nothing behind
        with pytest.raises(Denied) as caught:
            await runner.run_frozen(protocol, snapshot, snapshot_dir, "bob")
        assert caught.value.code == "state"

    assert runner.status("snap-1", protocol) == "none"
    assert db.one("SELECT COUNT(*) AS n FROM research_runs")["n"] == 0
    assert sandbox.calls == []


async def test_cancelling_the_request_still_records_the_run(runner, sandbox, snapshot_dir):
    protocol, snapshot = make_protocol(), snapshot_of(snapshot_dir)
    runner.freeze_analysis(protocol, SCRIPT, "alice")
    sandbox.block = True

    request = asyncio.create_task(runner.run_frozen(protocol, snapshot, snapshot_dir, "bob"))
    assert await asyncio.to_thread(sandbox.entered.wait, GATE_SECONDS)
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    assert runner.status("snap-1", protocol) == "running"  # the sandbox is still going
    sandbox.release.set()
    for _ in range(300):
        if runner.status("snap-1", protocol) != "running":
            break
        await asyncio.sleep(0.01)

    assert runner.status("snap-1", protocol) == "succeeded"  # recorded, though nobody waited


async def test_verification_and_the_admit_check_run_off_the_event_loop(
    runner, sandbox, snapshot_dir, monkeypatch
):
    protocol, snapshot = make_protocol(), snapshot_of(snapshot_dir)
    runner.freeze_analysis(protocol, SCRIPT, "alice")
    real, entered, gate, seen = (
        analysis_module._check_snapshot,
        threading.Event(),
        threading.Event(),
        [],
    )

    def slow_check(snap, directory):
        seen.append(threading.get_ident())
        entered.set()
        assert gate.wait(GATE_SECONDS), "verification was never released"
        real(snap, directory)

    monkeypatch.setattr(analysis_module, "_check_snapshot", slow_check)
    admitted = []
    request = asyncio.create_task(
        runner.run_frozen(
            protocol,
            snapshot,
            snapshot_dir,
            "bob",
            admit=lambda: admitted.append(threading.get_ident()),
        )
    )
    try:
        assert await asyncio.to_thread(entered.wait, GATE_SECONDS)
        for _ in range(3):
            await asyncio.sleep(0.01)  # the loop is free while the files are hashed
        assert not request.done() and runner.status("snap-1", protocol) == "none"
    finally:
        gate.set()
    run = await asyncio.wait_for(request, GATE_SECONDS)

    assert run.status == "succeeded"
    loop_thread = threading.get_ident()
    assert seen[0] != loop_thread and admitted[0] != loop_thread


# --- a script that cannot run is not frozen ----------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [b"def broken(:\n", b"print('a')\x00\n", b"x = (1,\n"],
    ids=["syntax-error", "nul-byte", "unclosed"],
)
def test_a_script_that_cannot_compile_is_refused_when_frozen(runner, bad):
    with pytest.raises(Denied) as caught:
        runner.freeze_analysis(make_protocol(), bad, "alice")

    assert caught.value.code == "param"
    assert runner.frozen_script(make_protocol()) is None


def test_the_refusal_names_the_line_of_the_error(runner):
    with pytest.raises(Denied) as caught:
        runner.freeze_analysis(make_protocol(), b"x = 1\ny = (\n", "alice")

    assert "analysis.py" in str(caught.value) or "line" in str(caught.value)


def test_a_script_is_compiled_when_frozen_never_executed(runner, tmp_path):
    marker = tmp_path / "ran"
    script = f"open({str(marker)!r}, 'w').write('x')\nraise SystemExit(3)\n".encode()

    runner.freeze_analysis(make_protocol(), script, "alice")

    assert not marker.exists()
