import subprocess
import sys
import textwrap

import pytest

from growbridge.archive.db import Database
from growbridge.archive.ids import file_digest
from growbridge.archive.models import Snapshot
from growbridge.ports import Denied
from growbridge.research.analysis import (
    AnalysisFacts,
    ConfirmatoryRunner,
    classify,
    conclusion,
)
from growbridge.research.sandbox import SandboxResult
from growbridge.research.stats import BlockEstimate
from growbridge.sim.clock import FakeClock
from growbridge.sim.fixtures import make_protocol


def facts(**overrides) -> AnalysisFacts:
    fields = {
        "independent_replicates": 4,
        "confounded_with_time": False,
        "missing_fraction": 0.0,
        "changed_after_outcomes": False,
        "deviation_fraction": 0.0,
        "planned_sample_size": 4,
        "achieved_sample_size": 4,
        "early_terminated": False,
    }
    return AnalysisFacts(**{**fields, **overrides})


def estimate(p_value: float | None = 0.01, blocks: int = 8, estimable: bool = True):
    return BlockEstimate(effect=1.0, blocks=blocks, p_value=p_value, estimable=estimable, note="")


# --- §9.3 downgrade rules ---------------------------------------------------------------------


def test_clean_facts_stay_confirmatory():
    decision = classify(make_protocol(), facts())

    assert decision.label == "confirmatory"
    assert decision.reasons == ()


def test_no_independent_replicates_is_descriptive():
    decision = classify(make_protocol(), facts(independent_replicates=1))

    assert decision.label == "descriptive"
    assert any("重复" in reason for reason in decision.reasons)


def test_treatment_confounded_with_time_is_descriptive():
    decision = classify(make_protocol(), facts(confounded_with_time=True))

    assert decision.label == "descriptive"
    assert any("时间" in reason for reason in decision.reasons)


def test_missing_above_protocol_limit_is_exploratory():
    limit = make_protocol().analysis.max_missing_fraction

    at_limit = classify(make_protocol(), facts(missing_fraction=limit))
    over = classify(make_protocol(), facts(missing_fraction=limit + 0.01))

    assert at_limit.label == "confirmatory"
    assert over.label == "exploratory"
    assert any("缺失" in reason for reason in over.reasons)


def test_plan_changed_after_seeing_outcomes_is_exploratory():
    decision = classify(make_protocol(), facts(changed_after_outcomes=True))

    assert decision.label == "exploratory"
    assert any("变更" in reason for reason in decision.reasons)


def test_deviation_above_protocol_limit_is_exploratory():
    limit = make_protocol().analysis.max_deviation_fraction

    decision = classify(make_protocol(), facts(deviation_fraction=limit + 0.01))

    assert decision.label == "exploratory"
    assert any("偏离" in reason for reason in decision.reasons)


def test_descriptive_outranks_exploratory_and_all_reasons_are_listed():
    decision = classify(
        make_protocol(), facts(independent_replicates=1, changed_after_outcomes=True)
    )

    assert decision.label == "descriptive"
    assert len(decision.reasons) == 2


# --- conclusions ------------------------------------------------------------------------------


def test_significant_full_sample_is_supported():
    assert conclusion(estimate(0.01), facts()) == "supported"


def test_non_significant_full_sample_is_not_supported():
    assert conclusion(estimate(0.4), facts()) == "not_supported"


def test_short_sample_is_uncertain_never_no_effect():
    short = facts(achieved_sample_size=2)

    assert conclusion(estimate(0.9), short) == "uncertain"
    assert conclusion(estimate(0.001), short) == "uncertain"


def test_early_termination_is_uncertain():
    assert conclusion(estimate(0.001), facts(early_terminated=True)) == "uncertain"


def test_unestimable_or_unreachable_alpha_is_uncertain():
    assert conclusion(estimate(None, blocks=1, estimable=False), facts()) == "uncertain"
    # two blocks cannot reach p < 0.05, so a non-significant result says nothing
    assert conclusion(estimate(0.5, blocks=2), facts()) == "uncertain"


# --- confirmatory runner ----------------------------------------------------------------------


class RecordingSandbox:
    def __init__(self):
        self.calls = []

    def run(self, script, snapshot_dir, out_dir, timeout):
        self.calls.append((script, snapshot_dir, out_dir, timeout))
        return SandboxResult(exit_code=0, stdout="ok", stderr="", timed_out=False)


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
    return directory


