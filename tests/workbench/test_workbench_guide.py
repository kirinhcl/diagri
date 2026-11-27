"""The routes of the guided setup: a session from its first step to the saved protocol."""

import pytest
from vocab_support import WITH_OLD
from workbench_support import Bench

from growbridge.planning.design import estimate_sample_size
from growbridge.sim.fixtures import make_protocol

GUIDE = "/wb/guide/sessions"
TREATMENTS = {
    "treatments": [
        {"id": "control", "name": "Light 40", "factors": {"light": 40}},
        {"id": "high", "name": "Light 70", "factors": {"light": 70}},
    ],
    "control_treatment_id": "control",
}
ANSWERS = {
    "question": {"question": "Does more light speed up canopy growth?", "hypothesis": ""},
    "crop": {"crop": "Lettuce", "crop_taxon": "NCBITaxon:4236"},
    "treatments": TREATMENTS,
    "measures": {
        "variables": ["canopy_area_growth"],
        "primary_endpoint": "canopy_area_growth",
    },
    "analysis": {"target_effect": 0.15, "method": "paired_block"},
    "scale": {"layout": "series", "units": ["tent-1"], "blocks": 3, "stages": ["vegetative"]},
}


def detail(response) -> dict:
    return response.json()["detail"]


def new_project(bench: Bench, client) -> str:
    return bench.post(client, "/wb/projects", {"name": "guided"}).json()["project_id"]


def start(bench: Bench, client, project_id: str) -> str:
    return bench.post(client, GUIDE, {"project_id": project_id}).json()["session_id"]


def choose(bench: Bench, client, sid: str, step: str, answer: dict, option_ids=()):
    body = {"answer": answer, "option_ids": list(option_ids)}
    return bench.post(client, f"{GUIDE}/{sid}/steps/{step}/choose", body)


def answer_all(bench: Bench, client, sid: str) -> None:
    for step, answer in ANSWERS.items():
        ids = ["lettuce"] if step == "crop" else []
        assert choose(bench, client, sid, step, answer, ids).status_code == 200, step


@pytest.fixture
def pid(bench, operator) -> str:
    return new_project(bench, operator)


@pytest.fixture
def sid(bench, operator, pid) -> str:
    return start(bench, operator, pid)


def test_a_new_session_has_six_pending_steps(bench, operator, sid):
    view = operator.get(f"{GUIDE}/{sid}").json()

    assert [s["status"] for s in view["steps"]] == ["pending"] * 6
    assert view["saved"] == [] and view["session"]["operator"] == "alice"


def test_choosing_an_offered_crop_records_offer_and_choice(bench, operator, sid):
    r = choose(bench, operator, sid, "crop", ANSWERS["crop"], ["lettuce"])

    events = bench.guide.events(sid)
    assert r.status_code == 200
    assert [e.kind for e in events][-2:] == ["offered", "chosen"]
    assert events[-1].payload["source"] == "system"
    assert events[-1].payload["option_ids"] == ["lettuce"]
    assert {o["id"] for o in events[-2].payload["options"]} >= {"lettuce"}


def test_an_answer_of_the_researcher_is_recorded_as_own(bench, operator, sid):
    choose(bench, operator, sid, "question", ANSWERS["question"])

    assert bench.guide.events(sid)[-1].payload["source"] == "own"


def test_an_unknown_factor_is_refused_with_the_step(bench, operator, sid):
    unknown = [
        {"id": t["id"], "name": "x", "factors": {"nutrient": 2}} for t in TREATMENTS["treatments"]
    ]
    before = len(bench.guide.events(sid))

    r = choose(bench, operator, sid, "treatments", {**TREATMENTS, "treatments": unknown})

    assert r.status_code == 422 and detail(r)["reason"] == "guide_answer_invalid"
    assert detail(r)["params"] == {"step": "treatments"}
    assert len(bench.guide.events(sid)) == before


def test_an_answer_that_does_not_parse_is_refused(bench, operator, sid):
    r = choose(bench, operator, sid, "analysis", {"method": "paired_block"})

    assert r.status_code == 422 and detail(r)["params"] == {"step": "analysis"}


def test_an_option_that_was_not_offered_is_refused(bench, operator, sid):
    before = len(bench.guide.events(sid))

    r = choose(bench, operator, sid, "crop", ANSWERS["crop"], ["moss"])

    assert r.status_code == 422 and detail(r)["reason"] == "guide_answer_invalid"
    assert len(bench.guide.events(sid)) == before


def test_a_step_outside_the_list_is_refused(bench, operator, sid):
    assert operator.get(f"{GUIDE}/{sid}/steps/dinner").status_code == 422
    assert choose(bench, operator, sid, "dinner", {}).status_code == 422


def test_the_options_of_a_step_are_the_servers(bench, operator, sid):
    body = operator.get(f"{GUIDE}/{sid}/steps/crop").json()

    assert body["step"] == "crop" and body["options"][0]["id"] == "lettuce"
    assert set(body["options"][0]) == {"id", "value", "label_en", "label_zh"}


