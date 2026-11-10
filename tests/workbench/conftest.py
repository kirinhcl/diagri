import pytest
from workbench_support import SECRET, Bench


@pytest.fixture
def bench(tmp_path):
    instance = Bench(tmp_path)
    instance.operators.add("alice", SECRET)
    yield instance
    instance.db.close()


@pytest.fixture
def operator(bench):
    """A logged-in operator on the LAN entry (cookie kept in ``bench.lan``)."""
    assert bench.login(bench.lan).status_code == 200
    return bench.lan


@pytest.fixture
def bench_without_lan(tmp_path):
    """The same bench with no on-site listener configured (lan_port unset)."""
    instance = Bench(tmp_path, lan_port=None)
    instance.operators.add("alice", SECRET)
    yield instance
    instance.db.close()
