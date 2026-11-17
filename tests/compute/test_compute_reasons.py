"""Every refusal of the compute service carries a registered reason and its params."""

import math

import pytest
from compute_support import GOOD_PARAMS, INPUTS, TEMPLATE

from growbridge.compute.backend import JobTemplate, ParamSpec
from growbridge.compute.service import MAX_TEXT_CHARS, validate_params
from growbridge.ports import Denied


def spec_template(**specs: ParamSpec) -> JobTemplate:
    return TEMPLATE.model_copy(update={"parameters": specs})


def refused_value(spec: ParamSpec, value) -> Denied:
    with pytest.raises(Denied) as info:
        validate_params(spec_template(x=spec), {"x": value})
    return info.value


async def submit(env, who="alice"):
    return await env.service.submit_compute_job("t1", who, "segment", GOOD_PARAMS, INPUTS)


async def failed_attempt(env):
    attempt = await submit(env)
    env.backend.finish(attempt.remote_job_id, ok=False)
    return await env.service.get_compute_job(attempt.id, "alice")


async def done_attempt(env):
    attempt = await submit(env)
    env.backend.finish(attempt.remote_job_id)
    await env.service.get_compute_job(attempt.id, "alice")
    await env.service.fetch_compute_artifacts(attempt.id, "alice", env.tmp / "out")
    return attempt


def test_param_too_long_carries_the_field_and_the_limit():
    error = refused_value(ParamSpec(kind="str", pattern=".*", max_length=5), "abcdef")
    assert (error.reason, error.params) == ("param_too_long", {"field": "x", "max_length": 5})


def test_param_too_long_caps_a_text_without_a_declared_length():
    error = refused_value(ParamSpec(kind="str", pattern=".*"), "a" * (MAX_TEXT_CHARS + 1))
    assert error.params == {"field": "x", "max_length": MAX_TEXT_CHARS}


def test_param_bad_characters_carries_the_field():
    error = refused_value(ParamSpec(kind="str", pattern=".*"), "a\nb")
    assert (error.reason, error.params) == ("param_bad_characters", {"field": "x"})


def test_param_bad_format_carries_the_field():
    error = refused_value(ParamSpec(kind="str", pattern="[a-z]+"), "A1")
    assert (error.reason, error.params) == ("param_bad_format", {"field": "x"})


def test_param_not_in_choices_carries_the_field_and_the_choices():
    error = refused_value(ParamSpec(kind="str", choices=("small", "large")), "huge")
    assert error.reason == "param_not_in_choices"
    assert error.params == {"field": "x", "choices": ["small", "large"]}


def test_param_wrong_type_carries_the_field_and_the_expected_kind():
    error = refused_value(ParamSpec(kind="int"), "three")
    assert (error.reason, error.params) == (
        "param_wrong_type",
        {"field": "x", "expected_kind": "int"},
    )


def test_param_not_finite_carries_the_field():
    error = refused_value(ParamSpec(kind="float"), math.nan)
    assert (error.reason, error.params) == ("param_not_finite", {"field": "x"})


def test_param_out_of_range_carries_both_bounds():
    error = refused_value(ParamSpec(kind="int", minimum=1, maximum=1000), 5000)
    assert error.reason == "param_out_of_range"
    assert error.params == {"field": "x", "minimum": 1, "maximum": 1000}


def test_param_below_minimum_carries_only_the_minimum():
    error = refused_value(ParamSpec(kind="int", minimum=1), 0)
    assert (error.reason, error.params) == ("param_below_minimum", {"field": "x", "minimum": 1})


def test_param_above_maximum_carries_only_the_maximum():
    error = refused_value(ParamSpec(kind="float", maximum=2.5), 3.0)
    assert (error.reason, error.params) == ("param_above_maximum", {"field": "x", "maximum": 2.5})


def test_param_unknown_fields_carries_the_names():
    with pytest.raises(Denied) as info:
        validate_params(TEMPLATE, {**GOOD_PARAMS, "zeta": 1, "alpha": 2})
    assert info.value.reason == "param_unknown_fields"
    assert info.value.params == {"names": ["alpha", "zeta"]}


