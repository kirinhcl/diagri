"""Shared vocabulary of the Auto Research services (architecture doc §6, §7 and §11.1).

Every model is frozen: a change is a new object, and a changed run sheet or protocol is a new
version. Only structural rules live here; whether a run sheet is safe to run is decided by
``growbridge.planning.validate``.
"""

import math
from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from growbridge.archive.ids import content_digest
from growbridge.workflow.states import TaskState

TIME_OF_DAY = r"^([01]\d|2[0-3]):[0-5]\d$"
Quality = Literal["ok", "suspect", "invalid"]
Label = Literal["confirmatory", "exploratory", "descriptive"]
SampleKind = Literal["planned", "query"]


class Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    def digest(self) -> str:
        return content_digest(self.model_dump(mode="json"))


def non_finite_paths(value: Any, path: str = "") -> list[str]:
    """Dotted paths, such as ``sampling.interval_seconds``, where a dumped model holds NaN or an
    infinity. Pydantic accepts both (also spelled as text) unless a model forbids them."""
    if isinstance(value, float):
        return [] if math.isfinite(value) else [path]
    if isinstance(value, dict):
        items: Iterable[tuple[Any, Any]] = value.items()
    elif isinstance(value, list | tuple):
        items = enumerate(value)
    else:
        return []
    return [
        found
        for key, item in items
        for found in non_finite_paths(item, f"{path}.{key}" if path else str(key))
    ]


def require_finite(model: BaseModel, what: str) -> None:
    """For a model that drives the device. NaN would be stored as null and could not be read
    back, and a NaN threshold never compares true, so a rule holding it would never act."""
    spoiled = non_finite_paths(model.model_dump())
    if spoiled:
        raise ValueError(f"{what} numbers must be finite; not at {', '.join(spoiled)}")


class Channel(StrEnum):
    LIGHT = "light"
    EXHAUST = "exhaust"
    FAN = "fan"
    PUMP = "pump"


class Ownership(StrEnum):
    DEVICE = "device"  # the AC5 timer runs it; GrowBridge only reads
    HOST = "host"  # the executor writes it


class RightKind(StrEnum):
    STAGE = "stage"
    MANUAL = "manual"
    CARE = "care"
    PROTECTION = "protection"


class ActionState(StrEnum):
    PENDING = "pending"  # 待发送
    MAYBE_SENT = "maybe_sent"  # 可能已发送
    CONFIRMED = "confirmed"  # 已回读确认
    UNKNOWN = "unknown"  # 结果未知
    FAILED = "failed"  # 失败
    VOID = "void"  # 作废


class Entry(StrEnum):
    LAN = "lan"
    OVERLAY = "overlay"


LEVEL_RANGES: dict[Channel, tuple[int, int]] = {
    Channel.LIGHT: (0, 100),
    Channel.EXHAUST: (0, 100),
    Channel.FAN: (0, 10),
    Channel.PUMP: (0, 1),
}


def check_level(channel: Channel, level: int) -> int:
    low, high = LEVEL_RANGES[channel]
    if not low <= level <= high:
        raise ValueError(f"{channel.value} level {level} is outside {low}..{high}")
    return level


# --- run sheet --------------------------------------------------------------------------------


class Condition(Model):
    op: Literal[">", ">=", "<", "<="]
    value: float

    def holds(self, reading: float) -> bool:
        return {
            ">": reading > self.value,
            ">=": reading >= self.value,
            "<": reading < self.value,
            "<=": reading <= self.value,
        }[self.op]


class RuleAction(Model):
    channel: Channel
    level: int

    @model_validator(mode="after")
    def _in_range(self) -> "RuleAction":
        check_level(self.channel, self.level)
        return self


class TimedAction(Model):
    id: str
    channel: Channel
    at: str = Field(pattern=TIME_OF_DAY)  # project-local HH:MM
    level: int
    evidence: str | None = None

    @model_validator(mode="after")
    def _in_range(self) -> "TimedAction":
        check_level(self.channel, self.level)
        return self

    @property
    def minute(self) -> int:
        return int(self.at[:2]) * 60 + int(self.at[3:])


def scheduled_level(actions: Iterable[TimedAction], minute: int) -> int | None:
    """Level set by the latest action at or before ``minute`` of the day.

    Before the first action of the day the previous day's last action still applies, which is
    what aligns a channel to its original schedule after a missed timer.
    """
    ordered = sorted(actions, key=lambda action: action.minute)
    if not ordered:
        return None
    due = [action for action in ordered if action.minute <= minute]
    return (due[-1] if due else ordered[-1]).level


