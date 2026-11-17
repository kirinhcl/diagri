import pytest

from growbridge.control.device import SENSORS
from growbridge.vocab import CatalogError, load_catalog, packaged_catalog

BASE = """version = 1
[[variable]]
id = "leaf_count"
kind = "manual"
label_en = "Leaf count"
label_zh = "叶片数"
quantity = "count"
unit = "1"
method = "counted by hand"
min = 0
"""
ENTRY = BASE.removeprefix("version = 1\n")
SENSOR = """
[[variable]]
id = "leaf_wetness"
kind = "sensor"
label_en = "Leaf wetness"
label_zh = "叶面湿润度"
quantity = "level"
unit = "%"
aliases = ["wet"]
"""
BROKEN = {  # case -> (text, a name the message must contain)
    "duplicate id": (BASE + ENTRY, "leaf_count"),
    "bad id": (BASE.replace('"leaf_count"', '"Leaf-Count"'), "Leaf-Count"),
    "unknown kind": (BASE.replace('"manual"', '"derived"'), "leaf_count"),
    "unknown quantity": (BASE.replace('"count"', '"amount"'), "leaf_count"),
    "manual without method": (BASE.replace('method = "counted by hand"\n', ""), "leaf_count"),
    "alias on a manual entry": (BASE + 'aliases = ["leaves"]\n', "leaf_count"),
    "min above max": (BASE + "max = -1\n", "leaf_count"),
    "dangling replaced_by": (BASE + 'deprecated = true\nreplaced_by = "gone"\n', "leaf_count"),
    "alias equals an id": (BASE + SENSOR.replace('["wet"]', '["leaf_count"]'), "leaf_count"),
    "duplicate alias": (BASE + SENSOR + SENSOR.replace("leaf_wetness", "leaf_wet_2"), "wet"),
}


def test_packaged_catalog_loads():
    catalog = packaged_catalog()
    assert catalog.version >= 1
    assert len(catalog.digest) == 64


def test_every_device_sensor_resolves_with_its_unit():
    catalog = packaged_catalog()
    for key, unit in SENSORS.items():
        variable = catalog.resolve(key)
        assert variable is not None and variable.kind == "sensor", key
        assert catalog.unit_aliases.get(unit, unit) == variable.unit, key


def test_fixture_names_are_catalogued():
    catalog = packaged_catalog()
    assert catalog.get("canopy_area_growth").kind == "manual"
    assert catalog.get("canopy_area_growth").unit == "cm2/d"
    assert catalog.get("light").kind == "factor"


def test_resolve_is_exact():
    catalog = packaged_catalog()
    assert catalog.resolve("temp").id == "air_temperature"
    assert catalog.resolve("air_temperature").id == "air_temperature"
    for near in ("Temp", "temp ", "air-temperature", ""):
        assert catalog.resolve(near) is None
    assert catalog.get("temp") is None  # get never follows an alias


def test_same_compares_ids_and_unresolved_strings():
    catalog = packaged_catalog()
    assert catalog.same("temp", "air_temperature")
    assert catalog.same("heigth", "heigth")
    assert not catalog.same("heigth", "height")
    assert not catalog.same("temp", "heigth")


def test_deprecated_entry_resolves_to_itself():
    old = ENTRY.replace("leaf_count", "leaf_number")
    catalog = load_catalog(BASE + old + 'deprecated = true\nreplaced_by = "leaf_count"\n')
    assert catalog.resolve("leaf_number").id == "leaf_number"


@pytest.mark.parametrize("case", sorted(BROKEN))
def test_broken_catalog_names_the_entry(case):
    text, name = BROKEN[case]
    with pytest.raises(CatalogError, match=name):
        load_catalog(text)


def test_text_that_is_not_toml_is_refused():
    with pytest.raises(CatalogError):
        load_catalog("version = [")
