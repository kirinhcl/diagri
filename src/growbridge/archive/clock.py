"""Wall and monotonic time behind one interface.

Durations, minimum switch intervals and care rules during an untrusted clock use
``monotonic()``; calendar triggers use ``now()`` and stop while ``synced`` is false.
"""

import time
from typing import Protocol


class Clock(Protocol):
    synced: bool

    def now(self) -> float:
        """UTC seconds since the epoch."""
        ...

    def monotonic(self) -> float: ...


class SystemClock:
    """Real time. ``synced`` is set by whoever checks the host's time synchronisation."""

    def __init__(self, synced: bool = True):
        self.synced = synced

    def now(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.monotonic()
