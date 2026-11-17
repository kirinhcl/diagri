"""The refusals of the workbench analysis routes carry a registered reason and the params the
console builds its text from; the coarse code, the HTTP status and the English message stay."""

import pytest
from test_workbench_analysis import (
    PROTOCOL,
    freeze,
    measurement,
    other_project_snapshot,
    round_reusing,
    run,
    save_v2,
    snapshot_of,
    start_the_stage,
)


@pytest.fixture
def seeded(bench, operator):
    bench.pending()
    return bench


def refused(response, status: int, code: str, reason: str, params: dict) -> dict:
    assert response.status_code == status
    body = response.json()["detail"]
    assert (body["code"], body["reason"], body["params"]) == (code, reason, params)
    return body


def test_protocol_not_found_carries_the_protocol_and_the_project(seeded, operator):
    body = {"project_id": seeded.project_id, "script": "print(1)\n"}
    response = seeded.post(operator, "/wb/protocols/nope/analysis", body)
    refused(
        response,
        409,
        "state",
        "protocol_not_found",
        {"protocol_id": "nope", "project_id": seeded.project_id},
    )


def test_analysis_freeze_too_late_carries_the_protocol_and_its_version_after_a_stage_started(
    seeded, operator
):
    start_the_stage(seeded)
    body = refused(
        freeze(seeded, operator),
        409,
        "state",
        "analysis_freeze_too_late",
        {"protocol_id": PROTOCOL, "version": 1},
    )
    assert "6.5" not in body["message"] and "has already started" in body["message"]


def test_analysis_freeze_too_late_carries_the_protocol_and_its_version_after_a_snapshot(
    seeded, operator
):
    snapshot_of(seeded)
    refused(
        freeze(seeded, operator),
        409,
        "state",
        "analysis_freeze_too_late",
        {"protocol_id": PROTOCOL, "version": 1},
    )


def test_analysis_script_not_frozen_carries_the_protocol_and_its_version(seeded, operator):
    snap = snapshot_of(seeded)
    refused(
        run(seeded, operator, snap.id),
        409,
        "state",
        "analysis_script_not_frozen",
        {"protocol_id": PROTOCOL, "version": 1},
    )


def test_not_this_protocol_carries_the_protocol(seeded, operator):
    freeze(seeded, operator)
    for snapshot_id in (
        "snap_nope",
        other_project_snapshot(seeded).id,
        snapshot_of(seeded, experiment="experiment-without-stage").id,
    ):
        refused(
            run(seeded, operator, snapshot_id),
            403,
            "scope",
            "not_this_protocol",
            {"protocol_id": PROTOCOL},
        )


def test_mixed_protocol_carries_no_params(seeded, operator):
    start_the_stage(seeded)
    seeded.clock.advance(60)
    save_v2(seeded)
    round_reusing(seeded, "experiment-stage-1", "stage-v2", version=2)
    freeze(seeded, operator)
    snap = snapshot_of(seeded)
    refused(run(seeded, operator, snap.id), 403, "scope", "mixed_protocol", {})


def test_snapshot_invalidated_carries_the_snapshot(seeded, operator):
    freeze(seeded, operator)
    snap = snapshot_of(seeded, rows=[measurement()])
    assert seeded.archive.mark_dependents_invalid("m1") == (snap.id,)
    refused(
        run(seeded, operator, snap.id),
        409,
        "state",
        "snapshot_invalidated",
        {"snapshot_id": snap.id},
    )


def test_snapshot_predates_freeze_carries_the_snapshot(seeded, operator):
    freeze(seeded, operator)
    seeded.clock.advance(60)
    start_the_stage(seeded)
    seeded.db.execute(  # as if the stage had started before the script was frozen
        "UPDATE wf_stages SET started_at = ? WHERE stage_id = 'stage-1'",
        (seeded.clock.now() - 600,),
    )
    snap = snapshot_of(seeded)
    refused(
        run(seeded, operator, snap.id),
        409,
        "state",
        "snapshot_predates_freeze",
        {"snapshot_id": snap.id},
    )


def test_holdout_rows_carries_the_project(seeded, operator):
    seeded.holdout.register(seeded.project_id, "hold-1", ("b3",), ("yield_g",), ("d-1", "d-2"))
    freeze(seeded, operator)
    leaky = snapshot_of(seeded, rows=[measurement("yield_g", "b3")])
    refused(
        run(seeded, operator, leaky.id),
        403,
        "scope",
        "holdout_rows",
        {"project_id": seeded.project_id},
    )


def test_snapshot_not_complete_carries_the_snapshot(seeded, operator):
    freeze(seeded, operator)
    snap = snapshot_of(seeded, complete=False)
    refused(
        run(seeded, operator, snap.id),
        403,
        "snapshot_incomplete",
        "snapshot_not_complete",
        {"snapshot_id": snap.id},
    )


def test_script_syntax_through_the_route_keeps_the_compiler_text_in_detail(seeded, operator):
    response = freeze(seeded, operator, script="def broken(:\n")
    body = response.json()["detail"]
    assert (response.status_code, body["code"], body["reason"]) == (403, "param", "script_syntax")
    assert set(body["params"]) == {"detail"}
