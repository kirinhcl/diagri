import json
import tomllib
from pathlib import Path

import growbridge.vocab
from growbridge.vocab import packaged_catalog

LOCK = Path(growbridge.vocab.__file__).with_name("catalog.lock.json")
PYPROJECT = Path(__file__).parents[2] / "pyproject.toml"


def test_catalog_version_is_locked():
    lock, catalog = json.loads(LOCK.read_text()), packaged_catalog()
    assert lock["versions"].get(str(catalog.version)) == catalog.digest, (
        "catalog.toml changed: bump `version` and add "
        f'"{catalog.version}": "{catalog.digest}" to "versions" in catalog.lock.json'
    )
    assert len(set(lock["versions"].values())) == len(lock["versions"])


def test_defining_fields_never_change():
    entries, catalog = json.loads(LOCK.read_text())["entries"], packaged_catalog()
    for variable in catalog.variables:
        expected = variable.defining_digest()
        assert entries.get(variable.id) == expected, (
            f'{variable.id}: add "{variable.id}": "{expected}" to "entries" if it is new; '
            "an existing entry's id, kind, quantity, unit, method, min and max never change"
        )
    assert set(entries) <= {v.id for v in catalog.variables}, "entries are never removed"


def test_catalog_ships_with_the_package():
    config = tomllib.loads(PYPROJECT.read_text())
    assert "vocab/*.toml" in config["tool"]["setuptools"]["package-data"]["growbridge"]
