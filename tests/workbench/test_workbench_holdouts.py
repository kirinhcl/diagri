"""Registering a holdout through the workbench: operators only, before any outcome data exists."""

import pytest
from fastapi.testclient import TestClient
from workbench_support import LAN_HOST, LAN_PORT, ROLE_TOKENS, SECRET

from growbridge.api import create_app
from growbridge.archive.models import ManualMeasurement
from growbridge.sim.clock import START
from growbridge.sim.fixtures import make_protocol
from growbridge.workbench.api import create_workbench

HOLDOUTS = "/wb/holdouts"
BODY = {
    "batch_ids": ["b3"],
    "development_batch_ids": ["dev-1", "dev-2"],
    "outcome_fields": ["yield_g", "canopy_score"],
}


def detail(response) -> dict:
    return response.json()["detail"]


def register(bench, client, **changes):
    body = {"project_id": bench.project_id, **BODY, **changes}
    return bench.post(client, HOLDOUTS, body)


def listing(bench, client, **params):
    return client.get(HOLDOUTS, params={"project_id": bench.project_id, **params})


def measurement(metric="yield_g", batch="b3", experiment="experiment-stage-1", ident="m1"):
    return ManualMeasurement(
        id=ident,
        experiment_id=experiment,
        batch=batch,
        plant_id="p0",
        layout_version="v1",
        measured_at=START,
        position="tent-1",
        method="ruler",
        metric=metric,
        value=12.5,
        unit="g",
        operator="alice",
    )


@pytest.fixture
def seeded(bench, operator):
    bench.pending()  # a project with one experiment, experiment-stage-1
    return bench


# --- registering -------------------------------------------------------------------------------


def test_an_operator_registers_a_holdout_and_the_server_makes_its_id(seeded, operator):
    response = register(seeded, operator)

    assert response.status_code == 200
    body = response.json()
    assert body["holdout_id"].startswith("holdout_")
    assert body["project_id"] == seeded.project_id
    assert body["batch_ids"] == ["b3"] and body["development_batch_ids"] == ["dev-1", "dev-2"]
    assert body["outcome_fields"] == ["yield_g", "canopy_score"]
    assert body["registered_by"] == "alice" and body["registered_at"] == seeded.clock.now()
    (stored,) = seeded.holdout.holdouts(seeded.project_id)
    assert stored.holdout_id == body["holdout_id"]


def test_the_id_and_the_registrant_come_from_the_server_never_the_body(seeded, operator):
    body = register(
        seeded, operator, holdout_id="mine", registered_by="mallory", operator="mallory"
    ).json()

    assert body["holdout_id"] != "mine" and body["registered_by"] == "alice"


def test_registering_needs_a_recent_reauthentication(seeded, operator):
    seeded.clock.advance(301)

    stale = register(seeded, operator)

    assert stale.status_code == 403 and detail(stale)["code"] == "reauth_required"
    assert seeded.holdout.holdouts(seeded.project_id) == ()
    assert seeded.post(operator, "/wb/reauth", {"secret": SECRET}).status_code == 200
    assert register(seeded, operator).status_code == 200


def test_an_unknown_project_is_refused_as_out_of_scope(seeded, operator):
    response = register(seeded, operator, project_id="no-such-project")

    assert response.status_code == 403 and detail(response)["code"] == "scope"
    assert seeded.holdout.holdouts("no-such-project") == ()


@pytest.mark.parametrize(
    "changes",
    [
        {"development_batch_ids": ["dev-1"]},
        {"development_batch_ids": ["dev-1", "b3"]},
        {"batch_ids": ["b3", "b3"]},
        {"development_batch_ids": ["dev-1", "dev-1"]},
    ],
    ids=["one-dev", "overlap", "dup-held", "dup-dev"],
)
def test_batch_lists_that_make_no_holdout_are_refused(seeded, operator, changes):
    response = register(seeded, operator, **changes)

    assert response.status_code == 403 and detail(response)["code"] == "batches"
    assert seeded.holdout.holdouts(seeded.project_id) == ()


@pytest.mark.parametrize(
    "changes",
    [
        {"batch_ids": [""]},
        {"development_batch_ids": ["dev-1", ""]},
        {"outcome_fields": [""]},
        {"batch_ids": []},
        {"outcome_fields": []},
    ],
    ids=["empty-held", "empty-dev", "empty-field", "no-held", "no-field"],
)
def test_empty_names_and_empty_lists_are_rejected(seeded, operator, changes):
    response = register(seeded, operator, **changes)

    assert response.status_code in (403, 422)
    assert seeded.holdout.holdouts(seeded.project_id) == ()


