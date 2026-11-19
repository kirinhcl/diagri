import pytest
from vocab_support import bare_packaged_text

from growbridge.archive.models import Allocation, Treatment
from growbridge.dataset.rows_design import treatment_rows, unit_rows, variable_rows
from growbridge.dataset.schema import table
from growbridge.dataset.source import ExportRefused
from growbridge.sim.fixtures import make_protocol
from growbridge.vocab import load_catalog

PLAIN = load_catalog(bare_packaged_text())
WITH_REFS = load_catalog(
    bare_packaged_text().replace("refs = []", 'refs = ["ENVO:09200001"]', 1)
    + '\n[unit_refs]\n"Cel" = "UO:0000027"\n'
)


def test_variable_defining_fields_come_from_the_record_and_refs_from_current():
    record = PLAIN.snapshot_record(["air_temperature"])
    record["variables"][0]["label_en"] = "As frozen"
    (row,) = variable_rows(["air_temperature"], record, WITH_REFS)
    assert set(row) == {c.name for c in table("variables.csv").columns}
    assert row["label_en"] == "As frozen" and row["unit_ucum"] == "Cel"
    assert row["refs"] == "ENVO:09200001" and row["unit_uo"] == "UO:0000027"
    assert row["mapped"] is True


def test_unmapped_variable():
    (row,) = variable_rows(["air_temperature"], PLAIN.snapshot_record([]), PLAIN)
    assert row["refs"] == ""
    assert row["mapped"] is False and row["unit_uo"] is None


def test_unknown_variable_is_refused():
    with pytest.raises(ExportRefused, match="nope"):
        variable_rows(["nope"], PLAIN.snapshot_record([]), PLAIN)


def test_treatment_rows_flag_the_control_and_keep_factorless_treatments():
    protocol = make_protocol(
        treatments=(
            Treatment(id="control", name="c", factors={"light": 40}),
            Treatment(id="high", name="h", factors={"light": 70, "fan": "on"}),
            Treatment(id="bare", name="b"),
        )
    )
    rows = treatment_rows(protocol)
    assert {(r["treatment_id"], r["variable_id"], r["value"]) for r in rows} == {
        ("control", "light", 40),
        ("high", "light", 70),
        ("high", "fan", "on"),
        ("bare", None, None),
    }
    bare = next(r for r in rows if r["treatment_id"] == "bare")
    assert bare["variable_id"] is None and bare["value"] is None and bare["is_control"] is False
    assert next(r for r in rows if r["treatment_id"] == "control")["is_control"] is True


def test_unit_rows_cover_every_allocation():
    protocol = make_protocol()
    rows = unit_rows(protocol)
    assert len(rows) == len(protocol.allocations) == 4
    assert rows[0] == {"round": 1, "block": 1, "unit": "tent-1", "treatment_id": "high"}


def test_unit_rows_other_protocol():
    protocol = make_protocol(
        allocations=(Allocation(round=2, block=1, unit="u", treatment_id="x"),)
    )
    assert [r["round"] for r in unit_rows(protocol)] == [2]
