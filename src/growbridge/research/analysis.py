"""Confirmatory-analysis gate (architecture doc §9.1 and §9.3).

``classify`` applies the five downgrade rules, ``conclusion`` refuses to call an under-powered
result "no effect", and ``ConfirmatoryRunner`` lets exactly one frozen script run once per
protocol version and data snapshot.
"""

import asyncio
import hashlib
import logging
import shutil
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from growbridge.archive.clock import Clock
from growbridge.archive.db import Database
from growbridge.archive.ids import file_digest, new_id
from growbridge.archive.models import Label, Model, ResearchProtocol, Snapshot
from growbridge.ports import Denied
from growbridge.research.notes import Note, note
from growbridge.research.sandbox import Sandbox, SandboxResult
from growbridge.research.stats import BlockEstimate

Conclusion = Literal["supported", "not_supported", "uncertain"]
RunStatus = Literal["none", "running", "succeeded", "failed"]
LOG = logging.getLogger(__name__)
MANIFEST = "manifest.json"
MAX_SCRIPT_CHARS = 20_000
MIN_REPLICATES = 2
DEFAULT_TIMEOUT_SECONDS = 600.0

STEPS = (
    "CREATE TABLE research_scripts("
    "protocol_id TEXT NOT NULL, protocol_version INTEGER NOT NULL, script_sha256 TEXT NOT NULL, "
    "frozen_at REAL NOT NULL, PRIMARY KEY(protocol_id, protocol_version))",
    "CREATE TABLE research_runs("
    "id TEXT PRIMARY KEY, protocol_id TEXT NOT NULL, protocol_version INTEGER NOT NULL, "
    "snapshot_id TEXT NOT NULL, script_sha256 TEXT NOT NULL, started_at REAL NOT NULL, "
    "finished_at REAL, exit_code INTEGER, timed_out INTEGER, "
    "UNIQUE(protocol_id, protocol_version, snapshot_id))",
    "CREATE TABLE research_script_files(sha256 TEXT PRIMARY KEY, content BLOB NOT NULL)",
    "ALTER TABLE research_scripts ADD COLUMN frozen_by TEXT",
    "ALTER TABLE research_runs ADD COLUMN started_by TEXT",
    "ALTER TABLE research_runs ADD COLUMN interrupted INTEGER NOT NULL DEFAULT 0",
)


class AnalysisFacts(Model):
    independent_replicates: int
    confounded_with_time: bool
    missing_fraction: float
    changed_after_outcomes: bool
    deviation_fraction: float
    planned_sample_size: int
    achieved_sample_size: int
    early_terminated: bool


class AnalysisDecision(Model):
    """The label and why it was lowered: ``notes`` in both languages, ``reasons`` their text."""

    label: Label
    reasons: tuple[str, ...] = ()
    notes: tuple[Note, ...] = ()


def decided(label: Label, notes: tuple[Note, ...] = ()) -> AnalysisDecision:
    return AnalysisDecision(label=label, reasons=tuple(n.text() for n in notes), notes=notes)


class AnalysisRun(Model):
    id: str
    protocol_id: str
    protocol_version: int
    snapshot_id: str
    script_sha256: str
    label: Label
    status: Literal["succeeded", "failed"]
    started_at: float
    finished_at: float
    exit_code: int
    timed_out: bool
    out_dir: str
    stdout: str = ""
    stderr: str = ""


def classify(protocol: ResearchProtocol, facts: AnalysisFacts) -> AnalysisDecision:
    """§9.3: the label a result may carry, and why it was lowered."""
    plan = protocol.analysis
    descriptive: list[Note] = []
    exploratory: list[Note] = []
    if facts.independent_replicates < MIN_REPLICATES:
        descriptive.append(note("no_replicates"))
    if facts.confounded_with_time:
        descriptive.append(note("confounded_with_time"))
    if facts.missing_fraction > plan.max_missing_fraction:
        exploratory.append(note("missing_over_limit"))
    if facts.changed_after_outcomes:
        exploratory.append(note("changed_after_outcomes"))
    if facts.deviation_fraction > plan.max_deviation_fraction:
        exploratory.append(note("deviation_over_limit"))
    notes = tuple(descriptive + exploratory)
    if descriptive:
        return decided("descriptive", notes)
    if exploratory:
        return decided("exploratory", notes)
    return decided("confirmatory")