def test_repeated_outcome_fields_are_refused(seeded, operator):
    response = register(seeded, operator, outcome_fields=["yield_g", "yield_g"])

    assert response.status_code == 403 and detail(response)["code"] == "param"


# --- before any outcome data exists ------------------------------------------------------------


def test_a_holdout_is_refused_once_its_outcome_data_exists(seeded, operator):
    seeded.archive.add_measurement(measurement())  # an outcome of the batch to hold out

    response = register(seeded, operator)

    assert response.status_code == 409 and detail(response)["code"] == "state"
    assert "may already have been seen" in detail(response)["message"]
    assert "12.5" not in detail(response)["message"]
    assert seeded.holdout.holdouts(seeded.project_id) == ()


def test_a_corrected_outcome_still_counts(seeded, operator):
    seeded.archive.add_measurement(measurement())
    seeded.archive.add_measurement(measurement(ident="m2").model_copy(update={"corrects": "m1"}))

    assert register(seeded, operator).status_code == 409


@pytest.mark.parametrize(
    "row",
    [measurement(metric="temp"), measurement(batch="b1")],
    ids=["other-metric", "other-batch"],
)
def test_other_measurements_do_not_stand_in_the_way(seeded, operator, row):
    seeded.archive.add_measurement(row)

    assert register(seeded, operator).status_code == 200


def second_project_experiment(bench) -> str:
    """A real second project with a staged experiment of its own, declaring the same outcome."""
    designer = bench.designer
    project = bench.workflow.create_project("other series", designer)
    variables = ("canopy_area_growth", "yield_g")
    protocol = make_protocol(
        project_id=project, id="protocol-2", stages=("vegetative",), variables=variables
    )
    bench.workflow.save_protocol(protocol, designer)
    round_id = bench.workflow.create_round(project, protocol.id, designer)
    change = {"project_id": project, "protocol_id": "protocol-2", "experiment_id": "experiment-p2"}
    sheet = bench.sheet("stage-2").model_copy(update=change)
    bench.workflow.submit_run_sheet(round_id, sheet, designer)
    return "experiment-p2"


def post_measurement(bench, client, **changes):
    fields = {
        "experiment_id": "experiment-stage-1",
        "batch": "b3",
        "plant_id": "p0",
        "layout_version": "v1",
        "measured_at": START,
        "position": "tent-1",
        "method": "ruler",
        "metric": "yield_g",
        "value": 12.5,
        "unit": "g",
        **changes,
    }
    return bench.post(client, "/wb/measurements", fields)


def test_the_data_of_a_staged_experiment_of_another_project_does_not_count(seeded, operator):
    other = second_project_experiment(seeded)
    assert post_measurement(seeded, operator, experiment_id=other).status_code == 200

    assert register(seeded, operator).status_code == 200


def test_an_outcome_in_an_experiment_no_stage_owns_stands_in_the_way(seeded, operator):
    """Seeded straight into the archive: a record from before the measurement route checked."""
    seeded.archive.add_measurement(measurement(experiment="experiment-nobody-runs"))

    response = register(seeded, operator)

    assert response.status_code == 409 and detail(response)["code"] == "state"
    assert seeded.holdout.holdouts(seeded.project_id) == ()


def test_the_measurement_that_would_open_the_gap_is_refused_at_the_first_step(seeded, operator):
    """Reproduction: record an outcome for an experiment no stage owns, register the holdout,
    then give the project a stage for that experiment id."""
    first = post_measurement(seeded, operator, experiment_id="experiment-nobody-runs")

    assert first.status_code == 403 and detail(first)["code"] == "scope"
    assert "experiment of an existing stage" in detail(first)["message"]
    assert seeded.archive.measurements("experiment-nobody-runs") == ()
    assert register(seeded, operator).status_code == 200  # nothing was recorded to stop it


def test_a_measurement_of_a_staged_experiment_is_accepted_and_then_blocks_registering(
    seeded, operator
):
    assert post_measurement(seeded, operator).status_code == 200

    assert register(seeded, operator).status_code == 409


