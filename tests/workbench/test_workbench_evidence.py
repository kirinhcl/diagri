"""The workbench entry of evidence cards: an operator enters and verifies cards, lists them with
their trail, and sees the evidence hints of every set point when reviewing a run sheet.

A card entered by an operator is verified by that operator at once. A card proposed by a model
role is stored unverified; only an operator's verification record changes that.
"""

import pytest
from fastapi.testclient import TestClient
from workbench_support import LAN_HOST, LAN_PORT, Bench

from growbridge.archive.evidence_ledger import EvidenceOrigin, EvidenceRelation
from growbridge.archive.models import EvidenceCard, TimedAction
from growbridge.planning.evidence_validity import evidence_gate
from growbridge.ports import Actor, Finding

CARDS = "/wb/evidence"
CARD = {
    "source_class": "handbook",
    "citation": "Handbook of Lettuce Production, 3rd ed., p. 41",
    "claim": "200 umol m-2 s-1 suits lettuce",
    "value": 200.0,
    "unit": "umol m-2 s-1",
}


def detail(response) -> dict:
    return response.json()["detail"]


def enter(bench, client, **fields):
    return bench.post(client, CARDS, {**CARD, **fields})


def verify(bench, client, card_id: str, **body):
    return bench.post(client, f"{CARDS}/{card_id}/verify", body)


def proposed(bench, ident: str = "card-m", **fields) -> str:
    """A card as the planner's tool stores it: unverified, with the planner as its source."""
    card = EvidenceCard(
        id=ident, source_class="paper", citation="Doe 2024", claim="more light, more leaf", **fields
    )
    bench.archive.add_evidence(card, source="model:planner", task_id="task-1")
    return ident


# --- entering ---------------------------------------------------------------------------------


def test_an_operator_enters_a_card_and_it_is_verified_by_that_operator(bench, operator):
    response = enter(bench, operator)

    body = response.json()
    assert response.status_code == 200 and body["verified"] is True
    (entry,) = bench.archive.evidence_entries()
    assert entry.card.id == body["id"] and entry.card.verified is True
    assert entry.source == "operator:alice" and entry.verified_by == "alice"
    assert entry.card.citation == CARD["citation"] and entry.card.value == 200.0


def test_the_card_id_comes_from_the_server(bench, operator):
    first = enter(bench, operator, id="mine")
    second = enter(bench, operator, id="mine")

    ids = {first.json()["id"], second.json()["id"]}
    assert len(ids) == 2 and "mine" not in ids


def test_who_entered_the_card_comes_from_the_session_never_from_the_body(bench, operator):
    enter(bench, operator, source="operator:mallory", verified_by="mallory", operator="mallory")

    (entry,) = bench.archive.evidence_entries()
    assert entry.source == "operator:alice" and entry.verified_by == "alice"


def test_entering_a_card_needs_no_recent_reauthentication(bench, operator):
    bench.clock.advance(301)

    response = enter(bench, operator)

    assert response.status_code == 200


@pytest.mark.parametrize(
    "fields",
    [
        {"citation": ""},
        {"citation": "   "},
        {"citation": "x" * 501},
        {"claim": ""},
        {"source_class": "blog"},
        {"unit": "u" * 41},
    ],
)
def test_a_card_that_is_not_acceptable_is_refused_and_stores_nothing(bench, operator, fields):
    response = enter(bench, operator, **fields)

    assert response.status_code == 422
    assert bench.archive.evidence_entries() == ()


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_a_value_that_is_not_a_finite_number_is_refused(bench, operator, value):
    body = (
        '{"source_class": "paper", "citation": "c", "claim": "k", "value": ' + value + "}"
    ).encode()

    response = operator.post(
        CARDS,
        content=body,
        headers={**bench.ui(operator), "content-type": "application/json"},
    )

    assert response.status_code == 422 and bench.archive.evidence_entries() == ()


def test_a_card_without_a_value_is_accepted(bench, operator):
    fields = {k: v for k, v in CARD.items() if k not in ("value", "unit")}

    response = bench.post(operator, CARDS, fields)

    assert response.status_code == 200
    assert bench.archive.evidence()[0].value is None


# --- verifying --------------------------------------------------------------------------------


def test_an_operator_verifies_a_proposed_card_with_a_note(bench, operator):
    proposed(bench)

    response = verify(bench, operator, "card-m", note="read the paper")

    body = response.json()
    assert response.status_code == 200 and body["verified_by"] == "alice"
    assert body["note"] == "read the paper"
    assert bench.archive.evidence(["card-m"])[0].verified is True
    (entry,) = bench.archive.evidence_entries()
    assert entry.source == "model:planner" and entry.task_id == "task-1"


