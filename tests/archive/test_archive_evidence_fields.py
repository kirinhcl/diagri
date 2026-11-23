from growbridge.archive.models import ApplicabilityRange, EvidenceCard


def test_an_old_card_dumps_exactly_as_before():
    old = EvidenceCard(
        id="ev-1", source_class="handbook", citation="H", claim="c", value=1.0, unit="x"
    )
    assert set(old.model_dump(mode="json")) == {
        "id",
        "source_class",
        "citation",
        "claim",
        "value",
        "unit",
        "verified",
        "calibrated",
    }


def test_new_fields_round_trip_through_the_archive(archive):
    new = EvidenceCard(
        id="ev-2",
        source_class="paper",
        citation="P",
        claim="c",
        variable="air_temperature",
        value=24.0,
        unit="Cel",
        conditions=(ApplicabilityRange(variable="co2_concentration", max=800),),
        crop_taxon="NCBITaxon:4236",
        growth_stage="head",
    )
    archive.add_evidence(new, source="operator:op", verified_by="op")
    (stored,) = archive.evidence(["ev-2"])
    assert stored.conditions[0].max == 800 and stored.crop_taxon == "NCBITaxon:4236"
