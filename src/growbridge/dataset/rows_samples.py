"""Rows for sensor_readings.csv and device_states.csv, built from snapshot samples."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from growbridge.archive.models import SampleRecord
from growbridge.vocab.catalog import Catalog


@dataclass(frozen=True)
class SampleRows:
    sensor: tuple[dict, ...]
    device: tuple[dict, ...]
    unresolved_keys: int
    non_numeric: int


def time_of(sample: SampleRecord) -> tuple[float, str]:
    if sample.captured_at is not None and sample.clock_synced:
        return sample.captured_at, "captured"
    return sample.received_at, "received"


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _leaves(data: Mapping[str, Any], prefix: str = "") -> list[tuple[str, Any]]:
    """Every leaf outside nested dicts, keys joined with dots as ``snapshot._numbers`` does."""
    found: list[tuple[str, Any]] = []
    for key, value in data.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            found.extend(_leaves(value, f"{name}."))
        else:
            found.append((name, value))
    return found


def _is_stuck(key: str, at: float, catalog: Catalog, frozen: Sequence[Mapping[str, Any]]) -> bool:
    return any(
        catalog.same(period["sensor"], key)
        and period["first_at"] <= at
        and (period["last_at"] is None or at <= period["last_at"])
        for period in frozen
    )


def _common(sample: SampleRecord, round_number: int) -> dict[str, Any]:
    at, source = time_of(sample)
    return {
        "time": at,
        "time_source": source,
        "clock_synced": sample.clock_synced,
        "sample_id": sample.id,
        "device_id": sample.device_id,
        "experiment_id": sample.experiment_id,
        "stage_id": sample.stage_id,
        "round": round_number,
        "quality": sample.quality,
    }


def sample_rows(
    samples: Sequence[SampleRecord],
    round_number: int,
    catalog: Catalog,
    frozen: Sequence[Mapping[str, Any]],
) -> SampleRows:
    sensor: list[dict] = []
    device: list[dict] = []
    unresolved = 0
    non_numeric = 0
    for sample in samples:
        common = _common(sample, round_number)
        readings = sample.data.get("sensor")
        for key, value in readings.items() if isinstance(readings, dict) else ():
            if not _is_number(value):
                non_numeric += 1
                continue
            variable = catalog.canonical(key)
            unresolved += variable is None
            stuck = _is_stuck(key, common["time"], catalog, frozen)
            sensor.append(
                {**common, "variable_id": variable, "raw_key": key, "value": value, "stuck": stuck}
            )
        others = {k: v for k, v in sample.data.items() if k != "sensor"}
        for key, value in _leaves(others):
            if _is_number(value):
                device.append({**common, "key": key, "value": value})
            else:
                non_numeric += 1
    return SampleRows(tuple(sensor), tuple(device), unresolved, non_numeric)
