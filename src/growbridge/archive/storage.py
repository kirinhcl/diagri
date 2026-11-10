"""Storage-pressure degradation (architecture doc §11.5).

``low``: pause research cache writes, bulk transfers and images outside the run sheet's
measurement plan. ``critical``: also pause new experiment actions. Care rules, protection rules
and sample records are never blocked.
"""

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

Level = Literal["ok", "low", "critical"]
BLOCKED_WHEN_LOW = frozenset({"research_cache", "bulk_transfer", "unplanned_image"})
BLOCKED_WHEN_CRITICAL = BLOCKED_WHEN_LOW | {"experiment_action"}
ALWAYS_ALLOWED = frozenset({"care", "protection", "sample"})
KNOWN_KINDS = BLOCKED_WHEN_CRITICAL | ALWAYS_ALLOWED


class StorageGuard:
    def __init__(
        self,
        root: Path,
        low_bytes: int,
        critical_bytes: int,
        usage: Callable[[Path], Any] = shutil.disk_usage,
    ):
        if critical_bytes > low_bytes:
            raise ValueError("critical_bytes must not exceed low_bytes")
        self.root = Path(root)
        self.low_bytes = low_bytes
        self.critical_bytes = critical_bytes
        self.usage = usage

    def level(self) -> Level:
        free = self.usage(self.root).free
        if free < self.critical_bytes:
            return "critical"
        if free < self.low_bytes:
            return "low"
        return "ok"

    def allows(self, kind: str) -> bool:
        if kind not in KNOWN_KINDS:
            raise ValueError(f"unknown storage use {kind!r}")
        level = self.level()
        if level == "critical":
            return kind not in BLOCKED_WHEN_CRITICAL
        if level == "low":
            return kind not in BLOCKED_WHEN_LOW
        return True
