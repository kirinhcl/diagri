import threading

import pytest

from growbridge.agents.budget import CallBudget
from growbridge.archive.models import Budget
from growbridge.ports import Denied


@pytest.fixture
def budget(db, clock):
    service = CallBudget(db, clock)
    service.set("p1", Budget(max_calls=3, max_cost=10.0))
    return service


def test_budget_remaining_after_set(budget):
    assert budget.remaining("p1") == (3, 10.0)


def test_budget_reserve_decrements(budget):
    budget.reserve("p1")
    budget.reserve("p1", 2)
    assert budget.remaining("p1") == (0, 10.0)


def test_budget_reserve_over_limit_is_denied_and_leaves_balance(budget):
    with pytest.raises(Denied) as info:
        budget.reserve("p1", 4)
    assert info.value.code == "budget"
    assert budget.remaining("p1") == (3, 10.0)


def test_budget_exhausted_calls_deny(budget):
    budget.reserve("p1", 3)
    with pytest.raises(Denied) as info:
        budget.reserve("p1")
    assert info.value.code == "budget"


def test_budget_charge_reduces_cost_and_exhausted_cost_denies_reserve(budget):
    budget.charge("p1", 4.5)
    assert budget.remaining("p1") == (3, 5.5)
    budget.charge("p1", 5.5)
    with pytest.raises(Denied) as info:
        budget.reserve("p1")
    assert info.value.code == "budget"


def test_budget_overspent_cost_reports_zero(budget):
    budget.charge("p1", 12.0)
    assert budget.remaining("p1") == (3, 0.0)


def test_budget_unknown_project_is_denied(budget):
    for call in (lambda: budget.reserve("ghost"), lambda: budget.charge("ghost", 1.0)):
        with pytest.raises(Denied) as info:
            call()
        assert info.value.code == "budget"
    with pytest.raises(Denied):
        budget.remaining("ghost")


@pytest.mark.parametrize("calls", [0, -1])
def test_budget_rejects_non_positive_reservation(budget, calls):
    with pytest.raises(ValueError):
        budget.reserve("p1", calls)


def test_budget_rejects_negative_charge(budget):
    with pytest.raises(ValueError):
        budget.charge("p1", -0.01)


def test_budget_set_again_keeps_usage(budget):
    budget.reserve("p1", 2)
    budget.charge("p1", 3.0)
    budget.set("p1", Budget(max_calls=10, max_cost=20.0))
    assert budget.remaining("p1") == (8, 17.0)


def test_budget_projects_are_independent(budget):
    budget.set("p2", Budget(max_calls=1, max_cost=1.0))
    budget.reserve("p2")
    assert budget.remaining("p1") == (3, 10.0)


def test_budget_survives_reopen(db, clock, budget):
    budget.reserve("p1")
    assert CallBudget(db, clock).remaining("p1") == (2, 10.0)


def test_budget_concurrent_reserves_never_oversell(db, clock):
    service = CallBudget(db, clock)
    service.set("p1", Budget(max_calls=5, max_cost=10.0))
    granted: list[int] = []
    denied: list[int] = []
    gate = threading.Barrier(20)

    def worker(index: int) -> None:
        gate.wait()
        try:
            service.reserve("p1")
        except Denied:
            denied.append(index)
        else:
            granted.append(index)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(granted) == 5
    assert len(denied) == 15
    assert service.remaining("p1") == (0, 10.0)