def test_verifying_the_same_card_twice_writes_one_record(bench, operator):
    proposed(bench)
    first = verify(bench, operator, "card-m", note="first")
    bench.clock.advance(60)

    second = verify(bench, operator, "card-m", note="second")

    assert second.status_code == 200 and second.json() == first.json()
    assert len(bench.db.query("SELECT * FROM evidence_verifications")) == 1


def test_who_verified_comes_from_the_session_never_from_the_body(bench, operator):
    proposed(bench)

    verify(bench, operator, "card-m", verified_by="mallory", verifier="mallory")

    assert bench.archive.evidence_verification("card-m").verifier == "alice"


def test_verifying_an_unknown_card_is_refused(bench, operator):
    response = verify(bench, operator, "card-none")

    assert response.status_code == 409 and detail(response)["code"] == "state"


def test_verifying_leaves_the_card_text_alone(bench, operator):
    proposed(bench)
    before = bench.db.one("SELECT body FROM evidence WHERE id = 'card-m'")["body"]

    verify(bench, operator, "card-m")

    assert bench.db.one("SELECT body FROM evidence WHERE id = 'card-m'")["body"] == before


# --- listing ----------------------------------------------------------------------------------


def test_the_list_shows_source_verification_and_time(bench, operator):
    proposed(bench)
    enter(bench, operator)
    verify(bench, operator, "card-m", note="ok")

    cards = operator.get(CARDS).json()["cards"]

    by_id = {card["id"]: card for card in cards}
    entered = next(card for card in cards if card["source"] == "operator:alice")
    assert by_id["card-m"]["source"] == "model:planner" and by_id["card-m"]["task_id"] == "task-1"
    assert by_id["card-m"]["verified"] is True and by_id["card-m"]["verified_by"] == "alice"
    assert by_id["card-m"]["verified_at"] == bench.clock.now() and by_id["card-m"]["note"] == "ok"
    assert entered["verified"] is True and entered["claim"] == CARD["claim"]


def test_an_unverified_card_is_listed_as_unverified(bench, operator):
    proposed(bench)

    (card,) = operator.get(CARDS).json()["cards"]

    assert card["verified"] is False and card["verified_by"] is None


# --- who may call -----------------------------------------------------------------------------


def send(bench, client, name, headers=None, ui=True):
    base = bench.ui(client) if ui else {}
    merged = {**base, **(headers or {})}
    if name == "list":
        return client.get(CARDS, headers=headers)
    if name == "enter":
        return client.post(CARDS, json=CARD, headers=merged)
    return client.post(f"{CARDS}/card-m/verify", json={}, headers=merged)


@pytest.mark.parametrize("name", ["list", "enter", "verify"])
def test_a_model_token_cannot_call_any_evidence_route(bench, operator, name):
    proposed(bench)

    response = send(bench, operator, name, headers=bench.model())

    assert response.status_code == 403 and detail(response)["code"] == "model_role"
    assert len(bench.archive.evidence_entries()) == 1
    assert bench.archive.evidence_verification("card-m") is None


@pytest.mark.parametrize("name", ["list", "enter", "verify"])
def test_evidence_routes_need_a_session(bench, name):
    visitor = TestClient(bench.app, base_url=f"http://{LAN_HOST}:{LAN_PORT}")

    response = send(bench, visitor, name)

    assert response.status_code == 401 and detail(response)["code"] == "session"


@pytest.mark.parametrize("name", ["enter", "verify"])
def test_evidence_writes_need_the_workbench_origin_and_header(bench, operator, name):
    proposed(bench)

    response = send(bench, operator, name, ui=False)

    assert response.status_code == 403 and detail(response)["code"] == "entry"
    assert bench.archive.evidence_verification("card-m") is None


# --- the review shows the evidence hints ------------------------------------------------------

REVIEW = "/wb/stages/stage-1/run-sheet"


