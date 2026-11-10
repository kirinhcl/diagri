"""Operator credentials, sessions and the server-side entry decision (no HTTP)."""

import hashlib

import pytest
from workbench_support import FAST_SCRYPT, LAN_HOST, OVERLAY_HOST, SECRET

from growbridge.archive.db import Database
from growbridge.archive.models import Entry
from growbridge.config import Settings
from growbridge.ports import Denied
from growbridge.sim.clock import FakeClock
from growbridge.workbench.auth import (
    MAX_FAILURES,
    MAX_GLOBAL_FAILURES,
    SESSION_SECONDS,
    Operators,
    entry_for,
)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "operators.db")
    yield database
    database.close()


@pytest.fixture
def operators(db, clock):
    book = Operators(db, clock, scrypt_n=FAST_SCRYPT)
    book.add("alice", SECRET)
    return book


def settings(**fields) -> Settings:
    return Settings(device="SIMULATED", token="t" * 32, data_dir="unused", **fields)


# --- credentials -------------------------------------------------------------------------------


def test_login_returns_a_token_that_resolves_to_the_operator(operators):
    token = operators.login("alice", SECRET, Entry.LAN, recovery_number=3)

    actor = operators.actor(token, 3)

    assert (actor.kind, actor.id, actor.entry) == ("operator", "alice", Entry.LAN)
    assert actor.reauth_at is not None


def test_wrong_secret_and_unknown_operator_are_indistinguishable(operators):
    with pytest.raises(Denied) as wrong:
        operators.login("alice", "not the secret at all", Entry.LAN)
    with pytest.raises(Denied) as unknown:
        operators.login("mallory", SECRET, Entry.LAN)

    assert (wrong.value.code, str(wrong.value)) == (unknown.value.code, str(unknown.value))
    assert wrong.value.code == "session"


def test_same_secret_gets_different_salt_and_hash(operators, db):
    operators.add("bob", SECRET)

    rows = db.query("SELECT salt, hash FROM operators ORDER BY name")

    assert rows[0]["salt"] != rows[1]["salt"]
    assert rows[0]["hash"] != rows[1]["hash"]
    assert SECRET.encode() not in bytes(rows[0]["hash"])


def test_add_rejects_duplicates_empty_names_and_short_secrets(operators):
    with pytest.raises(ValueError):
        operators.add("alice", SECRET)
    with pytest.raises(ValueError):
        operators.add("  ", SECRET)
    with pytest.raises(ValueError):
        operators.add("carol", "short")


def test_token_is_stored_only_as_sha256(operators, db):
    token = operators.login("alice", SECRET, Entry.LAN, recovery_number=1)

    stored = [row["token_hash"] for row in db.query("SELECT token_hash FROM operator_sessions")]

    assert stored == [hashlib.sha256(token.encode()).hexdigest()]
    dump = " ".join(str(tuple(row)) for row in db.query("SELECT * FROM operator_sessions"))
    assert token not in dump


# --- sessions ----------------------------------------------------------------------------------


def test_session_expires(operators, clock):
    token = operators.login("alice", SECRET, Entry.LAN, recovery_number=1)

    clock.advance(SESSION_SECONDS + 1)

    with pytest.raises(Denied) as error:
        operators.actor(token, 1)
    assert error.value.code == "session"


def test_unknown_token_is_denied(operators):
    with pytest.raises(Denied) as error:
        operators.actor("not-a-token", 1)
    assert error.value.code == "session"


def test_recovery_number_change_voids_the_session_for_good(operators):
    token = operators.login("alice", SECRET, Entry.LAN, recovery_number=1)

    with pytest.raises(Denied) as error:
        operators.actor(token, 2)
    assert error.value.code == "session"
    with pytest.raises(Denied):  # the old number coming back does not revive it
        operators.actor(token, 1)


def test_session_without_login_number_binds_at_first_use(operators):
    token = operators.login("alice", SECRET, Entry.OVERLAY)

    assert operators.actor(token, 7).id == "alice"
    with pytest.raises(Denied):
        operators.actor(token, 8)


