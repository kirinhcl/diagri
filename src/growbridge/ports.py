"""Contracts between the Auto Research services (architecture doc §4, §7 and Appendix B).

Services depend on these protocols, never on each other's classes. The workflow service is the
only owner of stage state, the control service is the only BLE writer, the archive owns records.
Authorization always comes from the server side: an ``Actor`` is built from an authenticated
session or service identity, never from fields in model output.
"""

from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import Field

from growbridge.archive.models import (
    ActionRecord,
    Channel,
    Entry,
    Model,
    Quality,
    RightKind,
    RuleAction,
    RunSheet,
    SafetyConfig,
    SampleKind,
    SampleRecord,
    WriteRight,
)
from growbridge.workflow.states import StageState


class Denied(Exception):
    """A request was refused by a permission or control check.

    Codes used across services: ``host_unregistered``, ``controls_disabled``, ``right_invalid``,
    ``right_held``, ``scope``, ``pump_on_forbidden``, ``interlock``, ``not_connected``,
    ``stale``, ``request_id_reused``, ``not_operator``, ``model_role``, ``reauth_required``,
    ``entry``, ``approval_invalid``, ``state``, ``safety_conflict``, ``budget``, ``session``,
    ``member``, ``quota``, ``param`` (compute), ``clock_unsynced`` (archive), ``script_hash``,
    ``snapshot_incomplete``, ``already_run``, ``batches``, ``model_unregistered``,
    ``sandbox_unavailable`` (research), ``unsettled``, ``cooldown`` (control),
    ``unavailable`` (an optional backend is not configured), ``locked`` (login rate limit).
    """

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


class Actor(Model):
    kind: Literal["operator", "workflow", "observer", "model", "probe"]
    id: str
    entry: Entry | None = None  # which address the request arrived on; decided by the server
    reauth_at: float | None = None  # when the operator last re-authenticated


class PumpReading(Model):
    """The pump outlet as last read back from the panel; ``on`` is None when unknown."""

    on: bool | None
    at: float  # wall time the status was received
    mono: float  # monotonic time the status was received; 0.0 before the first status


PumpOffTrigger = Literal["interlock", "watchdog"]


class Reading(Model):
    sensor: str
    value: float | None
    unit: str
    at: float  # wall time the reading was received
    mono: float  # monotonic time the reading was received
    quality: Quality = "ok"


class DeviceState(Model):
    levels: dict[Channel, int]
    modes: dict[Channel, int]  # AC5 modeType per channel; 0 means manual (host-controlled)
    at: float


class Capabilities(Model):
    version: str
    sensors: dict[str, str]  # sensor name -> unit
    level_ranges: dict[Channel, tuple[int, int]]
    outlets: dict[Channel, int]


class RightScope(Model):
    device_id: str
    experiment_id: str | None = None
    stage_id: str | None = None
    run_sheet_digest: str | None = None
    channels: tuple[Channel, ...] = ()
    levels: tuple[RuleAction, ...] = ()  # required for care and protection rights


class ActionRequest(Model):
    request_id: str
    right_number: int
    channel: Channel
    level: int
    trigger: str  # the evidence for the write: timed action id, rule id, operator note
    experiment_id: str | None = None
    stage_id: str | None = None
    operator: str | None = None
    supersedes: str | None = None


class Difference(Model):
    channel: Channel
    field: Literal["level", "mode"]
    expected: int
    actual: int | None


class Finding(Model):
    code: str
    message: str
    blocking: bool = True


class RawSample(Model):
    cursor: int  # position in the source; ingestion resumes after the last stored cursor
    received_at: float
    captured_at: float | None = None
    mono: float | None = None
    clock_synced: bool = True
    source: SampleKind = "planned"
    data: dict[str, Any] = Field(default_factory=dict)


class StageRuntime(Model):
    """What the executor may know about the stage whose run sheet governs the device."""

    stage_id: str
    experiment_id: str
    project_id: str
    state: StageState
    run_sheet: RunSheet
    prior_state: StageState | None = None  # state before 恢复待核对
    right_number: int | None = None  # stage write right; None unless 执行中
    care_right: int | None = None  # None during 人工接管
    manual_right: int | None = None
    started_at: float | None = None
    paused_at: float | None = None
    end_pending: bool = False  # end condition met; end actions not yet confirmed
    ended_at: float | None = None  # when it actually ended or was stopped; None until then


class StageEventKind(StrEnum):
    DISCONNECT_AFFECTS = "disconnect_affects"
    READINGS_STALE = "readings_stale"
    EXTERNAL_CHANGE = "external_change"
    CLOCK_ANOMALY = "clock_anomaly"
    RESULT_UNKNOWN = "result_unknown"
    PUMP_OFF_UNCONFIRMED = "pump_off_unconfirmed"
    TRANSPORT_UNCONFIRMED = "transport_unconfirmed"
    END_CONDITION_MET = "end_condition_met"
    END_ACTIONS = "end_actions"  # detail: {"confirmed": bool}
    ALERT_PAUSE = "alert_pause"
    RULE_PAUSE = "rule_pause"
    MAX_WAIT_EXPIRED = "max_wait_expired"


