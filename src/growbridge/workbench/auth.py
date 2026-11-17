"""Operator credentials, sessions and the entry decision for the workbench (architecture §10).

Passkeys (WebAuthn) are a deployment item: they need a relying-party identity, an HTTPS origin
and a browser. Until they are set up, each operator has a separate secret that stands in for
the passkey: stored as a per-user salted ``hashlib.scrypt`` hash and compared in constant time.
The rest of the design (session bound to the recovery number, recent re-authentication, the
entry decided by the server) does not change when the credential type does.

Session tokens are random, are only ever stored as SHA-256 and expire. Failed logins are
rate-limited per operator name with the injected clock.
"""

import hashlib
import hmac
import secrets

from growbridge.archive.clock import Clock
from growbridge.archive.db import Database
from growbridge.archive.models import Entry
from growbridge.config import Settings
from growbridge.ports import Actor, Denied

SESSION_SECONDS = 8 * 3600
MAX_FAILURES = 5  # failed attempts inside the window that lock one (name, source) pair
MAX_GLOBAL_FAILURES = 25  # failed attempts from all sources that lock a name for everyone
SESSION_SOURCE = "session:"  # prefix of the failure source used for re-authentication
FAILURE_WINDOW_SECONDS = 15 * 60
MIN_SECRET_LENGTH = 12
MAX_SECRET_LENGTH = 256
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
KEY_BYTES = 32
SALT_BYTES = 16
NAME_LIMIT = 64
NAMESPACE = "workbench"

STEPS = (
    "CREATE TABLE operators(name TEXT PRIMARY KEY, salt BLOB NOT NULL, hash BLOB NOT NULL, "
    "n INTEGER NOT NULL, created_at REAL NOT NULL)",
    "CREATE TABLE operator_sessions(token_hash TEXT PRIMARY KEY, name TEXT NOT NULL, "
    "entry TEXT NOT NULL, recovery_number INTEGER, created_at REAL NOT NULL, "
    "expires_at REAL NOT NULL, reauth_at REAL NOT NULL)",
    "CREATE TABLE login_failures(name TEXT NOT NULL, at REAL NOT NULL)",
    "CREATE INDEX login_failures_name ON login_failures(name, at)",
    "ALTER TABLE login_failures ADD COLUMN source TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE operators ADD COLUMN role TEXT NOT NULL DEFAULT 'user'",
    "ALTER TABLE operators ADD COLUMN disabled_at REAL",
)
ROLES = ("user", "admin")

_NO_SALT = bytes(SALT_BYTES)  # stands in for an unknown name so the work done stays the same
_NO_HASH = bytes(KEY_BYTES)


