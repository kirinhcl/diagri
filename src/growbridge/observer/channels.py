"""Delivery channels (architecture doc section 8.3).

Secrets and endpoints come only from environment variables. The Telegram channel posts to the
registered chat ids and has no code path that reads inbound messages. A channel reports one of
``accepted``, ``unknown`` (the request may have arrived) or ``failed`` (it certainly did not).
"""

import asyncio
import os
import smtplib
import ssl
from collections.abc import Callable, Sequence
from email.message import EmailMessage
from typing import Literal, Protocol

import httpx

Outcome = Literal["accepted", "unknown", "failed"]
TELEGRAM_TOKEN_ENV = "GROWBRIDGE_TELEGRAM_TOKEN"
TELEGRAM_API = "https://api.telegram.org"
SMTP_DEFAULT_PORT = 587
REQUEST_TIMEOUT_SECONDS = 10.0
SMTP_REFUSALS = (
    smtplib.SMTPRecipientsRefused,
    smtplib.SMTPAuthenticationError,
    smtplib.SMTPSenderRefused,
    smtplib.SMTPNotSupportedError,
)


class NotifyChannel(Protocol):
    async def send(self, text: str) -> Outcome: ...


def _http_outcome(response: httpx.Response) -> Outcome:
    if response.status_code >= 500:
        return "unknown"
    if response.status_code != 200:
        return "failed"
    try:
        return "accepted" if response.json().get("ok") is True else "failed"
    except ValueError:
        return "unknown"


async def _post(client: httpx.AsyncClient, url: str, payload: dict) -> Outcome:
    try:
        return _http_outcome(await client.post(url, json=payload))
    except (httpx.ConnectError, httpx.ConnectTimeout):
        return "failed"  # never connected, so nothing was sent
    except httpx.HTTPError:
        return "unknown"


def _combine(outcomes: Sequence[Outcome]) -> Outcome:
    if all(o == "accepted" for o in outcomes):
        return "accepted"
    return "unknown" if "unknown" in outcomes else "failed"


class TelegramChannel:
    def __init__(self, chat_ids: Sequence[str], client: httpx.AsyncClient | None = None):
        self.chat_ids = tuple(chat_ids)
        self.client = client

    async def send(self, text: str) -> Outcome:
        token = os.environ.get(TELEGRAM_TOKEN_ENV)
        if not token or not self.chat_ids:
            return "failed"
        url = f"{TELEGRAM_API}/bot{token}/sendMessage"
        client = self.client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)
        try:
            outcomes = [
                await _post(client, url, {"chat_id": c, "text": text}) for c in self.chat_ids
            ]
        finally:
            if self.client is None:
                await client.aclose()
        return _combine(outcomes)


class _NotConfigured(Exception):
    pass


def _smtp_send(message: EmailMessage) -> None:
    host = os.environ.get("GROWBRIDGE_SMTP_HOST")
    if not host:
        raise _NotConfigured("GROWBRIDGE_SMTP_HOST is not set")
    port = int(os.environ.get("GROWBRIDGE_SMTP_PORT", SMTP_DEFAULT_PORT))
    user = os.environ.get("GROWBRIDGE_SMTP_USER")
    password = os.environ.get("GROWBRIDGE_SMTP_PASSWORD", "")
    message["From"] = os.environ.get("GROWBRIDGE_SMTP_FROM", user or "growbridge@localhost")
    with smtplib.SMTP(host, port, timeout=REQUEST_TIMEOUT_SECONDS) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        if user:
            smtp.login(user, password)
        smtp.send_message(message)


class EmailChannel:
    def __init__(
        self,
        recipients: Sequence[str],
        sender: Callable[[EmailMessage], None] | None = None,
        subject: str = "GrowBridge notification",
    ):
        self.recipients = tuple(recipients)
        self.sender = sender or _smtp_send
        self.subject = subject

    def _message(self, text: str) -> EmailMessage:
        message = EmailMessage()
        message["To"] = ", ".join(self.recipients)
        message["Subject"] = self.subject
        message.set_content(text)
        return message

    async def send(self, text: str) -> Outcome:
        if not self.recipients:
            return "failed"
        message = self._message(text)
        try:
            await asyncio.to_thread(self.sender, message)
        except (_NotConfigured, *SMTP_REFUSALS):
            return "failed"
        except (OSError, smtplib.SMTPException):
            return "unknown"
        return "accepted"


class HeartbeatChannel:
    """A dead-man's-switch endpoint (for example Healthchecks.io); the URL is read from ``env``."""

    def __init__(self, env: str, client: httpx.AsyncClient | None = None):
        self.env = env
        self.client = client

    async def _get(self, suffix: str) -> bool:
        base = os.environ.get(self.env)
        if not base:
            return False
        client = self.client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)
        try:
            return (await client.get(base + suffix)).is_success
        except httpx.HTTPError:
            return False
        finally:
            if self.client is None:
                await client.aclose()

    async def ping(self) -> bool:
        return await self._get("")

    async def fail(self) -> bool:
        return await self._get("/fail")
