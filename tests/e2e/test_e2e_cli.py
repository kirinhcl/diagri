"""CLI subcommands that belong to the Auto Research runtime (temp config, no radio, no network)."""

import fcntl
import json
import sqlite3
import stat
import sys

import pytest

from growbridge.archive.db import Database
from growbridge.cli import main, role_tokens_from_env
from growbridge.control.ledger import Ledger

SECRET = "correct horse battery"


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "config.toml"
    data = tmp_path / "data"
    path.write_text(
        f'device = "SIMULATED"\ntoken = "{"t" * 32}"\ndata_dir = "{data}"\nauto_research = true\n'
    )
    return path


@pytest.fixture
def run(monkeypatch, config):
    def invoke(*args):
        monkeypatch.setattr(sys, "argv", ["growbridge", "--config", str(config), *args])
        main()

    return invoke


def operators(tmp_path) -> list[str]:
    path = tmp_path / "data" / "workflow.sqlite3"
    if not path.exists():
        return []
    with sqlite3.connect(path) as connection:
        return [row[0] for row in connection.execute("SELECT name FROM operators")]


def test_operator_add_reads_the_secret_from_getpass_and_stores_only_a_hash(
    run, monkeypatch, tmp_path
):
    monkeypatch.setattr("getpass.getpass", lambda prompt="": SECRET)

    run("operator", "add", "alice")

    assert operators(tmp_path) == ["alice"]
    stored = (tmp_path / "data" / "workflow.sqlite3").read_bytes()
    assert SECRET.encode() not in stored


def test_operator_add_refuses_a_short_secret(run, monkeypatch, tmp_path):
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "short")

    with pytest.raises(SystemExit) as stopped:
        run("operator", "add", "alice")

    assert stopped.value.code not in (0, None)
    assert operators(tmp_path) == []


def test_operator_add_refuses_a_duplicate_name(run, monkeypatch):
    monkeypatch.setattr("getpass.getpass", lambda prompt="": SECRET)
    run("operator", "add", "alice")

    with pytest.raises(SystemExit) as stopped:
        run("operator", "add", "alice")

    assert stopped.value.code not in (0, None)


def host_of(tmp_path) -> str | None:
    db = Database(tmp_path / "data" / "control.sqlite3")
    try:
        return Ledger(db).host_of("SIMULATED")
    finally:
        db.close()


def test_host_register_creates_a_private_host_id_and_claims_the_device(run, tmp_path):
    run("host", "register")

    host_file = tmp_path / "data" / "host_id"
    assert stat.S_IMODE(host_file.stat().st_mode) == 0o600
    assert host_of(tmp_path) == host_file.read_text().strip() != ""
    run("host", "register")  # registering twice is harmless
    assert host_of(tmp_path) == host_file.read_text().strip()


def test_host_register_refuses_when_another_host_holds_the_device(run, tmp_path):
    (tmp_path / "data").mkdir()
    db = Database(tmp_path / "data" / "control.sqlite3")
    assert Ledger(db).register_host("SIMULATED", "other-host", 1.0)
    db.close()

    with pytest.raises(SystemExit) as stopped:
        run("host", "register")

    assert stopped.value.code not in (0, None)
    assert host_of(tmp_path) == "other-host"


def test_simulate_runs_a_short_stage_and_prints_a_summary(run, capsys):
    run("simulate")

    summary = json.loads(capsys.readouterr().out)
    assert summary["stage"] == "ended"
    assert summary["round"] == "data_verification"
    assert summary["samples"] > 0
    assert summary["writes"] > 0


def test_role_tokens_come_only_from_prefixed_environment_variables():
    environment = {
        "GROWBRIDGE_ROLE_TOKEN_PLANNER": "planner-secret",
        "GROWBRIDGE_ROLE_TOKEN_": "ignored-empty-role",
        "GROWBRIDGE_ROLE_TOKEN_RESEARCHER": "",
        "PATH": "/usr/bin",
    }

    assert role_tokens_from_env(environment) == {"planner": "planner-secret"}


def recovery_number(tmp_path) -> int:
    db = Database(tmp_path / "data" / "control.sqlite3")
    try:
        return Ledger(db).recovery()
    finally:
        db.close()


def test_recovery_bump_raises_the_recovery_number_when_no_daemon_runs(run, tmp_path):
    run("recovery", "bump", "--reason", "restored from backup")

    assert recovery_number(tmp_path) == 2  # a new ledger starts at 1


def test_recovery_bump_refuses_while_a_daemon_holds_the_lock(run, tmp_path):
    (tmp_path / "data").mkdir()
    with (tmp_path / "data" / "daemon.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(SystemExit) as stopped:
            run("recovery", "bump", "--reason", "restored from backup")

    assert stopped.value.code not in (0, None)
    assert not (tmp_path / "data" / "control.sqlite3").exists()


def test_recovery_bump_needs_a_reason(run):
    with pytest.raises(SystemExit) as stopped:
        run("recovery", "bump")

    assert stopped.value.code == 2
