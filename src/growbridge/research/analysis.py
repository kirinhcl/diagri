"""Confirmatory-analysis gate (architecture doc §9.1 and §9.3).

``classify`` applies the five downgrade rules, ``conclusion`` refuses to call an under-powered
result "no effect", and ``ConfirmatoryRunner`` lets exactly one frozen script run once per
protocol version and data snapshot.
"""

import hashlib
import sqlite3
from pathlib import Path
from typing import Literal

from growbridge.archive.clock import Clock
from growbridge.archive.db import Database
from growbridge.archive.ids import file_digest, new_id
from growbridge.archive.models import Label, Model, ResearchProtocol, Snapshot
from growbridge.ports import Denied
from growbridge.research.sandbox import Sandbox
from growbridge.research.stats import BlockEstimate

Conclusion = Literal["supported", "not_supported", "uncertain"]
MANIFEST = "manifest.json"
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
    label: Label
    reasons: tuple[str, ...] = ()


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
    descriptive: list[str] = []
    exploratory: list[str] = []
    if facts.independent_replicates < MIN_REPLICATES:
        descriptive.append("缺少独立的处理重复：只能描述已观察到的差异，不能推断处理效应")
    if facts.confounded_with_time:
        descriptive.append("处理与时间或生长期无法区分：只能描述随时间的变化")
    if facts.missing_fraction > plan.max_missing_fraction:
        exploratory.append("缺失超过预定标准：结果只能作为探索性线索")
    if facts.changed_after_outcomes:
        exploratory.append("看到结局数据后变更了终点、排除规则或分析方法：结果只能作为探索")
    if facts.deviation_fraction > plan.max_deviation_fraction:
        exploratory.append("实际处理偏离批准范围，超过协议预定的比例：结果只能作为探索")
    reasons = tuple(descriptive + exploratory)
    if descriptive:
        return AnalysisDecision(label="descriptive", reasons=reasons)
    if exploratory:
        return AnalysisDecision(label="exploratory", reasons=reasons)
    return AnalysisDecision(label="confirmatory", reasons=())


def conclusion(estimate: BlockEstimate, facts: AnalysisFacts, alpha: float = 0.05) -> Conclusion:
    """Never "no effect" from an incomplete, stopped or too small experiment."""
    if facts.early_terminated or facts.achieved_sample_size < facts.planned_sample_size:
        return "uncertain"
    if not estimate.estimable or estimate.p_value is None:
        return "uncertain"
    if 2.0 ** (1 - estimate.blocks) > alpha:
        return "uncertain"  # the test cannot reach alpha with so few blocks
    return "supported" if estimate.p_value < alpha else "not_supported"


class ConfirmatoryRunner:
    def __init__(self, db: Database, clock: Clock, sandbox: Sandbox, work_root: Path):
        self.db = db
        self.clock = clock
        self.sandbox = sandbox
        self.work_root = work_root
        self.timeout = DEFAULT_TIMEOUT_SECONDS
        db.migrate("research_analysis", STEPS)

    def freeze_analysis(self, protocol: ResearchProtocol, script: Path) -> str:
        """Register the script hash for this protocol version; a version has one script."""
        sha = file_digest(script)
        declared = protocol.analysis.script_sha256
        if declared is not None and declared != sha:
            raise Denied("script_hash", "script differs from the hash in the protocol")
        with self.db.transaction():
            frozen = self._frozen(protocol)
            if frozen is not None and frozen != sha:
                raise Denied("script_hash", "a different script is already frozen")
            if frozen is None:
                self.db.execute(
                    "INSERT INTO research_scripts VALUES (?, ?, ?, ?)",
                    (protocol.id, protocol.version, sha, self.clock.now()),
                )
        return sha

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

    def _frozen(self, protocol: ResearchProtocol) -> str | None:
        row = self.db.one(
            "SELECT script_sha256 FROM research_scripts "
            "WHERE protocol_id = ? AND protocol_version = ?",
            (protocol.id, protocol.version),
        )
        return None if row is None else row["script_sha256"]

    def run(
        self, protocol: ResearchProtocol, snapshot: Snapshot, snapshot_dir: Path, script: Path
    ) -> AnalysisRun:
        """Run the frozen script once. A failed or timed-out run is recorded as failed (never
        confirmatory) but still consumes the single confirmatory attempt for this snapshot."""
        # Hash and execute the same bytes: the copy below is what the sandbox runs.
        content = script.read_bytes()
        sha = hashlib.sha256(content).hexdigest()
        if self._frozen(protocol) != sha:
            raise Denied("script_hash", "script does not match the frozen analysis")
        _check_snapshot(snapshot, snapshot_dir)
        run_id = new_id("run")
        started = self.clock.now()
        self._claim(run_id, protocol, snapshot, sha, started)
        out_dir = self.work_root / run_id / "out"
        out_dir.mkdir(parents=True)
        frozen_copy = self.work_root / run_id / "analysis.py"
        frozen_copy.write_bytes(content)
        try:
            result = self.sandbox.run(frozen_copy, snapshot_dir, out_dir, self.timeout)
        except Denied:
            self.db.execute("DELETE FROM research_runs WHERE id = ?", (run_id,))  # never ran
            raise
        finished = self.clock.now()
        succeeded = result.exit_code == 0 and not result.timed_out
        self.db.execute(
            "UPDATE research_runs SET finished_at = ?, exit_code = ?, timed_out = ? WHERE id = ?",
            (finished, result.exit_code, int(result.timed_out), run_id),
        )
        return AnalysisRun(
            id=run_id,
            protocol_id=protocol.id,
            protocol_version=protocol.version,
            snapshot_id=snapshot.id,
            script_sha256=sha,
            label="confirmatory" if succeeded else "exploratory",
            status="succeeded" if succeeded else "failed",
            started_at=started,
            finished_at=finished,
            exit_code=result.exit_code,
            timed_out=result.timed_out,
            out_dir=str(out_dir),
            stdout=result.stdout,
            stderr=result.stderr,
        )

    def _claim(
        self, run_id: str, protocol: ResearchProtocol, snapshot: Snapshot, sha: str, at: float
    ) -> None:
        try:
            self.db.execute(
                "INSERT INTO research_runs(id, protocol_id, protocol_version, snapshot_id, "
                "script_sha256, started_at) VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, protocol.id, protocol.version, snapshot.id, sha, at),
            )
        except sqlite3.IntegrityError:
            raise Denied("already_run", "this snapshot was already analysed") from None


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
