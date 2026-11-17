"""A manual measurement names a variable the experiment's protocol declared, in its unit."""

from growbridge.sim.fixtures import make_protocol

EXPERIMENT = "experiment-stage-1"  # the experiment of the bench's stage-1
UNKNOWN = "experiment-nobody-runs"


def measurement(**fields) -> dict:
    return {
        "experiment_id": EXPERIMENT,
        "batch": "batch-a",
        "plant_id": "plant-01",
        "layout_version": "layout-1",
        "measured_at": 1_799_999_000.0,
        "position": "tray-1",
        "method": "ruler",
        "metric": "height",
        "value": 12.5,
        "unit": "cm",
        **fields,
    }


def stored(bench):
    return bench.archive.measurements(EXPERIMENT, False)


def detail(response) -> dict:
    return response.json()["detail"]


def test_undeclared_metric_is_refused_with_422(bench, operator):
    bench.pending()

    response = bench.post(operator, "/wb/measurements", measurement(metric="heigth"))

    assert response.status_code == 422
    assert detail(response)["code"] == "param" and "height" in detail(response)["message"]
    assert stored(bench) == ()


def test_wrong_unit_is_refused(bench, operator):
    bench.pending()

    response = bench.post(operator, "/wb/measurements", measurement(unit="mm"))

    assert response.status_code == 422
    assert detail(response)["code"] == "param" and "cm" in detail(response)["message"]
    assert stored(bench) == ()


def test_variables_endpoint_lists_declared_variables(bench, operator):
    bench.pending()

    response = operator.get(f"/wb/experiments/{EXPERIMENT}/variables")

    assert response.status_code == 200
    body = response.json()
    assert body["experiment_id"] == EXPERIMENT
    variables = body["variables"]
    assert [item["id"] for item in variables] == ["canopy_area_growth", "height", "yield_g"]
    assert [item["unit"] for item in variables] == ["cm2/d", "cm", "g"]
    assert variables[1]["method"] == "ruler, soil to apex"
    assert all(item["method"] for item in variables)
    keys = {"id", "label_en", "label_zh", "unit", "method", "min", "max", "deprecated"}
    assert all(set(item) == keys for item in variables)


def test_variables_endpoint_refuses_unknown_experiment(bench, operator):
    bench.pending()

    read = operator.get(f"/wb/experiments/{UNKNOWN}/variables")
    write = bench.post(operator, "/wb/measurements", measurement(experiment_id=UNKNOWN))

    assert read.status_code == write.status_code == 403
    assert detail(read)["code"] == detail(write)["code"] == "scope"


def test_union_over_protocol_versions(bench, operator):
    bench.pending()
    score = measurement(id="m-score", metric="canopy_score", unit="{score}", value=3.0)
    assert bench.post(operator, "/wb/measurements", score).status_code == 422

    variables = ("canopy_area_growth", "canopy_score")
    v2 = make_protocol(
        project_id=bench.project_id, version=2, stages=("vegetative",), variables=variables
    )
    bench.workflow.save_protocol(v2, bench.designer)
    round_id = bench.workflow.create_round(bench.project_id, v2.id, bench.designer)
    change = {"experiment_id": EXPERIMENT, "protocol_version": 2}
    bench.workflow.submit_run_sheet(
        round_id, bench.sheet("stage-v2").model_copy(update=change), bench.designer
    )

    assert bench.post(operator, "/wb/measurements", measurement(id="m-height")).status_code == 200
    assert bench.post(operator, "/wb/measurements", score).status_code == 200
    assert {record.metric for record in stored(bench)} == {"height", "canopy_score"}


def test_variables_endpoint_needs_a_caller_and_a_model_may_read_it(bench):
    bench.pending()
    path = f"/wb/experiments/{EXPERIMENT}/variables"

    anonymous = bench.lan.get(path)
    model = bench.lan.get(path, headers=bench.model())

    assert anonymous.status_code == 401 and detail(anonymous)["code"] == "session"
    assert model.status_code == 200 and model.json()["experiment_id"] == EXPERIMENT