def cite(bench, light_on=None, light_off=None, exhaust=None, care="user:the grower"):
    """A pending stage whose three timed set points cite the given cards.

    The two care-rule steps cite ``care`` (a user statement by default), so only the timed set
    points decide what the review shows.
    """
    bench.seed_round()
    plan = bench.sheet()
    timed = tuple(
        TimedAction(id=a.id, channel=a.channel, at=a.at, level=a.level, evidence=ref)
        for a, ref in zip(plan.timed_actions, (light_on, light_off, exhaust), strict=True)
    )
    rules = tuple(
        rule.model_copy(
            update={
                "schedule": tuple(s.model_copy(update={"evidence": care}) for s in rule.schedule)
            }
        )
        for rule in plan.care_rules
    )
    sheet = plan.model_copy(update={"timed_actions": timed, "care_rules": rules})
    bench.workflow.submit_run_sheet(bench.round_id, sheet, bench.designer)


def codes(client) -> list[str]:
    return [item["code"] for item in client.get(REVIEW).json()["findings"]]


def test_the_review_shows_a_missing_card_as_no_evidence(bench, operator):
    cite(bench, "card-none", "user:the grower", "user:the grower")

    body = operator.get(REVIEW).json()

    assert [item["code"] for item in body["findings"]] == ["no_evidence"]
    assert "light-on" in body["findings"][0]["message"] and body["blocking"] is False


def test_the_review_shows_an_unverified_source_until_an_operator_verifies_it(bench, operator):
    proposed(bench)
    cite(bench, "card-m", "user:x", "user:x")
    # nobody but the model vouched for the card: unverified and uncalibrated
    assert codes(operator) == ["unverified_source", "uncalibrated"]

    verify(bench, operator, "card-m", calibrated=True)

    assert codes(operator) == []


def test_verifying_without_the_attestation_leaves_the_uncalibrated_hint(bench, operator):
    proposed(bench)
    cite(bench, "card-m", "user:x", "user:x")

    response = verify(bench, operator, "card-m")

    assert response.json()["calibrated"] is False
    assert codes(operator) == ["uncalibrated"]


def test_a_model_proposed_card_is_listed_as_uncalibrated_until_attested(bench, operator):
    proposed(bench)
    before = operator.get(CARDS).json()["cards"][0]
    verify(bench, operator, "card-m", calibrated=True)
    after = operator.get(CARDS).json()["cards"][0]

    assert before["calibrated"] is False and after["calibrated"] is True


def test_the_attestation_is_stored_with_the_verification_record(bench, operator):
    proposed(bench)

    response = verify(bench, operator, "card-m", note="measured here", calibrated=True)

    record = bench.archive.evidence_verification("card-m")
    assert response.json()["calibrated"] is True
    assert record.calibrated is True and record.verifier == "alice"


def test_a_later_attestation_does_not_change_the_first_verification(bench, operator):
    proposed(bench)
    first = verify(bench, operator, "card-m")

    second = verify(bench, operator, "card-m", calibrated=True)

    assert second.json() == first.json() and second.json()["calibrated"] is False
    assert bench.archive.evidence(["card-m"])[0].calibrated is False


def test_who_attested_comes_from_the_session_never_from_the_body(bench, operator):
    proposed(bench)

    verify(bench, operator, "card-m", calibrated=True, calibrated_by="mallory", verifier="mallory")

    assert bench.archive.evidence_verification("card-m").verifier == "alice"


def test_an_operator_entered_card_keeps_the_calibration_the_operator_entered(bench, operator):
    calibrated = enter(bench, operator, calibrated=True).json()["id"]
    uncalibrated = enter(bench, operator, calibrated=False).json()["id"]

    flags = {c.id: c.calibrated for c in bench.archive.evidence([calibrated, uncalibrated])}

    assert flags == {calibrated: True, uncalibrated: False}


def local_card(ident: str = "card-l", **fields) -> EvidenceCard:
    values = {"id": ident, "source_class": "local", "citation": "our tent log", "claim": "par 180"}
    return EvidenceCard(**{**values, **fields})


def test_an_operator_entered_local_card_gives_no_hint_when_calibrated(bench, operator):
    entered = enter(bench, operator, source_class="local", citation="our tent log").json()["id"]
    cite(bench, entered, entered, entered)

    assert codes(operator) == []


def test_an_operator_entered_local_card_still_must_be_calibrated(bench, operator):
    entered = enter(bench, operator, source_class="local", calibrated=False).json()["id"]
    cite(bench, entered, "user:x", "user:x")

    assert codes(operator) == ["uncalibrated"]


def test_a_local_card_without_a_verification_record_gets_the_hint(bench, operator):
    """Seeded directly, with no operator behind it: the class "local" earns no exemption."""
    bench.archive.add_evidence(local_card(), source="model:planner", task_id="task-1")
    cite(bench, "card-l", "user:x", "user:x")

    # a model-sourced card is unverified and, with no operator attestation, uncalibrated
    assert codes(operator) == ["unverified_source", "uncalibrated"]