def test_param_required_carries_the_field():
    with pytest.raises(Denied) as info:
        validate_params(TEMPLATE, {})
    assert (info.value.reason, info.value.params) == ("param_required", {"field": "epochs"})


async def test_param_required_names_the_reason_of_a_settlement(env):
    attempt = await submit(env)
    with pytest.raises(Denied) as info:
        await env.service.settle_attempt(attempt.id, "carol", "  ")
    assert (info.value.reason, info.value.params) == ("param_required", {"field": "reason"})


def test_param_negative_amount_carries_the_field(env):
    with pytest.raises(Denied) as info:
        env.service.set_task_budget("t1", 5.0, -1.0)
    assert info.value.reason == "param_negative_amount"
    assert info.value.params == {"field": "storage_gb"}


async def test_param_bad_input_path_carries_the_input_name(env):
    with pytest.raises(Denied) as info:
        await env.service.submit_compute_job(
            "t1", "alice", "segment", GOOD_PARAMS, {"images": "../outside"}
        )
    assert (info.value.reason, info.value.params) == ("param_bad_input_path", {"field": "images"})


async def test_param_input_missing_carries_the_input_name(env):
    with pytest.raises(Denied) as info:
        await env.service.submit_compute_job(
            "t1", "alice", "segment", GOOD_PARAMS, {"images": "s1/nothing_here"}
        )
    assert (info.value.reason, info.value.params) == ("param_input_missing", {"field": "images"})


async def test_inputs_unavailable_carries_no_params(env):
    env.service.input_root = None
    with pytest.raises(Denied) as info:
        await submit(env)
    assert (info.value.reason, info.value.params) == ("inputs_unavailable", {})


async def test_template_not_found_carries_the_template_id(env):
    with pytest.raises(Denied) as info:
        await env.service.submit_compute_job("t1", "alice", "nope", GOOD_PARAMS, INPUTS)
    assert info.value.reason == "template_not_found"
    assert info.value.params == {"template_id": "nope"}


async def test_template_version_unregistered_carries_template_and_version(env):
    failed = await failed_attempt(env)
    env.service.templates["segment"] = TEMPLATE.model_copy(update={"version": 2})
    with pytest.raises(Denied) as info:
        await env.service.retry(failed.id, {})
    assert info.value.reason == "template_version_unregistered"
    assert info.value.params == {"template_id": "segment", "version": 1}


async def test_attempt_already_final_carries_the_attempt_and_phase(env):
    attempt = await done_attempt(env)
    with pytest.raises(Denied) as info:
        await env.service.settle_attempt(attempt.id, "carol", "again")
    assert info.value.reason == "attempt_already_final"
    assert info.value.params == {"attempt_id": attempt.id, "phase": "done"}


async def test_attempt_settled_by_operator_carries_the_attempt(env):
    attempt = await submit(env)
    await env.service.settle_attempt(attempt.id, "carol", "gone")
    with pytest.raises(Denied) as info:
        await env.service.fetch_compute_artifacts(attempt.id, "alice", env.tmp / "out")
    assert info.value.reason == "attempt_settled_by_operator"
    assert info.value.params == {"attempt_id": attempt.id}


async def test_attempt_not_cancellable_carries_the_attempt_and_phase(env):
    attempt = await done_attempt(env)
    with pytest.raises(Denied) as info:
        await env.service.cancel(attempt.id, "alice")
    assert info.value.reason == "attempt_not_cancellable"
    assert info.value.params == {"attempt_id": attempt.id, "phase": "done"}


async def test_attempt_nothing_to_fetch_carries_the_attempt_and_phase(env):
    attempt = await submit(env)
    with pytest.raises(Denied) as info:
        await env.service.fetch_compute_artifacts(attempt.id, "alice", env.tmp / "out")
    assert info.value.reason == "attempt_nothing_to_fetch"
    assert info.value.params == {"attempt_id": attempt.id, "phase": attempt.phase}


async def test_attempt_outputs_over_limit_carries_the_attempt(env):
    attempt = await submit(env)
    env.backend.finish(attempt.remote_job_id)
    await env.service.get_compute_job(attempt.id, "alice")
    env.service._update(
        attempt.id, phase="needs_review", error="too big", error_code="output_limit"
    )
    with pytest.raises(Denied) as info:
        await env.service.fetch_compute_artifacts(attempt.id, "alice", env.tmp / "out")
    assert (info.value.reason, info.value.params) == (
        "attempt_outputs_over_limit",
        {"attempt_id": attempt.id},
    )


