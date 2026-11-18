"""The golden fixture of the training-dataset export: one snapshot built through the real APIs.

It covers spec §13: two rounds with two units in round 1 (the snapshot's round), a correction
chain, a frozen-sensor period, a sample without a capture time, an unresolvable sensor key,
light, fan and outlet states with one non-numeric leaf, a manual and a planned-irrigation action
whose notes name the operator, a holdout registered before the freeze and one after it, a
``plant_id`` with a comma, quotes, a newline and Chinese, and a protocol question with a comma
and Chinese text. Ids, the clock and the pseudonym key are fixed, so the output is too.

Regenerate the golden files (then read each one before committing it):
    PYTHONPATH=src .venv/bin/python tests/dataset_support.py
"""

from __future__ import annotations

import csv
import io
import itertools
import tempfile
from pathlib import Path

import pytest

from growbridge.archive import snapshot as snap
from growbridge.archive import store
from growbridge.archive.db import Database
from growbridge.archive.models import (
    ActionRecord,
    ActionState,
    Allocation,
    Channel,
    ManualMeasurement,
    RightKind,
    SampleRecord,
)
from growbridge.archive.store import Archive
from growbridge.dataset.build import ExportInputs, build_dataset
from growbridge.dataset.pseudonym import Pseudonymizer
from growbridge.dataset.source import read_snapshot
from growbridge.research.holdout import HoldoutRegistry
from growbridge.sim.clock import START, FakeClock
from growbridge.sim.fixtures import make_protocol
from growbridge.vocab import load_catalog

GOLDEN = Path(__file__).parent / "dataset" / "golden"
OPERATOR_NAMES = ["Alice Moreau", "Bo Chen", "王芳"]
HELD_RECORD_IDS = ("m-held-before", "m-held-after")

EXPERIMENT = "exp-1"
STAGE = "vegetative"
PROJECT = "project-1"
OUTCOME = "canopy_area_growth"
WINDOW = 600.0
PLANT = 'A,"1"\n二'

# Test catalogs, independent of the packaged one: the snapshot is frozen under version 1 and
# exported under version 2, which adds terms. The terms only exercise the format; they are the
# values the vocabulary tests use, not mappings anyone has confirmed.
_ENTRIES = """
[unit_aliases]
C = "Cel"

[[variable]]
id = "air_temperature"
kind = "sensor"
label_en = "Air temperature"
label_zh = "空气温度"
quantity = "temperature"
unit = "Cel"
aliases = ["temp"]
refs = {temperature_refs}

[[variable]]
id = "air_relative_humidity"
kind = "sensor"
label_en = "Air relative humidity"
label_zh = "空气相对湿度"
quantity = "relative_humidity"
unit = "%"
aliases = ["humi"]
min = 0
max = 100

[[variable]]
id = "co2_concentration"
kind = "sensor"
label_en = "CO2 concentration"
label_zh = "二氧化碳浓度"
quantity = "concentration"
unit = "[ppm]"
aliases = ["co2"]
min = 0

[[variable]]
id = "canopy_area_growth"
kind = "manual"
label_en = "Canopy area growth"
label_zh = "冠层面积增长"
quantity = "area_growth_rate"
unit = "cm2/d"
method = "Canopy area from top-view images, change per day"

[[variable]]
id = "plant_height"
kind = "manual"
label_en = "Plant height"
label_zh = "株高"
quantity = "length"
unit = "cm"
method = "ruler, soil to apex"

[[variable]]
id = "light"
kind = "factor"
label_en = "Light level"
label_zh = "光照水平"
quantity = "level"
unit = "%"
min = 0
max = 100
"""
FROZEN_CATALOG = load_catalog("version = 1\n" + _ENTRIES.format(temperature_refs="[]"))
CURRENT_CATALOG = load_catalog(
    "version = 2\n"
    + _ENTRIES.format(temperature_refs='["ENVO:09200001"]')
    + '\n[unit_refs]\n"Cel" = "UO:0000027"\n'
)

PROTOCOL = make_protocol(
    question="With more light, does canopy area grow faster? 提高光照后，冠层增长是否加快？",
    cultivar="Grand Rapids",
    allocations=(
        Allocation(round=1, block=1, unit="tent-1", treatment_id="high"),
        Allocation(round=1, block=1, unit="tent-2", treatment_id="control"),
        Allocation(round=2, block=1, unit="tent-1", treatment_id="control"),
        Allocation(round=2, block=1, unit="tent-2", treatment_id="high"),
    ),
    rounds=2,
    blocks=1,
    variables=(OUTCOME, "plant_height"),
)


