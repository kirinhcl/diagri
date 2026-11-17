"""The refusals of the analysis runner, the holdout registry, the pre-registration rule and the
sandbox carry a registered reason and the params the console builds its text from; the coarse
code and the English message stay as they were."""

import asyncio

import pytest
from test_research_analysis import RecordingSandbox, make_snapshot
from test_research_holdout import DEV, DEV3, OUTCOMES, measurement, write_rows
from test_research_preregistration import FROZEN_AT, recorded, row, write
from vocab_support import TEST_CATALOG

from growbridge.archive.db import Database
from growbridge.ports import Denied
from growbridge.research.analysis import MAX_SCRIPT_CHARS, ConfirmatoryRunner
from growbridge.research.holdout import HoldoutRegistry, project_outcomes, refuse_holdout_rows
from growbridge.research.preregistration import require_measurements_after, require_stages_after
from growbridge.research.sandbox import RefusingSandbox
from growbridge.sim.clock import FakeClock
from growbridge.sim.fixtures import make_protocol


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "research.db")
    yield database
    database.close()


@pytest.fixture
def runner(db, tmp_path):
    return ConfirmatoryRunner(db, FakeClock(), RecordingSandbox(), tmp_path / "work")


@pytest.fixture
def snapshot_dir(tmp_path):
    directory = tmp_path / "snapshot"
    directory.mkdir()
    (directory / "samples.jsonl").write_text('{"v": 1}\n')
    return directory


@pytest.fixture
def script(tmp_path):
    path = tmp_path / "analysis.py"
    path.write_text("print('analysis v1')\n")
    return path


def refused(call, code: str, reason: str, params: dict | None) -> Denied:
    with pytest.raises(Denied) as caught:
        call()
    exc = caught.value
    assert (exc.code, exc.reason) == (code, reason)
    if params is not None:
        assert exc.params == params
    return exc


# --- the analysis script -----------------------------------------------------------------------


def freeze_text(runner, content: bytes):
    return lambda: runner.freeze_analysis(make_protocol(), content)


def test_script_not_text_carries_no_params(runner):
    refused(freeze_text(runner, b"\xff\xfe"), "param", "script_not_text", {})


def test_script_empty_carries_no_params(runner):
    refused(freeze_text(runner, b"  \n"), "param", "script_empty", {})


def test_script_too_long_carries_the_character_limit(runner):
    long = b"x" * (MAX_SCRIPT_CHARS + 1)
    refused(freeze_text(runner, long), "param", "script_too_long", {"max_length": MAX_SCRIPT_CHARS})


def test_script_syntax_carries_the_compiler_text_as_detail(runner):
    exc = refused(freeze_text(runner, b"def broken(:\n"), "param", "script_syntax", None)
    assert set(exc.params) == {"detail"} and "invalid syntax" in exc.params["detail"]


def test_script_syntax_also_covers_a_script_that_cannot_be_compiled(runner):
    exc = refused(freeze_text(runner, b"x = 1\x00\n"), "param", "script_syntax", None)
    assert set(exc.params) == {"detail"}


# --- freezing and running ----------------------------------------------------------------------


def test_script_not_protocol_script_carries_the_protocol(runner):
    declared = make_protocol().model_copy(
        update={"analysis": make_protocol().analysis.model_copy(update={"script_sha256": "0" * 64})}
    )
    refused(
        lambda: runner.freeze_analysis(declared, b"print(1)\n"),
        "script_hash",
        "script_not_protocol_script",
        {"protocol_id": declared.id},
    )


def test_script_other_frozen_carries_the_protocol(runner):
    protocol = make_protocol()
    runner.freeze_analysis(protocol, b"print(1)\n")
    refused(
        lambda: runner.freeze_analysis(protocol, b"print(2)\n"),
        "script_hash",
        "script_other_frozen",
        {"protocol_id": protocol.id},
    )


