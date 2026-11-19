import pytest

from growbridge.archive.ids import canonical_json
from growbridge.archive.models import ActionRecord, ActionState, Allocation, ManualMeasurement
from growbridge.dataset.pseudonym import Pseudonymizer
from growbridge.dataset.rows_records import (
    action_rows,
    intervention_rows,
    measurement_rows,
    withheld_rows,
)
from growbridge.dataset.schema import table
from growbridge.dataset.source import ExportRefused
from growbridge.research.holdout import Holdout
from growbridge.sim.fixtures import make_protocol
from growbridge.vocab.catalog import packaged_catalog

CAT = packaged_catalog()
P = Pseudonymizer(b"k" * 32)
PROTOCOL = make_protocol()
TWO_UNIT_PROTOCOL = make_protocol(
    allocations=(
        Allocation(round=1, block=1, unit="tent-1", treatment_id="high"),
        Allocation(round=1, block=1, unit="tent-2", treatment_id="control"),
    )
)


def KEEP_ALL(_):
    return True


def m(id, **overrides):
    fields = {
        "id": id,
        "experiment_id": "exp-1",
        "batch": "batch-1",
        "plant_id": "p1",
        "layout_version": "v1",
        "measured_at": 10.0,
        "position": "tent-1",
        "method": "image",
        "metric": "canopy_area_growth",
        "value": 1.5,
        "unit": "cm2/d",
        "operator": "bob",
    }
    return ManualMeasurement(**{**fields, **overrides})


def holdout(id, batches, fields):
    return Holdout(
        holdout_id=id,
        project_id="project-1",
        batch_ids=batches,
        outcome_fields=fields,
        development_batch_ids=None,
        registered_at=1.0,
        registered_by=None,
    )


def action(id, **overrides):
    fields = {
        "request_id": id,
        "state": ActionState.CONFIRMED,
        "channel": "light",
        "planned_level": 50,
        "right_number": 1,
        "right_kind": "manual",
        "trigger": "manual",
        "created_at": 1.0,
        "operator": "alice",
    }
    return ActionRecord(**{**fields, **overrides})


def test_only_the_last_correction_is_a_row():
    rows = measurement_rows(
        [m("m1"), m("m2", corrects="m1"), m("m3", corrects="m2")], KEEP_ALL, PROTOCOL, 1, CAT, P
    )
    assert [(r["record_id"], r["corrects"]) for r in rows.rows] == [("m3", "m2")]
    assert rows.superseded == 2


def test_rows_the_filter_rejects_are_withheld():
    rows = measurement_rows([m("m1"), m("m2")], lambda x: x.id != "m2", PROTOCOL, 1, CAT, P)
    assert [r["record_id"] for r in rows.rows] == ["m1"] and rows.withheld_at_export == 1


def test_a_held_out_correction_does_not_bring_back_what_it_corrects():
    """Superseded is decided over every record before the filter: rejecting the correction must
    not leave the original it replaced as the latest version."""
    pair = [m("m1"), m("m2", corrects="m1")]
    rows = measurement_rows(pair, lambda x: x.id != "m2", PROTOCOL, 1, CAT, P)
    assert rows.rows == ()
    assert (rows.superseded, rows.withheld_at_export) == (1, 1)


def test_a_held_out_original_that_was_corrected_counts_as_superseded():
    pair = [m("m1"), m("m2", corrects="m1")]
    rows = measurement_rows(pair, lambda x: x.id != "m1", PROTOCOL, 1, CAT, P)
    assert [(r["record_id"], r["corrects"]) for r in rows.rows] == [("m2", "m1")]
    assert (rows.superseded, rows.withheld_at_export) == (1, 0)


def test_operator_is_a_pseudonym():
    (row,) = measurement_rows([m("m1", operator="alice")], KEEP_ALL, PROTOCOL, 1, CAT, P).rows
    assert row["operator"] == P("alice") and "alice" not in map(str, row.values())


def test_rows_use_the_schema_columns_and_the_unit_treatment():
    (row,) = measurement_rows([m("m1")], KEEP_ALL, PROTOCOL, 1, CAT, P).rows
    assert set(row) == {c.name for c in table("measurements.csv").columns}
    assert (row["unit"], row["treatment_id"], row["round"]) == ("tent-1", "high", 1)
    assert row["variable_id"] == "canopy_area_growth" and row["time"] == 10.0


def test_unit_alias_is_accepted():
    cat = CAT
    temp = cat.get("air_temperature")
    alias = next(a for a, u in cat.unit_aliases.items() if u == temp.unit)
    (row,) = measurement_rows(
        [m("m1", metric="air_temperature", unit=alias)], KEEP_ALL, PROTOCOL, 1, cat, P
    ).rows
    assert row["variable_id"] == "air_temperature"


def test_unit_mismatch_is_refused():
    with pytest.raises(ExportRefused, match="m1"):
        measurement_rows([m("m1", unit="mm2/d")], KEEP_ALL, PROTOCOL, 1, CAT, P)


def test_unknown_metric_is_refused():
    with pytest.raises(ExportRefused, match="m1"):
        measurement_rows([m("m1", metric="not_in_catalog")], KEEP_ALL, PROTOCOL, 1, CAT, P)


def test_unplaced_measurement_is_kept_and_counted():
    rows = measurement_rows([m("m1", position="nowhere")], KEEP_ALL, TWO_UNIT_PROTOCOL, 1, CAT, P)
    assert rows.rows[0]["unit"] is None and rows.rows[0]["treatment_id"] is None
    assert rows.unplaced == 1


def test_withheld_rows():
    rows = withheld_rows(
        [
            holdout("h1", ("b2", "b1"), ("canopy_area_growth",)),
            holdout("h2", ("b3",), ("not_in_catalog", "canopy_area_growth")),
        ],
        CAT,
    )
    assert [(r["holdout_id"], r["batch"], r["variable_id"]) for r in rows] == [
        ("h1", "b1", "canopy_area_growth"),
        ("h1", "b2", "canopy_area_growth"),
        ("h2", "b3", "*"),
    ]


def test_triggers_lose_their_notes():
    rows = action_rows(
        [action("a1", trigger="manual: Alice moved the lamp"), action("a2", trigger="weird")], P
    )
    assert [r["trigger"] for r in rows.rows] == ["manual", "other"]
    assert rows.notes_dropped == 1 and rows.other_triggers == 1
    assert set(rows.rows[0]) == {c.name for c in table("actions.csv").columns}
    assert rows.rows[0]["operator"] == P("alice") and rows.rows[0]["state"] == "confirmed"


def test_intervention_detail_is_canonical_json():
    (row,) = intervention_rows(
        [
            {
                "id": "i1",
                "experiment_id": "e",
                "stage_id": "s",
                "kind": "takeover",
                "detail": {"b": 1, "a": 2},
                "operator": "bob",
                "at": 5.0,
            }
        ],
        P,
    )
    assert row["detail"] == canonical_json({"b": 1, "a": 2})
    assert row["operator"] == P("bob") and row["time"] == 5.0
    assert set(row) == {c.name for c in table("interventions.csv").columns}
