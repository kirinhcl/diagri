"""The multi-user workbench fixture: users, locks, a fully mounted app and an absent twin."""

from workbench_support import Bench


def test_full_bench_mounts_every_optional_service(tmp_path):
    bench = Bench.full(tmp_path)
    paths = {path for _method, path in bench.wb_routes()}

    for path in ("/wb/compute", "/wb/holdouts", "/wb/analysis/runs", "/wb/goals", "/wb/alerts"):
        assert path in paths
    assert bench.workflow.access is bench.access and bench.access is not None
    assert bench.settings.multi_user is True


def test_user_helper_logs_in(tmp_path):
    bench = Bench(tmp_path, multi_user=True)

    alice = bench.user("alice")
    root = bench.user("root", role="admin")

    assert alice.get("/wb/me").json()["operator"] == "alice"
    assert bench.operators.role("root") == "admin" and root.get("/wb/me").status_code == 200


def test_seeding_as_a_user_owns_and_locks(tmp_path):
    bench = Bench(tmp_path, multi_user=True)
    bench.user("alice")

    stage_id = bench.pending_as("alice")

    assert bench.workflow.store.project_owner(bench.project_id) == "alice"
    assert bench.locks.held_by("alice") == ("gh-01",)
    assert bench.state(stage_id) == "pending_review"


def test_absent_twin_has_the_accounts_but_not_the_data(tmp_path):
    bench = Bench(tmp_path, multi_user=True)
    bench.user("alice")
    bench.pending_as("alice")

    twin = bench.absent_twin()

    assert twin.operators.role("alice") == "user"
    assert twin.workflow.store.find_stage("stage-1") is None
    assert twin.user("alice").get("/wb/me").status_code == 200


def test_single_user_bench_is_unchanged(tmp_path):
    bench = Bench(tmp_path)

    assert bench.workflow.access is None and bench.settings.multi_user is False
