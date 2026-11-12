"""No secret reaches the log: heartbeat URLs, the Telegram bot token and the SMTP password.

httpx logs every request URL at INFO, and ``serve`` runs at INFO, so these tests configure logging
the way ``serve`` does (``configure_logging``) before they send anything.
"""

import logging

import httpx
import pytest

from growbridge.logging_setup import configure_logging
from growbridge.observer import channels
from growbridge.observer.channels import EmailChannel, HeartbeatChannel, TelegramChannel

PING_URL = "https://hc.example.invalid/ping/SECRET-UUID-1234"
TOKEN = "123456:FAKE-BOT-TOKEN-SECRET"
PASSWORD = "fake-smtp-password-SECRET"


@pytest.fixture(autouse=True)
def serve_logging():
    """The logging ``serve`` sets up, with the library loggers restored afterwards."""
    names = ("httpx", "httpcore", "")
    saved = {name: logging.getLogger(name).level for name in names}
    configure_logging()
    yield
    for name, level in saved.items():
        logging.getLogger(name).setLevel(level)


def fake_client():
    return httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))
    )


def test_configure_logging_keeps_http_libraries_below_info():
    for name in ("httpx", "httpcore"):
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("growbridge").getEffectiveLevel() <= logging.INFO


async def test_a_heartbeat_ping_logs_no_record_containing_the_url(monkeypatch, caplog):
    monkeypatch.setenv("GROWBRIDGE_HEARTBEAT_HOST_URL", PING_URL)
    beat = HeartbeatChannel("GROWBRIDGE_HEARTBEAT_HOST_URL", client=fake_client())

    with caplog.at_level(logging.INFO):
        assert await beat.ping() is True
        assert await beat.fail() is True

    assert "SECRET-UUID" not in caplog.text
    assert "hc.example.invalid" not in caplog.text


async def test_a_telegram_send_logs_no_record_containing_the_token(monkeypatch, caplog):
    monkeypatch.setenv("GROWBRIDGE_TELEGRAM_TOKEN", TOKEN)
    channel = TelegramChannel(["111"], client=fake_client())

    with caplog.at_level(logging.INFO):
        assert await channel.send("too hot") == "accepted"

    assert "FAKE-BOT-TOKEN" not in caplog.text


async def test_an_email_send_logs_no_record_containing_the_smtp_password(monkeypatch, caplog):
    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self, context=None):
            pass

        def login(self, user, password):
            pass

        def send_message(self, message):
            pass

    monkeypatch.setattr(channels.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setenv("GROWBRIDGE_SMTP_HOST", "smtp.example.invalid")
    monkeypatch.setenv("GROWBRIDGE_SMTP_USER", "fake-user")
    monkeypatch.setenv("GROWBRIDGE_SMTP_PASSWORD", PASSWORD)

    with caplog.at_level(logging.DEBUG):
        assert await EmailChannel(["ops@example.invalid"]).send("x") == "accepted"

    assert "SECRET" not in caplog.text


async def test_a_failing_email_logs_no_password_even_when_the_error_carries_it(caplog):
    def broken(message):
        raise OSError(f"login failed with {PASSWORD}")

    with caplog.at_level(logging.DEBUG):
        outcome = await EmailChannel(["ops@example.invalid"], sender=broken).send("x")

    assert outcome == "unknown"
    assert "SECRET" not in caplog.text


async def test_a_heartbeat_url_with_surrounding_whitespace_is_stripped_where_it_is_read(
    monkeypatch,
):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setenv("GROWBRIDGE_HEARTBEAT_RUN_URL", f"  {PING_URL}\n")

    beat = HeartbeatChannel("GROWBRIDGE_HEARTBEAT_RUN_URL", client=client)

    assert await beat.ping() is True
    assert await beat.fail() is True
    assert seen == [PING_URL, PING_URL + "/fail"]
