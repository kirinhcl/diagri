import pytest

from growbridge.vocab.curie import taxon_problems


@pytest.mark.parametrize("taxon", ["NCBITaxon:4236", "NCBITaxon:9"])
def test_valid_taxon_has_no_problems(taxon):
    assert taxon_problems(taxon, "") == []


@pytest.mark.parametrize(
    "taxon", ["", "NCBITaxon:abc", "ncbitaxon:4236", "NCBITaxon:4236 ", "NCBITaxon:4236\n", "4236"]
)
def test_bad_taxon_is_a_problem(taxon):
    problems = taxon_problems(taxon, "")
    assert len(problems) == 1 and "crop_taxon" in problems[0]


def test_cultivar_up_to_200_characters():
    assert taxon_problems("NCBITaxon:4236", "x" * 200) == []
    assert any("200" in p for p in taxon_problems("NCBITaxon:4236", "x" * 201))
