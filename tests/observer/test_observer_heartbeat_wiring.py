import httpx
import pytest

from growbridge.runtime_heartbeat import HOST_ENV, RUN_ENV, heartbeats_from_env

HOST_URL = "https://hc.example.invalid/ping/fake-host-secret"
RUN_URL = "https://hc.example.invalid/ping/fake-run-secret"


@pytest.fixture(autouse=True)
def no_heartbeat_env(monkeypatch):
    monkeypatch.delenv(HOST_ENV, raising=False)
    monkeypatch.delenv(RUN_ENV, raising=False)


def fake_client(seen):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text="OK")

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_the_environment_variable_names_are_the_documented_ones():
    assert HOST_ENV == "GROWBRIDGE_HEARTBEAT_HOST_URL"
    assert RUN_ENV == "GROWBRIDGE_HEARTBEAT_RUN_URL"


def test_neither_url_configured_gives_no_heartbeats():
    assert heartbeats_from_env() is None


def test_blank_values_count_as_not_configured(monkeypatch):
    monkeypatch.setenv(HOST_ENV, "  ")
    monkeypatch.setenv(RUN_ENV, "")

    assert heartbeats_from_env() is None


async def test_both_urls_configured_gives_a_host_and_a_run_heartbeat(monkeypatch):
    monkeypatch.setenv(HOST_ENV, HOST_URL)
    monkeypatch.setenv(RUN_ENV, RUN_URL)
    seen: list[str] = []

    pair = heartbeats_from_env(client=fake_client(seen))
    assert pair is not None
    host, run = pair
    await host.ping()
    await run.ping()
    await run.fail()

    assert seen == [HOST_URL, RUN_URL, RUN_URL + "/fail"]


@pytest.mark.parametrize(("set_name", "missing_name"), [(HOST_ENV, RUN_ENV), (RUN_ENV, HOST_ENV)])
def test_only_one_url_refuses_to_start_and_names_the_missing_variable(
    monkeypatch, set_name, missing_name
):
    monkeypatch.setenv(set_name, HOST_URL)

    with pytest.raises(ValueError) as refused:
        heartbeats_from_env()

    message = str(refused.value)
    assert missing_name in message and set_name in message
    assert "fake-host-secret" not in message
    assert "hc.example.invalid" not in message


def test_the_urls_do_not_appear_in_any_repr(monkeypatch):
    monkeypatch.setenv(HOST_ENV, HOST_URL)
    monkeypatch.setenv(RUN_ENV, RUN_URL)

    pair = heartbeats_from_env()

    assert pair is not None
    for channel in pair:
        assert "fake-" not in repr(channel)
        assert "hc.example.invalid" not in repr(channel)
        assert "fake-" not in str(vars(channel))