def make_snapshot(snapshot_dir, **overrides) -> Snapshot:
    manifest = snapshot_dir / "manifest.json"
    if not manifest.exists():
        manifest.write_text('{"files": "samples.jsonl"}')
    fields = {
        "id": "snap-1",
        "experiment_id": "experiment-1",
        "version": 1,
        "created_at": 1_800_000_000.0,
        "manifest_sha256": file_digest(manifest),
        "complete": True,
        "coverage": 0.99,
        "files": {"samples.jsonl": file_digest(snapshot_dir / "samples.jsonl")},
    }
    return Snapshot(**{**fields, **overrides})


@pytest.fixture
def script(tmp_path):
    path = tmp_path / "analysis.py"
    path.write_text("print('analysis v1')\n")
    return path


@pytest.fixture
def runner(db, tmp_path):
    return ConfirmatoryRunner(db, FakeClock(), RecordingSandbox(), tmp_path / "work")


def test_freeze_returns_the_script_hash(runner, script):
    assert runner.freeze_analysis(make_protocol(), script) == file_digest(script)


def test_run_executes_the_frozen_script_and_labels_it_confirmatory(runner, script, snapshot_dir):
    protocol = make_protocol()
    runner.freeze_analysis(protocol, script)

    run = runner.run(protocol, make_snapshot(snapshot_dir), snapshot_dir, script)

    assert run.label == "confirmatory"
    assert run.script_sha256 == file_digest(script)
    assert run.exit_code == 0
    assert len(runner.sandbox.calls) == 1


def test_run_refuses_a_script_that_changed_after_freezing(runner, script, snapshot_dir):
    protocol = make_protocol()
    runner.freeze_analysis(protocol, script)
    script.write_text("print('p-hacked')\n")

    with pytest.raises(Denied) as caught:
        runner.run(protocol, make_snapshot(snapshot_dir), snapshot_dir, script)

    assert caught.value.code == "script_hash"
    assert runner.sandbox.calls == []


def test_run_refuses_a_script_that_was_never_frozen(runner, script, snapshot_dir):
    with pytest.raises(Denied) as caught:
        runner.run(make_protocol(), make_snapshot(snapshot_dir), snapshot_dir, script)

    assert caught.value.code == "script_hash"


def test_run_refuses_an_incomplete_snapshot(runner, script, snapshot_dir):
    protocol = make_protocol()
    runner.freeze_analysis(protocol, script)

    with pytest.raises(Denied) as caught:
        runner.run(protocol, make_snapshot(snapshot_dir, complete=False), snapshot_dir, script)

    assert caught.value.code == "snapshot_incomplete"


def test_run_refuses_a_snapshot_directory_that_no_longer_matches(runner, script, snapshot_dir):
    protocol = make_protocol()
    runner.freeze_analysis(protocol, script)
    snapshot = make_snapshot(snapshot_dir)
    (snapshot_dir / "samples.jsonl").write_text("tampered\n")

    with pytest.raises(Denied) as caught:
        runner.run(protocol, snapshot, snapshot_dir, script)

    assert caught.value.code == "snapshot_incomplete"


def test_second_confirmatory_run_on_the_same_snapshot_is_denied(runner, script, snapshot_dir):
    protocol = make_protocol()
    runner.freeze_analysis(protocol, script)
    snapshot = make_snapshot(snapshot_dir)
    runner.run(protocol, snapshot, snapshot_dir, script)

    with pytest.raises(Denied) as caught:
        runner.run(protocol, snapshot, snapshot_dir, script)

    assert caught.value.code == "already_run"
    assert len(runner.sandbox.calls) == 1


def test_a_new_snapshot_version_can_be_analysed_once_more(runner, script, snapshot_dir):
    protocol = make_protocol()
    runner.freeze_analysis(protocol, script)
    runner.run(protocol, make_snapshot(snapshot_dir), snapshot_dir, script)

    second = make_snapshot(snapshot_dir, id="snap-2", version=2)
    run = runner.run(protocol, second, snapshot_dir, script)

    assert run.snapshot_id == "snap-2"


def test_a_new_protocol_version_may_freeze_a_new_script(runner, script, tmp_path):
    runner.freeze_analysis(make_protocol(), script)
    other = tmp_path / "analysis2.py"
    other.write_text("print('v2')\n")

    sha = runner.freeze_analysis(make_protocol(version=2), other)

    assert sha == file_digest(other)


def test_refreezing_a_different_script_for_the_same_version_is_denied(runner, script, tmp_path):
    runner.freeze_analysis(make_protocol(), script)
    other = tmp_path / "analysis2.py"
    other.write_text("print('v2')\n")

    with pytest.raises(Denied) as caught:
        runner.freeze_analysis(make_protocol(), other)

    assert caught.value.code == "script_hash"


