import inspect
import smtplib
import ssl

import httpx
import pytest

from growbridge.observer import channels
from growbridge.observer.channels import EmailChannel, HeartbeatChannel, TelegramChannel

TOKEN = "fake-token-123"
HOST_URL = "https://hc.example.invalid/ping/fake-host-uuid"
RUN_ENV = "GROWBRIDGE_HEARTBEAT_RUN_URL"


def client_for(handler, seen=None):
    def wrapped(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return handler(request)

    return httpx.AsyncClient(transport=httpx.MockTransport(wrapped))


@pytest.fixture
def telegram_env(monkeypatch):
    monkeypatch.setenv("GROWBRIDGE_TELEGRAM_TOKEN", TOKEN)


async def test_telegram_sends_only_to_registered_chats(telegram_env):
    seen: list[httpx.Request] = []
    client = client_for(lambda r: httpx.Response(200, json={"ok": True}), seen)
    channel = TelegramChannel(["111", "222"], client=client)

    assert await channel.send("too hot") == "accepted"

    assert [r.url.path for r in seen] == [f"/bot{TOKEN}/sendMessage"] * 2
    bodies = [r.content.decode() for r in seen]
    assert any('"111"' in b for b in bodies) and any('"222"' in b for b in bodies)
    assert all("too hot" in b for b in bodies)


def test_telegram_has_no_path_that_reads_incoming_messages():
    source = inspect.getsource(channels)

    for forbidden in ("getUpdates", "setWebhook", "getUpdate"):
        assert forbidden not in source


async def test_telegram_without_token_or_chats_fails_without_a_request(monkeypatch):
    seen: list[httpx.Request] = []
    client = client_for(lambda r: httpx.Response(200), seen)
    monkeypatch.delenv("GROWBRIDGE_TELEGRAM_TOKEN", raising=False)

    assert await TelegramChannel(["111"], client=client).send("x") == "failed"
    monkeypatch.setenv("GROWBRIDGE_TELEGRAM_TOKEN", TOKEN)
    assert await TelegramChannel([], client=client).send("x") == "failed"
    assert seen == []


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(400, json={"ok": False}), "failed"),
        (httpx.Response(403, json={"ok": False}), "failed"),
        (httpx.Response(500), "unknown"),
        (httpx.Response(200, json={"ok": False}), "failed"),
    ],
)
async def test_telegram_maps_http_results(telegram_env, response, expected):
    channel = TelegramChannel(["111"], client=client_for(lambda r: response))

    assert await channel.send("x") == expected


async def test_telegram_network_errors_are_unknown_unless_never_connected(telegram_env):
    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    def refused(request):
        raise httpx.ConnectError("refused", request=request)

    assert await TelegramChannel(["1"], client=client_for(timeout)).send("x") == "unknown"
    assert await TelegramChannel(["1"], client=client_for(refused)).send("x") == "failed"


async def test_telegram_partial_delivery_is_not_reported_as_accepted(telegram_env):
    def handler(request):
        return httpx.Response(200 if b'"111"' in request.content else 500)

    channel = TelegramChannel(["111", "222"], client=client_for(handler))

    assert await channel.send("x") == "unknown"


async def test_email_channel_builds_a_message_for_the_recipients():
    sent = []
    channel = EmailChannel(["ops@example.invalid"], sender=sent.append, subject="GrowBridge")

    assert await channel.send("too hot") == "accepted"

    message = sent[0]
    assert message["To"] == "ops@example.invalid"
    assert message["Subject"] == "GrowBridge"
    assert "too hot" in message.get_content()


async def test_email_error_mapping():
    def refuse(message):
        raise smtplib.SMTPRecipientsRefused({})

    def drop(message):
        raise OSError("connection reset")

    assert await EmailChannel(["a@example.invalid"], sender=refuse).send("x") == "failed"
    assert await EmailChannel(["a@example.invalid"], sender=drop).send("x") == "unknown"
    assert await EmailChannel([], sender=lambda m: None).send("x") == "failed"


async def test_email_default_sender_reads_smtp_settings_from_the_environment(monkeypatch):
    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            calls.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self, context=None):
            verifying = (
                isinstance(context, ssl.SSLContext)
                and context.verify_mode == ssl.CERT_REQUIRED
                and context.check_hostname
            )
            calls.append(("starttls", verifying))

        def login(self, user, password):
            calls.append(("login", user, password))

        def send_message(self, message):
            calls.append(("send", message["From"]))

    monkeypatch.setattr(channels.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setenv("GROWBRIDGE_SMTP_HOST", "smtp.example.invalid")
    monkeypatch.setenv("GROWBRIDGE_SMTP_PORT", "2525")
    monkeypatch.setenv("GROWBRIDGE_SMTP_USER", "fake-user")
    monkeypatch.setenv("GROWBRIDGE_SMTP_PASSWORD", "fake-password")
    monkeypatch.setenv("GROWBRIDGE_SMTP_FROM", "growbridge@example.invalid")

    assert await EmailChannel(["ops@example.invalid"]).send("x") == "accepted"

    assert calls == [
        ("connect", "smtp.example.invalid", 2525),
        ("starttls", True),  # a context that verifies the server certificate and host name
        ("login", "fake-user", "fake-password"),
        ("send", "growbridge@example.invalid"),
    ]


async def test_email_without_smtp_host_fails(monkeypatch):
    monkeypatch.delenv("GROWBRIDGE_SMTP_HOST", raising=False)

    assert await EmailChannel(["ops@example.invalid"]).send("x") == "failed"


async def test_heartbeat_ping_and_fail_urls(monkeypatch):
    monkeypatch.setenv("GROWBRIDGE_HEARTBEAT_HOST_URL", HOST_URL)
    seen: list[httpx.Request] = []
    beat = HeartbeatChannel(
        "GROWBRIDGE_HEARTBEAT_HOST_URL",
        client=client_for(lambda r: httpx.Response(200, text="OK"), seen),
    )

    assert await beat.ping() is True
    assert await beat.fail() is True

    assert [str(r.url) for r in seen] == [HOST_URL, HOST_URL + "/fail"]


async def test_heartbeat_unconfigured_or_unreachable_returns_false(monkeypatch):
    monkeypatch.delenv(RUN_ENV, raising=False)
    seen: list[httpx.Request] = []
    unset = HeartbeatChannel(RUN_ENV, client=client_for(lambda r: httpx.Response(200), seen))
    assert await unset.ping() is False
    assert seen == []

    monkeypatch.setenv(RUN_ENV, HOST_URL)

    def down(request):
        raise httpx.ConnectError("down", request=request)

    assert await HeartbeatChannel(RUN_ENV, client=client_for(down)).ping() is False