def test_reopening_a_step_records_it(bench, operator, sid):
    r = bench.post(operator, f"{GUIDE}/{sid}/steps/crop/reopen")

    assert r.status_code == 200 and bench.guide.events(sid)[-1].kind == "reopened"


def test_a_complete_draft_reviews_ready_and_saves_through_the_normal_route(bench, operator, sid):
    answer_all(bench, operator, sid)
    review = operator.get(f"{GUIDE}/{sid}/review").json()
    assert review["ready"] is True and review["missing"] == []

    saved = bench.post(operator, "/wb/protocols", {"protocol": review["protocol"]})
    assert saved.status_code == 200
    body = {"protocol_id": review["protocol_id"], "version": review["version"]}
    view = bench.post(operator, f"{GUIDE}/{sid}/saved", body).json()

    assert view["saved"][0]["edited"] == []
    assert view["saved"][0]["digest"] == saved.json()["digest"]


def test_an_unfinished_draft_names_what_is_missing(bench, operator, sid):
    review = operator.get(f"{GUIDE}/{sid}/review").json()

    assert review["ready"] is False and review["protocol"] is None
    assert review["missing"] == list(ANSWERS)


def test_editing_the_question_in_the_form_is_recorded(bench, operator, sid):
    answer_all(bench, operator, sid)
    review = operator.get(f"{GUIDE}/{sid}/review").json()
    edited = {**review["protocol"], "question": "A question typed into the form instead"}
    assert bench.post(operator, "/wb/protocols", {"protocol": edited}).status_code == 200

    body = {"protocol_id": review["protocol_id"], "version": review["version"]}
    view = bench.post(operator, f"{GUIDE}/{sid}/saved", body).json()

    assert view["saved"][0]["edited"] == ["question"]


def test_saved_refuses_a_protocol_of_another_project(bench, operator, sid):
    other = new_project(bench, operator)
    bench.workflow.save_protocol(make_protocol(project_id=other), bench.designer)
    before = len(bench.guide.events(sid))

    r = bench.post(operator, f"{GUIDE}/{sid}/saved", {"protocol_id": "protocol-1", "version": 1})

    assert r.status_code == 409 and detail(r)["reason"] == "record_not_found"
    assert len(bench.guide.events(sid)) == before


def test_saved_refuses_a_protocol_that_does_not_exist(bench, operator, sid):
    r = bench.post(operator, f"{GUIDE}/{sid}/saved", {"protocol_id": "nope", "version": 1})

    assert r.status_code == 409 and detail(r)["reason"] == "record_not_found"
    assert [e.kind for e in bench.guide.events(sid)] == []


def test_a_new_project_gets_the_id_the_form_proposes(bench, operator, sid, pid):
    answer_all(bench, operator, sid)

    review = operator.get(f"{GUIDE}/{sid}/review").json()

    assert review["protocol_id"] == f"protocol-1-{pid[-6:]}" and review["version"] == 1


def test_a_project_with_a_protocol_starts_from_it(bench, operator, pid):
    bench.workflow.save_protocol(make_protocol(project_id=pid), bench.designer)

    sid = start(bench, operator, pid)
    view = operator.get(f"{GUIDE}/{sid}").json()
    review = operator.get(f"{GUIDE}/{sid}/review").json()

    assert [s["status"] for s in view["steps"]] == ["done"] * 6
    assert {s["chosen"]["source"] for s in view["steps"]} == {"carried"}
    origin = bench.guide.events(sid)[0].payload["carried_from"]
    assert origin == {"protocol_id": "protocol-1", "version": 1}
    assert review["protocol_id"] == "protocol-1" and review["version"] == 2
    assert review["ready"] is True
    kept = make_protocol().model_dump(mode="json")["allocations"]
    assert review["protocol"]["allocations"] == kept


def test_the_latest_saved_version_is_the_one_carried(bench, operator, pid):
    bench.workflow.save_protocol(make_protocol(project_id=pid), bench.designer)
    newer = make_protocol(project_id=pid, version=2, question="the second wording")
    bench.workflow.save_protocol(newer, bench.designer)

    sid = start(bench, operator, pid)

    answer = operator.get(f"{GUIDE}/{sid}").json()["steps"][0]["chosen"]["answer"]
    assert answer["question"] == "the second wording"


def test_after_saving_the_next_review_is_the_next_version(bench, operator, sid):
    answer_all(bench, operator, sid)
    first = operator.get(f"{GUIDE}/{sid}/review").json()
    bench.post(operator, "/wb/protocols", {"protocol": first["protocol"]})
    body = {"protocol_id": first["protocol_id"], "version": first["version"]}
    bench.post(operator, f"{GUIDE}/{sid}/saved", body)

    second = operator.get(f"{GUIDE}/{sid}/review").json()

    assert second["protocol_id"] == first["protocol_id"] and second["version"] == 2


