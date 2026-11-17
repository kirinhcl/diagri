from vocab_support import WITH_OLD

from growbridge.archive.models import ManualMeasurement
from growbridge.vocab import load_catalog, packaged_text
from growbridge.vocab.checks import check_measurement

FIELDS = dict(
    id="m-2",
    experiment_id="e1",
    batch="b1",
    plant_id="p1",
    layout_version="v1",
    measured_at=1.0,
    position="tent-1",
    method="m",
    operator="op",
)
DECLARED = frozenset({"canopy_area_growth", "canopy_growth_old", "light"})
BOUNDED = """
[[variable]]
id = "leaf_cover"
kind = "manual"
label_en = "Leaf cover"
label_zh = "叶面覆盖"
quantity = "level"
unit = "%"
method = "grid count"
min = 0
max = 100
"""


def record(metric, unit, value):
    return ManualMeasurement(**FIELDS, metric=metric, unit=unit, value=value)


def test_declared_manual_metric_in_its_unit_passes():
    assert check_measurement(record("canopy_area_growth", "cm2/d", 3.0), WITH_OLD, DECLARED) == []


def test_experiment_without_declared_variables_is_refused():
    (problem,) = check_measurement(
        record("canopy_area_growth", "cm2/d", 3.0), WITH_OLD, frozenset()
    )
    assert "declares no variables" in problem
    # A new version only applies once a new round runs the experiment under it (Ruling 5).
    assert "protocol version that declares them" in problem and "new round" in problem


def test_near_names_are_refused_with_the_declared_ids():  # Review Focus 1
    for near in ("canopy_area_growth ", "Canopy_area_growth", "canopy-area-growth"):
        (problem,) = check_measurement(record(near, "cm2/d", 3.0), WITH_OLD, DECLARED)
        assert "canopy_area_growth" in problem and "light" in problem


def test_kind_unit_and_bounds_are_reported_together():
    problems = check_measurement(record("light", "lux", -5.0), WITH_OLD, DECLARED)
    assert len(problems) == 3
    assert any("%" in p for p in problems)


def test_bounds_are_inclusive():  # Review Focus 4
    bounded = load_catalog(packaged_text() + BOUNDED)
    for value in (0.0, 100.0):
        assert (
            check_measurement(record("leaf_cover", "%", value), bounded, frozenset({"leaf_cover"}))
            == []
        )


def test_declared_deprecated_variable_is_accepted():
    assert check_measurement(record("canopy_growth_old", "cm2/d", 1.0), WITH_OLD, DECLARED) == []


def test_correction_may_change_the_metric():
    fixed = record("canopy_area_growth", "cm2/d", 2.0).model_copy(update={"corrects": "m-1"})
    assert check_measurement(fixed, WITH_OLD, DECLARED) == []