def test_script_not_frozen_script_carries_the_protocol(runner, script, snapshot_dir):
    protocol = make_protocol()
    runner.freeze_analysis(protocol, script)
    script.write_text("print('p-hacked')\n")
    refused(
        lambda: runner.run(protocol, make_snapshot(snapshot_dir), snapshot_dir, script),
        "script_hash",
        "script_not_frozen_script",
        {"protocol_id": protocol.id},
    )


def test_analysis_script_not_frozen_carries_the_protocol_and_its_version(
    runner, script, snapshot_dir
):
    protocol = make_protocol()
    snapshot = make_snapshot(snapshot_dir)
    refused(
        lambda: asyncio.run(runner.run_frozen(protocol, snapshot, snapshot_dir, "operator")),
        "state",
        "analysis_script_not_frozen",
        {"protocol_id": protocol.id, "version": protocol.version},
    )


def test_already_run_carries_no_params(runner, script, snapshot_dir):
    protocol = make_protocol()
    runner.freeze_analysis(protocol, script)
    snapshot = make_snapshot(snapshot_dir)
    runner.run(protocol, snapshot, snapshot_dir, script)
    refused(
        lambda: runner.run(protocol, snapshot, snapshot_dir, script),
        "already_run",
        "already_run",
        {},
    )


def test_analysis_workdir_unwritable_carries_no_params(db, tmp_path, script, snapshot_dir):
    blocked = tmp_path / "work"
    blocked.write_text("a file where the work folder should be")
    runner = ConfirmatoryRunner(db, FakeClock(), RecordingSandbox(), blocked)
    protocol = make_protocol()
    runner.freeze_analysis(protocol, script)
    refused(
        lambda: runner.run(protocol, make_snapshot(snapshot_dir), snapshot_dir, script),
        "state",
        "analysis_workdir_unwritable",
        {},
    )


# --- the snapshot on disk ----------------------------------------------------------------------


def run_snapshot(runner, script, snapshot_dir, **overrides):
    protocol = make_protocol()
    runner.freeze_analysis(protocol, script)
    snapshot = make_snapshot(snapshot_dir, **overrides)
    return protocol, snapshot, lambda: runner.run(protocol, snapshot, snapshot_dir, script)


def test_snapshot_not_complete_carries_the_snapshot(runner, script, snapshot_dir):
    _, _, call = run_snapshot(runner, script, snapshot_dir, complete=False)
    refused(call, "snapshot_incomplete", "snapshot_not_complete", {"snapshot_id": "snap-1"})


def test_snapshot_manifest_changed_carries_the_snapshot(runner, script, snapshot_dir):
    _, _, call = run_snapshot(runner, script, snapshot_dir)
    (snapshot_dir / "manifest.json").write_text("rewritten")
    refused(call, "snapshot_incomplete", "snapshot_manifest_changed", {"snapshot_id": "snap-1"})


def test_snapshot_files_mismatch_carries_the_snapshot(runner, script, snapshot_dir):
    _, _, call = run_snapshot(runner, script, snapshot_dir)
    (snapshot_dir / "extra.jsonl").write_text("smuggled")
    refused(call, "snapshot_incomplete", "snapshot_files_mismatch", {"snapshot_id": "snap-1"})


def test_snapshot_file_changed_carries_the_snapshot_and_the_file_name(runner, script, snapshot_dir):
    _, _, call = run_snapshot(runner, script, snapshot_dir)
    (snapshot_dir / "samples.jsonl").write_text("tampered\n")
    refused(
        call,
        "snapshot_incomplete",
        "snapshot_file_changed",
        {"snapshot_id": "snap-1", "file": "samples.jsonl"},
    )


# --- the pre-registration rule -----------------------------------------------------------------


def test_snapshot_predates_freeze_carries_the_snapshot_for_a_stage(tmp_path):
    refused(
        lambda: require_stages_after(FROZEN_AT, "snap-1", [99.0]),
        "state",
        "snapshot_predates_freeze",
        {"snapshot_id": "snap-1"},
    )