def read_rows(data: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(data.decode("utf-8"), newline="")))


def _fixed_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    """``new_id`` is a uuid4; a counter makes snapshot, frozen-period and intervention ids fixed."""
    counter = itertools.count(1)

    def new_id(prefix: str) -> str:
        return f"{prefix}_{next(counter):04d}"

    for module in (snap, store):
        monkeypatch.setattr(module, "new_id", new_id)


def _device(light: int, fan: int, **extra: object) -> dict:
    return {
        "light": {"on": int(light > 0), "level": light},
        "fan": {"on": int(fan > 0), "level": fan, **extra},
        "outlet": {"O1": {"on": 1}},
    }


def _sample(
    sample_id: str, at: float, sensor: dict, device: dict | None = None, **fields: object
) -> SampleRecord:
    values: dict = {
        "id": sample_id,
        "experiment_id": EXPERIMENT,
        "stage_id": STAGE,
        "device_id": "ggs-1",
        "captured_at": START + at,
        "received_at": START + at + 1.5,
        "clock_synced": True,
        "data": {"sensor": sensor, **(device or _device(70, 3))},
    }
    return SampleRecord(**{**values, **fields})


def _samples(archive: Archive) -> None:
    for record in (
        _sample("s-000", 0, {"temp": 24.25, "humi": 61.5}),
        _sample("s-060", 60, {"temp": 24.0, "humi": 61.0}),
        _sample("s-120", 120, {"temp": 24.0, "humi": 60.5, "tempLeaf": 22.75}),
        _sample("s-180", 180, {"temp": 24.0, "humi": 60.0}),
        _sample("s-300", 300, {"temp": 24.5, "humi": 59.5}, clock_synced=False),
        _sample("s-360", 360, {"temp": 24.75, "humi": 59.0}, quality="suspect"),
        _sample("s-420", 420, {"temp": 25.0, "humi": 58.5}, captured_at=None),
        _sample("s-480", 480, {"temp": 25.25, "humi": 58.0}, _device(0, 2, mode="auto")),
        _sample("s-600", 600, {"temp": 25.5, "humi": 57.5}),
    ):
        archive.append_sample(record)
    period = archive.open_frozen("temp", 24.0, START + 60)
    archive.close_frozen(period, "temp", START + 180, "value_changed")


def _measurement(record_id: str, **fields: object) -> ManualMeasurement:
    values: dict = {
        "id": record_id,
        "experiment_id": EXPERIMENT,
        "batch": "batch-1",
        "plant_id": "p-1",
        "layout_version": "layout-1",
        "measured_at": START + 100,
        "position": "tent-1",
        "method": "top-view image",
        "metric": OUTCOME,
        "value": 1.5,
        "unit": "cm2/d",
        "operator": "Alice Moreau",
    }
    return ManualMeasurement(**{**values, **fields})


def _measurements(archive: Archive) -> None:
    height = {"metric": "plant_height", "unit": "cm", "method": "ruler"}
    for record in (
        _measurement("m-plant", plant_id=PLANT),
        _measurement("m-plant-fix-1", plant_id=PLANT, value=1.25, corrects="m-plant"),
        _measurement("m-plant-fix-2", plant_id=PLANT, value=1.3, corrects="m-plant-fix-1"),
        _measurement("m-tent-2", batch="batch-2", position="tent-2", value=2.0, operator="Bo Chen"),
        _measurement(
            "m-bench", batch="batch-2", position="bench", value=12.5, operator="王芳", **height
        ),
        _measurement("m-held-before", batch="batch-h1", value=3.0),
        _measurement("m-held-before-height", batch="batch-h1", value=14.0, **height),
        _measurement("m-held-after", batch="batch-h2", position="tent-2", value=2.5),
    ):
        archive.add_measurement(record)


