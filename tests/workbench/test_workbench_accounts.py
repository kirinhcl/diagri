"""Operator roles, disabling and secret reset."""

import argparse

import pytest

from growbridge.archive.db import Database
from growbridge.archive.models import Entry
from growbridge.config import Settings
from growbridge.ports import Denied
from growbridge.sim.clock import FakeClock
from growbridge.workbench.auth import Operators

SECRET = "correct horse battery staple"  # obviously fake
FAST = 2**10


@pytest.fixture
def operators(tmp_path):
    db = Database(tmp_path / "accounts.db")
    yield Operators(db, FakeClock(), scrypt_n=FAST)
    db.close()


def login(operators: Operators, name: str, secret: str = SECRET) -> str:
    return operators.login(name, secret, Entry.LAN, recovery_number=1)


def test_add_admin_role(operators):
    operators.add("root", SECRET, role="admin")

    assert operators.role("root") == "admin"
    assert operators.actor(login(operators, "root"), 1).role == "admin"


def test_default_role_is_user(operators):
    operators.add("alice", SECRET)

    assert operators.role("alice") == "user"
    assert operators.actor(login(operators, "alice"), 1).role == "user"
    assert operators.role("nobody") is None


def test_unknown_role_refused(operators):
    with pytest.raises(ValueError):
        operators.add("alice", SECRET, role="owner")


def test_disabled_cannot_log_in(operators):
    operators.add("alice", SECRET)
    operators.disable("alice")

    with pytest.raises(Denied) as denied:
        login(operators, "alice")

    assert denied.value.code == "session"
    assert str(denied.value) == "invalid credentials"
    assert operators.active("alice") is False


def test_disabled_user_session_ends(operators):
    operators.add("alice", SECRET)
    token = login(operators, "alice")

    operators.disable("alice")

    with pytest.raises(Denied) as denied:
        operators.actor(token, 1)
    assert denied.value.code == "session"


def test_a_session_that_outlived_its_disable_is_still_refused(operators):
    # a login that raced a disable could store its session after the sessions were deleted
    operators.add("alice", SECRET)
    token = login(operators, "alice")
    operators.db.execute("UPDATE operators SET disabled_at = 1 WHERE name = 'alice'")

    with pytest.raises(Denied) as denied:
        operators.actor(token, 1)

    assert denied.value.code == "session"


def test_an_operator_cannot_disable_their_own_account(operators):
    operators.add("root", SECRET, role="admin")
    operators.add("ops", SECRET, role="admin")

    with pytest.raises(ValueError):
        operators.disable("root", by="root")

    assert operators.active("root") is True


def test_the_last_active_administrator_cannot_be_disabled(operators):
    operators.add("root", SECRET, role="admin")
    operators.add("ops", SECRET, role="admin")
    operators.add("alice", SECRET)
    operators.disable("ops", by="root")  # another administrator is left
    operators.disable("alice", by="root")

    with pytest.raises(ValueError):
        operators.disable("root")

    assert operators.active("root") is True


def test_disable_unknown_name_refused(operators):
    with pytest.raises(ValueError):
        operators.disable("nobody")


def test_reset_secret_ends_sessions(operators):
    operators.add("alice", SECRET)
    token = login(operators, "alice")

    operators.reset_secret("alice", "another long secret")

    with pytest.raises(Denied):
        operators.actor(token, 1)
    with pytest.raises(Denied):
        login(operators, "alice")
    assert operators.actor(login(operators, "alice", "another long secret"), 1).id == "alice"


def test_listing_has_no_secrets(operators):
    operators.add("alice", SECRET)
    operators.add("root", SECRET, role="admin")
    operators.disable("alice")

    listed = {row["name"]: row for row in operators.listing()}

    assert set(listed) == {"alice", "root"}
    for row in listed.values():
        assert set(row) == {"name", "role", "created_at", "disabled_at"}
    assert listed["alice"]["disabled_at"] is not None
    assert listed["root"]["role"] == "admin"


def test_name_with_slash_is_manageable(operators):
    operators.add("lab/alice", SECRET)

    operators.reset_secret("lab/alice", "another long secret")
    operators.disable("lab/alice")

    assert operators.active("lab/alice") is False


def test_cli_add_admin(tmp_path, monkeypatch):
    from growbridge import cli
    from growbridge.runtime import private_dir

    monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt: SECRET)
    settings = Settings(device="AC5", token="t" * 32, data_dir=tmp_path, auto_research=True)

    cli._add_operator(argparse.ArgumentParser(), settings, "root", admin=True)

    db = Database(private_dir(tmp_path) / "workflow.sqlite3")
    try:
        assert Operators(db, FakeClock()).role("root") == "admin"
    finally:
        db.close()
