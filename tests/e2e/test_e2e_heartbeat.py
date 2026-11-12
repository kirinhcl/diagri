import logging

import httpx
import pytest

from growbridge import cli
from growbridge.runtime_heartbeat import HOST_ENV, RUN_ENV, heartbeats_from_env

HOST_URL = "https://hc.example.invalid/ping/fake-host-secret"
RUN_URL = "https://hc.example.invalid/ping/fake-run-secret"
STANDING = "monitor_unconfigured"


def client_for(handler, seen):
    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return handler(request)

    return httpx.AsyncClient(transport=httpx.MockTransport(wrapped))


def configured(monkeypatch, seen, handler=lambda request: httpx.Response(200)):
    monkeypatch.setenv(HOST_ENV, HOST_URL)
    monkeypatch.setenv(RUN_ENV, RUN_URL)
    return heartbeats_from_env(client=client_for(handler, seen))


def standing(runtime):
    return [a for a in runtime.book.open() if a.kind == STANDING]


async def test_both_urls_send_heartbeats_once_per_interval(world, monkeypatch):
    seen: list[str] = []
    runtime = await world.boot(heartbeats=configured(monkeypatch, seen), channels={})

    for _ in range(30):
        await world.beat(runtime, 1)
    assert seen == [HOST_URL, RUN_URL]

    for _ in range(60):
        await world.beat(runtime, 1)
    assert seen == [HOST_URL, RUN_URL] * 2
    assert standing(runtime) == []


async def test_a_bad_run_health_sends_the_failure_signal_to_the_run_url(world, monkeypatch):
    seen: list[str] = []
    runtime = await world.boot(heartbeats=configured(monkeypatch, seen), channels={})
    await world.beat(runtime, 1)
    seen.clear()

    runtime.health.probes["capture"] = lambda: None
    await world.beat(runtime, 1)

    assert seen == [HOST_URL, RUN_URL + "/fail"]


async def test_no_heartbeat_configured_is_a_standing_warning_and_sends_nothing(world, monkeypatch):
    async def forbidden(self, *args, **kwargs):
        raise AssertionError("a heartbeat request was made without configuration")

    monkeypatch.delenv(HOST_ENV, raising=False)
    monkeypatch.delenv(RUN_ENV, raising=False)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    runtime = await world.boot(heartbeats=heartbeats_from_env(), channels={})

    for _ in range(70):
        await world.beat(runtime, 1)

    (alert,) = standing(runtime)
    assert alert.severity == "warning"
    assert HOST_ENV in alert.message and RUN_ENV in alert.message
    assert runtime.monitor is None


async def test_configuring_the_heartbeats_clears_the_standing_warning(world, monkeypatch):
    first = await world.boot(channels={})
    assert len(standing(first)) == 1
    await first.stop()

    second = await world.boot(heartbeats=configured(monkeypatch, []), channels={})

    assert standing(second) == []


async def test_serve_refuses_to_start_with_only_one_heartbeat_url(settings, monkeypatch):
    def not_reached(*args, **kwargs):
        raise AssertionError("the runtime was built although the heartbeat set is half configured")

    monkeypatch.delenv(RUN_ENV, raising=False)
    monkeypatch.setenv(HOST_ENV, HOST_URL)
    monkeypatch.setattr("growbridge.runtime.build_runtime", not_reached)

    with pytest.raises(SystemExit) as stopped:
        await cli._serve_auto_research(settings)

    message = str(stopped.value)
    assert RUN_ENV in message and "fake-host-secret" not in message


async def test_urls_never_appear_in_logs_or_alert_text(world, monkeypatch, caplog):
    def down(request):
        raise httpx.ConnectError(f"cannot reach {request.url}", request=request)

    seen: list[str] = []
    runtime = await world.boot(heartbeats=configured(monkeypatch, seen, down), channels={})

    with caplog.at_level(logging.DEBUG):
        await world.beat(runtime, 1)

    assert seen  # the beat was attempted
    assert [a for a in runtime.book.open() if a.kind == "external_monitor"]
    text = caplog.text + " ".join(a.message for a in runtime.book.open()) + repr(runtime.monitor)
    assert "fake-" not in text and "hc.example.invalid" not in text