def test_logout_ends_the_session(operators):
    token = operators.login("alice", SECRET, Entry.LAN, recovery_number=1)

    operators.logout(token)

    with pytest.raises(Denied):
        operators.actor(token, 1)
    operators.logout(token)  # a second logout is harmless


def test_reauthenticate_refreshes_the_timestamp(operators, clock):
    token = operators.login("alice", SECRET, Entry.LAN, recovery_number=1)
    first = operators.actor(token, 1).reauth_at

    clock.advance(600)
    operators.reauthenticate(token, SECRET)

    second = operators.actor(token, 1).reauth_at
    assert first is not None and second == first + 600


def test_reauthenticate_with_wrong_secret_changes_nothing(operators, clock):
    token = operators.login("alice", SECRET, Entry.LAN, recovery_number=1)
    first = operators.actor(token, 1).reauth_at
    clock.advance(600)

    with pytest.raises(Denied) as error:
        operators.reauthenticate(token, "some other secret entirely")

    assert error.value.code == "session"
    assert operators.actor(token, 1).reauth_at == first


# --- rate limit --------------------------------------------------------------------------------


def test_repeated_failures_lock_even_the_correct_secret(operators):
    for _ in range(5):
        with pytest.raises(Denied) as bad:
            operators.login("alice", "wrong wrong wrong", Entry.LAN)
        assert bad.value.code == "session"

    with pytest.raises(Denied) as locked:
        operators.login("alice", SECRET, Entry.LAN)
    assert locked.value.code == "locked"


def test_lock_ends_when_the_failures_age_out(operators, clock):
    for _ in range(5):
        with pytest.raises(Denied):
            operators.login("alice", "wrong wrong wrong", Entry.LAN)

    clock.advance(24 * 3600)

    assert operators.login("alice", SECRET, Entry.LAN, recovery_number=1)


def test_lock_is_per_name_and_success_clears_failures(operators):
    operators.add("bob", SECRET)
    for _ in range(4):
        with pytest.raises(Denied):
            operators.login("alice", "wrong wrong wrong", Entry.LAN)

    operators.login("bob", SECRET, Entry.LAN)  # unaffected
    operators.login("alice", SECRET, Entry.LAN)  # fifth attempt is correct: clears the count
    for _ in range(4):
        with pytest.raises(Denied) as bad:
            operators.login("alice", "wrong wrong wrong", Entry.LAN)
        assert bad.value.code == "session"


def test_failed_reauthentication_counts_toward_the_lock(operators):
    token = operators.login("alice", SECRET, Entry.LAN, recovery_number=1)
    for _ in range(5):
        with pytest.raises(Denied):
            operators.reauthenticate(token, "wrong wrong wrong")

    with pytest.raises(Denied) as locked:
        operators.reauthenticate(token, SECRET)
    assert locked.value.code == "locked"


def fail(operators, source, times, name="alice"):
    for _ in range(times):
        with pytest.raises(Denied) as bad:
            operators.login(name, "wrong wrong wrong", Entry.LAN, source=source)
        assert bad.value.code == "session"


def test_one_source_cannot_lock_the_operator_out_for_another(operators):
    fail(operators, "198.51.100.7", 5)

    with pytest.raises(Denied) as locked:
        operators.login("alice", SECRET, Entry.LAN, source="198.51.100.7")
    assert locked.value.code == "locked"
    assert operators.login("alice", SECRET, Entry.LAN, source="192.0.2.10")


def test_lock_clears_for_a_source_after_its_own_success(operators):
    fail(operators, "192.0.2.10", 4)

    operators.login("alice", SECRET, Entry.LAN, source="192.0.2.10")

    fail(operators, "192.0.2.10", 4)


