"""Greenhouse lock routes and administrator routes."""

import pytest
from workbench_support import SECRET, Bench


@pytest.fixture
def bench(tmp_path):
    bench = Bench(tmp_path, multi_user=True)
    for name, role in (("alice", "user"), ("bob", "user"), ("root", "admin")):
        bench.user(name, role)
    return bench


def code(response) -> str:
    return response.json()["detail"]["code"]


def states(client) -> dict[str, dict]:
    return {row["id"]: row for row in client.get("/wb/greenhouses").json()["greenhouses"]}


def test_lock_flow_over_http(bench):
    alice, bob = bench.user("alice"), bench.user("bob")

    locked = bench.post(alice, "/wb/greenhouses/lock", {"greenhouse_ids": ["gh-01", "gh-02"]})

    assert locked.json() == {"locked": ["gh-01", "gh-02"]}
    seen = states(bob)
    assert [seen[g]["state"] for g in ("gh-01", "gh-02", "gh-03")] == ["taken", "taken", "free"]
    assert "holder" not in seen["gh-01"]
    assert states(alice)["gh-01"]["state"] == "mine"
    assert states(bench.user("root"))["gh-01"]["holder"] == "alice"
    again = bench.post(bob, "/wb/greenhouses/lock", {"greenhouse_ids": ["gh-02", "gh-03"]})
    assert again.status_code == 409 and code(again) == "lock_taken"
    assert states(bob)["gh-03"]["state"] == "free"


def test_lock_needs_reauth(bench):
    alice = bench.user("alice")
    bench.clock.advance(3600)

    response = bench.post(alice, "/wb/greenhouses/lock", {"greenhouse_ids": ["gh-01"]})

    assert code(response) == "reauth_required"


def test_release_over_http(bench):
    alice = bench.user("alice")
    bench.post(alice, "/wb/greenhouses/lock", {"greenhouse_ids": ["gh-02"]})

    assert (
        bench.post(bench.user("bob"), "/wb/greenhouses/gh-02/release").json()["detail"]["code"]
        == "not_lock_holder"
    )
    confirmed = {"plants_removed": True}
    assert bench.post(alice, "/wb/greenhouses/gh-02/release", confirmed).json() == {
        "released": "gh-02"
    }
    assert states(alice)["gh-02"]["state"] == "free"


def test_release_over_http_needs_the_plants_gone(bench):
    alice = bench.user("alice")
    bench.post(alice, "/wb/greenhouses/lock", {"greenhouse_ids": ["gh-02"]})

    for body in ({}, {"plants_removed": False}):
        refused = bench.post(alice, "/wb/greenhouses/gh-02/release", body)
        assert refused.status_code == 409
        assert refused.json()["detail"]["reason"] == "plants_not_removed"
    assert states(alice)["gh-02"]["state"] == "mine"
    done = bench.post(alice, "/wb/greenhouses/gh-02/release", {"plants_removed": True})
    assert done.json() == {"released": "gh-02"}


def test_admin_force_release_needs_note(bench):
    bench.lock("alice", "gh-02")
    root = bench.user("root")

    assert bench.post(root, "/wb/admin/greenhouses/gh-02/release", {}).status_code == 422
    done = bench.post(root, "/wb/admin/greenhouses/gh-02/release", {"note": "alice left"})

    assert done.status_code == 200
    events = root.get("/wb/admin/locks").json()["events"]
    assert (events[0]["action"], events[0]["note"]) == ("force_release", "alice left")


def test_force_release_refused_while_stage_live(bench):
    bench.pending_as("alice")

    response = bench.post(bench.user("root"), "/wb/admin/greenhouses/gh-01/release", {"note": "x"})

    assert response.status_code == 409 and code(response) == "greenhouse_busy"


ADMIN_ROUTES = [
    ("GET", "/wb/admin/operators", None),
    ("POST", "/wb/admin/operators", {"name": "eve", "secret": SECRET, "role": "user"}),
    ("POST", "/wb/admin/operators/disable", {"name": "bob"}),
    ("POST", "/wb/admin/operators/secret", {"name": "bob", "secret": SECRET}),
    ("GET", "/wb/admin/locks", None),
    ("POST", "/wb/admin/greenhouses/gh-01/release", {"note": "x"}),
    ("POST", "/wb/admin/projects/project-x/owner", {"owner": "bob", "note": "x"}),
]


