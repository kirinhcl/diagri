"""A correction replaces a measurement of its own experiment, never one of another experiment:
otherwise one project's record could hide another project's measurement and invalidate the
snapshots built on it."""

import pytest

from growbridge.archive.models import ManualMeasurement


def row(ident: str, experiment_id: str, **fields) -> ManualMeasurement:
    values = {
        "id": ident,
        "experiment_id": experiment_id,
        "batch": "batch-1",
        "plant_id": "p1",
        "layout_version": "v1",
        "measured_at": 1.0,
        "position": "tent-1",
        "method": "ruler",
        "metric": "canopy_area_growth",
        "value": 1.0,
        "unit": "cm2",
        "operator": "op-1",
    }
    return ManualMeasurement(**{**values, **fields})


def test_correction_must_stay_in_experiment(archive):
    archive.add_measurement(row("a1", "experiment-a"))

    with pytest.raises(ValueError, match="another experiment"):
        archive.add_measurement(row("b1", "experiment-b", corrects="a1"))

    assert [m.id for m in archive.measurements("experiment-a")] == ["a1"]
    assert archive.measurements("experiment-b") == ()


def test_correction_within_the_experiment_still_replaces(archive):
    archive.add_measurement(row("a1", "experiment-a"))

    archive.add_measurement(row("a2", "experiment-a", corrects="a1", value=2.0))

    assert [m.id for m in archive.measurements("experiment-a")] == ["a2"]
