"""In-memory ``ControlPort`` for workflow tests: settable device facts, a log of rights."""

from collections.abc import Mapping

from growbridge.archive.models import (
    LEVEL_RANGES,
    ActionRecord,
    ActionState,
    Channel,
    RightKind,
    RunSheet,
    SafetyConfig,
    WriteRight,
)
from growbridge.control.service import snapshot_digest
from growbridge.ports import (
    ActionRequest,
    Capabilities,
    ChannelSnapshot,
    DeviceState,
    Difference,
    PumpOffTrigger,
    PumpReading,
    Reading,
    RightScope,
)
from growbridge.sim.fixtures import DEVICE, make_safety


class FakeControl:
    """Does not write anything: ``submit`` and ``irrigate`` are out of scope for it."""

    def __init__(self, clock=None):
        self.clock = clock
        self.recovery = 1
        self.capability_version = "caps-1"
        self.stopped = True  # transport_stopped(): old writes confirmed gone
        self.interlock = False
        self._last_pump_off: str | None = None
        self.unsettled: tuple[ActionRecord, ...] = ()
        self.diffs: tuple[Difference, ...] = ()
        self.differences_error: Exception | None = None  # raised by differences() when set
        self.reconcile_leaves: tuple[ActionRecord, ...] | None = None  # None: settle nothing
        self.conflicts: tuple[str, ...] = ()
        self.is_connected = True
        self.safety_config: SafetyConfig | None = make_safety(approved_by="op-1", approved_at=1.0)
        self.highest_version: int | None = self.safety_config.version  # settable, like the rest
        self.levels: dict[Channel, int] = {}
        self.rights: dict[int, WriteRight] = {}
        self.revoked: set[int] = set()
        self.log: list[tuple] = []
        self.expected_seen: list[Mapping[Channel, int]] = []
        self._next = 1

    # --- observation helpers for tests ---------------------------------------------------------

    @property
    def grants(self) -> list[tuple[int, RightKind]]:
        return [(entry[1], entry[2]) for entry in self.log if entry[0] == "grant"]

    @property
    def handovers(self) -> list[tuple[int, str]]:
        return [(entry[1], entry[2]) for entry in self.log if entry[0] == "handover"]

    def granted(self, kind: RightKind) -> list[int]:
        return [number for number, grant_kind in self.grants if grant_kind is kind]

    def live(self, kind: RightKind) -> list[int]:
        return [number for number in self.granted(kind) if number not in self.revoked]

    # --- ControlPort ---------------------------------------------------------------------------

    def recovery_number(self) -> int:
        return self.recovery

    def bump_recovery(self, reason: str) -> int:
        self.recovery += 1
        self.revoked.update(self.rights)
        self.log.append(("bump", self.recovery, reason))
        return self.recovery

    def capabilities(self) -> Capabilities:
        return Capabilities(
            version=self.capability_version,
            sensors={"temp": "C", "humi": "%"},
            level_ranges=dict(LEVEL_RANGES),
            outlets={},
        )

    def connected(self) -> bool:
        return self.is_connected

    def readings(self) -> tuple[Reading, ...]:
        return ()

    async def read_state(self) -> DeviceState:
        return DeviceState(levels=dict(self.levels), modes={}, at=self._now())

    async def differences(self, expected: Mapping[Channel, int]) -> tuple[Difference, ...]:
        if self.differences_error is not None:
            raise self.differences_error
        self.expected_seen.append(dict(expected))
        return self.diffs

    def grant(self, kind: RightKind, scope: RightScope, operator: str | None = None) -> int:
        number = self._next
        self._next += 1
        self.rights[number] = WriteRight(
            number=number,
            kind=kind,
            device_id=scope.device_id,
            recovery_number=self.recovery,
            granted_at=self._now(),
            channels=scope.channels,
            levels=scope.levels,
            experiment_id=scope.experiment_id,
            stage_id=scope.stage_id,
            run_sheet_digest=scope.run_sheet_digest,
            operator=operator,
        )
        self.log.append(("grant", number, kind, scope, operator))
        return number

    async def handover(self, number: int, reason: str) -> None:
        self.revoked.add(number)
        self.log.append(("handover", number, reason))

    def right(self, number: int) -> WriteRight | None:
        return None if number in self.revoked else self.rights.get(number)

    def protection_right(self) -> int | None:
        return None

    async def submit(self, request: ActionRequest) -> ActionRecord:
        raise NotImplementedError("FakeControl does not simulate writes")

    async def irrigate(
        self, request: ActionRequest, seconds: float, planned: bool = False
    ) -> ActionRecord:
        raise NotImplementedError("FakeControl does not simulate writes")

    async def snapshot(self, channel: Channel) -> ChannelSnapshot:
        raise NotImplementedError("FakeControl does not simulate writes")

    async def restore(self, request: ActionRequest, snapshot: ChannelSnapshot) -> ActionRecord:
        raise NotImplementedError("FakeControl does not simulate writes")

    def irrigating(self) -> bool:
        return False

    def pump_reading(self) -> PumpReading:
        return PumpReading(on=None, at=0.0, mono=0.0)  # no status ever received

    def last_cycle_end(self) -> float | None:
        return None

    def last_pump_off_id(self) -> str | None:
        return self._last_pump_off

    async def pump_off(self, trigger: PumpOffTrigger = "interlock") -> bool:
        self._last_pump_off = f"pumpoff-{trigger}"
        self.log.append(("pump_off", trigger))
        return True

    def receipt(self, request_id: str) -> ActionRecord | None:
        return None

    def unsettled_actions(self) -> tuple[ActionRecord, ...]:
        return self.unsettled

    async def reconcile_unsettled(self) -> tuple[ActionRecord, ...]:
        self.log.append(("reconcile",))
        if self.reconcile_leaves is not None:
            self.unsettled = self.reconcile_leaves
        return self.unsettled

    async def confirm_transport_stopped(self) -> bool:
        return self.stopped

    def transport_stopped(self) -> bool:
        return self.stopped

    def interlocked(self) -> bool:
        return self.interlock

    async def onsite_check(self, operator: str, note: str) -> None:
        self.unsettled = ()
        self.interlock = False
        self.log.append(("onsite_check", operator, note))

    def safety(self) -> SafetyConfig | None:
        return self.safety_config

    def highest_safety_version(self) -> int | None:
        return self.highest_version

    def approve_safety(self, config: SafetyConfig, operator: str) -> int:
        """Stores whatever it is given: the version rule is ``ControlService``'s."""
        self.safety_config = config.model_copy(update={"approved_by": operator})
        self.highest_version = max(self.highest_version or 0, config.version)
        return self.grant(RightKind.PROTECTION, RightScope(device_id=DEVICE), operator)

    def safety_conflicts(self, run_sheet: RunSheet) -> tuple[str, ...]:
        return self.conflicts

    def _now(self) -> float:
        return self.clock.now() if self.clock is not None else 0.0


