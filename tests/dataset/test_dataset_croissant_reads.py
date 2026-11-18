"""The exported dataset is read back by MLCommons' own Croissant reader, not only by our tests."""

import mlcroissant as mlc
import rdflib
from dataset_support import build_fixture, read_rows

from growbridge.dataset.build import build_dataset
from growbridge.dataset.schema import TABLES

SCHEMA_ABOUT = rdflib.URIRef("https://schema.org/about")


def _write(files, directory):
    for name, content in files.items():
        (directory / name).write_bytes(content)
    return directory / "croissant.json"


def test_mlcroissant_reads_every_record_set(archive, clock, monkeypatch, tmp_path):
    files = build_dataset(build_fixture(archive, clock, monkeypatch))
    dataset = mlc.Dataset(jsonld=_write(files, tmp_path))

    read = {rs.uuid for rs in dataset.metadata.record_sets}
    assert read == {t.file.removesuffix(".csv") for t in TABLES}
    for t in TABLES:
        records = list(dataset.records(record_set=t.file.removesuffix(".csv")))
        assert len(records) == len(read_rows(files[t.file])), t.file


def test_crop_taxon_expands_to_its_obo_iri(archive, clock, monkeypatch, tmp_path):
    inputs = build_fixture(archive, clock, monkeypatch)
    graph = rdflib.Graph().parse(_write(build_dataset(inputs), tmp_path), format="json-ld")

    number = inputs.protocol.crop_taxon.removeprefix("NCBITaxon:")
    about = rdflib.URIRef(f"http://purl.obolibrary.org/obo/NCBITaxon_{number}")
    assert (None, SCHEMA_ABOUT, about) in graph
