import hashlib
import json
import sqlite3
import sys

import pytest
from dataset_support import (
    CURRENT_CATALOG,
    EXPERIMENT,
    HELD_RECORD_IDS,
    OPERATOR_NAMES,
    OUTCOME,
    PROTOCOL,
    STAGE,
    WINDOW,
    build_fixture,
    read_rows,
)

from growbridge.archive import snapshot as snap
from growbridge.archive.db import Database
from growbridge.archive.store import Archive
from growbridge.cli import main
from growbridge.dataset import command
from growbridge.dataset.build import COUNT_NAMES
from growbridge.dataset.command import export_dataset
from growbridge.dataset.pseudonym import Pseudonymizer
from growbridge.dataset.schema import TABLES
from growbridge.dataset.source import ExportRefused
from growbridge.ports import Actor
from growbridge.research.holdout import HoldoutRegistry
from growbridge.sim.clock import START, FakeClock
from growbridge.sim.control import FakeControl
from growbridge.sim.fixtures import make_run_sheet
from growbridge.workflow.service import WorkflowService

WAL_FILES = {".sqlite3-wal", ".sqlite3-shm"}
ARGS = ("CC-BY-4.0", "Lab", None, "0.0.0-test")


class World:
    def __init__(self, data_dir, snapshot_id, service, operator):
        self.data_dir = data_dir
        self.snapshot_id = snapshot_id
        self.service = service
        self.operator = operator
        self.project_id = service.store.projects_of_experiment(EXPERIMENT)[0]


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A daemon-shaped data directory: archive, workflow and agents databases, one frozen round."""
    monkeypatch.setattr(command, "packaged_catalog", lambda: CURRENT_CATALOG)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    clock = FakeClock()
    archive_db = Database(data_dir / "archive.sqlite3")
    workflow_db = Database(data_dir / "workflow.sqlite3")
    agents_db = Database(data_dir / "agents.sqlite3")
    archive = Archive(archive_db, data_dir / "archive", clock)
    inputs = build_fixture(archive, clock, monkeypatch)
    service = WorkflowService(
        workflow_db, clock, FakeControl(clock), check_treatments=False, catalog=CURRENT_CATALOG
    )
    operator = Actor(kind="operator", id="op-1", reauth_at=clock.now())
    project_id = service.create_project("lettuce light series", operator)
    protocol = PROTOCOL.model_copy(update={"project_id": project_id})
    service.save_protocol(protocol, operator)
    round_id = service.create_round(project_id, protocol.id, operator)
    sheet = make_run_sheet(
        id="sheet-1", project_id=project_id, experiment_id=EXPERIMENT, stage_id=STAGE
    )
    service.submit_run_sheet(round_id, sheet, operator)
    registry = HoldoutRegistry(agents_db, clock, None, CURRENT_CATALOG)
    development = ["batch-1", "batch-2"]
    registry.register(project_id, "holdout-before", ["batch-h1"], [OUTCOME], development)
    registry.register(project_id, "holdout-after", ["batch-h2"], [OUTCOME], development)
    found = World(data_dir, inputs.data.snapshot.id, service, operator)
    found.archive, found.clock = archive, clock
    yield found
    for db in (archive_db, workflow_db, agents_db):
        db.close()


def dumps(data_dir):
    """Logical content of the databases and the hash of every other file (not -wal/-shm)."""
    state = {}
    for path in sorted(data_dir.rglob("*")):
        if path.suffix == ".sqlite3":
            connection = sqlite3.connect(path)
            try:
                state[path.name] = list(connection.iterdump())
            finally:
                connection.close()
        elif path.is_file() and path.name != "pseudonym.key" and path.suffix not in WAL_FILES:
            state[str(path.relative_to(data_dir))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return state


def run(world, out, *args):
    return export_dataset(world.data_dir, world.snapshot_id, out, *(args or ARGS))


def test_export_writes_the_dataset(world, tmp_path):
    summary = run(world, tmp_path / "out")
    names = sorted(p.name for p in (tmp_path / "out").iterdir())
    assert names == sorted([t.file for t in TABLES] + ["croissant.json"])
    assert summary.rows["measurements.csv"] >= 1
    assert set(summary.counts) == set(COUNT_NAMES)
    assert summary.out == tmp_path / "out"


def test_export_applies_the_registered_holdouts(world, tmp_path):
    summary = run(world, tmp_path / "out")
    assert summary.rows["withheld.csv"] >= 1


def rows_of(out, name):
    return read_rows((out / name).read_bytes())


def test_export_withholds_outcomes_held_out_after_the_freeze(world, tmp_path):
    """``m-held-after`` is in the snapshot: its holdout was registered in agents.sqlite3 after
    the freeze, and only the export-time filter keeps it out (spec §9)."""
    summary = run(world, tmp_path / "out")
    ids = {row["record_id"] for row in rows_of(tmp_path / "out", "measurements.csv")}
    assert ids and not ids & set(HELD_RECORD_IDS)
    assert summary.counts["withheld_at_export"] == 1


def test_export_reports_records_corrected_after_the_freeze(world, tmp_path):
    summary = run(world, tmp_path / "out")
    assert summary.counts["corrected_after_freeze"] == 1
    metadata = json.loads((tmp_path / "out" / "croissant.json").read_text(encoding="utf-8"))
    values = {p["name"]: p["value"] for p in metadata["additionalProperty"]}
    assert values["corrected_after_freeze_ids"] == "m-tent-2"


ROW_IDS = {"measurements.csv": "record_id", "actions.csv": "request_id", "interventions.csv": "id"}


def operators(out):
    """(file, row id) to the exported operator pseudonym, for every row that names one."""
    return {
        (name, row[id_column]): row["operator"]
        for name, id_column in ROW_IDS.items()
        for row in rows_of(out, name)
        if row["operator"]
    }


def test_one_person_keeps_one_pseudonym_across_snapshots(world, tmp_path):
    second = snap.freeze(
        world.archive,
        EXPERIMENT,
        world.clock,
        START,
        START + WINDOW,
        60,
        90,
        declared=PROTOCOL.variables,
        catalog=CURRENT_CATALOG,
    )
    assert second.id != world.snapshot_id
    run(world, tmp_path / "first")
    export_dataset(world.data_dir, second.id, tmp_path / "second", *ARGS)
    first, later = operators(tmp_path / "first"), operators(tmp_path / "second")
    key = (world.data_dir / "export" / "pseudonym.key").read_bytes()
    named = {Pseudonymizer(key)(name) for name in OPERATOR_NAMES}
    assert set(first.values()) == set(later.values()) == named and len(named) == 3
    shared = first.keys() & later.keys()
    assert ("measurements.csv", "m-bench") in shared
    assert all(first[row] == later[row] for row in shared)
    # Bo Chen recorded m-tent-2 and, after the first freeze, its correction
    tent = first[("measurements.csv", "m-tent-2")]
    assert later[("measurements.csv", "m-tent-2-late-fix")] == tent


def test_export_writes_nothing_but_the_key(world, tmp_path):
    before = dumps(world.data_dir)
    run(world, tmp_path / "out")
    assert dumps(world.data_dir) == before
    assert (world.data_dir / "export" / "pseudonym.key").exists()


@pytest.mark.parametrize("where", ["exists", "inside_data_dir", "missing_parent"])
def test_bad_out_is_refused(world, tmp_path, where):
    inside = world.data_dir / "out"
    out = {"exists": tmp_path, "inside_data_dir": inside, "missing_parent": tmp_path / "no" / "out"}
    with pytest.raises(ExportRefused):
        run(world, out[where])
    assert not inside.exists() and not (tmp_path / "no").exists()


def test_experiment_in_two_rounds_is_refused(world, tmp_path):
    service, operator = world.service, world.operator
    second = service.create_round(world.project_id, PROTOCOL.id, operator)
    sheet = make_run_sheet(
        id="sheet-2",
        project_id=world.project_id,
        experiment_id=EXPERIMENT,
        stage_id="stage-2",
    )
    service.submit_run_sheet(second, sheet, operator)
    with pytest.raises(ExportRefused, match="round"):
        run(world, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_failed_write_leaves_nothing_behind(world, tmp_path, monkeypatch):
    calls = []
    original = command.Path.write_bytes

    def failing(self, content):
        calls.append(self.name)
        if len(calls) == 2:
            raise OSError("disk full")
        return original(self, content)

    monkeypatch.setattr(command.Path, "write_bytes", failing)
    with pytest.raises(OSError, match="disk full"):
        run(world, tmp_path / "out")
    assert len(calls) == 2
    assert not (tmp_path / "out").exists()
    assert not any(p.name.startswith(".out.partial") for p in tmp_path.iterdir())


@pytest.mark.parametrize("name", ["archive", "workflow", "agents"])
def test_missing_database_is_refused_and_not_created(world, tmp_path, name):
    (world.data_dir / f"{name}.sqlite3").unlink()
    with pytest.raises(ExportRefused, match=f"{name}.sqlite3"):
        run(world, tmp_path / "out")
    assert not (world.data_dir / f"{name}.sqlite3").exists()


NAMESPACE_OF = {"archive": "archive", "workflow": "workflow", "agents": "research_holdout"}


def lag(data_dir, name):
    """Make one database one schema step older than the code, in the namespace the export reads."""
    connection = sqlite3.connect(data_dir / f"{name}.sqlite3")
    try:
        connection.execute(
            "DELETE FROM schema_steps WHERE namespace = ? AND step = "
            "(SELECT MAX(step) FROM schema_steps WHERE namespace = ?)",
            (NAMESPACE_OF[name], NAMESPACE_OF[name]),
        )
        connection.commit()
    finally:
        connection.close()


@pytest.mark.parametrize("name", ["archive", "workflow", "agents"])
def test_database_older_than_the_code_is_refused_unchanged(world, tmp_path, name):
    lag(world.data_dir, name)
    before = dumps(world.data_dir)
    with pytest.raises(ExportRefused, match=f"{name}.sqlite3 is older"):
        run(world, tmp_path / "out")
    assert dumps(world.data_dir) == before
    assert not (world.data_dir / "export").exists()
    assert not (tmp_path / "out").exists()


def test_unmigrated_database_is_refused_unchanged(world, tmp_path):
    path = world.data_dir / "agents.sqlite3"
    path.rename(tmp_path / "moved.sqlite3")
    sqlite3.connect(path).close()
    before = dumps(world.data_dir)
    with pytest.raises(ExportRefused, match="older"):
        run(world, tmp_path / "out")
    assert dumps(world.data_dir) == before


def test_busy_database_is_refused(world, tmp_path, monkeypatch):
    def busy(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(command, "_lag", busy)
    with pytest.raises(ExportRefused, match="busy"):
        run(world, tmp_path / "out")


def test_unknown_snapshot_is_refused(world, tmp_path):
    with pytest.raises(ExportRefused, match="does not exist"):
        export_dataset(world.data_dir, "snap-missing", tmp_path / "out", *ARGS)


def test_measurement_unit_mismatch_is_refused(world, tmp_path):
    from dataset_support import _measurement

    world.archive.add_measurement(_measurement("m-bad-unit", batch="batch-1", unit="mm"))
    frozen = snap.freeze(
        world.archive,
        EXPERIMENT,
        world.clock,
        START,
        START + WINDOW,
        60,
        90,
        declared=PROTOCOL.variables,
        catalog=CURRENT_CATALOG,
    )
    with pytest.raises(ExportRefused, match="m-bad-unit"):
        export_dataset(world.data_dir, frozen.id, tmp_path / "out", *ARGS)
    assert not (tmp_path / "out").exists()


@pytest.fixture
def main_with(world, tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    config.write_text(
        f'device = "SIMULATED"\ntoken = "{"t" * 32}"\ndata_dir = "{world.data_dir}"\n'
    )

    def invoke(*args):
        monkeypatch.setattr(sys, "argv", ["growbridge", "--config", str(config), *args])
        main()

    return invoke


def test_cli_reports_a_refusal(main_with, tmp_path, capsys):
    argv = ["--out", str(tmp_path / "out"), "--licence", "CC-BY-4.0", "--creator", "Lab"]
    with pytest.raises(SystemExit) as exit_info:
        main_with("export-dataset", "--snapshot", "snap-missing", *argv)
    assert exit_info.value.code == 1
    assert "export refused" in capsys.readouterr().err


def test_cli_prints_the_summary(main_with, world, tmp_path, capsys):
    main_with(
        "export-dataset",
        "--snapshot",
        world.snapshot_id,
        "--out",
        str(tmp_path / "out"),
        "--licence",
        " CC-BY-4.0 ",
        "--creator",
        "Lab",
        "--url",
        "  ",
    )
    report = json.loads(capsys.readouterr().out)
    assert report["out"] == str(tmp_path / "out")
    assert report["rows"]["measurements.csv"] >= 1
    assert set(report["counts"]) == set(COUNT_NAMES)
    metadata = json.loads((tmp_path / "out" / "croissant.json").read_text(encoding="utf-8"))
    assert metadata["license"] == "CC-BY-4.0"


def test_blank_licence_is_refused(world, tmp_path):
    with pytest.raises(ExportRefused, match="licence"):
        run(world, tmp_path / "out", "  ", "Lab", None, "0.0.0-test")
    assert not (tmp_path / "out").exists()
