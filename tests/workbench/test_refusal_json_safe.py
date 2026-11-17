"""A refusal whose params hold a value JSON cannot carry still answers with its status and a
JSON body, never a 500."""

import json
import math

import pytest

from growbridge.httperror import CodedHTTPError
from growbridge.ports import Denied
from growbridge.workbench.api import not_found, refusal
from growbridge.workbench.common import rejected

AWKWARD = {"seconds": math.inf, "also": math.nan, "names": ["\ud800"]}


def check_body(body: dict) -> None:
    assert body["params"] == {"seconds": "inf", "also": "nan", "names": ["\\ud800"]}


def test_a_refusal_with_inf_nan_and_a_lone_surrogate_still_has_its_status_and_a_json_body():
    response = refusal(Denied("param", "bad", reason="irrigation_seconds_range", params=AWKWARD))

    assert response.status_code == 403
    check_body(json.loads(response.body)["detail"])


def test_a_not_found_with_awkward_params_still_answers_404_with_a_json_body():
    response = not_found(Denied("state", "gone", reason="record_not_found", params=AWKWARD))

    assert response.status_code == 404
    check_body(json.loads(response.body)["detail"])


def test_a_rejected_422_with_awkward_params_has_a_json_safe_detail():
    error = rejected("bad", reason="param_unknown_fields", params=AWKWARD)

    assert error.status_code == 422
    check_body(json.loads(json.dumps(error.detail, ensure_ascii=False).encode("utf-8")))


def test_a_coded_http_error_with_awkward_params_has_a_json_safe_body():
    error = CodedHTTPError(409, "bad", code="state", reason="record_not_found", params=AWKWARD)

    check_body(json.loads(json.dumps(error.body(), ensure_ascii=False).encode("utf-8")))


@pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan])
def test_every_non_finite_float_becomes_text(value):
    response = refusal(Denied("param", "x", reason="r", params={"v": value}))

    assert json.loads(response.body)["detail"]["params"]["v"] == str(value)