async def test_attempt_no_storage_limit_carries_the_attempt_and_template(env):
    attempt = await submit(env)
    env.backend.finish(attempt.remote_job_id)
    await env.service.get_compute_job(attempt.id, "alice")
    env.db.execute(
        "UPDATE compute_attempts SET storage_limit_gb = NULL WHERE id = ?", (attempt.id,)
    )
    env.service.templates.clear()
    with pytest.raises(Denied) as info:
        await env.service.fetch_compute_artifacts(attempt.id, "alice", env.tmp / "out")
    assert info.value.reason == "attempt_no_storage_limit"
    assert info.value.params == {"attempt_id": attempt.id, "template_id": "segment"}


async def test_attempt_not_retryable_carries_the_attempt_and_phase(env):
    attempt = await submit(env)
    with pytest.raises(Denied) as info:
        await env.service.retry(attempt.id, {})
    assert info.value.reason == "attempt_not_retryable"
    assert info.value.params == {"attempt_id": attempt.id, "phase": attempt.phase}


async def test_attempt_other_submitter_carries_the_attempt(env):
    attempt = await submit(env)
    with pytest.raises(Denied) as info:
        await env.service.cancel(attempt.id, "bob")
    assert (info.value.reason, info.value.params) == (
        "attempt_other_submitter",
        {"attempt_id": attempt.id},
    )


async def test_an_unknown_attempt_is_record_not_found(env):
    with pytest.raises(Denied) as info:
        await env.service.cancel("att_missing", "alice")
    assert info.value.reason == "record_not_found"
    assert info.value.params == {"record_kind": "attempt", "record_id": "att_missing"}


async def test_member_carries_no_params(env):
    with pytest.raises(Denied) as info:
        await submit(env, who="mallory")
    assert (info.value.reason, info.value.params) == ("member", {})


async def test_quota_not_recorded_carries_the_task(env):
    env.db.execute("DELETE FROM compute_task_budgets")
    with pytest.raises(Denied) as info:
        await submit(env)
    assert (info.value.reason, info.value.params) == ("quota_not_recorded", {"task_id": "t1"})


@pytest.mark.parametrize(
    ("caps", "reason", "resource", "need", "available"),
    [
        ({"task_cpu": 4.0}, "quota_over_task_budget", "cpu_hours", 10.0, 4.0),
        ({"task_storage": 2.0}, "quota_over_task_budget", "storage_gb", 5.0, 2.0),
        ({"cpu_cap": 6.0}, "quota_over_service_cap", "cpu_hours", 10.0, 6.0),
        ({"storage_cap": 3.0}, "quota_over_service_cap", "storage_gb", 5.0, 3.0),
    ],
)
async def test_quota_over_carries_the_resource_and_both_amounts(
    env, caps, reason, resource, need, available
):
    service = await env.build(**caps)
    with pytest.raises(Denied) as info:
        await service.submit_compute_job("t1", "alice", "segment", GOOD_PARAMS, INPUTS)
    assert info.value.reason == reason
    assert info.value.params == {
        "resource": resource,
        "need_amount": need,
        "available_amount": available,
    }


async def test_quota_over_balance_carries_the_cpu_hours(env):
    env.service.record_balance(3.0, "carol")
    with pytest.raises(Denied) as info:
        await submit(env)
    assert info.value.reason == "quota_over_balance"
    assert info.value.params == {
        "resource": "cpu_hours",
        "need_amount": 10.0,
        "available_amount": 3.0,
    }


async def test_quota_retry_limit_carries_the_maximum(env):
    current = await failed_attempt(env)
    for _ in range(2):
        current, _ = await env.service.retry(current.id, {})
        env.backend.finish(current.remote_job_id, ok=False)
        current = await env.service.get_compute_job(current.id, "alice")
    with pytest.raises(Denied) as info:
        await env.service.retry(current.id, {})
    assert (info.value.reason, info.value.params) == ("quota_retry_limit", {"max_retries": 2})
