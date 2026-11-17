"""What the memory reads from (design 2026-11-17): the stores a model's history is computed from."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MemorySources:
    workflow: Any  # WorkflowService (only ``.store`` is read)
    archive: Any  # Archive
    book: Any  # AlertBook or None
    notes: Any  # DeviceNotes or None
    holdout: Any  # HoldoutRegistry or None
    clock: Any
    timezone: str
    device_id: str | None
    multi_user: bool
