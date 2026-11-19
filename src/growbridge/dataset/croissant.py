"""``croissant.json``: MLCommons Croissant 1.1 metadata describing the exported tables."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from growbridge.dataset.csvfmt import format_time
from growbridge.dataset.schema import TABLES, Column, Table, table
from growbridge.vocab.curie import context_prefixes

if TYPE_CHECKING:
    from growbridge.dataset.build import ExportInputs

CONFORMS_TO = "http://mlcommons.org/croissant/1.1"
PROV = "http://www.w3.org/ns/prov#"
SOFTWARE = "growbridge"
COMMAND = "export-dataset"
FACILITY = "controlled-environment grow tent"  # text only: no confirmed term yet
CSV = "text/csv"

# The @context mlcroissant 1.1.1 writes for Croissant 1.1 (``core/rdf.py: make_context``), which
# is also what the 1.1 example datasets use. The spec's Appendix 1 lists a variant that maps
# ``value`` to ``cr:value``; that would turn PropertyValue ``value`` into a Croissant term.
_STANDARD_CONTEXT: Mapping[str, Any] = {
    "@language": "en",
    "@vocab": "https://schema.org/",
    "arrayShape": "cr:arrayShape",
    "citeAs": "cr:citeAs",
    "column": "cr:column",
    "conformsTo": "dct:conformsTo",
    "containedIn": "cr:containedIn",
    "cr": "http://mlcommons.org/croissant/",
    "rai": "http://mlcommons.org/croissant/RAI/",
    "data": {"@id": "cr:data", "@type": "@json"},
    "dataType": {"@id": "cr:dataType", "@type": "@vocab"},
    "dct": "http://purl.org/dc/terms/",
    "description": {"@container": "@language"},
    "equivalentProperty": "cr:equivalentProperty",
    "examples": {"@id": "cr:examples", "@type": "@json"},
    "extract": "cr:extract",
    "field": "cr:field",
    "fileProperty": "cr:fileProperty",
    "fileObject": "cr:fileObject",
    "fileSet": "cr:fileSet",
    "format": "cr:format",
    "includes": "cr:includes",
    "isArray": "cr:isArray",
    "isLiveDataset": "cr:isLiveDataset",
    "jsonPath": "cr:jsonPath",
    "key": "cr:key",
    "md5": "cr:md5",
    "name": {"@container": "@language"},
    "parentField": "cr:parentField",
    "path": "cr:path",
    "recordSet": "cr:recordSet",
    "references": "cr:references",
    "regex": "cr:regex",
    "repeated": "cr:repeated",
    "replace": "cr:replace",
    "samplingRate": "cr:samplingRate",
    "sc": "https://schema.org/",
    "separator": "cr:separator",
    "source": "cr:source",
    "subField": "cr:subField",
    "transform": "cr:transform",
}
_GEN_DELIMS = (":", "/", "?", "#", "[", "]", "@")


def context_entry(base: str) -> str | dict[str, Any]:
    """A prefix's @context entry. JSON-LD 1.1 uses a plain term as a prefix only when its IRI
    ends in a gen-delim; OBO bases end in ``_``, so they must say ``@prefix`` outright."""
    if base.endswith(_GEN_DELIMS):
        return base
    return {"@id": base, "@prefix": True}


def _curies_in_data(tables: Mapping[str, bytes]) -> list[str]:
    rows = csv.DictReader(io.StringIO(tables["variables.csv"].decode("utf-8"), newline=""))
    found: list[str] = []
    for row in rows:
        found.extend(row["refs"].split())
        if row["unit_uo"]:
            found.append(row["unit_uo"])
    return found


def _context(curies: Iterable[str]) -> dict[str, Any]:
    prefixes = {name: context_entry(base) for name, base in context_prefixes(curies).items()}
    return {**_STANDARD_CONTEXT, "prov": PROV, **prefixes}


def _record_set_id(file: str) -> str:
    return file.removesuffix(".csv")


def _field(owner: Table, column: Column) -> dict[str, Any]:
    field: dict[str, Any] = {
        "@type": "cr:Field",
        "@id": f"{_record_set_id(owner.file)}/{column.name}",
        "name": column.name,
        "description": column.description,
        "dataType": f"sc:{column.data_type}",
        "source": {"fileObject": {"@id": owner.file}, "extract": {"column": column.name}},
    }
    if not column.references:
        return field
    file, _, name = column.references.rpartition(".")
    if table(file).sort_key == (name,):
        return {**field, "references": {"field": {"@id": f"{_record_set_id(file)}/{name}"}}}
    # Croissant reads ``references`` as a join on the target's key; joining on a column that
    # repeats (treatments.csv has a row per factor) would multiply the records.
    return {
        **field,
        "description": f"{column.description} Takes its values from `{name}` in {file}.",
    }


def _record_set(owner: Table) -> dict[str, Any]:
    return {
        "@type": "cr:RecordSet",
        "@id": _record_set_id(owner.file),
        "name": _record_set_id(owner.file),
        "description": owner.description,
        "field": [_field(owner, column) for column in owner.columns],
    }


def _file_object(file: str, content: bytes) -> dict[str, Any]:
    return {
        "@type": "cr:FileObject",
        "@id": file,
        "name": file,
        "contentUrl": file,
        "encodingFormat": CSV,
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _property(name: str, value: object) -> dict[str, Any]:
    return {"@type": "sc:PropertyValue", "name": name, "value": value}


def _properties(inputs: ExportInputs, counts: Mapping[str, int]) -> list[dict[str, Any]]:
    snapshot = inputs.data.snapshot
    gaps = [[format_time(start), format_time(end)] for start, end in snapshot.gaps]
    return [
        _property("cultivar", inputs.protocol.cultivar),
        _property("facility_type", FACILITY),
        _property("snapshot_catalog_version", inputs.data.catalog_record["version"]),
        _property("current_catalog_version", inputs.catalog.version),
        _property("coverage", snapshot.coverage),
        _property("gaps", json.dumps(gaps, separators=(",", ":"))),
        *(_property(name, value) for name, value in counts.items()),
        _property(
            "corrected_after_freeze_ids", " ".join(sorted(set(inputs.corrected_after_freeze)))
        ),
    ]


def _provenance(inputs: ExportInputs) -> dict[str, Any]:
    snapshot = inputs.data.snapshot
    return {
        "prov:wasDerivedFrom": {
            "@id": f"urn:diagri:snapshot:{snapshot.id}",
            "@type": "prov:Entity",
            "identifier": snapshot.id,
            "description": "DiAGRI snapshot; sha256 is the digest of its manifest.json.",
            "sha256": snapshot.manifest_sha256,
        },
        "prov:wasGeneratedBy": {
            "@type": "prov:Activity",
            "prov:label": COMMAND,
            "prov:wasAssociatedWith": {
                "@type": ["prov:SoftwareAgent", "sc:SoftwareApplication"],
                "name": SOFTWARE,
                "softwareVersion": inputs.software_version,
            },
        },
    }


def croissant(
    tables: Mapping[str, bytes], inputs: ExportInputs, counts: Mapping[str, int]
) -> dict[str, Any]:
    """The metadata document; ``tables`` maps each CSV file name to its exact bytes."""
    snapshot = inputs.data.snapshot
    protocol = inputs.protocol
    published = datetime.fromtimestamp(snapshot.created_at, UTC).date().isoformat()
    return {
        "@context": _context([*_curies_in_data(tables), protocol.crop_taxon]),
        "@type": "sc:Dataset",
        "conformsTo": CONFORMS_TO,
        "name": f"diagri-{snapshot.id}",
        "description": f"Question: {protocol.question}\nHypothesis: {protocol.hypothesis}",
        "license": inputs.licence,
        "creator": {"@type": "sc:Organization", "name": inputs.creator},
        "url": inputs.url or f"urn:diagri:snapshot:{snapshot.id}",
        "datePublished": published,
        "version": str(snapshot.version),
        "about": {"@id": protocol.crop_taxon},
        "distribution": [_file_object(t.file, tables[t.file]) for t in TABLES],
        "recordSet": [_record_set(t) for t in TABLES],
        **_provenance(inputs),
        "additionalProperty": _properties(inputs, counts),
    }
