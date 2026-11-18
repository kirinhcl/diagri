"""CURIEs for ontology terms: format check and the prefix table for a JSON-LD context."""

import re
from collections.abc import Iterable, Mapping
from types import MappingProxyType

_OBO = "http://purl.obolibrary.org/obo/"
PREFIXES: Mapping[str, str] = MappingProxyType(
    {name: f"{_OBO}{name}_" for name in ("PECO", "ENVO", "AGRO", "PATO", "UO", "NCBITaxon")}
)

_CURIE = re.compile(r"(?P<prefix>[A-Za-z][A-Za-z0-9_]*):(?P<local>[A-Za-z0-9_.-]+)")
_CROP_ONTOLOGY = re.compile(r"CO_[0-9]+")
_TAXON = re.compile(r"NCBITaxon:[0-9]+")
MAX_CULTIVAR_LENGTH = 200


def crop_ontology_base(prefix: str) -> str:
    # Pattern from the Crop Ontology API help, "get the owl version of a term":
    # https://cropontology.org/api_help -> https://cropontology.org/rdf/{term_id},
    # e.g. https://cropontology.org/rdf/CO_321:0001199. The term id is the CURIE
    # itself, so the base ends with "<prefix>:".
    return f"https://cropontology.org/rdf/{prefix}:"


def curie_prefix(curie: str) -> str | None:
    match = _CURIE.fullmatch(curie)
    if match is None:
        return None
    prefix = match["prefix"]
    if prefix in PREFIXES or _CROP_ONTOLOGY.fullmatch(prefix):
        return prefix
    return None


def context_prefixes(curies: Iterable[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    for curie in curies:
        prefix = curie_prefix(curie)
        if prefix is not None:
            found[prefix] = PREFIXES.get(prefix) or crop_ontology_base(prefix)
    return found


def taxon_problems(crop_taxon: str, cultivar: str) -> list[str]:
    """What is wrong with a protocol's crop species and cultivar; empty when both are fine."""
    problems: list[str] = []
    if _TAXON.fullmatch(crop_taxon) is None:
        if crop_taxon:
            problems.append(f"crop_taxon {crop_taxon} is not NCBITaxon:<number>")
        else:
            problems.append(
                "name the crop species as an NCBI Taxonomy ID: crop_taxon = NCBITaxon:<number>"
            )
    if len(cultivar) > MAX_CULTIVAR_LENGTH:
        problems.append(f"cultivar is longer than {MAX_CULTIVAR_LENGTH} characters")
    return problems