def test_distributed_guessing_hits_a_global_cap_per_name(operators):
    for index in range(MAX_GLOBAL_FAILURES // MAX_FAILURES):
        fail(operators, f"203.0.113.{index}", MAX_FAILURES)

    with pytest.raises(Denied) as locked:
        operators.login("alice", SECRET, Entry.LAN, source="192.0.2.99")
    assert locked.value.code == "locked"


def test_global_cap_is_per_name(operators):
    operators.add("bob", SECRET)
    for index in range(MAX_GLOBAL_FAILURES // MAX_FAILURES):
        fail(operators, f"203.0.113.{index}", MAX_FAILURES)

    assert operators.login("bob", SECRET, Entry.LAN, source="192.0.2.99")


def test_failed_logins_from_other_sources_do_not_block_reauthentication(operators, clock):
    token = operators.login("alice", SECRET, Entry.LAN, recovery_number=1, source="192.0.2.10")
    for index in range(MAX_GLOBAL_FAILURES // MAX_FAILURES):
        fail(operators, f"203.0.113.{index}", MAX_FAILURES)  # also trips the global cap
    clock.advance(10)

    operators.reauthenticate(token, SECRET)

    assert operators.actor(token, 1).reauth_at == clock.now()


def test_reauthentication_failures_count_against_that_session_only(operators):
    first = operators.login("alice", SECRET, Entry.LAN, recovery_number=1, source="192.0.2.10")
    second = operators.login("alice", SECRET, Entry.LAN, recovery_number=1, source="192.0.2.11")
    for _ in range(MAX_FAILURES):
        with pytest.raises(Denied):
            operators.reauthenticate(first, "wrong wrong wrong")

    with pytest.raises(Denied) as locked:
        operators.reauthenticate(first, SECRET)
    assert locked.value.code == "locked"
    operators.reauthenticate(second, SECRET)  # another session of the same operator is fine
    assert operators.login("alice", SECRET, Entry.LAN, source="192.0.2.12")


# --- entry decided by the server ---------------------------------------------------------------


LAN_PORT_NUMBER = 9443
MAIN = 8766


@pytest.mark.parametrize(
    ("host", "port", "expected"),
    [
        (LAN_HOST, LAN_PORT_NUMBER, Entry.LAN),
        (f"{LAN_HOST}:9443", LAN_PORT_NUMBER, Entry.LAN),
        (LAN_HOST.upper(), LAN_PORT_NUMBER, Entry.LAN),
        (OVERLAY_HOST, MAIN, Entry.OVERLAY),
        (f"{OVERLAY_HOST}:443", MAIN, Entry.OVERLAY),
        (LAN_HOST, MAIN, None),  # a LAN host name on the proxied listener: spoofed
        (OVERLAY_HOST, LAN_PORT_NUMBER, None),  # an overlay host name on the LAN listener
        (LAN_HOST, None, None),  # no listener information: fail closed
        (LAN_HOST, 1234, None),
        ("localhost", MAIN, None),
        ("evil.test", LAN_PORT_NUMBER, None),
        ("", MAIN, None),
        (f"{LAN_HOST}.evil.test", LAN_PORT_NUMBER, None),
    ],
)
def test_entry_for_needs_the_accepting_listener_and_the_host(host, port, expected):
    config = settings(lan_hosts=[LAN_HOST], overlay_hosts=[OVERLAY_HOST], lan_port=LAN_PORT_NUMBER)

    assert entry_for(host, config, port) is expected


def test_entry_for_has_no_lan_entry_without_a_lan_port():
    config = settings(lan_hosts=[LAN_HOST], overlay_hosts=[OVERLAY_HOST])

    assert entry_for(LAN_HOST, config, 9443) is None
    assert entry_for(LAN_HOST, config, MAIN) is None
    assert entry_for(OVERLAY_HOST, config, MAIN) is Entry.OVERLAY


def test_entry_for_handles_ipv6_literals():
    config = settings(lan_hosts=["[fd00::5]"], overlay_hosts=["100.64.0.9"], lan_port=9443)

    assert entry_for("[fd00::5]:9443", config, 9443) is Entry.LAN
    assert entry_for("100.64.0.9:8766", config, MAIN) is Entry.OVERLAY


def test_entry_for_fails_closed_when_an_address_is_on_both_lists():
    config = settings(lan_hosts=["shared.test"], overlay_hosts=["shared.test"], lan_port=9443)

    assert entry_for("shared.test", config, 9443) is None
    assert entry_for("shared.test", config, MAIN) is None