def _action(request_id: str, at: float, trigger: str, **fields: object) -> ActionRecord:
    values: dict = {
        "request_id": request_id,
        "state": ActionState.CONFIRMED,
        "channel": Channel.LIGHT,
        "planned_level": 40,
        "right_number": 1,
        "right_kind": RightKind.MANUAL,
        "trigger": trigger,
        "created_at": START + at,
        "sent_at": START + at + 0.25,
        "confirmed_at": START + at + 1.0,
        "confirmed_level": 40,
        "experiment_id": EXPERIMENT,
        "stage_id": STAGE,
    }
    return ActionRecord(**{**values, **fields})


def _actions(archive: Archive) -> None:
    for record in (
        _action(
            "req-manual",
            200,
            "manual: Alice Moreau dimmed it, secret-note-text",
            operator="Alice Moreau",
        ),
        _action(
            "req-irrigation",
            240,
            "planned irrigation task-water: Bo Chen watered, secret-note-text",
            channel=Channel.PUMP,
            planned_level=1,
            confirmed_level=1,
            ran_seconds=30.0,
            operator="Bo Chen",
        ),
        _action(
            "req-rule",
            270,
            "rule:light-day",
            right_kind=RightKind.STAGE,
            planned_level=70,
            confirmed_level=70,
        ),
        _action(
            "req-unknown",
            280,
            "scheduler v2",
            state=ActionState.FAILED,
            channel=Channel.FAN,
            confirmed_at=None,
            confirmed_level=None,
            error_code="device_offline",
        ),
    ):
        archive.append_action(record)


def _interventions(archive: Archive, clock: FakeClock) -> None:
    clock.advance(250)  # interventions are stamped with the clock, inside the window
    detail = {"off_confirmed": True, "request_id": "req-irrigation", "status_at": START + 245}
    archive.record_intervention(EXPERIMENT, STAGE, "unexpected_watering", detail, None)
    archive.record_intervention(EXPERIMENT, STAGE, "pruning", {"plants": 2}, "王芳")


def _corrected_after_freeze(archive: Archive, frozen_ids: set[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            m.corrects
            for m in archive.measurements(EXPERIMENT, include_corrected=True)
            if m.corrects in frozen_ids and m.id not in frozen_ids
        )
    )


def build_fixture(
    archive: Archive, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> ExportInputs:
    """Freeze round 1 of ``exp-1`` and return the inputs of its export."""
    _fixed_ids(monkeypatch)
    registry = HoldoutRegistry(archive.db, clock, outcomes=None, catalog=CURRENT_CATALOG)
    development = ["batch-1", "batch-2"]
    registry.register(PROJECT, "holdout-before", ["batch-h1"], [OUTCOME], development)
    _samples(archive)
    _measurements(archive)
    _actions(archive)
    _interventions(archive, clock)
    clock.advance(WINDOW)
    frozen = snap.freeze(
        archive,
        EXPERIMENT,
        clock,
        START,
        START + WINDOW,
        60,
        90,
        measurement_filter=registry.development_filter(PROJECT),
        declared=PROTOCOL.variables,
        catalog=FROZEN_CATALOG,
    )
    clock.advance(86_400)
    registry.register(PROJECT, "holdout-after", ["batch-h2"], [OUTCOME], development, "Bo Chen")
    late_fix = _measurement(
        "m-tent-2-late-fix",
        batch="batch-2",
        position="tent-2",
        value=2.25,
        corrects="m-tent-2",
        operator="Bo Chen",
    )
    archive.add_measurement(late_fix)
    data = read_snapshot(archive, frozen.id)
    return ExportInputs(
        data=data,
        protocol=PROTOCOL,
        round_number=1,
        catalog=CURRENT_CATALOG,
        holdouts=registry.holdouts(PROJECT),
        keep=registry.development_filter(PROJECT),
        pseudonym=Pseudonymizer(bytes(range(32))),
        licence="CC-BY-4.0",
        creator="DiAGRI test lab",
        url=None,
        corrected_after_freeze=_corrected_after_freeze(archive, {m.id for m in data.measurements}),
        software_version="0.0.0-test",
    )


def _write_golden() -> None:
    with tempfile.TemporaryDirectory() as tmp, pytest.MonkeyPatch.context() as monkeypatch:
        root = Path(tmp)
        clock = FakeClock()
        db = Database(root / "archive.db")
        try:
            archive = Archive(db, root / "archive", clock)
            files = build_dataset(build_fixture(archive, clock, monkeypatch))
        finally:
            db.close()
    GOLDEN.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (GOLDEN / name).write_bytes(content)


if __name__ == "__main__":
    _write_golden()