def _token_hash(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


class Operators:
    """Operator accounts and their workbench sessions."""

    def __init__(self, db: Database, clock: Clock, scrypt_n: int = SCRYPT_N):
        self.db = db
        self.clock = clock
        self.scrypt_n = scrypt_n
        db.migrate(NAMESPACE, STEPS)

    # --- accounts ------------------------------------------------------------------------------

    def add(self, name: str, secret: str, role: str = "user") -> None:
        """Register an operator; ``ValueError`` for a duplicate, empty name, weak secret or an
        unknown role."""
        name = name.strip()
        if not name or len(name) > NAME_LIMIT:
            raise ValueError(f"an operator name is 1..{NAME_LIMIT} characters")
        if role not in ROLES:
            raise ValueError(f"a role is one of {', '.join(ROLES)}")
        salt, key = self._hashed(secret)
        with self.db.transaction():
            if self.db.one("SELECT 1 FROM operators WHERE name = ?", (name,)) is not None:
                raise ValueError(f"operator {name!r} already exists")
            self.db.execute(
                "INSERT INTO operators(name, salt, hash, n, created_at, role) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (name, salt, key, self.scrypt_n, self.clock.now(), role),
            )

    def _hashed(self, secret: str) -> tuple[bytes, bytes]:
        if not MIN_SECRET_LENGTH <= len(secret) <= MAX_SECRET_LENGTH:
            raise ValueError(f"a secret is {MIN_SECRET_LENGTH}..{MAX_SECRET_LENGTH} characters")
        salt = secrets.token_bytes(SALT_BYTES)
        return salt, self._derive(secret, salt, self.scrypt_n)

    def role(self, name: str) -> str | None:
        row = self.db.one("SELECT role FROM operators WHERE name = ?", (name,))
        return None if row is None else row["role"]

    def active(self, name: str) -> bool:
        row = self.db.one("SELECT disabled_at FROM operators WHERE name = ?", (name,))
        return row is not None and row["disabled_at"] is None

    def disable(self, name: str, *, by: str | None = None) -> None:
        """Stop an operator from signing in and end their sessions; their locks stay. Nothing in
        the console enables an account again, so ``by`` (the administrator asking) cannot disable
        themselves and the last active administrator is never disabled (``ValueError``)."""
        with self.db.transaction():
            self._require_known(name)
            if by == name:
                raise ValueError("an administrator cannot disable their own account")
            if self.role(name) == "admin" and self.active(name):
                others = self.db.one(
                    "SELECT COUNT(*) AS n FROM operators"
                    " WHERE role = 'admin' AND disabled_at IS NULL AND name != ?",
                    (name,),
                )
                if others["n"] == 0:
                    raise ValueError("the last active administrator cannot be disabled")
            self.db.execute(
                "UPDATE operators SET disabled_at = ? WHERE name = ?", (self.clock.now(), name)
            )
            self.db.execute("DELETE FROM operator_sessions WHERE name = ?", (name,))

    def reset_secret(self, name: str, secret: str) -> None:
        """Replace an operator's secret and end their sessions."""
        salt, key = self._hashed(secret)
        with self.db.transaction():
            self._require_known(name)
            self.db.execute(
                "UPDATE operators SET salt = ?, hash = ?, n = ? WHERE name = ?",
                (salt, key, self.scrypt_n, name),
            )
            self.db.execute("DELETE FROM operator_sessions WHERE name = ?", (name,))

    def listing(self) -> list[dict]:
        """Every account without its secret, oldest first."""
        rows = self.db.query(
            "SELECT name, role, created_at, disabled_at FROM operators ORDER BY created_at, name"
        )
        return [dict(row) for row in rows]

    def _require_known(self, name: str) -> None:
        if self.db.one("SELECT 1 FROM operators WHERE name = ?", (name,)) is None:
            raise ValueError(f"no operator {name!r}")

    @staticmethod
    def _derive(secret: str, salt: bytes, n: int) -> bytes:
        return hashlib.scrypt(
            secret.encode(),
            salt=salt,
            n=n,
            r=SCRYPT_R,
            p=SCRYPT_P,
            maxmem=2 * 128 * SCRYPT_R * (n + SCRYPT_P + 1),
            dklen=KEY_BYTES,
        )

    # --- sessions ------------------------------------------------------------------------------

    def login(
        self,
        name: str,
        secret: str,
        entry: Entry,
        recovery_number: int | None = None,
        source: str = "",
    ) -> str:
        """Check the credential and open a session; returns the token (shown to the client once).

        ``recovery_number`` binds the session to the control service's current recovery number.
        When omitted, the session binds to the number it is first used with. ``source`` is the
        client address: failures are counted per (name, source), so one source cannot lock the
        operator out for the others; a higher per-name cap bounds distributed guessing.
        """
        self._verify(name, secret, source)
        token = secrets.token_urlsafe(32)
        now = self.clock.now()
        with self.db.transaction():
            self.db.execute("DELETE FROM operator_sessions WHERE expires_at <= ?", (now,))
            self.db.execute(
                "INSERT INTO operator_sessions(token_hash, name, entry, recovery_number, "
                "created_at, expires_at, reauth_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    _token_hash(token),
                    name,
                    Entry(entry).value,
                    recovery_number,
                    now,
                    now + SESSION_SECONDS,
                    now,
                ),
            )
        return token

    def reauthenticate(self, token: str, secret: str) -> None:
        row = self._session(token)
        # Failures here count against this session only; logins from elsewhere do not block it.
        self._verify(row["name"], secret, SESSION_SOURCE + _token_hash(token)[:16], session=True)
        self.db.execute(
            "UPDATE operator_sessions SET reauth_at = ? WHERE token_hash = ?",
            (self.clock.now(), _token_hash(token)),
        )

    def actor(self, token: str, recovery_number: int) -> Actor:
        """The operator behind ``token``; an unknown, expired or outdated session is denied, and so
        is one whose account was disabled (a login racing the disable may outlive its delete)."""
        row = self._session(token)
        if not self.active(row["name"]):
            self.logout(token)
            raise Denied("session", "the session is no longer valid")
        bound = row["recovery_number"]
        if bound is None:
            self.db.execute(
                "UPDATE operator_sessions SET recovery_number = ? "
                "WHERE token_hash = ? AND recovery_number IS NULL",
                (recovery_number, _token_hash(token)),
            )
        elif bound != recovery_number:
            self.logout(token)
            raise Denied("session", "the session is no longer valid")
        return Actor(
            kind="operator",
            id=row["name"],
            entry=Entry(row["entry"]),
            reauth_at=row["reauth_at"],
            role=self.role(row["name"]),
        )

    def logout(self, token: str) -> None:
        self.db.execute("DELETE FROM operator_sessions WHERE token_hash = ?", (_token_hash(token),))

    def _session(self, token: str):
        row = self.db.one(
            "SELECT * FROM operator_sessions WHERE token_hash = ?", (_token_hash(token),)
        )
        if row is None:
            raise Denied("session", "the session is not valid")
        if row["expires_at"] <= self.clock.now():
            self.logout(token)
            raise Denied("session", "the session is not valid")
        return row

    # --- credential check and rate limit -------------------------------------------------------

    def _verify(self, name: str, secret: str, source: str, session: bool = False) -> None:
        key = name[:NAME_LIMIT]
        source = source[: NAME_LIMIT * 2]
        now = self.clock.now()
        self._require_unlocked(key, source, now, session)
        row = self.db.one(
            "SELECT salt, hash, n, disabled_at FROM operators WHERE name = ?", (name,)
        )
        if row is None:
            salt, expected, cost = _NO_SALT, _NO_HASH, self.scrypt_n
        else:
            salt, expected, cost = bytes(row["salt"]), bytes(row["hash"]), row["n"]
        fits = len(secret) <= MAX_SECRET_LENGTH
        derived = self._derive(secret if fits else "", salt, cost)
        refused = row is None or row["disabled_at"] is not None  # same work either way
        if refused or not fits or not hmac.compare_digest(derived, expected):
            self._record_failure(key, source, now)
            raise Denied("session", "invalid credentials")
        self.db.execute("DELETE FROM login_failures WHERE name = ? AND source = ?", (key, source))

    def _failures(self, condition: str, params: tuple) -> int:
        row = self.db.one(
            f"SELECT COUNT(*) AS failures FROM login_failures WHERE {condition}", params
        )
        return 0 if row is None else row["failures"]

    def _require_unlocked(self, key: str, source: str, now: float, session: bool) -> None:
        since = now - FAILURE_WINDOW_SECONDS
        pair = self._failures("name = ? AND source = ? AND at > ?", (key, source, since))
        if pair >= MAX_FAILURES:
            raise Denied("locked", "too many failed attempts; try again later")
        if session:
            return
        everywhere = self._failures(
            "name = ? AND source NOT LIKE ? AND at > ?", (key, SESSION_SOURCE + "%", since)
        )
        if everywhere >= MAX_GLOBAL_FAILURES:
            raise Denied("locked", "too many failed attempts; try again later")

    def _record_failure(self, key: str, source: str, now: float) -> None:
        with self.db.transaction():
            self.db.execute(
                "DELETE FROM login_failures WHERE at <= ?", (now - FAILURE_WINDOW_SECONDS,)
            )
            self.db.execute(
                "INSERT INTO login_failures(name, at, source) VALUES (?, ?, ?)", (key, now, source)
            )


