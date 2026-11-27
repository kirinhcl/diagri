"""Write-right rules that need no I/O: what a right may carry and what it may write (spec 7.1)."""

from growbridge.archive.models import (
    ActionRecord,
    ActionState,
    Channel,
    RightKind,
    RuleAction,
    WriteRight,
    check_level,
)
from growbridge.ports import ActionRequest, Denied, RightScope

LISTED_LEVEL_KINDS = (RightKind.CARE, RightKind.PROTECTION)
ORDINARY_KINDS = (RightKind.STAGE, RightKind.MANUAL, RightKind.TEST)
OPERATOR_KINDS = (RightKind.MANUAL, RightKind.TEST)  # bound to an authenticated operator


def build_right(
    kind: RightKind, scope: RightScope, operator: str | None, recovery: int, at: float
) -> WriteRight:
    """A right ready to store (``number`` is assigned by the ledger); raises ``Denied``."""
    channels = scope.channels
    if kind in LISTED_LEVEL_KINDS:
        if not scope.levels:
            raise Denied(
                "scope",
                f"a {kind.value} right must list the values it may write",
                reason="right_incomplete",
                params={"right_id": None},
            )
        if not channels:
            channels = tuple(dict.fromkeys(level.channel for level in scope.levels))
    if kind in OPERATOR_KINDS and not (operator and operator.strip()):
        raise Denied(
            "right_invalid",
            f"a {kind.value} right is bound to an authenticated operator",
            reason="right_needs_operator",
            params={"right_id": None},
        )
    return WriteRight(
        number=0,
        kind=kind,
        device_id=scope.device_id,
        recovery_number=recovery,
        granted_at=at,
        channels=channels,
        levels=scope.levels if kind in LISTED_LEVEL_KINDS else (),
        experiment_id=scope.experiment_id,
        stage_id=scope.stage_id,
        run_sheet_digest=scope.run_sheet_digest,
        operator=operator,
    )


def check_valid(right: WriteRight | None, device_id: str, recovery: int, number: int) -> WriteRight:
    if right is None:
        raise Denied(
            "right_invalid",
            "unknown write right",
            reason="right_unknown",
            params={"right_id": number},
        )
    if right.revoked_at is not None:
        raise Denied(
            "right_invalid",
            f"write right {right.number} was revoked",
            reason="right_revoked",
            params={"right_id": right.number},
        )
    if right.recovery_number != recovery or right.device_id != device_id:
        raise Denied(
            "right_invalid",
            f"write right {right.number} is from an earlier recovery",
            reason="right_from_old_recovery",
            params={"right_id": right.number},
        )
    return right


def check_scope(right: WriteRight, request: ActionRequest) -> None:
    """The request must stay inside the channels, values, stage and operator of the right."""
    if request.channel not in right.channels:
        raise Denied(
            "scope",
            f"{request.channel.value} is outside write right {right.number}",
            reason="right_channel",
            params={"right_id": right.number, "channel": request.channel.value},
        )
    try:
        check_level(request.channel, request.level)
    except ValueError as error:
        raise Denied(
            "scope",
            str(error),
            reason="right_value",
            params={
                "right_id": right.number,
                "channel": request.channel.value,
                "level": request.level,
            },
        ) from error
    if right.kind in LISTED_LEVEL_KINDS:
        wanted = RuleAction(channel=request.channel, level=request.level)
        if wanted not in right.levels:
            raise Denied(
                "scope",
                f"{request.channel.value}={request.level} is not a listed value",
                reason="right_value",
                params={
                    "right_id": right.number,
                    "channel": request.channel.value,
                    "level": request.level,
                },
            )
    for name in ("experiment_id", "stage_id", "operator"):
        claimed, granted = getattr(request, name), getattr(right, name)
        if claimed is not None and granted is not None and claimed != granted:
            raise Denied(
                "scope",
                f"{name} does not match write right {right.number}",
                reason="right_binding",
                params={"right_id": right.number, "stage_id": right.stage_id},
            )


def check_pump_not_started(request: ActionRequest) -> None:
    if request.channel is Channel.PUMP and request.level != 0:
        raise Denied(
            "pump_on_forbidden",
            "only an operator-triggered irrigation starts the pump",
            reason="pump_on_forbidden",
        )


def intent(
    request: ActionRequest, right: WriteRight, planned_level: int, now: float
) -> ActionRecord:
    """The ledger entry written before anything is sent (state PENDING)."""
    return ActionRecord(
        request_id=request.request_id,
        state=ActionState.PENDING,
        channel=request.channel,
        planned_level=planned_level,
        right_number=right.number,
        right_kind=right.kind,
        trigger=request.trigger,
        created_at=now,
        operator=request.operator or right.operator,
        experiment_id=request.experiment_id or right.experiment_id,
        stage_id=request.stage_id or right.stage_id,
        supersedes=request.supersedes,
    )