class FeedbackRule(Model):
    id: str
    sensor: str
    position: str
    unit: str
    validity_seconds: float
    trigger: Condition
    recover: Condition
    duration_seconds: float
    action: RuleAction
    release: RuleAction | None = None
    min_switch_seconds: float = 0
    on_missing: Literal["hold", "pause"] = "hold"
    priority: int = 0
    evidence: str | None = None


class CareRule(Model):
    id: str
    channel: Channel
    schedule: tuple[TimedAction, ...]


class ProtectionRule(Model):
    id: str
    sensor: str
    unit: str
    validity_seconds: float
    trigger: Condition
    duration_seconds: float
    action: RuleAction


DEFAULT_FROZEN_MINUTES = {"temp": 120.0, "humi": 60.0, "co2": 60.0, "tempSoil": 240.0}


class FrozenCheck(Model):
    """How long a sensor may report exactly the same value before it is flagged as frozen.
    A sensor missing from ``minutes`` is not checked; an empty dict checks nothing."""

    minutes: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_FROZEN_MINUTES))
    max_gap_seconds: float = 600.0

    @model_validator(mode="after")
    def _positive_and_finite(self) -> "FrozenCheck":
        bad = [name for name, value in self.minutes.items() if not 0 < value < math.inf]
        if bad:
            raise ValueError(
                f"frozen minutes must be finite and positive; not for {', '.join(bad)}"
            )
        if not 0 < self.max_gap_seconds < math.inf:
            raise ValueError("frozen max_gap_seconds must be finite and positive")
        return self


class FrozenPeriod(Model):
    """A sensor that has reported exactly ``value`` since ``first_at`` and has not yet recovered."""

    period_id: str
    sensor: str
    value: float
    first_at: float
    opened_at: float


class SafetyConfig(Model):
    version: int
    rules: tuple[ProtectionRule, ...]
    frozen: FrozenCheck = Field(default_factory=FrozenCheck)
    approved_by: str | None = None
    approved_at: float | None = None

    @model_validator(mode="after")
    def _finite(self) -> "SafetyConfig":
        require_finite(self, "Safety configuration")
        return self


class ChannelPlan(Model):
    channel: Channel
    ownership: Ownership
    retained_level: int | None = None  # state the channel may keep while paused or offline
    max_tolerance_seconds: float | None = None
    onsite_handling: str = ""


class ManualTask(Model):
    id: str
    kind: Literal["irrigation", "measurement", "photo"]
    at: str = Field(pattern=TIME_OF_DAY)
    make_up_allowed: bool = False


class SamplingPlan(Model):
    interval_seconds: float
    max_gap_seconds: float


class RunSheet(Model):
    id: str
    project_id: str
    experiment_id: str
    stage_id: str
    protocol_id: str
    protocol_version: int
    device_id: str
    version: int
    timezone: str
    channels: tuple[ChannelPlan, ...]
    duration_seconds: float
    sampling: SamplingPlan
    max_wait_seconds: float
    on_expiry: Literal["stay_paused", "stop"] = "stay_paused"
    timed_actions: tuple[TimedAction, ...] = ()
    feedback_rules: tuple[FeedbackRule, ...] = ()
    care_rules: tuple[CareRule, ...] = ()
    manual_tasks: tuple[ManualTask, ...] = ()
    end_actions: tuple[RuleAction, ...] = ()

    @model_validator(mode="after")
    def _structure(self) -> "RunSheet":
        channels = [plan.channel for plan in self.channels]
        if len(channels) != len(set(channels)):
            raise ValueError("Each channel may appear once in a run sheet")
        try:
            ZoneInfo(self.timezone)
        except (KeyError, ValueError) as error:
            raise ValueError(f"Unknown timezone {self.timezone!r}") from error
        return self

    @model_validator(mode="after")
    def _finite(self) -> "RunSheet":
        require_finite(self, "Run sheet")  # an infinite duration or interval is no plan either
        return self

    def plan(self, channel: Channel) -> ChannelPlan | None:
        return next((plan for plan in self.channels if plan.channel is channel), None)

    def host_channels(self) -> tuple[Channel, ...]:
        return tuple(plan.channel for plan in self.channels if plan.ownership is Ownership.HOST)

    def local_minute(self, at: float) -> int:
        local = datetime.fromtimestamp(at, ZoneInfo(self.timezone))
        return local.hour * 60 + local.minute

    def expected_levels(self, at: float) -> dict[Channel, int]:
        """Timed-action target of each host-controlled channel at UTC time ``at``."""
        return self._levels(self.timed_actions, at)

    def care_levels(self, at: float) -> dict[Channel, int]:
        """Care-rule target of each host-controlled channel at UTC time ``at``."""
        return self._levels((step for rule in self.care_rules for step in rule.schedule), at)

    def _levels(self, actions: Iterable[TimedAction], at: float) -> dict[Channel, int]:
        hosted = set(self.host_channels())
        grouped: dict[Channel, list[TimedAction]] = {}
        for action in actions:
            if action.channel in hosted:
                grouped.setdefault(action.channel, []).append(action)
        minute = self.local_minute(at)
        return {channel: scheduled_level(items, minute) for channel, items in grouped.items()}


