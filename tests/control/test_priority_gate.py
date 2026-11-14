import asyncio

import pytest

from growbridge.control.priority_gate import NORMAL, URGENT, PriorityGate


async def take(gate, order, name, priority):
    async with gate.acquire(priority):
        order.append(name)


async def test_urgent_waiter_goes_before_earlier_normal_waiters():
    gate, order = PriorityGate(), []
    async with gate.acquire(NORMAL):
        tasks = [
            asyncio.create_task(take(gate, order, n, p))
            for n, p in (("a", NORMAL), ("b", NORMAL), ("c", URGENT))
        ]
        await asyncio.sleep(0)
    await asyncio.gather(*tasks)
    assert order == ["c", "a", "b"]


async def test_same_level_is_first_come_first_served():
    gate, order = PriorityGate(), []
    async with gate.acquire(NORMAL):
        tasks = [asyncio.create_task(take(gate, order, n, NORMAL)) for n in ("a", "b", "c")]
        await asyncio.sleep(0)
    await asyncio.gather(*tasks)
    assert order == ["a", "b", "c"]


async def test_cancelled_waiter_is_skipped():
    gate, order = PriorityGate(), []
    async with gate.acquire(NORMAL):
        a = asyncio.create_task(take(gate, order, "a", NORMAL))
        b = asyncio.create_task(take(gate, order, "b", NORMAL))
        await asyncio.sleep(0)
        a.cancel()
        await asyncio.sleep(0)
    await asyncio.gather(a, b, return_exceptions=True)
    assert order == ["b"]
    assert gate.locked() is False


async def test_waiter_cancelled_right_after_being_granted_hands_the_gate_on():
    gate, order = PriorityGate(), []
    cm = gate.acquire(NORMAL)
    await cm.__aenter__()
    a = asyncio.create_task(take(gate, order, "a", NORMAL))
    b = asyncio.create_task(take(gate, order, "b", NORMAL))
    await asyncio.sleep(0)
    await cm.__aexit__(None, None, None)
    a.cancel()
    await asyncio.gather(a, b, return_exceptions=True)
    assert order == ["b"]
    assert gate.locked() is False


async def test_error_inside_releases_the_gate():
    gate = PriorityGate()
    with pytest.raises(RuntimeError):
        async with gate.acquire(NORMAL):
            raise RuntimeError("boom")
    assert gate.locked() is False
    async with gate.acquire(NORMAL):
        assert gate.locked() is True


def test_priority_must_be_given():
    with pytest.raises(TypeError):
        PriorityGate().acquire()  # type: ignore[call-arg]
