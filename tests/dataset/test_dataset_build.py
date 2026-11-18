import dataclasses
import hashlib
import json

import pytest
from dataset_support import (
    CURRENT_CATALOG,
    GOLDEN,
    HELD_RECORD_IDS,
    OPERATOR_NAMES,
    PROJECT,
    build_fixture,
    read_rows,
)
from vocab_support import TEST_CATALOG

from growbridge.dataset.build import COUNT_NAMES, build_dataset
from growbridge.dataset.croissant import context_entry
from growbridge.dataset.schema import TABLES
from growbridge.dataset.source import ExportRefused
from growbridge.research.holdout import HoldoutRegistry
from growbridge.vocab.curie import PREFIXES, crop_ontology_base


def test_golden(archive, clock, monkeypatch):
    files = build_dataset(build_fixture(archive, clock, monkeypatch))
    assert sorted(files) == sorted([t.file for t in TABLES] + ["croissant.json"])
    for name, content in files.items():
        assert content == (GOLDEN / name).read_bytes(), name


def test_build_is_deterministic(archive, clock, monkeypatch):
    inputs = build_fixture(archive, clock, monkeypatch)
    assert build_dataset(inputs) == build_dataset(inputs)


def test_references_hold(archive, clock, monkeypatch):
    files = build_dataset(build_fixture(archive, clock, monkeypatch))
    ids = {r["variable_id"] for r in read_rows(files["variables.csv"])}
    for t in TABLES:
        for c in t.columns:
            if c.references == "variables.csv.variable_id":
                assert {r[c.name] for r in read_rows(files[t.file])} - {""} <= ids, (t.file, c.name)


def test_every_schema_reference_holds(archive, clock, monkeypatch):
    files = build_dataset(build_fixture(archive, clock, monkeypatch))
    for t in TABLES:
        for c in t.columns:
            if c.references:
                file, _, name = c.references.rpartition(".")
                targets = {r[name] for r in read_rows(files[file])}
                assert {r[c.name] for r in read_rows(files[t.file])} - {""} <= targets, c


def test_croissant_references_only_a_key(archive, clock, monkeypatch):
    # Croissant joins on ``references``; treatments.csv repeats treatment_id once per factor.
    meta = json.loads(build_dataset(build_fixture(archive, clock, monkeypatch))["croissant.json"])
    fields = {f["@id"]: f for rs in meta["recordSet"] for f in rs["field"]}
    assert fields["measurements/variable_id"]["references"] == {
        "field": {"@id": "variables/variable_id"}
    }
    assert "references" not in fields["units/treatment_id"]
    assert "treatment_id` in treatments.csv" in fields["units/treatment_id"]["description"]
    assert "(`round`, `unit`) in units.csv" in fields["measurements/unit"]["description"]


def test_holdout_with_an_unresolved_outcome_hides_its_whole_batch(archive, clock, monkeypatch):
    inputs = build_fixture(archive, clock, monkeypatch)
    before = read_rows(build_dataset(inputs)["measurements.csv"])
    assert any(r["batch"] == "batch-2" for r in before)
    # "yield_g" resolved when registered (TEST_CATALOG); the export's catalog lacks it, as a
    # holdout registered before outcome fields had to resolve may hold such a name.
    legacy = HoldoutRegistry(archive.db, clock, outcomes=None, catalog=TEST_CATALOG)
    legacy.register(PROJECT, "holdout-legacy", ["batch-2"], ["yield_g"], ["batch-1", "batch-3"])
    current = HoldoutRegistry(archive.db, clock, outcomes=None, catalog=CURRENT_CATALOG)

    files = build_dataset(
        dataclasses.replace(
            inputs,
            holdouts=current.holdouts(PROJECT),
            keep=current.development_filter(PROJECT),
        )
    )

    withheld = read_rows(files["withheld.csv"])
    assert {"holdout_id": "holdout-legacy", "batch": "batch-2", "variable_id": "*"} in withheld
    assert "*" not in {r["variable_id"] for r in read_rows(files["variables.csv"])}
    assert all(r["batch"] != "batch-2" for r in read_rows(files["measurements.csv"]))


def test_no_names_or_notes_leave(archive, clock, monkeypatch):
    blob = b"".join(build_dataset(build_fixture(archive, clock, monkeypatch)).values())
    for secret in OPERATOR_NAMES + ["secret-note-text"]:
        assert secret.encode() not in blob


def test_holdouts_before_and_after_freeze(archive, clock, monkeypatch):
    inputs = build_fixture(archive, clock, monkeypatch)
    files = build_dataset(inputs)
    meta = json.loads(files["croissant.json"])
    counts = {p["name"]: p["value"] for p in meta["additionalProperty"]}
    assert counts["excluded_at_freeze"] == inputs.data.manifest["measurements_excluded"] > 0
    assert counts["withheld_at_export"] > 0
    withheld = {(r["holdout_id"], r["batch"]) for r in read_rows(files["withheld.csv"])}
    assert {(h.holdout_id, b) for h in inputs.holdouts for b in h.batch_ids} <= withheld
    measured = {r["record_id"] for r in read_rows(files["measurements.csv"])}
    assert measured.isdisjoint(HELD_RECORD_IDS)


def test_croissant_required_fields(archive, clock, monkeypatch):
    inputs = build_fixture(archive, clock, monkeypatch)
    files = build_dataset(inputs)
    meta = json.loads(files["croissant.json"])
    assert meta["conformsTo"] == "http://mlcommons.org/croissant/1.1"
    for key in (
        "name",
        "description",
        "license",
        "url",
        "creator",
        "datePublished",
        "distribution",
    ):
        assert meta[key]
    assert meta["about"] == {"@id": inputs.protocol.crop_taxon}
    for obj in meta["distribution"]:
        assert obj["sha256"] == hashlib.sha256(files[obj["contentUrl"]]).hexdigest()


def test_every_count_is_reported(archive, clock, monkeypatch):
    meta = json.loads(build_dataset(build_fixture(archive, clock, monkeypatch))["croissant.json"])
    names = [p["name"] for p in meta["additionalProperty"]]
    assert len(names) == len(set(names))
    assert set(COUNT_NAMES) <= set(names)


def test_given_url_replaces_the_snapshot_urn(archive, clock, monkeypatch):
    inputs = dataclasses.replace(
        build_fixture(archive, clock, monkeypatch), url="https://example.org/d"
    )
    assert json.loads(build_dataset(inputs)["croissant.json"])["url"] == "https://example.org/d"


def test_obo_prefixes_are_declared_as_prefixes():
    # OBO bases end in "_", which JSON-LD 1.1 does not take as a prefix unless told to.
    assert context_entry(PREFIXES["NCBITaxon"]) == {"@id": PREFIXES["NCBITaxon"], "@prefix": True}
    assert context_entry(crop_ontology_base("CO_331")) == crop_ontology_base("CO_331")


@pytest.mark.parametrize("change", [{"licence": " "}, {"creator": ""}])
def test_blank_licence_or_creator_is_refused(archive, clock, monkeypatch, change):
    with pytest.raises(ExportRefused):
        build_dataset(dataclasses.replace(build_fixture(archive, clock, monkeypatch), **change))


def test_protocol_without_crop_taxon_is_refused(archive, clock, monkeypatch):
    inputs = build_fixture(archive, clock, monkeypatch)
    with pytest.raises(ExportRefused, match="crop_taxon"):
        build_dataset(
            dataclasses.replace(
                inputs, protocol=inputs.protocol.model_copy(update={"crop_taxon": ""})
            )
        )
