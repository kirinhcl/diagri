import pytest

from growbridge.archive import snapshot as snap
from growbridge.archive.models import ManualMeasurement, SampleRecord
from growbridge.dataset.source import ExportRefused, SnapshotData, read_snapshot
from growbridge.sim.clock import START
from growbridge.vocab import packaged_catalog


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
                data={"sensor": {"temperature": 24.0}},
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


def test_reads_a_frozen_snapshot(archive, frozen):
    data = read_snapshot(archive, frozen.id)

    assert isinstance(data, SnapshotData)
    assert data.snapshot.id == frozen.id
    assert len(data.samples) == 10 and data.samples_untrusted == ()
    assert [m.id for m in data.measurements] == ["m1"]
    assert data.catalog_record["version"] == packaged_catalog().version  # what freeze recorded
    assert data.manifest["files"] == frozen.files
    assert data.frozen_periods == () and data.interventions == ()


def test_unknown_snapshot_is_refused(archive):
    with pytest.raises(ExportRefused, match="snap-missing"):
        read_snapshot(archive, "snap-missing")


def test_tampered_snapshot_is_refused(archive, frozen):
    path = archive.root / "snapshots" / frozen.id / "samples.jsonl"
    with path.open("ab") as handle:
        handle.write(b" ")

    with pytest.raises(ExportRefused, match="verif"):
        read_snapshot(archive, frozen.id)


def test_snapshot_without_catalog_is_refused(archive, frozen, monkeypatch):
    files = {k: v for k, v in frozen.files.items() if k != snap.CATALOG_FILE}
    monkeypatch.setattr(archive, "snapshot", lambda _id: frozen.model_copy(update={"files": files}))
    monkeypatch.setattr(snap, "verify", lambda *_: True)

    with pytest.raises(ExportRefused, match="catalog.json"):
        read_snapshot(archive, frozen.id)