def test_a_deprecated_variable_a_version_declared_may_be_kept(bench, operator, pid):
    bench.workflow.catalog = WITH_OLD
    old = make_protocol(project_id=pid, variables=("canopy_growth_old", "canopy_area_growth"))
    bench.workflow.store.put_protocol(old, bench.clock.now())
    sid = start(bench, operator, pid)
    measures = {
        "variables": ["canopy_growth_old", "canopy_area_growth"],
        "primary_endpoint": "canopy_area_growth",
    }
    fresh_sid = start(bench, operator, new_project(bench, operator))

    kept = choose(bench, operator, sid, "measures", measures)
    fresh = choose(bench, operator, fresh_sid, "measures", measures)

    assert kept.status_code == 200
    assert fresh.status_code == 422 and detail(fresh)["params"] == {"step": "measures"}


@pytest.mark.parametrize("design", ["paired_block", "two_group"])
def test_sample_size_matches_the_design_helper(operator, design):
    params = {"effect": 0.15, "sd": 0.1, "design": design}

    r = operator.get("/wb/guide/sample-size", params=params).json()

    assert r == {"n": estimate_sample_size(0.15, 0.1, design=design), "design": design}


def test_a_sample_size_needs_positive_numbers(operator):
    params = {"effect": 0, "sd": 0.1, "design": "paired_block"}

    assert operator.get("/wb/guide/sample-size", params=params).status_code == 422


def test_a_model_identity_cannot_use_a_guide_write_route(bench, operator, pid, sid):
    model = bench.model()
    before = len(bench.guide.events(sid))
    calls = [
        (GUIDE, {"project_id": pid}),
        (f"{GUIDE}/{sid}/steps/question/choose", {"answer": ANSWERS["question"]}),
        (f"{GUIDE}/{sid}/steps/question/reopen", {}),
        (f"{GUIDE}/{sid}/saved", {"protocol_id": "protocol-1", "version": 1}),
    ]

    for path, body in calls:
        r = bench.post(bench.lan, path, body, headers=model)
        assert r.status_code == 403 and detail(r)["code"] == "model_role", path

    assert len(bench.guide.events(sid)) == before


def test_an_unknown_session_is_refused(bench, operator):
    assert operator.get(f"{GUIDE}/guide-nothing").status_code == 409
    assert choose(bench, operator, "guide-nothing", "crop", {}).status_code == 409


def test_a_project_that_does_not_exist_cannot_start_a_session(bench, operator):
    r = bench.post(operator, GUIDE, {"project_id": "project-none"})

    assert r.status_code == 409 and detail(r)["reason"] == "record_not_found"


# --- more than one operator ------------------------------------------------------------------


@pytest.fixture
def world(tmp_path):
    bench = Bench.full(tmp_path)
    for name, role in (("alice", "user"), ("bob", "user"), ("root", "admin")):
        bench.user(name, role)
    alice = bench.user("alice")
    project = new_project(bench, alice)
    session = start(bench, alice, project)
    return bench, session


def test_only_the_operator_who_started_a_guide_can_change_it(world):
    bench, sid = world
    project = bench.guide.session(sid).project_id
    store = bench.workflow.store
    store.set_project_owner(project, "bob", "root", "handed over", bench.clock.now(), lambda: None)
    bob = bench.user("bob")  # now owns the project, but did not start the guide
    before = len(bench.guide.events(sid))

    r = choose(bench, bob, sid, "question", ANSWERS["question"])

    assert r.status_code == 409 and detail(r)["reason"] == "guide_not_owner"
    assert bench.post(bob, f"{GUIDE}/{sid}/steps/question/reopen").status_code == 409
    body = {"protocol_id": "protocol-1", "version": 1}
    assert bench.post(bob, f"{GUIDE}/{sid}/saved", body).status_code == 409
    assert len(bench.guide.events(sid)) == before
    assert bob.get(f"{GUIDE}/{sid}").status_code == 200  # the project's owner may read it


def test_an_administrator_reads_but_does_not_act_on_anothers_guide(world):
    bench, sid = world
    root = bench.user("root")

    r = choose(bench, root, sid, "question", ANSWERS["question"])

    assert r.status_code == 403 and detail(r)["reason"] == "not_owner"
    assert root.get(f"{GUIDE}/{sid}").status_code == 200


def test_another_operator_gets_the_answer_for_a_session_that_does_not_exist(world):
    bench, sid = world
    bob, twin = bench.user("bob"), bench.absent_twin().user("bob")
    paths = [f"{GUIDE}/{sid}", f"{GUIDE}/{sid}/review", f"{GUIDE}/{sid}/steps/crop"]

    for path in paths:
        seen, absent = bob.get(path), twin.get(path)
        assert (seen.status_code, seen.json()) == (absent.status_code, absent.json()), path
        assert seen.status_code >= 400
    written = choose(bench, bob, sid, "question", ANSWERS["question"])
    assert detail(written)["reason"] == "record_not_found"


def test_another_operator_cannot_start_a_session_on_the_project(world):
    bench, sid = world
    project = bench.guide.session(sid).project_id

    r = bench.post(bench.user("bob"), GUIDE, {"project_id": project})

    assert r.status_code == 409 and detail(r)["reason"] == "record_not_found"