def conclusion(estimate: BlockEstimate, facts: AnalysisFacts, alpha: float = 0.05) -> Conclusion:
    """Never "no effect" from an incomplete, stopped or too small experiment."""
    if facts.early_terminated or facts.achieved_sample_size < facts.planned_sample_size:
        return "uncertain"
    if not estimate.estimable or estimate.p_value is None:
        return "uncertain"
    if 2.0 ** (1 - estimate.blocks) > alpha:
        return "uncertain"  # the test cannot reach alpha with so few blocks
    return "supported" if estimate.p_value < alpha else "not_supported"


class FrozenScript(Model):
    """What is registered for a protocol version; the text itself is read with ``frozen_script``."""

    protocol_id: str
    protocol_version: int
    sha256: str
    frozen_at: float
    frozen_by: str | None = None  # None: frozen before the person was recorded


@dataclass(frozen=True)
class _Started:
    """A run that has been claimed: its id, its own copy of the script and its output folder."""

    run_id: str
    protocol: ResearchProtocol
    snapshot: Snapshot
    sha: str
    started: float
    script: Path
    out_dir: Path


def _script_text(content: bytes) -> None:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise Denied("param", "the analysis script must be UTF-8 text") from None
    if not text.strip():
        raise Denied("param", "the analysis script is empty")
    if len(text) > MAX_SCRIPT_CHARS:
        raise Denied("param", f"the analysis script is longer than {MAX_SCRIPT_CHARS} characters")
    # Frozen means final: a script that cannot even compile would burn the only attempt.
    # It is compiled here, never executed.
    try:
        compile(text, "analysis.py", "exec")
    except SyntaxError as error:
        raise Denied("param", f"the analysis script has a syntax error: {error}") from None
    except (ValueError, RecursionError, MemoryError) as error:
        raise Denied("param", f"the analysis script cannot be compiled: {error}") from None


