"""A body that holds a lone surrogate is refused with a readable 422, never a server error."""


def test_a_lone_surrogate_in_a_workbench_body_is_a_readable_422(bench, operator):
    raw = '{"name": "series \\ud800"}'  # JSON text: a lone surrogate escape
    headers = {**bench.ui(operator), "content-type": "application/json"}

    response = operator.post("/wb/projects", content=raw, headers=headers)

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][-1] == "name"
    assert "series" in response.text  # what was sent is still shown, with the surrogate escaped