def test_a_local_card_with_no_source_at_all_gets_the_hint(bench, operator):
    bench.archive.add_evidence(local_card(calibrated=False))
    cite(bench, "card-l", "user:x", "user:x")

    assert set(codes(operator)) == {"unverified_source", "uncalibrated"}


def test_verifying_a_local_card_clears_its_hint(bench, operator):
    bench.archive.add_evidence(local_card(), source="operator:alice")
    cite(bench, "card-l", "user:x", "user:x")
    assert codes(operator) == ["unverified_source"]

    verify(bench, operator, "card-l")

    assert codes(operator) == []


def test_a_verified_calibrated_card_gives_no_hint(bench, operator):
    entered = enter(bench, operator).json()["id"]
    cite(bench, entered, entered, entered)

    assert codes(operator) == []


def test_set_points_without_any_reference_are_listed_one_by_one(bench, operator):
    cite(bench)

    assert codes(operator) == ["no_evidence"] * 3


def test_the_hints_do_not_block_approval(bench, operator):
    proposed(bench)
    cite(bench, "card-m", None, "card-none")
    assert set(codes(operator)) == {"unverified_source", "uncalibrated", "no_evidence"}

    approval = bench.workflow.approve(
        "stage-1", Actor(kind="operator", id="alice", reauth_at=bench.clock.now())
    )

    assert approval.operator == "alice"
    assert operator.get(REVIEW).json()["blocking"] is False


# --- evidence validity in the review -------------------------------------------------------------


def supersede_card(bench, old: str, new: str) -> None:
    relation = EvidenceRelation(
        id=f"{new}-over-{old}",
        kind="supersedes",
        subject_id=new,
        object_id=old,
        reason="newer",
        source="operator:op",
        task_id=None,
        project_id=None,
        proposed_in=None,
        at=1.0,
    )
    bench.archive.ledger.add_relation(relation, confirmed_by="op")


def gated(bench) -> None:
    """The workflow as the runtime builds it: its validator carries the evidence gate."""
    bench.workflow.validate = lambda sheet: evidence_gate(sheet, bench.archive)


def test_a_pending_stage_shows_the_superseded_card_as_blocking(bench, operator):
    gated(bench)
    proposed(bench, "old")
    proposed(bench, "new")
    cite(bench, "old", "old", "old")
    supersede_card(bench, "old", "new")

    review = operator.get(REVIEW).json()

    blocking = [f["code"] for f in review["findings"] if f["blocking"]]
    assert set(blocking) == {"superseded_source"} and review["blocking"] is True


def test_a_running_stage_shows_the_superseded_card_as_a_hint(bench, operator):
    gated(bench)
    proposed(bench, "old")
    proposed(bench, "new")
    cite(bench, "old", "old", "old")
    actor = Actor(kind="operator", id="alice", reauth_at=bench.clock.now())
    bench.workflow.approve("stage-1", actor)
    bench.run(bench.workflow.start_stage("stage-1", actor))
    supersede_card(bench, "old", "new")

    review = operator.get(REVIEW).json()

    found = [f for f in review["findings"] if f["code"] == "superseded_source"]
    assert found and all(f["blocking"] is False for f in found)
    assert review["blocking"] is False


def test_a_running_stage_keeps_other_blocking_findings_blocking(bench, operator):
    cite(bench)
    actor = Actor(kind="operator", id="alice", reauth_at=bench.clock.now())
    bench.workflow.approve("stage-1", actor)
    bench.run(bench.workflow.start_stage("stage-1", actor))
    bench.workflow.validate = lambda sheet: (Finding(code="other_problem", message="m"),)

    review = operator.get(REVIEW).json()

    assert review["blocking"] is True


def test_another_projects_round_card_is_no_evidence_in_the_review(bench, operator):
    proposed(bench, "theirs")
    bench.archive.ledger.add_origin(
        EvidenceOrigin(
            card_id="theirs",
            project_id="other-project",
            round_id="r",
            report_artifact_id="a",
            snapshot_ids=(),
            label="descriptive",
            at=0.0,
        )
    )
    cite(bench, "theirs", "theirs", "theirs")

    assert codes(operator) == ["no_evidence"] * 3


# --- catalog-linked cards and the scoped list ---------------------------------------------------

LINKED = {"variable": "air_temperature", "value": 24.0, "unit": "C"}