class WritingFakeControl(FakeControl):
    """A ``FakeControl`` that also writes: levels and blocks change in memory, every call is
    logged, and ``fail_restore`` / ``unreadable`` simulate a restore the device did not take and
    a device that cannot be read."""

    def __init__(self, clock=None):
        super().__init__(clock)
        self.blocks: dict[Channel, dict] = {}
        self.fail_restore = False
        self.unreadable = False

    async def submit(self, request: ActionRequest) -> ActionRecord:
        self.levels[request.channel] = request.level
        self.log.append(("submit", request.channel, request.level, request.request_id))
        return self._receipt(request, ActionState.CONFIRMED)

    async def irrigate(
        self, request: ActionRequest, seconds: float, planned: bool = False
    ) -> ActionRecord:
        self.levels[Channel.PUMP] = 0  # switched on, then off and confirmed
        self.log.append(("irrigate", seconds, request.request_id))
        return self._receipt(request, ActionState.CONFIRMED)

    async def snapshot(self, channel: Channel) -> ChannelSnapshot:
        if self.unreadable:
            raise ConnectionError("simulated: the device cannot be read")
        block = dict(self.blocks.get(channel, {"modeType": 0}))
        level = self.levels.get(channel, 0)
        digest = snapshot_digest(channel, block)
        return ChannelSnapshot(
            channel=channel,
            block=block,
            level=level,
            mode=block.get("modeType"),
            block_digest=digest,
        )

    async def restore(self, request: ActionRequest, snapshot: ChannelSnapshot) -> ActionRecord:
        self.log.append(("restore", request.channel, request.level, request.request_id))
        if self.fail_restore:
            return self._receipt(request, ActionState.FAILED)
        self.levels[request.channel] = request.level
        self.blocks[request.channel] = dict(snapshot.block)
        return self._receipt(request, ActionState.CONFIRMED)

    def _receipt(self, request: ActionRequest, state: ActionState) -> ActionRecord:
        right = self.rights[request.right_number]
        return ActionRecord(
            request_id=request.request_id,
            state=state,
            channel=request.channel,
            planned_level=request.level,
            right_number=right.number,
            right_kind=right.kind,
            trigger=request.trigger,
            created_at=self._now(),
            operator=request.operator or right.operator,
        )