class StageEvent(Model):
    event_id: str  # the same id advances the stage at most once
    kind: StageEventKind
    stage_id: str
    at: float
    detail: dict[str, Any] = Field(default_factory=dict)


PacketCallback = Callable[[bytes], None]


class WriteTransport(Protocol):
    """BLE transport. ``halt`` is the only source of old-write-stop confirmation (§7.3)."""

    connected: bool

    async def connect(self, callback: PacketCallback) -> None: ...

    async def send(self, command: dict[str, Any]) -> None: ...

    async def close(self) -> None: ...

    async def halt(self) -> bool:
        """True only when the old queue is empty and can no longer write, or the old process
        and its BLE session are both confirmed stopped. A timeout is not a confirmation."""
        ...


class SampleSource(Protocol):
    def read_after(self, cursor: int, limit: int) -> Sequence[RawSample]: ...


class RecordSink(Protocol):
    def append_sample(self, record: SampleRecord) -> None: ...

    def append_action(self, record: ActionRecord) -> None: ...


class StagePort(Protocol):
    """Implemented by the workflow service, read by the executor and the observer."""

    def active_stage(self) -> StageRuntime | None:
        """The stage whose run sheet currently governs the device, including the last ended
        stage while the next one waits for review (its care rules keep running)."""
        ...

    async def report(self, event: StageEvent) -> None: ...

    def record_intervention(self, stage_id: str, kind: str, detail: dict[str, Any]) -> None:
        """Write a system intervention (no operator) against a stage and hand it on."""
        ...


class ControlPort(Protocol):
    """Implemented by the control service: the single checkpoint for every BLE write."""

    def recovery_number(self) -> int: ...

    def bump_recovery(self, reason: str) -> int:
        """Restore or host change: every earlier right, approval and session becomes void."""
        ...

    def capabilities(self) -> Capabilities: ...

    def connected(self) -> bool: ...

    def irrigating(self) -> bool: ...

    def pump_reading(self) -> PumpReading: ...

    def last_cycle_end(self) -> float | None:
        """Monotonic time the last irrigation's pump-off finished, or None."""
        ...

    def last_pump_off_id(self) -> str | None: ...

    def readings(self) -> tuple[Reading, ...]: ...

    async def read_state(self) -> DeviceState: ...

    async def differences(self, expected: Mapping[Channel, int]) -> tuple[Difference, ...]:
        """Read back and compare level and mode of each expected host-controlled channel."""
        ...

    def grant(self, kind: RightKind, scope: RightScope, operator: str | None = None) -> int: ...

    async def handover(self, number: int, reason: str) -> None:
        """Persist that ``number`` may not write, void its undispatched actions, then wait for
        in-flight receipts while still blocking new ordinary writes."""
        ...

    def right(self, number: int) -> WriteRight | None: ...

    def protection_right(self) -> int | None: ...

    async def submit(self, request: ActionRequest) -> ActionRecord:
        """Check, persist the intent, send, read back. Idempotent by ``request_id``.

        Never switches the pump on. Raises ``Denied`` before anything is sent.
        """
        ...

    async def irrigate(
        self, request: ActionRequest, seconds: float, planned: bool = False
    ) -> ActionRecord:
        """Operator-triggered pump run; the only path that starts it. Under a manual right, or
        (``planned``) under the stage right for a run sheet's irrigation task."""
        ...

    async def pump_off(self, trigger: PumpOffTrigger = "interlock") -> bool:
        """Dedicated interlock path: switch the pump outlet off and read back."""
        ...

    def receipt(self, request_id: str) -> ActionRecord | None: ...

    def unsettled_actions(self) -> tuple[ActionRecord, ...]: ...

    async def reconcile_unsettled(self) -> tuple[ActionRecord, ...]:
        """Check the real device first (§7.9): once the old transport is confirmed stopped,
        read back and settle every unknown non-pump action as applied or not applied.
        Returns the actions that are still unsettled (pump actions stay with the interlock)."""
        ...

    async def confirm_transport_stopped(self) -> bool: ...

    def transport_stopped(self) -> bool: ...

    def interlocked(self) -> bool: ...

    async def onsite_check(self, operator: str, note: str) -> None:
        """An operator checked the device on site: settle unknown actions and the interlock."""
        ...

    def safety(self) -> SafetyConfig | None: ...

    def approve_safety(self, config: SafetyConfig, operator: str) -> int:
        """Store the separately approved safety config; returns its protection right."""
        ...

    def safety_conflicts(self, run_sheet: RunSheet) -> tuple[str, ...]:
        """Protection rules that act on a channel the run sheet leaves to the device."""
        ...
