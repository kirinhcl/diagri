"""The refusals of device tests (design 2026-11-27), each with its registered reason and params.

One function per reason, so the reason stays a literal at the ``Denied(...)`` call (the AST test
in tests/workbench/test_denial_codes.py reads it there). The caller raises what these return.
"""

from growbridge.ports import Denied


def not_held(greenhouse_id: str) -> Denied:
    return Denied(
        "not_lock_holder",
        f"you do not hold greenhouse {greenhouse_id}",
        reason="greenhouse_not_held",
        params={"greenhouse_id": greenhouse_id},
    )


def not_local(greenhouse_id: str) -> Denied:
    return Denied(
        "state",
        f"this installation does not drive the device of greenhouse {greenhouse_id}",
        reason="device_test_not_local",
        params={"greenhouse_id": greenhouse_id},
    )


def not_idle(greenhouse_id: str) -> Denied:
    return Denied(
        "state",
        f"greenhouse {greenhouse_id} has a current stage: test its devices before a round only",
        reason="device_test_not_idle",
        params={"greenhouse_id": greenhouse_id},
    )


def running(greenhouse_id: str, channel: str) -> Denied:
    return Denied(
        "state",
        f"a device test ({channel}) is running on greenhouse {greenhouse_id}",
        reason="device_test_running",
        params={"greenhouse_id": greenhouse_id, "channel": channel},
    )


def unsettled(greenhouse_id: str, test_id: str) -> Denied:
    return Denied(
        "state",
        f"device test {test_id} on greenhouse {greenhouse_id} did not restore the device",
        reason="device_test_unsettled",
        params={"greenhouse_id": greenhouse_id, "test_id": test_id},
    )


def protected(greenhouse_id: str, channel: str) -> Denied:
    return Denied(
        "state",
        f"a protection rule holds {channel} on greenhouse {greenhouse_id}",
        reason="device_test_protected",
        params={"greenhouse_id": greenhouse_id, "channel": channel},
    )