def round_card(bench, card_id: str, project_id: str, **fields) -> None:
    proposed(bench, card_id, **fields)
    bench.archive.ledger.add_origin(
        EvidenceOrigin(
            card_id=card_id,
            project_id=project_id,
            round_id="r",
            report_artifact_id=f"art-{card_id}",
            snapshot_ids=(),
            label="descriptive",
            at=0.0,
        )
    )


def test_an_alias_variable_is_refused_on_entry(bench, operator):
    response = enter(bench, operator, variable="temp", value=24.0, unit="Cel")

    assert response.status_code == 403
    assert detail(response)["reason"] == "evidence_card_invalid"
    assert not bench.archive.evidence_entries()


def test_the_unit_is_stored_as_the_catalog_unit(bench, operator):
    enter(bench, operator, **LINKED)

    (entry,) = bench.archive.evidence_entries()
    assert entry.card.unit == "Cel" and entry.card.variable == "air_temperature"


def test_a_card_enters_with_conditions_and_crop_fields(bench, operator):
    response = enter(
        bench,
        operator,
        **LINKED,
        conditions=[{"variable": "air_relative_humidity", "min": 50.0, "max": 80.0}],
        crop_taxon="NCBITaxon:4236",
        cultivar="Butterhead",
        growth_stage="vegetative",
        conditions_note="closed greenhouse",
    )

    assert response.status_code == 200
    (entry,) = bench.archive.evidence_entries()
    assert entry.card.conditions[0].variable == "air_relative_humidity"
    assert entry.card.crop_taxon == "NCBITaxon:4236" and entry.card.cultivar == "Butterhead"


def test_old_style_cards_still_enter_and_list(bench, operator):
    assert enter(bench, operator).status_code == 200

    (card,) = operator.get(CARDS).json()["cards"]
    assert card["status"]["validity"] == "active" and "origin" not in card


def test_the_list_filters_by_status_and_variable(bench, operator):
    old = enter(bench, operator, **LINKED).json()["id"]
    new = enter(bench, operator, **LINKED).json()["id"]
    enter(bench, operator)
    supersede_card(bench, old, new)

    def ids(query: str) -> set[str]:
        return {c["id"] for c in operator.get(f"{CARDS}?{query}").json()["cards"]}

    assert ids("status=superseded") == {old}
    assert ids("variable=air_temperature") == {old, new}
    assert ids("variable=temp&status=active") == {new}
    assert len(ids("")) == 3


def test_the_list_as_of_shows_the_status_at_that_time(bench, operator):
    old = enter(bench, operator).json()["id"]
    new = enter(bench, operator).json()["id"]
    supersede_card(bench, old, new)  # confirmed now; the relation is stamped at 1.0

    def validity(**query) -> str:
        cards = operator.get(CARDS, params=query).json()["cards"]
        return next(c for c in cards if c["id"] == old)["status"]["validity"]

    assert validity() == "superseded"
    assert validity(as_of=0.5) == "active"


def test_a_round_card_lists_with_its_origin_only_in_its_project(bench, operator):
    round_card(bench, "mine", "p-1")
    round_card(bench, "theirs", "p-2")
    enter(bench, operator)

    global_ids = {c["id"] for c in operator.get(CARDS).json()["cards"]}
    mine = {c["id"]: c for c in operator.get(CARDS, params={"project_id": "p-1"}).json()["cards"]}

    assert "mine" not in global_ids and "theirs" not in global_ids and len(global_ids) == 1
    assert set(mine) == {"mine", *global_ids} and "theirs" not in mine
    assert mine["mine"]["origin"] == {
        "round_id": "r",
        "report_artifact_id": "art-mine",
        "label": "descriptive",
    }


def test_the_list_offers_the_variables_a_card_may_name(bench, operator):
    variables = operator.get(CARDS).json()["variables"]

    kinds = {v["kind"] for v in variables}
    ids = {v["id"] for v in variables}
    assert kinds <= {"sensor", "manual"} and "air_temperature" in ids
    assert "temp" not in ids and {"id", "kind", "unit", "label_en", "label_zh"} <= set(variables[0])


def test_the_list_of_a_project_needs_access_to_it(tmp_path):
    bench = Bench.full(tmp_path)
    alice, bob = bench.user("alice"), bench.user("bob")
    bench.seed_round_as("alice")
    url = f"{CARDS}?project_id={bench.project_id}"

    assert alice.get(url).status_code == 200
    refused = bob.get(url)
    assert refused.status_code == 409
    assert detail(refused)["reason"] == "record_not_found"
    bench.db.close()
