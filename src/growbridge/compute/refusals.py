"""The refusals the compute service raises: each builds its own English message, coarse code,
reason and params (``growbridge.denial_codes``). Callers ``raise`` the result."""

from collections.abc import Sequence

from growbridge.ports import Denied


def param_too_long(field: str, limit: int) -> Denied:
    message = f"{field} is longer than {limit} characters"
    return Denied(
        "param", message, reason="param_too_long", params={"field": field, "max_length": limit}
    )


def param_bad_characters(field: str) -> Denied:
    return Denied(
        "param",
        f"{field} must not contain control characters",
        reason="param_bad_characters",
        params={"field": field},
    )


def param_bad_format(field: str) -> Denied:
    return Denied(
        "param",
        f"{field} does not match its pattern",
        reason="param_bad_format",
        params={"field": field},
    )


def param_not_in_choices(field: str, choices: Sequence[str]) -> Denied:
    message = f"{field} must be one of {list(choices)}"
    return Denied(
        "param",
        message,
        reason="param_not_in_choices",
        params={"field": field, "choices": list(choices)},
    )


def param_wrong_type(field: str, kind: str) -> Denied:
    return Denied(
        "param",
        f"{field} must be {kind}",
        reason="param_wrong_type",
        params={"field": field, "expected_kind": kind},
    )


def param_not_finite(field: str) -> Denied:
    return Denied(
        "param",
        f"{field} must be a finite number",
        reason="param_not_finite",
        params={"field": field},
    )


def param_out_of_range(field: str, minimum: float | None, maximum: float | None) -> Denied:
    """Names the bound or bounds the parameter declares, so the console text reads well."""
    message = f"{field} outside {minimum}..{maximum}"
    if minimum is not None and maximum is not None:
        return Denied(
            "param",
            message,
            reason="param_out_of_range",
            params={"field": field, "minimum": minimum, "maximum": maximum},
        )
    if minimum is not None:
        return Denied(
            "param",
            message,
            reason="param_below_minimum",
            params={"field": field, "minimum": minimum},
        )
    return Denied(
        "param", message, reason="param_above_maximum", params={"field": field, "maximum": maximum}
    )


def param_unknown_fields(names: list[str]) -> Denied:
    return Denied(
        "param",
        f"unknown parameters {names}",
        reason="param_unknown_fields",
        params={"names": names},
    )


def param_required(field: str, message: str | None = None) -> Denied:
    return Denied(
        "param", message or f"{field} is required", reason="param_required", params={"field": field}
    )


def param_negative_amount(field: str, what: str) -> Denied:
    message = f"{what} must be a finite, non-negative number"
    return Denied("param", message, reason="param_negative_amount", params={"field": field})


def param_bad_input_path(field: str) -> Denied:
    message = f"input {field} must be a relative path inside the snapshot"
    return Denied("param", message, reason="param_bad_input_path", params={"field": field})


def param_input_missing(field: str) -> Denied:
    return Denied(
        "param",
        f"input {field} is not available",
        reason="param_input_missing",
        params={"field": field},
    )


def inputs_unavailable() -> Denied:
    return Denied(
        "param",
        "inputs are unavailable: no input root or scope guard installed",
        reason="inputs_unavailable",
    )


def template_not_found(template_id: str) -> Denied:
    return Denied(
        "param",
        f"unknown template {template_id}",
        reason="template_not_found",
        params={"template_id": template_id},
    )


def template_version_unregistered(template_id: str, version: int) -> Denied:
    return Denied(
        "param",
        "the template version of the attempt is no longer registered",
        reason="template_version_unregistered",
        params={"template_id": template_id, "version": version},
    )


def attempt_not_found(attempt_id: str) -> Denied:
    return Denied(
        "state",
        f"unknown attempt {attempt_id}",
        reason="record_not_found",
        params={"record_kind": "attempt", "record_id": attempt_id},
    )


def attempt_not_cancellable(attempt_id: str, phase: str) -> Denied:
    message = f"cannot cancel an attempt in phase {phase}"
    return Denied(
        "state",
        message,
        reason="attempt_not_cancellable",
        params={"attempt_id": attempt_id, "phase": phase},
    )


def attempt_already_final(attempt_id: str, phase: str) -> Denied:
    message = f"an attempt in phase {phase} is already final"
    return Denied(
        "state",
        message,
        reason="attempt_already_final",
        params={"attempt_id": attempt_id, "phase": phase},
    )


def attempt_nothing_to_fetch(attempt_id: str, phase: str) -> Denied:
    message = f"nothing to fetch in phase {phase}"
    return Denied(
        "state",
        message,
        reason="attempt_nothing_to_fetch",
        params={"attempt_id": attempt_id, "phase": phase},
    )


def attempt_settled_by_operator(attempt_id: str, message: str) -> Denied:
    return Denied(
        "state", message, reason="attempt_settled_by_operator", params={"attempt_id": attempt_id}
    )


def attempt_outputs_over_limit(attempt_id: str) -> Denied:
    message = "the outputs are over the limit: an operator has to settle it"
    return Denied(
        "state", message, reason="attempt_outputs_over_limit", params={"attempt_id": attempt_id}
    )


def attempt_no_storage_limit(attempt_id: str, template_id: str) -> Denied:
    message = "no storage limit is known for this attempt: settle it"
    return Denied(
        "state",
        message,
        reason="attempt_no_storage_limit",
        params={"attempt_id": attempt_id, "template_id": template_id},
    )


def attempt_not_retryable(attempt_id: str, phase: str) -> Denied:
    message = f"only a failed attempt can be retried, not {phase}"
    return Denied(
        "state",
        message,
        reason="attempt_not_retryable",
        params={"attempt_id": attempt_id, "phase": phase},
    )


def attempt_other_submitter(attempt_id: str) -> Denied:
    return Denied(
        "scope",
        "the attempt belongs to another submitter",
        reason="attempt_other_submitter",
        params={"attempt_id": attempt_id},
    )


def member_unmapped(submitter: str) -> Denied:
    message = f"{submitter} is not mapped to a CSC project member"
    return Denied("member", message, reason="member")


def quota_not_recorded(task_id: str) -> Denied:
    return Denied(
        "quota",
        "no task budget or project balance recorded",
        reason="quota_not_recorded",
        params={"task_id": task_id},
    )


def quota_over_task_budget(resource: str, need: float, available: float) -> Denied:
    label = ("cpu hours" if resource == "cpu_hours" else "storage") + " over task budget"
    return Denied(
        "quota",
        f"{label}: need {need}, available {available}",
        reason="quota_over_task_budget",
        params={"resource": resource, "need_amount": need, "available_amount": available},
    )


def quota_over_service_cap(resource: str, need: float, available: float) -> Denied:
    label = ("cpu hours" if resource == "cpu_hours" else "storage") + " over service cap"
    return Denied(
        "quota",
        f"{label}: need {need}, available {available}",
        reason="quota_over_service_cap",
        params={"resource": resource, "need_amount": need, "available_amount": available},
    )


def quota_over_balance(resource: str, need: float, available: float) -> Denied:
    label = ("cpu hours" if resource == "cpu_hours" else "storage") + " over project balance"
    return Denied(
        "quota",
        f"{label}: need {need}, available {available}",
        reason="quota_over_balance",
        params={"resource": resource, "need_amount": need, "available_amount": available},
    )


def quota_retry_limit(max_retries: int) -> Denied:
    return Denied(
        "quota",
        f"retry limit of {max_retries} reached",
        reason="quota_retry_limit",
        params={"max_retries": max_retries},
    )
