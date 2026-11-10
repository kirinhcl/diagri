import json

import pytest

from growbridge.archive import snapshot as snap
from growbridge.archive.export import export_miappe
from growbridge.archive.models import ManualMeasurement, SampleRecord
from growbridge.sim.clock import START
from growbridge.sim.fixtures import make_protocol

LICENCE = "CC-BY-4.0"
DOI = "doi:10.0000/example"


@pytest.fixture
def frozen(archive, clock):
    for i in range(10):
        archive.append_sample(
            SampleRecord(
                id=f"d:{i}",
                experiment_id="exp-1",
                stage_id="veg",
                device_id="d",
                captured_at=START + i * 60,
                received_at=START + i * 60,
                clock_synced=True,
                data={"temperature": 24.0, "humidity": 60.0},
            )
        )
    archive.add_measurement(
        ManualMeasurement(
            id="m1",
            experiment_id="exp-1",
            batch="batch-1",
            plant_id="p1",
            layout_version="L1",
            measured_at=START + 5,
            position="top",
            method="ruler",
            metric="height",
            value=3.0,
            unit="cm",
            operator="alice",
        )
    )
    return snap.freeze(archive, "exp-1", clock, START, START + 600, 60, 90)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_export_writes_metadata_with_identifier_and_licence(archive, frozen, tmp_path):
    out = export_miappe(archive, frozen, make_protocol(), tmp_path / "out", LICENCE, DOI)

    meta = read(out)
    assert out.parent == tmp_path / "out"
    assert meta["identifier"] == DOI
    assert meta["licence"] == LICENCE
    assert meta["study"]["question"].startswith("提高光照")
    assert meta["study"]["protocol_version"] == 1


def test_export_lists_units_variables_and_files(archive, frozen, tmp_path):
    meta = read(export_miappe(archive, frozen, make_protocol(), tmp_path / "o", LICENCE, DOI))

    assert {u["unit"] for u in meta["experimental_units"]} == {"tent-1"}
    assert len(meta["experimental_units"]) == 4
    height = [v for v in meta["observed_variables"] if v["name"] == "height"]
    assert height == [{"name": "height", "unit": "cm", "method": "ruler", "origin": "manual"}]
    sensors = {v["name"] for v in meta["observed_variables"] if v["origin"] == "sensor"}
    assert sensors == {"humidity", "temperature"}
    assert meta["data_files"] == frozen.files
    assert meta["snapshot"]["complete"] is True
    assert meta["snapshot"]["id"] == frozen.id


def test_export_refuses_a_snapshot_whose_files_were_modified(archive, frozen, tmp_path):
    path = archive.root / "snapshots" / frozen.id / "samples.jsonl"
    path.write_text(path.read_text().replace("24.0", "30.0"))

    with pytest.raises(ValueError):
        export_miappe(archive, frozen, make_protocol(), tmp_path / "o", LICENCE, DOI)


@pytest.mark.parametrize(("licence", "identifier"), [("", DOI), (LICENCE, " ")])
def test_export_requires_licence_and_identifier(archive, frozen, tmp_path, licence, identifier):
    with pytest.raises(ValueError):
        export_miappe(archive, frozen, make_protocol(), tmp_path / "o", licence, identifier)
