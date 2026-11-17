"""Local browser sessions. The installation token never reaches browser JavaScript."""

import hashlib
import secrets
import time

from .httperror import CodedHTTPError

COOKIE = "growbridge_session"
SESSION_SECONDS = 12 * 3600


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class BrowserSessions:
    def __init__(self):
        self.codes: dict[str, float] = {}
        self.sessions: dict[str, float] = {}

    def prune(self):
        now = time.monotonic()
        self.codes = {key: expiry for key, expiry in self.codes.items() if expiry > now}
        self.sessions = {key: expiry for key, expiry in self.sessions.items() if expiry > now}

    def issue(self) -> str:
        self.prune()
        if len(self.codes) >= 64:
            raise CodedHTTPError(
                429,
                "Too many pending browser connections",
                code="locked",
                reason="too_many_pending_connections",
            )
        code = secrets.token_urlsafe(32)
        self.codes[digest(code)] = time.monotonic() + 60
        return code

    def redeem(self, code: str) -> str:
        self.prune()
        if self.codes.pop(digest(code), 0) <= time.monotonic():
            raise CodedHTTPError(
                401,
                "Connection link has expired or was already used",
                code="session",
                reason="link_used",
            )
        if len(self.sessions) >= 64:
            raise CodedHTTPError(
                429, "Too many browser sessions", code="locked", reason="too_many_sessions"
            )
        session = secrets.token_urlsafe(32)
        self.sessions[digest(session)] = time.monotonic() + SESSION_SECONDS
        return session

    def valid(self, session: str | None) -> bool:
        self.prune()
        return bool(session and digest(session) in self.sessions)

    def revoke(self, session: str | None):
        if session:
            self.sessions.pop(digest(session), None)