# --- research protocol ------------------------------------------------------------------------


class Treatment(Model):
    id: str
    name: str
    description: str = ""
    factors: dict[str, float | str] = Field(default_factory=dict)


class Allocation(Model):
    round: int
    block: int
    unit: str
    treatment_id: str


class AnalysisPlan(Model):
    primary_endpoint: str
    target_effect: float
    method: str
    script_sha256: str | None = None
    exclusion_rules: tuple[str, ...] = ()
    max_missing_fraction: float = 0.2
    max_deviation_fraction: float = 0.1


class ResearchProtocol(Model):
    id: str
    project_id: str
    version: int
    question: str
    hypothesis: str
    crop: str
    batch: str
    treatments: tuple[Treatment, ...]
    control_treatment_id: str
    allocations: tuple[Allocation, ...]
    randomization_seed: int
    analysis: AnalysisPlan
    stages: tuple[str, ...]
    rounds: int
    blocks: int
    experimental_unit: str = "tent"


# --- records ----------------------------------------------------------------------------------


class SampleRecord(Model):
    id: str
    experiment_id: str | None
    stage_id: str | None
    device_id: str
    captured_at: float | None  # None when the device gave no capture time
    received_at: float
    clock_synced: bool
    source: SampleKind = "planned"
    quality: Quality = "ok"
    data: dict[str, Any] = Field(default_factory=dict)


class ActionRecord(Model):
    request_id: str
    state: ActionState
    channel: Channel
    planned_level: int
    right_number: int
    right_kind: RightKind
    trigger: str
    created_at: float
    operator: str | None = None
    experiment_id: str | None = None
    stage_id: str | None = None
    sent_at: float | None = None
    confirmed_at: float | None = None
    confirmed_level: int | None = None
    error: str | None = None
    supersedes: str | None = None  # the unknown or failed request this one redoes
    settled_at: float | None = None  # when an operator recorded an on-site check


class ManualMeasurement(Model):
    id: str
    experiment_id: str
    batch: str
    plant_id: str
    layout_version: str
    measured_at: float
    position: str
    method: str
    metric: str
    value: float
    unit: str
    operator: str
    corrects: str | None = None  # the record this one corrects; raw records are never edited


class EvidenceCard(Model):
    id: str
    source_class: Literal["handbook", "paper", "local"]
    citation: str
    claim: str
    value: float | None = None
    unit: str | None = None
    verified: bool = False
    calibrated: bool = True  # False shows as "未校准" (light conversion without local measurement)


class Snapshot(Model):
    id: str
    experiment_id: str
    version: int
    created_at: float
    manifest_sha256: str
    complete: bool
    coverage: float
    gaps: tuple[tuple[float, float], ...] = ()
    files: dict[str, str] = Field(default_factory=dict)  # relative path -> sha256


class Artifact(Model):
    id: str
    task_id: str
    kind: str
    path: str
    sha256: str
    label: Label
    snapshot_id: str | None = None
    code_sha256: str | None = None
    environment: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    limitations: tuple[str, ...] = ()


class Budget(Model):
    max_calls: int
    max_cost: float
    max_revisions: int = 3
    max_delegation_depth: int = 2


class ResearchTask(Model):
    id: str
    project_id: str
    question: str
    owner_role: str
    budget: Budget
    trigger_event_id: str
    correlation_id: str
    constraints: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    input_refs: tuple[str, ...] = ()
    expected_artifacts: tuple[str, ...] = ()
    parent_task_id: str | None = None
    deadline: float | None = None
    state: TaskState = TaskState.IN_PROGRESS


class Approval(Model):
    id: str
    run_sheet_id: str
    run_sheet_version: int
    run_sheet_digest: str
    project_id: str
    experiment_id: str
    stage_id: str
    device_id: str
    capability_version: str
    recovery_number: int
    operator: str
    approved_at: float
    voided_at: float | None = None


class WriteRight(Model):
    number: int
    kind: RightKind
    device_id: str
    recovery_number: int
    granted_at: float
    channels: tuple[Channel, ...] = ()
    levels: tuple[RuleAction, ...] = ()  # the only values a care or protection right may write
    experiment_id: str | None = None
    stage_id: str | None = None
    run_sheet_digest: str | None = None
    operator: str | None = None
    revoked_at: float | None = None