def test_runner_hands_the_script_snapshot_and_output_dir_to_the_sandbox(db, tmp_path, snapshot_dir):
    """Wiring check with a stand-in sandbox that just runs the interpreter."""

    class PlainSandbox:
        def run(self, script, snapshot_dir, out_dir, timeout):
            done = subprocess.run(
                [sys.executable, "-I", str(script), str(snapshot_dir), str(out_dir)],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            return SandboxResult(done.returncode, done.stdout, done.stderr, False)

    script = tmp_path / "s.py"
    script.write_text(
        textwrap.dedent(
            """
            import sys, pathlib
            pathlib.Path(sys.argv[2], "result.txt").write_text("done")
            """
        )
    )
    runner = ConfirmatoryRunner(db, FakeClock(), PlainSandbox(), tmp_path / "work")
    protocol = make_protocol()
    runner.freeze_analysis(protocol, script)

    run = runner.run(protocol, make_snapshot(snapshot_dir), snapshot_dir, script)

    assert run.exit_code == 0
    assert (tmp_path / "work" / run.id / "out" / "result.txt").read_text() == "done"


def test_completed_is_true_only_after_a_successful_run_under_that_protocol(
    runner, script, snapshot_dir
):
    protocol = make_protocol()
    runner.freeze_analysis(protocol, script)
    assert runner.completed("snap-1", protocol) is False

    runner.run(protocol, make_snapshot(snapshot_dir), snapshot_dir, script)

    assert runner.completed("snap-1", protocol) is True
    assert runner.completed("snap-other", protocol) is False
    assert runner.completed("snap-1", make_protocol(version=2)) is False
    assert runner.completed("snap-1", make_protocol(id="protocol-2")) is False


def failing_runner(db, tmp_path, **result):
    fields = {"exit_code": 1, "stdout": "", "stderr": "boom", "timed_out": False}

    class FailingSandbox:
        def run(self, script, snapshot_dir, out_dir, timeout):
            return SandboxResult(**{**fields, **result})

    return ConfirmatoryRunner(db, FakeClock(), FailingSandbox(), tmp_path / "work")


def test_a_failed_run_is_not_confirmatory_not_completed_and_uses_up_the_attempt(
    db, tmp_path, snapshot_dir, script
):
    runner = failing_runner(db, tmp_path)
    protocol = make_protocol()
    runner.freeze_analysis(protocol, script)

    run = runner.run(protocol, make_snapshot(snapshot_dir), snapshot_dir, script)

    assert run.label != "confirmatory"
    assert run.status == "failed"
    assert runner.completed("snap-1", protocol) is False
    with pytest.raises(Denied) as caught:
        runner.run(protocol, make_snapshot(snapshot_dir), snapshot_dir, script)
    assert caught.value.code == "already_run"


def test_a_timed_out_run_is_not_confirmatory(db, tmp_path, snapshot_dir, script):
    runner = failing_runner(db, tmp_path, exit_code=0, timed_out=True)
    protocol = make_protocol()
    runner.freeze_analysis(protocol, script)

    run = runner.run(protocol, make_snapshot(snapshot_dir), snapshot_dir, script)

    assert run.label != "confirmatory"
    assert run.status == "failed"


def test_a_forged_snapshot_object_is_caught_by_the_manifest_digest(runner, script, snapshot_dir):
    protocol = make_protocol()
    runner.freeze_analysis(protocol, script)
    snapshot = make_snapshot(snapshot_dir)
    (snapshot_dir / "manifest.json").write_text("rewritten")

    with pytest.raises(Denied) as caught:
        runner.run(protocol, snapshot, snapshot_dir, script)

    assert caught.value.code == "snapshot_incomplete"


def test_a_missing_manifest_or_unlisted_extra_file_is_caught(runner, script, snapshot_dir):
    protocol = make_protocol()
    runner.freeze_analysis(protocol, script)
    snapshot = make_snapshot(snapshot_dir)
    (snapshot_dir / "extra.jsonl").write_text("smuggled")

    with pytest.raises(Denied) as extra:
        runner.run(protocol, snapshot, snapshot_dir, script)
    (snapshot_dir / "extra.jsonl").unlink()
    (snapshot_dir / "manifest.json").unlink()
    with pytest.raises(Denied) as missing:
        runner.run(protocol, snapshot, snapshot_dir, script)

    assert extra.value.code == missing.value.code == "snapshot_incomplete"
