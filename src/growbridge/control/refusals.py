"""The refusals device control raises: each builds its own English message, coarse code, reason
and params (``growbridge.denial_codes``). Callers ``raise`` the result."""

from growbridge.ports import Denied


def other_host_registered(device_id: str) -> Denied:
    return Denied(
        "host_unregistered",
        "another host is registered for this device",
        reason="other_host_registered",
        params={"device_id": device_id},
    )


def not_write_host(device_id: str) -> Denied:
    return Denied(
        "host_unregistered",
        "this host is not the registered write host",
        reason="not_write_host",
        params={"device_id": device_id},
    )


def state_unreadable(device_id: str, error: Exception) -> Denied:
    return Denied(
        "not_connected",
        str(error),
        reason="state_unreadable",
        params={"device_id": device_id, "detail": str(error)},
    )


def unknown_device(device_id: str) -> Denied:
    return Denied(
        "scope",
        f"{device_id} is not the controlled device",
        reason="unknown_device",
        params={"device_id": device_id},
    )


def right_held(device_id: str, stage_id: str | None) -> Denied:
    return Denied(
        "right_held",
        "a stage write right is already held for this device",
        reason="right_held",
        params={"device_id": device_id, "stage_id": stage_id},
    )


def safety_needs_approver() -> Denied:
    return Denied(
        "approval_invalid",
        "the safety configuration needs an approver",
        reason="safety_needs_approver",
    )


def safety_unknown_sensors(names: list[str]) -> Denied:
    return Denied(
        "approval_invalid",
        f"frozen thresholds name sensors the device does not have: {', '.join(names)}",
        reason="safety_unknown_sensors",
        params={"sensors": names},
    )


def safety_version_not_above(version: int, current_version: int) -> Denied:
    """``current_version`` is the highest version ever approved on the device (0 before the
    first), in force or not: a repeated number would make two approved sets look the same."""
    return Denied(
        "state",
        f"safety configuration version {version} is not above version {current_version},"
        " the highest approved so far",
        reason="safety_version_not_above",
        params={"version": version, "current_version": current_version},
    )


def onsite_needs_operator() -> Denied:
    return Denied(
        "not_operator",
        "an on-site check needs an identified operator",
        reason="not_operator",
    )


def irrigation_seconds_range(seconds: object, limit: float) -> Denied:
    return Denied(
        "scope",
        f"irrigation must run for more than 0 and at most {limit} s",
        reason="irrigation_seconds_range",
        params={"seconds": seconds, "max_seconds": limit},
    )


def irrigation_wrong_request() -> Denied:
    return Denied(
        "scope",
        "irrigation switches the pump on (channel pump, level 1)",
        reason="irrigation_wrong_request",
    )


def irrigation_running(device_id: str) -> Denied:
    return Denied(
        "cooldown",
        "an irrigation is already running",
        reason="irrigation_running",
        params={"device_id": device_id},
    )


def irrigation_too_soon(cooldown: float, last: float, now: float) -> Denied:
    """``last`` is when the previous irrigation started; it may run again at last + cooldown."""
    return Denied(
        "cooldown",
        f"the pump needs {cooldown} s between irrigations",
        reason="irrigation_too_soon",
        params={"wait_seconds": max(0.0, cooldown - (now - last)), "ready_at": last + cooldown},
    )


def request_id_reused(request_id: str) -> Denied:
    return Denied(
        "request_id_reused",
        f"{request_id} was used for other arguments",
        reason="request_id_reused",
        params={"request_id": request_id},
    )


def controls_disabled() -> Denied:
    return Denied(
        "controls_disabled",
        "controls are disabled in the local configuration",
        reason="controls_disabled",
    )


def restore_invalid(detail: str) -> Denied:
    return Denied(
        "param",
        f"cannot restore this snapshot: {detail}",
        reason="restore_invalid",
        params={"detail": detail},
    )


def right_wrong_kind(right_id: int) -> Denied:
    return Denied(
        "right_invalid",
        "irrigation needs a manual write right, or the stage right for a planned one",
        reason="right_wrong_kind",
        params={"right_id": right_id},
    )


def still_starting() -> Denied:
    return Denied(
        "unsettled",
        "the control service has not finished starting up",
        reason="still_starting",
    )


def pump_unconfirmed(device_id: str) -> Denied:
    return Denied(
        "interlock",
        "pump off is unconfirmed; ordinary writes are blocked",
        reason="pump_unconfirmed",
        params={"device_id": device_id},
    )


def old_path_running() -> Denied:
    return Denied(
        "unsettled",
        "the old write path is not confirmed stopped",
        reason="old_path_running",
    )


def unknown_result(count: int) -> Denied:
    return Denied(
        "unsettled",
        "an earlier action has an unknown result",
        reason="unknown_result",
        params={"count": count},
    )


def no_live_link(device_id: str) -> Denied:
    return Denied(
        "not_connected",
        "no live BLE connection",
        reason="no_live_link",
        params={"device_id": device_id},
    )


def stale(device_id: str, age_seconds: float | None) -> Denied:
    return Denied(
        "stale",
        "fresh device telemetry is required before an ordinary write",
        reason="stale",
        params={"device_id": device_id, "age_seconds": age_seconds},
    )


def right_voided(right_id: int) -> Denied:
    return Denied(
        "right_invalid",
        "the queued action was voided before it was sent",
        reason="right_voided",
        params={"right_id": right_id},
    )
