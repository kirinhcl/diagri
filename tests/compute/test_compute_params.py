"""Parameter values are bounded before they reach a remote environment."""

import math

import pytest
from pydantic import ValidationError

from growbridge.compute.backend import JobTemplate, ParamSpec
from growbridge.compute.service import MAX_TEXT_CHARS, validate_params
from growbridge.ports import Denied


def template(**specs: ParamSpec) -> JobTemplate:
    return JobTemplate(
        id="t",
        version=1,
        script="#!/bin/bash\n#SBATCH --time=10\n",
        parameters=specs,
        max_cpu_hours=1.0,
        max_storage_gb=1.0,
    )


def refused(spec: ParamSpec, value) -> Denied:
    with pytest.raises(Denied) as info:
        validate_params(template(x=spec), {"x": value})
    assert info.value.code == "param"
    return info.value


RUN_ID = ParamSpec(kind="str", pattern=r"[a-z0-9_]{1,32}")


def test_params_a_value_matching_the_pattern_in_full_is_accepted():
    assert validate_params(template(x=RUN_ID), {"x": "run_01"}) == {"x": "run_01"}


@pytest.mark.parametrize(
    "value",
    ["x; rm -rf /", "run 01", "$(id)", "run_01\n", "RUN", "", "a" * 33, "run_01 && true"],
)
def test_params_a_value_that_does_not_match_the_whole_pattern_is_refused(value):
    refused(RUN_ID, value)


def test_params_the_pattern_has_to_match_from_the_start_not_just_somewhere():
    refused(ParamSpec(kind="str", pattern=r"[a-z]+"), "abc1")
    refused(ParamSpec(kind="str", pattern=r"[a-z]+"), "1abc")


def test_params_max_length_is_enforced_even_where_the_pattern_would_allow_more():
    spec = ParamSpec(kind="str", pattern=r".*", max_length=5)
    assert validate_params(template(x=spec), {"x": "abcde"}) == {"x": "abcde"}
    refused(spec, "abcdef")


def test_params_text_has_a_global_cap_when_the_template_states_no_length():
    spec = ParamSpec(kind="str", pattern=r".*")
    refused(spec, "a" * (MAX_TEXT_CHARS + 1))


def test_params_a_value_with_a_nul_or_control_character_is_refused_whatever_the_pattern():
    spec = ParamSpec(kind="str", pattern=r".*")
    refused(spec, "a\x00b")
    refused(spec, "a\nb")


def test_params_choices_still_work_without_a_pattern():
    spec = ParamSpec(kind="str", choices=("small", "large"))
    assert validate_params(template(x=spec), {"x": "small"}) == {"x": "small"}
    refused(spec, "huge")


@pytest.mark.parametrize("bad", ["[unclosed", "(?P<n>", "*x"])
def test_params_an_invalid_pattern_cannot_be_declared(bad):
    with pytest.raises(ValidationError):
        ParamSpec(kind="str", pattern=bad)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_params_a_float_that_is_not_finite_is_refused_even_without_a_range(value):
    refused(ParamSpec(kind="float"), value)


@pytest.mark.parametrize("value", [math.nan, math.inf])
def test_params_a_float_that_is_not_finite_is_refused_inside_a_range_too(value):
    refused(ParamSpec(kind="float", minimum=0.0, maximum=1.0), value)


@pytest.mark.parametrize("field", ["max_cpu_hours", "max_storage_gb"])
@pytest.mark.parametrize("bad", [-1.0, math.nan, math.inf])
def test_template_limits_must_be_finite_and_not_negative(field, bad):
    values = {"max_cpu_hours": 1.0, "max_storage_gb": 1.0, field: bad}
    with pytest.raises(ValidationError):
        JobTemplate(id="t", version=1, script="#!/bin/bash\n", parameters={}, **values)


def test_template_zero_limits_are_allowed():
    JobTemplate(
        id="t",
        version=1,
        script="#!/bin/bash\n",
        parameters={},
        max_cpu_hours=0.0,
        max_storage_gb=0.0,
    )
