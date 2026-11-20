"""``POST /wb/rounds/{round_id}/evidence`` and what the round report says about converting."""

import json

import pytest
from workbench_support import Bench

from growbridge.archive.ids import file_digest
from growbridge.archive.models import Artifact
from growbridge.workflow.states import RoundState


def detail(response) -> dict:
    return response.json()["detail"]


def deliver(bench, report=None, state=RoundState.DELIVERED) -> str:
    """A round of the bench's project with a published report, in ``state``."""
    round_id = bench.round_id or bench.seed_round()
    path = bench.archive.root.parent / "agent_work" / "report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"label": "exploratory", "conclusion": "supported"} if report is None else report
    path.write_text(json.dumps(body), encoding="utf-8")
    bench.archive.add_artifact(
        Artifact(
            id="artifact-1",
            task_id="task-1",
            kind="research_report",
            path=str(path),
            sha256=file_digest(path),
            label="exploratory",
        )
    )
    bench.workflow.store.update_round(round_id, report_artifact_id="artifact-1", state=state)
    return round_id


def convert(bench, client, round_id, body=None):
    return bench.post(client, f"/wb/rounds/{round_id}/evidence", body or {})


def test_an_operator_turns_the_conclusion_into_a_verified_project_card(bench, operator):
    round_id = deliver(bench)

    response = convert(bench, operator, round_id, {"value": 0.4, "growth_stage": "rosette"})

    body = response.json()
    assert response.status_code == 200 and body["verified"] is True
    assert body["label"] == "exploratory"
    (entry,) = bench.archive.evidence_entries()
    assert entry.card.id == body["card_id"] and entry.card.source_class == "local"
    assert entry.card.unit == "cm2/d" and entry.card.growth_stage == "rosette"
    assert entry.verified_by == "alice"
    origin = bench.archive.ledger.origin(body["card_id"])
    assert origin.project_id == bench.project_id and origin.round_id == round_id


def test_the_card_is_listed_in_its_project_and_not_publicly(bench, operator):
    round_id = deliver(bench)
    card_id = convert(bench, operator, round_id).json()["card_id"]

    own = operator.get("/wb/evidence", params={"project_id": bench.project_id}).json()["cards"]
    public = operator.get("/wb/evidence").json()["cards"]

    assert [c["id"] for c in own] == [card_id] and own[0]["origin"]["round_id"] == round_id
    assert public == []


def test_a_second_conversion_is_refused_with_the_card(bench, operator):
    round_id = deliver(bench)
    card_id = convert(bench, operator, round_id).json()["card_id"]

    again = convert(bench, operator, round_id)

    assert again.status_code == 409 and detail(again)["reason"] == "round_card_exists"
    assert detail(again)["params"]["card_id"] == card_id


def test_an_unfinished_round_is_refused(bench, operator):
    round_id = deliver(bench, state=RoundState.STAGE_RUNNING)

    refused = convert(bench, operator, round_id)

    assert detail(refused)["reason"] == "round_card_not_delivered"


def test_a_wrong_unit_is_refused_by_the_card_check(bench, operator):
    round_id = deliver(bench)

    refused = convert(bench, operator, round_id, {"value": 1, "unit": "kg"})

    assert detail(refused)["reason"] == "evidence_card_invalid"
    assert bench.archive.evidence_entries() == ()


def test_an_unknown_round_is_refused_as_not_found(bench, operator):
    assert convert(bench, operator, "no-such-round").status_code in (404, 409)


def test_a_model_role_cannot_convert(bench, operator):
    round_id = deliver(bench)

    headers = {**bench.ui(operator), **bench.model()}
    response = operator.post(f"/wb/rounds/{round_id}/evidence", json={}, headers=headers)

    assert response.status_code == 403 and detail(response)["code"] == "model_role"
    assert bench.archive.evidence_entries() == ()


def test_the_report_says_the_round_can_be_converted(bench, operator):
    round_id = deliver(bench)

    assert operator.get(f"/wb/rounds/{round_id}/report").json()["round_card"] == {}


def test_the_report_names_the_card_once_converted(bench, operator):
    round_id = deliver(bench)
    card_id = convert(bench, operator, round_id).json()["card_id"]

    shown = operator.get(f"/wb/rounds/{round_id}/report").json()

    assert shown["round_card"] == {"card_id": card_id}


@pytest.mark.parametrize(
    ("report", "state", "reason"),
    [
        ({"conclusion": ""}, RoundState.DELIVERED, "round_card_no_conclusion"),
        (
            {"conclusion": "x", "holdout_id": "h"},
            RoundState.DELIVERED,
            "round_card_report_unusable",
        ),
        (None, RoundState.STAGE_RUNNING, "round_card_not_delivered"),
    ],
)
def test_the_report_gives_the_reason_it_cannot_be_converted(bench, operator, report, state, reason):
    round_id = deliver(bench, report, state)

    shown = operator.get(f"/wb/rounds/{round_id}/report").json()["round_card"]

    assert shown["refusal"]["reason"] == reason
    assert shown["refusal"]["params"]["round_id"] == round_id


def test_only_the_projects_owner_converts_and_others_see_no_such_round(tmp_path):
    bench = Bench.full(tmp_path)
    for name in ("alice", "bob"):
        bench.user(name)
    bench.seed_round_as("alice")
    round_id = deliver(bench)

    refused = convert(bench, bench.user("bob"), round_id)
    twin = bench.absent_twin()
    absent = convert(twin, twin.user("bob"), round_id)

    assert (refused.status_code, refused.json()) == (absent.status_code, absent.json())
    assert bench.archive.evidence_entries() == ()
    assert convert(bench, bench.user("alice"), round_id).status_code == 200


def test_more_than_eight_conditions_are_refused_at_input(bench, operator):
    round_id = deliver(bench)
    conditions = [{"variable": "air_temperature", "min": float(i)} for i in range(9)]

    response = convert(bench, operator, round_id, {"conditions": conditions})

    assert response.status_code == 422 and bench.archive.evidence_entries() == ()


def test_verifying_another_projects_round_card_answers_as_for_no_such_card(tmp_path):
    bench = Bench.full(tmp_path)
    for name in ("alice", "bob"):
        bench.user(name)
    bench.seed_round_as("alice")
    card_id = convert(bench, bench.user("alice"), deliver(bench)).json()["card_id"]
    path = f"/wb/evidence/{card_id}/verify"

    hidden = bench.post(bench.user("bob"), path)
    twin = bench.absent_twin()
    absent = twin.post(twin.user("bob"), path)

    assert (hidden.status_code, hidden.json()) == (absent.status_code, absent.json())
    assert detail(hidden)["reason"] == "record_not_found"
    assert bench.post(bench.user("alice"), path).status_code == 200
