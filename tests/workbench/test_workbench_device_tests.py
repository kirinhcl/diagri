"""Device test routes of the multi-user workbench (design 2026-11-27)."""

import asyncio

import pytest
from workbench_support import Bench

from growbridge.archive.models import Channel


@pytest.fixture
def bench(tmp_path):
    bench = Bench(tmp_path, multi_user=True)
    for name, role in (("alice", "user"), ("bob", "user"), ("root", "admin")):
        bench.user(name, role)
    bench.lock("alice", "gh-01", "gh-02")
    return bench


def rows(client) -> dict[str, dict]:
    return {row["id"]: row for row in client.get("/wb/greenhouses").json()["greenhouses"]}


def endpoint(bench, path: str):
    return next(route.endpoint for route in bench.router.routes if route.path == path)


def test_holder_runs_a_light_test_over_http(bench):
    alice = bench.user("alice")

    reply = bench.post(alice, "/wb/greenhouses/gh-01/test/light")

    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert (body["channel"], body["test_level"], body["seconds"]) == ("light", 100, 10)
    assert body["result"] == "restored"
    history = alice.get("/wb/greenhouses/gh-01/tests").json()["tests"]
    assert [(t["channel"], t["operator"], t["result"]) for t in history] == [
        ("light", "alice", "restored")
    ]
    assert set(history[0]) == {
        "test_id",
        "channel",
        "operator",
        "state",
        "result",
        "started_at",
        "ended_at",
        "note",
    }


def test_rows_show_testable_only_for_own_idle_local(bench):
    mine = rows(bench.user("alice"))
    theirs = rows(bench.user("bob"))

    assert (mine["gh-01"]["testable"], mine["gh-02"]["testable"]) == (True, False)
    assert theirs["gh-01"]["testable"] is False
    assert mine["gh-01"]["test_running"] is None and mine["gh-01"]["test_unsettled"] is None


def test_unknown_channel_is_422(bench):
    reply = bench.post(bench.user("alice"), "/wb/greenhouses/gh-01/test/heater")

    assert reply.status_code == 422


def test_other_user_cannot_run_or_read(bench):
    bob = bench.user("bob")

    assert bench.post(bob, "/wb/greenhouses/gh-01/test/fan").json()["detail"]["reason"] == (
        "greenhouse_not_held"
    )
    history = bob.get("/wb/greenhouses/gh-01/tests")
    assert history.status_code == 403 and history.json()["detail"]["code"] == "not_lock_holder"
    assert bench.user("root").get("/wb/greenhouses/gh-01/tests").status_code == 200


def test_settle_over_http_clears_test_unsettled(bench):
    alice = bench.user("alice")
    bench.control.fail_restore = True
    test_id = bench.post(alice, "/wb/greenhouses/gh-01/test/light").json()["test_id"]
    assert rows(alice)["gh-01"]["test_unsettled"] == {
        "test_id": test_id,
        "channel": "light",
        "state": "restore_failed",
    }
    assert rows(alice)["gh-01"]["testable"] is False

    blank = bench.post(alice, f"/wb/greenhouses/gh-01/tests/{test_id}/settle", {"note": "  "})
    assert blank.status_code == 422
    settled = bench.post(alice, f"/wb/greenhouses/gh-01/tests/{test_id}/settle", {"note": "ok"})

    assert settled.json() == {"settled": test_id}
    assert rows(alice)["gh-01"]["test_unsettled"] is None


def test_retry_over_http(bench):
    alice = bench.user("alice")
    bench.control.fail_restore = True
    test_id = bench.post(alice, "/wb/greenhouses/gh-01/test/light").json()["test_id"]
    bench.control.fail_restore = False

    reply = bench.post(alice, f"/wb/greenhouses/gh-01/tests/{test_id}/retry")

    assert reply.json()["result"] == "restored"
    assert rows(alice)["gh-01"]["testable"] is True


async def test_client_disconnect_still_restores(bench):
    bench.sleeper.gate = asyncio.Event()
    run = endpoint(bench, "/wb/greenhouses/{greenhouse_id}/test/{channel}")
    request = asyncio.create_task(run("gh-01", Channel.LIGHT, bench.actor("alice")))
    while not bench.sleeper.calls:
        await asyncio.sleep(0)

    request.cancel()  # the browser went away
    bench.sleeper.gate.set()
    for _ in range(100):
        await asyncio.sleep(0)

    (record,) = bench.device_tests.history("gh-01")
    assert (record.state, record.result) == ("done", "restored")


def test_single_user_workbench_has_no_test_routes(tmp_path):
    bench = Bench(tmp_path)
    bench.user("alice")

    assert bench.post(bench.user("alice"), "/wb/greenhouses/gh-01/test/light").status_code == 404