def test_snapshot_predates_freeze_carries_the_snapshot_for_a_measurement(tmp_path):
    path = tmp_path / "measurements.jsonl"
    write(path, row("m1"))
    refused(
        lambda: require_measurements_after(FROZEN_AT, "snap-1", path, recorded({"m1": 50.0})),
        "state",
        "snapshot_predates_freeze",
        {"snapshot_id": "snap-1"},
    )


# --- the holdout registry ----------------------------------------------------------------------


@pytest.fixture
def holdouts(tmp_path):
    database = Database(tmp_path / "holdout.db")
    yield HoldoutRegistry(database, FakeClock(), catalog=TEST_CATALOG)
    database.close()


def register(registry, **changes):
    fields = {
        "batch_ids": ("b3",),
        "outcome_fields": OUTCOMES,
        "development_batch_ids": DEV,
        **changes,
    }
    return lambda: registry.register("project-1", "hold-1", **fields)


def test_batches_no_holdout_carries_no_params(holdouts):
    refused(register(holdouts, batch_ids=()), "batches", "batches_no_holdout", {})


def test_batches_too_few_development_carries_the_minimum(holdouts):
    refused(
        register(holdouts, development_batch_ids=("dev-1",)),
        "batches",
        "batches_too_few_development",
        {"min_batches": 2},
    )


def test_batches_overlap_carries_no_params(holdouts):
    refused(register(holdouts, batch_ids=("dev-1",)), "batches", "batches_overlap", {})


def test_outcome_fields_invalid_carries_no_params(holdouts):
    refused(
        register(holdouts, outcome_fields=("yield_g", "yield_g"), development_batch_ids=DEV3),
        "param",
        "outcome_fields_invalid",
        {},
    )


def test_holdout_outcomes_exist_carries_the_project(db):
    source = project_outcomes(lambda b: [("m1", "yield_g")], lambda e: ("project-1",), TEST_CATALOG)
    registry = HoldoutRegistry(db, FakeClock(), source, TEST_CATALOG)
    refused(register(registry), "state", "holdout_outcomes_exist", {"project_id": "project-1"})


def test_holdout_outcome_fields_unknown_carries_the_fields(holdouts):
    refused(
        register(holdouts, outcome_fields=("yeild_g",)),
        "param",
        "holdout_outcome_fields_unknown",
        {"fields": ["yeild_g"]},
    )


def test_holdout_already_registered_carries_the_holdout(holdouts):
    register(holdouts)()
    refused(
        register(holdouts, batch_ids=("b4",)),
        "state",
        "holdout_already_registered",
        {"holdout_id": "hold-1"},
    )


def test_an_unregistered_holdout_is_a_record_not_found_of_kind_holdout(holdouts):
    refused(
        lambda: holdouts.evaluate("nope", "reader", "m" * 64),
        "state",
        "record_not_found",
        {"record_kind": "holdout", "record_id": "nope"},
    )


def test_model_unregistered_carries_no_params(holdouts):
    register(holdouts)()
    refused(
        lambda: holdouts.evaluate("hold-1", "reader", "m" * 64),
        "model_unregistered",
        "model_unregistered",
        {},
    )


def test_holdout_rows_carries_the_project(holdouts, tmp_path):
    register(holdouts)()
    path = write_rows(tmp_path / "measurements.jsonl", [measurement("yield_g", "b3")])
    refused(
        lambda: refuse_holdout_rows(holdouts, "project-1", "snap-1", path),
        "scope",
        "holdout_rows",
        {"project_id": "project-1"},
    )


# --- the sandbox -------------------------------------------------------------------------------


def test_sandbox_unavailable_carries_no_params(tmp_path):
    refused(
        lambda: RefusingSandbox().run(tmp_path, tmp_path, tmp_path, 1.0),
        "sandbox_unavailable",
        "sandbox_unavailable",
        {},
    )