def test_the_scan_is_a_query_not_a_load_of_the_measurements(seeded, operator, monkeypatch):
    seeded.archive.add_measurement(measurement(experiment="experiment-stage-1", batch="b1"))

    def forbidden(*args, **kwargs):
        raise AssertionError("the registration read the measurements one by one")

    monkeypatch.setattr(seeded.archive, "measurements", forbidden)

    assert register(seeded, operator).status_code == 200


def test_after_registering_the_outcomes_leave_the_development_data(seeded, operator):
    register(seeded, operator)

    keep = seeded.holdout.development_filter(seeded.project_id)

    assert keep(measurement()) is False  # the held-out outcome is hidden from development
    assert keep(measurement(batch="dev-1")) is True


# --- listing -----------------------------------------------------------------------------------


def test_the_list_shows_each_holdout_with_its_reads_and_needs_no_reauthentication(seeded, operator):
    made = register(seeded, operator).json()
    holdout_id = made["holdout_id"]
    seeded.holdout.register_model(holdout_id, "m" * 64, "f" * 64, "p" * 64)
    seeded.holdout.evaluate(holdout_id, "script-a", "m" * 64)
    seeded.clock.advance(3600)  # the reauthentication is old; reading does not need it

    response = listing(seeded, operator)

    assert response.status_code == 200
    (item,) = response.json()["holdouts"]
    assert {k: item[k] for k in made} == made
    assert item["reads"] == [
        {
            "reader": "script-a",
            "at": item["reads"][0]["at"],
            "label": "confirmatory",
            "model_sha": "m" * 64,
        }
    ]


def test_the_list_of_a_project_with_no_holdout_is_empty_and_an_unknown_project_is_refused(
    seeded, operator
):
    assert listing(seeded, operator).json() == {"holdouts": []}

    unknown = listing(seeded, operator, project_id="no-such-project")

    assert unknown.status_code == 403 and detail(unknown)["code"] == "scope"


# --- who may call ------------------------------------------------------------------------------


def send(bench, client, name, headers=None, ui=True):
    if name == "list":
        return client.get(HOLDOUTS, params={"project_id": bench.project_id}, headers=headers)
    base = bench.ui(client) if ui else {}
    body = {"project_id": bench.project_id, **BODY}
    return client.post(HOLDOUTS, json=body, headers={**base, **(headers or {})})


@pytest.mark.parametrize("name", ["register", "list"])
def test_a_model_token_cannot_call_the_holdout_routes(seeded, name):
    response = send(seeded, seeded.lan, name, headers=seeded.model())

    assert response.status_code == 403 and detail(response)["code"] == "model_role"
    assert seeded.holdout.holdouts(seeded.project_id) == ()


@pytest.mark.parametrize("name", ["register", "list"])
def test_the_holdout_routes_need_a_session(seeded, name):
    visitor = TestClient(seeded.app, base_url=f"http://{LAN_HOST}:{LAN_PORT}")  # no cookie

    response = send(seeded, visitor, name)

    assert response.status_code == 401 and detail(response)["code"] == "session"


def test_registering_needs_the_workbench_origin_and_header(seeded, operator):
    no_header = send(seeded, operator, "register", ui=False)
    foreign = send(seeded, operator, "register", headers={"Origin": "http://evil.test"})

    for response in (no_header, foreign):
        assert response.status_code == 403 and detail(response)["code"] == "entry"
    assert seeded.holdout.holdouts(seeded.project_id) == ()


@pytest.mark.parametrize("name", ["register", "list"])
def test_a_session_of_the_other_entry_is_refused(seeded, operator, name):
    seeded.overlay.cookies.set("growbridge_operator", operator.cookies.get("growbridge_operator"))

    response = send(seeded, seeded.overlay, name)

    assert response.status_code == 403 and detail(response)["code"] == "entry"


def test_the_routes_are_absent_without_a_holdout_registry(seeded):
    args = (seeded.workflow, seeded.control, seeded.archive, seeded.operators, seeded.settings)
    app = create_app(
        seeded.settings, bridge=object(), workbench=create_workbench(*args, ROLE_TOKENS)
    )
    bare = TestClient(app, base_url=f"http://{LAN_HOST}:{LAN_PORT}")
    assert seeded.login(bare).status_code == 200

    assert register(seeded, bare).status_code == 404
    assert listing(seeded, bare).status_code == 404