# --- entries ---------------------------------------------------------------------------------


def host_only(value: str) -> str:
    """The lower-cased host of a ``Host`` header or configured address, without any port."""
    host = value.strip().lower()
    if host.startswith("["):
        end = host.find("]")
        return host[: end + 1] if end != -1 else ""
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def _hosts(values: list[str]) -> set[str]:
    return {host for host in (host_only(value) for value in values) if host}


def entry_for(host: str, settings: Settings, server_port: int | None) -> Entry | None:
    """Which entry a request arrived on: the listener that accepted it AND the Host it names.

    The LAN entry is a connection accepted on ``settings.lan_port`` with a Host in
    ``lan_hosts``; the overlay entry is one accepted on ``settings.port`` with a Host in
    ``overlay_hosts``. A client-supplied Host alone proves nothing (the daemon sits behind a
    proxy on its main port), so anything else has no entry, and with ``lan_port`` unset there
    is no LAN entry at all: fail closed.
    """
    name = host_only(host)
    on_lan = name in _hosts(settings.lan_hosts)
    on_overlay = name in _hosts(settings.overlay_hosts)
    if not name or server_port is None or on_lan == on_overlay:
        return None
    if on_lan and settings.lan_port is not None and server_port == settings.lan_port:
        return Entry.LAN
    if on_overlay and server_port == settings.port:
        return Entry.OVERLAY
    return None


def trusted_hosts(settings: Settings) -> list[str]:
    """The registered entry addresses; they join the daemon's trusted hosts."""
    return sorted(_hosts(settings.lan_hosts) | _hosts(settings.overlay_hosts))


def allowed_origins(settings: Settings) -> set[str]:
    """Origins a browser may send: the local ones plus each entry address (overlay is HTTPS)."""
    origins = {settings.url, f"http://localhost:{settings.port}"}
    for host in _hosts(settings.lan_hosts):
        origins.add(f"http://{host}")
        if settings.lan_port is not None:
            origins.add(f"http://{host}:{settings.lan_port}")
    for host in _hosts(settings.overlay_hosts):
        origins |= {f"https://{host}", f"https://{host}:{settings.port}"}
    return origins
