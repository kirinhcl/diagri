"""Two-level priority gate: a mutual-exclusion lock whose waiters carry a priority.

Use it as ``async with gate.acquire(URGENT):`` (there is no ``release()``).

Not preemptive: an URGENT caller never interrupts the current holder, so it
waits for at most that one holder. Among waiters, URGENT goes before NORMAL;
within one level it is first come, first served.

The idea follows agentic-greenhouse's prioritylock.py; the code is independent.
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Final

URGENT: Final = 0
NORMAL: Final = 1


class PriorityGate:
    def __init__(self) -> None:
        self._held = False
        self._waiters: list[tuple[int, int, asyncio.Future[None]]] = []
        self._seq = itertools.count()

    def locked(self) -> bool:
        return self._held

    def acquire(self, priority: int) -> AbstractAsyncContextManager[None]:
        if type(priority) is not int or priority not in (URGENT, NORMAL):
            raise ValueError(f"unknown gate priority: {priority!r}")
        return self._hold(priority)

    @asynccontextmanager
    async def _hold(self, priority: int) -> AsyncIterator[None]:
        await self._take(priority)
        try:
            yield
        finally:
            self._release()

    async def _take(self, priority: int) -> None:
        if not self._held:
            self._held = True
            return
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        heapq.heappush(self._waiters, (priority, next(self._seq), future))
        try:
            await future
        except asyncio.CancelledError:
            if future.done() and not future.cancelled():
                # Granted the gate in the same moment we were cancelled: pass it on.
                self._release()
            else:
                self._waiters = [w for w in self._waiters if w[2] is not future]
                heapq.heapify(self._waiters)
            raise

    def _release(self) -> None:
        while self._waiters:
            _, _, future = heapq.heappop(self._waiters)
            if not future.done():
                future.set_result(None)
                return  # the gate stays held, now by that waiter
        self._held = False
