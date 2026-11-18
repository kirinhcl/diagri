import json

import pytest

from growbridge.vocab import (
    CatalogError,
    context_prefixes,
    load_catalog,
    packaged_catalog,
    packaged_text,
)


def with_first_refs(value: str) -> str:
    return packaged_text().replace("refs = []", f"refs = {value}", 1)  # air_temperature


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
    cat = load_catalog(packaged_text() + '\n[unit_refs]\n"Cel" = "UO:0000027"\n')
    assert dict(cat.unit_refs) == {"Cel": "UO:0000027"}


def test_unit_ref_for_an_unused_unit_is_refused():
    with pytest.raises(CatalogError, match="unit_refs: K"):
        load_catalog(packaged_text() + '\n[unit_refs]\n"K" = "UO:0000012"\n')


def test_unit_ref_must_be_a_uo_term():
    with pytest.raises(CatalogError, match="Cel"):
        load_catalog(packaged_text() + '\n[unit_refs]\n"Cel" = "ENVO:09200001"\n')


def test_unit_refs_must_map_text_to_text():
    with pytest.raises(CatalogError, match="unit_refs"):
        load_catalog(packaged_text() + '\n[unit_refs]\n"Cel" = 5\n')


def test_packaged_catalog_is_unchanged():
    assert packaged_catalog().version == 1
    assert dict(packaged_catalog().unit_refs) == {}


def test_context_prefixes_cover_what_is_used():
    found = context_prefixes(["ENVO:1", "CO_331:2", "ENVO:3"])
    assert set(found) == {"ENVO", "CO_331"}
    assert found["ENVO"] == "http://purl.obolibrary.org/obo/ENVO_"
    assert found["CO_331"].startswith("http") and "CO_331" in found["CO_331"]
