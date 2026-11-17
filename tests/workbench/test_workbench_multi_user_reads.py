"""Operators read only their own projects, rounds, stages and receipts; administrators read all.

A hidden object is answered exactly as the same id is answered where it does not exist."""

import pytest
from workbench_support import Bench

from growbridge.workbench.visibility import READ_RULES


@pytest.fixture
def world(tmp_path):
    bench = Bench.full(tmp_path)
    for name, role in (("alice", "user"), ("bob", "user"), ("root", "admin")):
        bench.user(name, role)
    bench.pending_as("alice")
    alice = bench.user("alice")
    bench.approve(alice)
    bench.post(alice, "/wb/stages/stage-1/start")
    bench.post(alice, "/wb/stages/stage-1/takeover")
    write = {"stage_id": "stage-1", "request_id": "req-alice-1", "level": 10}
    assert bench.post(alice, "/wb/manual/light", write).status_code == 200
    return bench


def paths(bench: Bench) -> dict[str, list[str]]:
    """Concrete GET paths naming alice's objects, by rule."""
    project, round_id = bench.project_id, bench.round_id
    stage = [
        f"/wb/stages/stage-1{tail}"
        for tail in ("", "/history", "/manual-tasks", "/measurements", "/readings", "/run-sheet")
    ]
    return {
        "project": [
            f"/wb/projects/{project}",
            f"/wb/projects/{project}/conversation",
            f"/wb/holdouts?project_id={project}",
            f"/wb/protocols/protocol-1/analysis?project_id={project}",
            "/wb/experiments/experiment-stage-1/variables",
        ],
        "stage": stage,
        "round": [f"/wb/rounds/{round_id}", f"/wb/rounds/{round_id}/report"],
        "receipt": ["/wb/receipts/req-alice-1"],
    }


def test_every_get_route_is_registered(world):
    served = {path for method, path in world.wb_routes() if method == "GET"}

    assert served == set(READ_RULES)


@pytest.mark.parametrize("rule", ["project", "stage", "round", "receipt"])
def test_b_cannot_see_a(world, rule):
    twin = world.absent_twin()
    bob, bob_there = world.user("bob"), twin.user("bob")

    for path in paths(world)[rule]:
        seen, absent = bob.get(path), bob_there.get(path)
        assert (seen.status_code, seen.json()) == (absent.status_code, absent.json()), path
        assert seen.status_code >= 400, path
        assert world.project_id not in seen.text or world.project_id in path, path


@pytest.mark.parametrize("rule", ["project", "stage", "round", "receipt"])
def test_admin_sees_everything(world, rule):
    root = world.user("root")

    for path in paths(world)[rule]:
        if path.endswith("/report"):
            continue  # no report was published; the round itself is readable
        assert root.get(path).status_code == 200, path


def test_owner_sees_her_own(world):
    alice = world.user("alice")

    for rule in ("project", "stage", "round", "receipt"):
        for path in paths(world)[rule]:
            if not path.endswith("/report"):
                assert alice.get(path).status_code == 200, path


def test_projects_list_only_own(world):
    names = lambda client: [p["project_id"] for p in client.get("/wb/projects").json()["projects"]]  # noqa: E731

    assert names(world.user("alice")) == [world.project_id]
    assert names(world.user("bob")) == []
    assert names(world.user("root")) == [world.project_id]
