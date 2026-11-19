import json

import pytest
from vocab_support import bare_packaged_text

from growbridge.vocab import (
    CatalogError,
    context_prefixes,
    load_catalog,
    packaged_catalog,
)

# Confirmed by the researcher one by one on 2026-11-19, from the candidates in
# docs/superpowers/notes/2026-11-18-ontology-candidates.md. Change a term only the same way.
CONFIRMED_REFS = {
    "air_temperature": ("ENVO:09200001",),
    "air_relative_humidity": ("AGRO:00000637",),
    "vapour_pressure_deficit": (),
    "co2_concentration": ("ENVO:04000004",),
    "photosynthetic_photon_flux_density": ("ENVO:06105204",),
    "soil_temperature": ("ENVO:09200012",),
    "canopy_area_growth": (),
    "light": ("PECO:0007224",),
}
CONFIRMED_UNIT_REFS = {
    "Cel": "UO:0000027",
    "%": "UO:0000187",
    "[ppm]": "UO:0000169",
    "umol/m2/s": "UO:0000160",
}


def with_first_refs(value: str) -> str:
    return bare_packaged_text().replace("refs = []", f"refs = {value}", 1)  # air_temperature


def test_known_prefixes_load():
    cat = load_catalog(with_first_refs('["ENVO:09200001", "CO_331:0000192", "PATO:0000146"]'))
    assert cat.get("air_temperature").refs == ("ENVO:09200001", "CO_331:0000192", "PATO:0000146")


@pytest.mark.parametrize(
    "ref", ["FOO:1", "air temperature", "ENVO:", ":123", "CO_:1", "CO_x1:1", "ENVO:1\n"]
)
def test_bad_ref_is_refused(ref):
    with pytest.raises(CatalogError, match="air_temperature"):
        load_catalog(with_first_refs(f"[{json.dumps(ref)}]"))


def test_unit_refs_load():
    cat = load_catalog(bare_packaged_text() + '\n[unit_refs]\n"Cel" = "UO:0000027"\n')
    assert dict(cat.unit_refs) == {"Cel": "UO:0000027"}


def test_unit_ref_for_an_unused_unit_is_refused():
    with pytest.raises(CatalogError, match="unit_refs: K"):
        load_catalog(bare_packaged_text() + '\n[unit_refs]\n"K" = "UO:0000012"\n')


def test_unit_ref_must_be_a_uo_term():
    with pytest.raises(CatalogError, match="Cel"):
        load_catalog(bare_packaged_text() + '\n[unit_refs]\n"Cel" = "ENVO:09200001"\n')


def test_unit_refs_must_map_text_to_text():
    with pytest.raises(CatalogError, match="unit_refs"):
        load_catalog(bare_packaged_text() + '\n[unit_refs]\n"Cel" = 5\n')


def test_packaged_catalog_carries_the_confirmed_terms():
    catalog = packaged_catalog()
    assert catalog.version == 2
    assert {v.id: v.refs for v in catalog.variables} == CONFIRMED_REFS
    assert dict(catalog.unit_refs) == CONFIRMED_UNIT_REFS


def test_bare_packaged_text_has_no_terms():
    bare = load_catalog(bare_packaged_text())
    assert [v.id for v in bare.variables] == [v.id for v in packaged_catalog().variables]
    assert all(v.refs == () for v in bare.variables)
    assert dict(bare.unit_refs) == {}


def test_context_prefixes_cover_what_is_used():
    found = context_prefixes(["ENVO:1", "CO_331:2", "ENVO:3"])
    assert set(found) == {"ENVO", "CO_331"}
    assert found["ENVO"] == "http://purl.obolibrary.org/obo/ENVO_"
    assert found["CO_331"].startswith("http") and "CO_331" in found["CO_331"]