class ConfirmatoryRunner:
    """One frozen script per protocol version, one run per snapshot.

    A run that fails or times out still uses up the snapshot's attempt: it is recorded as
    failed, never as confirmatory, and cannot be repeated.
    """

    def __init__(self, db: Database, clock: Clock, sandbox: Sandbox, work_root: Path):
        self.db = db
        self.clock = clock
        self.sandbox = sandbox
        self.work_root = work_root
        self.timeout = DEFAULT_TIMEOUT_SECONDS
        self._recording: set[asyncio.Future] = set()
        db.migrate("research_analysis", STEPS)

    def freeze_analysis(
        self, protocol: ResearchProtocol, script: bytes | Path, actor_id: str = ""
    ) -> str:
        """Register the script (its text and the freezer) for this protocol version.

        A version has one script; freezing the same text again changes nothing.
        """
        content = script.read_bytes() if isinstance(script, Path) else bytes(script)
        _script_text(content)
        sha = hashlib.sha256(content).hexdigest()
        declared = protocol.analysis.script_sha256
        if declared is not None and declared != sha:
            raise Denied("script_hash", "script differs from the hash in the protocol")
        with self.db.transaction():
            frozen = self._frozen(protocol)
            if frozen is not None and frozen != sha:
                raise Denied("script_hash", "a different script is already frozen")
            if frozen is None:
                self.db.execute(
                    "INSERT INTO research_scripts(protocol_id, protocol_version, script_sha256, "
                    "frozen_at, frozen_by) VALUES (?, ?, ?, ?, ?)",
                    (protocol.id, protocol.version, sha, self.clock.now(), actor_id or None),
                )
            self.db.execute(
                "INSERT OR IGNORE INTO research_script_files(sha256, content) VALUES (?, ?)",
                (sha, content),
            )
        return sha

    def frozen_info(self, protocol: ResearchProtocol) -> FrozenScript | None:
        row = self.db.one(
            "SELECT script_sha256, frozen_at, frozen_by FROM research_scripts "
            "WHERE protocol_id = ? AND protocol_version = ?",
            (protocol.id, protocol.version),
        )
        if row is None:
            return None
        return FrozenScript(
            protocol_id=protocol.id,
            protocol_version=protocol.version,
            sha256=row["script_sha256"],
            frozen_at=row["frozen_at"],
            frozen_by=row["frozen_by"],
        )

    def frozen_script(self, protocol: ResearchProtocol) -> tuple[str, bytes] | None:
        """The registered hash and the stored text; None when nothing, or only a hash, is known."""
        row = self.db.one(
            "SELECT f.sha256, f.content FROM research_scripts s JOIN research_script_files f "
            "ON f.sha256 = s.script_sha256 WHERE s.protocol_id = ? AND s.protocol_version = ?",
            (protocol.id, protocol.version),
        )
        return None if row is None else (row["sha256"], bytes(row["content"]))

    def status(self, snapshot_id: str, protocol: ResearchProtocol) -> RunStatus:
        row = self.db.one(
            "SELECT finished_at, exit_code, timed_out FROM research_runs "
            "WHERE protocol_id = ? AND protocol_version = ? AND snapshot_id = ?",
            (protocol.id, protocol.version, snapshot_id),
        )
        if row is None:
            return "none"
        if row["finished_at"] is None:
            return "running"
        return "succeeded" if row["exit_code"] == 0 and not row["timed_out"] else "failed"

    def completed(self, snapshot_id: str, protocol: ResearchProtocol) -> bool:
        """True when a run under this protocol version, with its registered script, succeeded."""
        row = self.db.one(
            "SELECT 1 FROM research_runs r JOIN research_scripts s "
            "ON s.protocol_id = r.protocol_id AND s.protocol_version = r.protocol_version "
            "AND s.script_sha256 = r.script_sha256 "
            "WHERE r.snapshot_id = ? AND r.protocol_id = ? AND r.protocol_version = ? "
            "AND r.exit_code = 0 AND r.timed_out = 0",
            (snapshot_id, protocol.id, protocol.version),
        )
        return row is not None

    def settle_interrupted(self) -> tuple[str, ...]:
        """Settle every run that never ended as failed, and mark it ``interrupted``.

        Called when the process starts: in one process nothing can still be running then, so an
        unfinished row belongs to a process that died. The attempt stays used up (the run cannot
        be repeated), and the snapshot no longer blocks a report, which is then exploratory.
        ``exit_code`` is -1 and ``interrupted`` is 1, which tells it from a script that failed.
        """
        with self.db.transaction():
            rows = self.db.query(
                "SELECT id, protocol_id, protocol_version, snapshot_id FROM research_runs "
                "WHERE finished_at IS NULL ORDER BY started_at, id"
            )
            now = self.clock.now()
            for row in rows:
                self.db.execute(
                    "UPDATE research_runs SET finished_at = ?, exit_code = -1, timed_out = 0, "
                    "interrupted = 1 WHERE id = ?",
                    (now, row["id"]),
                )
                LOG.warning(
                    "run %s of snapshot %s (protocol %s version %s) was interrupted by a restart;"
                    " settled as failed",
                    row["id"],
                    row["snapshot_id"],
                    row["protocol_id"],
                    row["protocol_version"],
                )
        return tuple(row["id"] for row in rows)

    def _frozen(self, protocol: ResearchProtocol) -> str | None:
        info = self.frozen_info(protocol)
        return None if info is None else info.sha256

    def run(
        self, protocol: ResearchProtocol, snapshot: Snapshot, snapshot_dir: Path, script: Path
    ) -> AnalysisRun:
        """Run a script file that matches the frozen hash, blocking until it is done."""
        content = script.read_bytes()
        self._matches_frozen(protocol, content)
        _verify(snapshot, snapshot_dir, None)
        started = self._begin(protocol, snapshot, content, "")
        try:
            result = self.sandbox.run(started.script, snapshot_dir, started.out_dir, self.timeout)
        except Exception as error:
            result = self._failed(started, error)
        return self._finish(started, result)

    async def run_frozen(
        self,
        protocol: ResearchProtocol,
        snapshot: Snapshot,
        snapshot_dir: Path,
        actor_id: str,
        admit: Callable[[], None] | None = None,
    ) -> AnalysisRun:
        """Run the stored frozen script once.

        Hashing the snapshot and the ``admit`` check (which refuses by raising ``Denied``) run in
        a worker thread, so a large snapshot does not stall the event loop. Everything after
        that up to the claim is synchronous: two requests cannot both claim the snapshot. The
        sandbox runs in a worker thread too. Once claimed, the run is recorded to its end in a
        task of its own: cancelling the request (shutdown, a client that goes away) does not
        leave the run ``running``.
        """
        stored = self.frozen_script(protocol)
        if stored is None:
            raise Denied("state", "no analysis script is frozen for this protocol version")
        self._matches_frozen(protocol, stored[1])
        await asyncio.to_thread(_verify, snapshot, snapshot_dir, admit)
        started = self._begin(protocol, snapshot, stored[1], actor_id)
        task = asyncio.ensure_future(self._execute(started, snapshot_dir))
        self._recording.add(task)  # a task nobody references may be collected half way
        task.add_done_callback(self._recording.discard)
        return await asyncio.shield(task)

    async def _execute(self, started: _Started, snapshot_dir: Path) -> AnalysisRun:
        try:
            call = (started.script, snapshot_dir, started.out_dir, self.timeout)
            result = await asyncio.to_thread(self.sandbox.run, *call)
        except Exception as error:
            result = self._failed(started, error)
        return self._finish(started, result)

    def _matches_frozen(self, protocol: ResearchProtocol, content: bytes) -> None:
        # Hash and execute the same bytes: the copy written by ``_begin`` is what the sandbox runs.
        if self._frozen(protocol) != hashlib.sha256(content).hexdigest():
            raise Denied("script_hash", "script does not match the frozen analysis")

    def _begin(
        self, protocol: ResearchProtocol, snapshot: Snapshot, content: bytes, actor_id: str
    ) -> _Started:
        """Prepare the run folder, then claim. Nothing that can fail on disk comes after the
        claim, so a failure never leaves a row that is ``running`` with nothing behind it."""
        run_id = new_id("run")
        folder = self.work_root / run_id
        script = folder / "analysis.py"
        try:
            (folder / "out").mkdir(parents=True)
            script.write_bytes(content)
        except OSError as error:
            LOG.error("cannot prepare the run folder %s", folder, exc_info=error)
            shutil.rmtree(folder, ignore_errors=True)
            raise Denied("state", "the analysis work folder cannot be written") from None
        started = self.clock.now()
        sha = hashlib.sha256(content).hexdigest()
        try:
            self._claim(run_id, protocol, snapshot, sha, started, actor_id)
        except Denied:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        return _Started(run_id, protocol, snapshot, sha, started, script, folder / "out")

    def _failed(self, started: _Started, error: Exception) -> SandboxResult:
        """A sandbox that refuses to run releases the attempt; any other failure is recorded
        as a failed run (the detail goes to the log, not to the record)."""
        if isinstance(error, Denied):
            LOG.warning(
                "the sandbox refused run %s (%s): the attempt is released, nothing ran",
                started.run_id,
                error.code,
            )
            self.db.execute("DELETE FROM research_runs WHERE id = ?", (started.run_id,))
            raise error
        LOG.error("sandbox failed for run %s", started.run_id, exc_info=error)
        return SandboxResult(-1, "", f"sandbox failed: {type(error).__name__}", False)

    def _finish(self, started: _Started, result: SandboxResult) -> AnalysisRun:
        finished = self.clock.now()
        succeeded = result.exit_code == 0 and not result.timed_out
        self.db.execute(
            "UPDATE research_runs SET finished_at = ?, exit_code = ?, timed_out = ? WHERE id = ?",
            (finished, result.exit_code, int(result.timed_out), started.run_id),
        )
        return AnalysisRun(
            id=started.run_id,
            protocol_id=started.protocol.id,
            protocol_version=started.protocol.version,
            snapshot_id=started.snapshot.id,
            script_sha256=started.sha,
            label="confirmatory" if succeeded else "exploratory",
            status="succeeded" if succeeded else "failed",
            started_at=started.started,
            finished_at=finished,
            exit_code=result.exit_code,
            timed_out=result.timed_out,
            out_dir=str(started.out_dir),
            stdout=result.stdout,
            stderr=result.stderr,
        )

    def _claim(
        self,
        run_id: str,
        protocol: ResearchProtocol,
        snapshot: Snapshot,
        sha: str,
        at: float,
        actor_id: str,
    ) -> None:
        try:
            self.db.execute(
                "INSERT INTO research_runs(id, protocol_id, protocol_version, snapshot_id, "
                "script_sha256, started_at, started_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, protocol.id, protocol.version, snapshot.id, sha, at, actor_id or None),
            )
        except sqlite3.IntegrityError:
            raise Denied("already_run", "this snapshot was already analysed") from None


def _verify(snapshot: Snapshot, snapshot_dir: Path, admit: Callable[[], None] | None) -> None:
    """Everything that is slow and refuses before a claim: the files, then ``admit``."""
    _check_snapshot(snapshot, snapshot_dir)
    if admit is not None:
        admit()


def _check_snapshot(snapshot: Snapshot, snapshot_dir: Path) -> None:
    """Trust the directory, not the object: manifest and every file are re-hashed."""
    if not snapshot.complete:
        raise Denied("snapshot_incomplete", "snapshot is marked incomplete")
    root = snapshot_dir.resolve()
    manifest = root / MANIFEST
    if not manifest.is_file() or file_digest(manifest) != snapshot.manifest_sha256:
        raise Denied("snapshot_incomplete", "snapshot manifest differs from its recorded digest")
    present = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path != manifest
    }
    if present != set(snapshot.files):
        raise Denied("snapshot_incomplete", "snapshot directory and manifest list different files")
    for relative, expected in snapshot.files.items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or file_digest(path) != expected:
            raise Denied("snapshot_incomplete", f"snapshot file differs from manifest: {relative}")