@pytest.mark.parametrize(("method", "path", "body"), ADMIN_ROUTES)
def test_user_cannot_call_admin_routes(bench, method, path, body):
    alice = bench.user("alice")
    response = alice.get(path) if method == "GET" else bench.post(alice, path, body)

    assert response.status_code == 403 and code(response) == "admin_only"


def test_admin_manages_operators(bench):
    root = bench.user("root")

    assert (
        bench.post(root, "/wb/admin/operators", {"name": "lab/eve", "secret": SECRET}).status_code
        == 200
    )
    assert bench.post(root, "/wb/admin/operators/disable", {"name": "lab/eve"}).status_code == 200
    names = {row["name"]: row for row in root.get("/wb/admin/operators").json()["operators"]}
    assert names["lab/eve"]["disabled_at"] is not None
    weak = bench.post(root, "/wb/admin/operators", {"name": "x", "secret": "short"})
    assert weak.status_code == 422


def test_others_do_not_see_when_a_taken_greenhouse_was_locked(bench):
    alice, bob = bench.user("alice"), bench.user("bob")
    bench.post(alice, "/wb/greenhouses/lock", {"greenhouse_ids": ["gh-01"]})

    assert states(bob)["gh-01"]["locked_at"] is None
    assert states(alice)["gh-01"]["locked_at"] is not None
    assert states(bench.user("root"))["gh-01"]["locked_at"] is not None


def test_an_administrator_cannot_disable_their_own_account_over_http(bench):
    root = bench.user("root")

    response = bench.post(root, "/wb/admin/operators/disable", {"name": "root"})

    assert response.status_code == 422 and code(response) == "param"
    assert bench.operators.active("root") is True


def test_transfer_rules(bench):
    bench.pending_as("alice")
    root, project = bench.user("root"), bench.project_id
    path = f"/wb/admin/projects/{project}/owner"

    active = bench.post(root, path, {"owner": "bob", "note": "x"})
    assert code(active) == "state"  # alice is still active
    bench.operators.disable("alice")
    live = bench.post(root, path, {"owner": "bob", "note": "x"})
    assert code(live) == "state"  # the stage has not ended or stopped
    bench.run(bench.workflow.stop_stage("stage-1", bench.actor("root")))
    assert bench.post(root, path, {"owner": "nobody", "note": "x"}).status_code == 409

    moved = bench.post(root, path, {"owner": "bob", "note": "alice left the lab"})

    assert moved.status_code == 200
    assert bench.workflow.store.project_owner(project) == "bob"
    bob = bench.user("bob")
    assert bob.get(f"/wb/projects/{project}").status_code == 200


def test_transfer_then_owner_can_act(bench):
    legacy = bench.workflow.create_project("legacy", bench.designer)  # no owner
    root = bench.user("root")

    response = bench.post(
        root, f"/wb/admin/projects/{legacy}/owner", {"owner": "alice", "note": "x"}
    )

    assert response.status_code == 200
    budget = {"max_calls": 1, "max_cost": 1.0}
    assert (
        bench.post(bench.user("alice"), f"/wb/projects/{legacy}/budget", budget).status_code == 200
    )


def test_admin_list_marks_unfinished_stages(bench):
    bench.pending_as("alice")

    rows = {r["name"]: r for r in bench.user("root").get("/wb/admin/operators").json()["operators"]}

    assert rows["alice"]["unfinished_stages"] == 1 and rows["bob"]["unfinished_stages"] == 0


def test_me_tells_the_console_about_multi_user(bench):
    bench.lock("alice", "gh-02")

    me = bench.user("alice").get("/wb/me").json()

    assert (me["multi_user"], me["role"], me["greenhouses"]) == (True, "user", ["gh-02"])
    single_dir = bench.tmp_path / "single"
    single_dir.mkdir()
    single = Bench(single_dir)
    single.operators.add("carol", SECRET)
    assert single.user("carol").get("/wb/me").json()["multi_user"] is False


def test_administrators_see_who_changed_an_account(bench):
    root = bench.user("root")
    bench.post(root, "/wb/admin/operators/secret", {"name": "alice", "secret": SECRET})

    events = root.get("/wb/admin/operators").json()["events"]

    assert (events[0]["name"], events[0]["action"], events[0]["actor"]) == (
        "alice",
        "reset_secret",
        "root",
    )
