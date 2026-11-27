"""Deterministic executor: each tick evaluates the approved run sheet and writes through control.

No model is involved. The engine decides from the run sheet, the safety config, the readings and
the clock, and every write goes through ``ControlPort.submit``; it has no call that can switch the
pump on (the only pump action is the dedicated switch-off interlock path).

Tick order (plan Task 12): interlock pump-off, protection rules, link accounting and the
disconnect decision, RUNNING (external change, timed actions, feedback rules, end condition, end
actions), care rules when the stage is not running or under takeover, and the longest-wait check
of a paused stage. A stage that changes state during a tick is acted on at the next tick. With no
current stage, the idle levels instead (design 2026-11-24), aligned like care rules.
"""

import asyncio
import logging
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from growbridge.archive.clock import Clock
from growbridge.archive.models import (
    ActionRecord,
    ActionState,
    Channel,
    Model,
    RuleAction,
    RunSheet,
    TimedAction,
)
from growbridge.executor.outage import ClockTrust, LinkWatch, Outage, outage_reasons
from growbridge.executor.rules import (
    Decision,
    RuleState,
    evaluate_feedback,
    evaluate_protection,
    resolve,
)
from growbridge.executor.watchdog import PumpWatchdog
from growbridge.ports import (
    ActionRequest,
    ControlPort,
    Denied,
    Difference,
    IdleRuntime,
    StageEvent,
    StagePort,
    StageRuntime,
)
from growbridge.ports import StageEventKind as Kind
from growbridge.workflow.states import StageState

WriteKind = Literal["experiment_action", "care", "protection"]
DEFAULT_MAX_GAP_SECONDS = 120.0  # continuity limit for protection when no stage is active
RETRYABLE = (ActionState.FAILED, ActionState.VOID)
MAX_FAILED_WRITES = 3  # consecutive failed readbacks per channel before the executor gives up
# A protection level that cannot be read back is re-sent at most this often per channel. It is
# the length of the shortest protection window (validity 20 s, duration 30 s): re-asserting once
# per window keeps the protection effective while a 1 Hz tick adds at most 120 records an hour.
PROTECTION_RESEND_SECONDS = 30.0
SKIPPED_FOR_CARE = (StageState.RUNNING, StageState.MANUAL)
TRANSPORT_STATES = (StageState.RUNNING, StageState.PAUSED, StageState.MANUAL)


class TickReport(Model):
    at: float
    writes: tuple[str, ...] = ()  # request ids of writes sent in this tick
    reported: tuple[Kind, ...] = ()  # stage events handed to the workflow service
    denied: tuple[str, ...] = ()  # writes that were refused or held back, with the reason
    gap_seconds: float | None = None  # a link outage that ended in this tick


class _Tick:
    def __init__(self) -> None:
        self.writes: list[str] = []
        self.reported: list[Kind] = []
        self.denied: list[str] = []
        self.gap: float | None = None


def due_action(
    actions: Iterable[TimedAction], channel: Channel, minute: int
) -> tuple[TimedAction, int]:
    """The action in force at ``minute`` of the day and how many days back it was due."""
    ordered = sorted((a for a in actions if a.channel is channel), key=lambda a: a.minute)
    due = [action for action in ordered if action.minute <= minute]
    return (due[-1], 0) if due else (ordered[-1], 1)


def care_steps(sheet: RunSheet) -> list[TimedAction]:
    """Every care step with its care rule's id in front of its own, ``<care id>/<step id>``.

    A step id is unique only within its care rule, and the id goes into the write's cause and so
    into its request id: two care rules with an ``on`` step on one channel at one level would
    otherwise share a request id on a day, and the second write would be filed as a retry of the
    first. Planning names a care step the same way in its findings."""
    return [
        step.model_copy(update={"id": f"{rule.id}/{step.id}"})
        for rule in sheet.care_rules
        for step in rule.schedule
    ]


log = logging.getLogger(__name__)


def slot_day(sheet: RunSheet, at: float, days_back: int) -> str:
    local = datetime.fromtimestamp(at, ZoneInfo(sheet.timezone))
    return (local.date() - timedelta(days=days_back)).isoformat()


class ExecutorEngine:
    def __init__(
        self,
        control: ControlPort,
        stages: StagePort,
        clock: Clock,
        allow: Callable[[str], bool] | None = None,
        idle: Callable[[], IdleRuntime | None] | None = None,
    ):
        self.control = control
        self.stages = stages
        self.clock = clock
        self._allow = allow  # storage guard: "experiment_action", "care" or "protection"
        self._idle_source = idle  # the idle right and levels while there is no current stage
        self._trust = ClockTrust(clock)
        # stages the clock anomaly paused -> the stage right they were paused under
        self._clock_paused: dict[str, int | None] = {}
        self._link = LinkWatch()
        self.watchdog = PumpWatchdog(control, stages, clock)
        self._lock = asyncio.Lock()
        self._beat: float | None = None
        self._gaps: tuple[float, ...] = ()
        self._applied: dict[Channel, int] = {}  # what this phase last confirmed on the device
        self._failed: dict[Channel, int] = {}  # consecutive failed readbacks in this phase
        self._unreadable_since: float | None = None  # monotonic start of a failing state read
        self._resent: dict[Channel, float] = {}  # last unverifiable protection re-send
        self._feedback: dict[str, RuleState] = {}
        self._protection: dict[str, RuleState] = {}
        self._phase: tuple[object, ...] | None = None
        self._phase_mono = 0.0
        self._sent: frozenset[str] = frozenset()  # event ids already reported in this phase

    def heartbeat(self) -> float | None:
        """Monotonic time at which the last tick completed; ``None`` before the first."""
        return self._beat

    @property
    def gaps(self) -> tuple[float, ...]:
        """Seconds of every link outage that did not affect the run."""
        return self._gaps

    async def tick(self) -> TickReport:
        async with self._lock:
            tick = _Tick()
            await self._tick(tick)
            self._beat = self.clock.monotonic()
            return TickReport(
                at=self.clock.now(),
                writes=tuple(tick.writes),
                reported=tuple(tick.reported),
                denied=tuple(tick.denied),
                gap_seconds=tick.gap,
            )

    async def _tick(self, tick: _Tick) -> None:
        stage = self.stages.active_stage()
        self._clock_checked(stage)
        self._trust.observe()
        now, mono = self._trust.now(), self.clock.monotonic()
        self._enter_phase(stage, mono)
        online = self.control.connected()
        await self._interlock(tick, stage)  # 1
        if online:
            try:
                await self.watchdog.step(stage)
            except Exception as error:  # the watchdog never blocks protection
                log.exception("pump watchdog step failed")
                self.watchdog.step_failed(error)
        if online:
            await self._protect(tick, stage, mono)  # 2
        outage = self._link.observe(online, mono, now)
        if stage is None:
            await self._idle(tick, online)
            return
        if outage is not None and await self._after_outage(tick, stage, outage, now):  # 3
            return
        if await self._transport_unconfirmed(tick, stage):
            pass  # no stage or care writes until the old write path is confirmed stopped
        elif stage.state is StageState.RUNNING and online:
            await self._run(tick, stage, now, mono)  # 4, 7
        elif online and stage.state not in SKIPPED_FOR_CARE:
            await self._care(tick, stage, now)  # 5
        if stage.state is StageState.PAUSED:
            await self._max_wait(tick, stage, now, mono)  # 6

    def _clock_checked(self, stage: StageRuntime | None) -> None:
        """Forget a clock step only when an operator has acknowledged it for the stage it paused.

        The workflow lets only an operator move a paused or manual stage back to RUNNING (resume,
        hand back); so a stage that the anomaly paused and that runs again under a different
        stage right has been looked at by an operator, who was told about the clock. A different
        stage that starts, or any stage the anomaly did not pause, proves nothing about the
        clock and leaves the suspicion in place. Called before the clock is observed, so a step
        since the last tick still counts (§7.7).
        """
        if not self._clock_paused or stage is None or stage.state is not StageState.RUNNING:
            return
        if stage.stage_id in self._clock_paused:
            if stage.right_number != self._clock_paused[stage.stage_id]:
                self._trust.accept()
                self._clock_paused = {}

    def _enter_phase(self, stage: StageRuntime | None, mono: float) -> None:
        """A new stage, state or stage write right restarts rule timing and the baseline.

        The external-change baseline is only valid under the right it was taken under; after a
        start, resume, handback or run-sheet switch the channels are first aligned and only then
        does the confirmed state become the new baseline.
        """
        key = self._phase_key(stage)
        if key == self._phase:
            return
        self._phase, self._phase_mono = key, mono
        self._applied, self._feedback, self._failed = {}, {}, {}
        self._unreadable_since = None
        self._sent = frozenset()

    def _phase_key(self, stage: StageRuntime | None) -> tuple[object, ...]:
        """A stage, its state and stage right; with no stage, the idle right (a new one after a
        restart or a refused start realigns the device)."""
        if stage is not None:
            return (stage.stage_id, stage.state, stage.right_number)
        idle = self._idle_runtime()
        return ("idle", None if idle is None else idle.right)

    def _idle_runtime(self) -> IdleRuntime | None:
        return None if self._idle_source is None else self._idle_source()

    async def _idle(self, tick: _Tick, online: bool) -> None:
        """No current stage: bring each idle channel to its level, skipping protected ones."""
        idle = self._idle_runtime()
        if not online or idle is None:
            return
        held = self._protected()
        for action in idle.levels:
            if action.channel in held or self._applied.get(action.channel) == action.level:
                continue
            cause = f"idle:{action.channel.value}"
            await self._write(tick, None, idle.right, "care", action, cause, str(idle.right))

    # --- 1. interlock -------------------------------------------------------------------------

    async def _interlock(self, tick: _Tick, stage: StageRuntime | None) -> None:
        if not self.control.interlocked():
            return
        try:
            confirmed = await self.control.pump_off()
        except Denied:
            confirmed = False
        if not confirmed and stage is not None:
            await self._report(tick, stage, Kind.PUMP_OFF_UNCONFIRMED, "interlock")

    # --- 2. protection ------------------------------------------------------------------------

    async def _protect(self, tick: _Tick, stage: StageRuntime | None, mono: float) -> None:
        safety, right = self.control.safety(), self.control.protection_right()
        if safety is None or right is None:
            return
        readings = {reading.sensor: reading for reading in self.control.readings()}
        gap = stage.run_sheet.sampling.max_gap_seconds if stage else DEFAULT_MAX_GAP_SECONDS
        for rule in safety.rules:
            old = self._protection.get(rule.id, RuleState())
            decision = evaluate_protection(rule, readings.get(rule.sensor), old, mono, gap)
            self._protection = {**self._protection, rule.id: decision.state}
            if decision.action is not None:
                await self._hold_protection(tick, stage, right, rule.id, decision, mono)

    async def _hold_protection(
        self,
        tick: _Tick,
        stage: StageRuntime | None,
        right: int,
        rule_id: str,
        decision: Decision,
        mono: float,
    ) -> None:
        action = decision.action
        assert action is not None
        verified = await self._verified(action)
        if verified:
            self._resent = {k: v for k, v in self._resent.items() if k is not action.channel}
            return
        last = self._resent.get(action.channel)
        if verified is None:  # unreadable: re-assert, but at most once per interval
            if last is not None and mono - last < PROTECTION_RESEND_SECONDS:
                return
            self._resent = {**self._resent, action.channel: mono}
        since = decision.state.since if decision.state.since is not None else mono
        slot = str(int(since * 1000))
        await self._write(tick, stage, right, "protection", action, f"protect:{rule_id}", slot)

    def _protecting(self) -> dict[Channel, str]:
        """Each channel an active protection rule holds, with that rule's id. Timed schedules,
        care, feedback rules and end actions all leave these channels alone (spec 7.4)."""
        safety = self.control.safety()
        rules = () if safety is None else safety.rules
        active = (r for r in rules if self._protection.get(r.id, RuleState()).active)
        return {rule.action.channel: rule.id for rule in active}

    def protected_channels(self) -> frozenset[Channel]:
        """The channels an active protection rule holds now (read by device tests)."""
        return self._protected()

    def _protected(self) -> frozenset[Channel]:
        """The channels in ``_protecting``."""
        return frozenset(self._protecting())

    async def _verified(self, action: RuleAction) -> bool | None:
        """Does the device show the level now? ``None`` when the state cannot be read: that is
        not a confirmation, so the caller re-asserts the level (rate limited)."""
        if self._applied.get(action.channel) != action.level:
            return False
        try:
            return not await self.control.differences({action.channel: action.level})
        except Denied:
            return None

    # --- 3. link accounting -------------------------------------------------------------------

    async def _after_outage(
        self, tick: _Tick, stage: StageRuntime, outage: Outage, now: float | None
    ) -> bool:
        """Record the gap; report and return True when the outage affects the running stage."""
        tick.gap = outage.seconds
        if stage.state is not StageState.RUNNING:
            self._gaps = (*self._gaps, outage.seconds)
            return False
        unsettled = bool(self.control.unsettled_actions())
        found = await self._differences()
        differs = found is None or bool(found)  # an unreadable state is not "no difference"
        reasons = outage_reasons(stage.run_sheet, outage, now, unsettled, differs)
        if not reasons:
            self._gaps = (*self._gaps, outage.seconds)
            return False
        detail = {"reasons": list(reasons), "seconds": outage.seconds}
        detail["state_unreadable"] = found is None
        await self._report(tick, stage, Kind.DISCONNECT_AFFECTS, f"{outage.start_mono}", detail)
        return True

    async def _differences(self) -> tuple[Difference, ...] | None:
        """Differences to what was applied; ``None`` when the device state cannot be read.

        While an irrigation runs the pump is on by design (a planned one runs while the stage
        keeps running), so the pump is left out of the comparison until it is over."""
        expected = self._applied
        if self.control.irrigating():
            expected = {c: level for c, level in expected.items() if c is not Channel.PUMP}
        if not expected:
            return ()
        try:
            return await self.control.differences(expected)
        except Denied:
            return None

    async def _transport_unconfirmed(self, tick: _Tick, stage: StageRuntime) -> bool:
        if stage.state not in TRANSPORT_STATES or self.control.transport_stopped():
            return False
        await self._report(tick, stage, Kind.TRANSPORT_UNCONFIRMED, "transport")
        return True

    # --- 4. running stage ---------------------------------------------------------------------

    async def _run(self, tick: _Tick, stage: StageRuntime, now: float | None, mono: float) -> None:
        if await self._unknown(tick, stage):
            return
        if now is None or not self._trust.trusted:
            await self._report(tick, stage, Kind.CLOCK_ANOMALY, "clock")
            self._clock_paused = {**self._clock_paused, stage.stage_id: stage.right_number}
            return
        if await self._readings_stale(tick, stage, mono):
            return
        if await self._external_change(tick, stage, mono):
            return
        if not stage.end_pending:
            await self._experiment(tick, stage, now, mono)
            if await self._unknown(tick, stage):
                return
            if await self._end_condition(tick, stage, now):
                stage = self.stages.active_stage() or stage
        await self._finish(tick, stage)  # 7

    async def _unknown(self, tick: _Tick, stage: StageRuntime) -> bool:
        records = self.control.unsettled_actions()
        if not records:
            return False
        ids = sorted(record.request_id for record in records)
        await self._report(tick, stage, Kind.RESULT_UNKNOWN, ids[0], {"request_ids": ids})
        return True

    async def _readings_stale(self, tick: _Tick, stage: StageRuntime, mono: float) -> bool:
        """Connected, but no valid reading within the run sheet's gap limit (monotonic)."""
        fresh = [
            r.mono for r in self.control.readings() if r.value is not None and r.quality == "ok"
        ]
        newest = max(fresh, default=None)
        limit = stage.run_sheet.sampling.max_gap_seconds
        if newest is not None and mono - newest <= limit:
            return False
        key = "none" if newest is None else str(int(newest * 1000))  # one per occurrence
        await self._report(tick, stage, Kind.READINGS_STALE, key)
        return True

    async def _external_change(self, tick: _Tick, stage: StageRuntime, mono: float) -> bool:
        found = await self._differences()
        if found is None:
            return await self._state_unreadable(tick, stage, mono)
        self._unreadable_since = None
        if not found:
            return False
        detail = {"differences": [item.model_dump(mode="json") for item in found]}
        await self._report(tick, stage, Kind.EXTERNAL_CHANGE, "panel", detail)
        return True

    async def _state_unreadable(self, tick: _Tick, stage: StageRuntime, mono: float) -> bool:
        """Connected with fresh telemetry, but the state read-back fails. A short failure is
        tolerated; one that outlasts the run sheet's gap limit is reported like stale data."""
        if self._unreadable_since is None:
            self._unreadable_since = mono
        seconds = mono - self._unreadable_since
        if seconds <= stage.run_sheet.sampling.max_gap_seconds:
            return False
        key = f"state-unreadable:{int(self._unreadable_since * 1000)}"
        detail = {"reason": "state_unreadable", "seconds": seconds}
        await self._report(tick, stage, Kind.READINGS_STALE, key, detail)
        return True

    async def _experiment(self, tick: _Tick, stage: StageRuntime, now: float, mono: float) -> None:
        held = self._protected() | self._overridden(stage.run_sheet)
        await self._align(tick, stage, now, held, care=False)
        await self._feedback_rules(tick, stage, mono)

    def _overridden(self, sheet: RunSheet) -> frozenset[Channel]:
        """Channels an active feedback rule holds away from the timed schedule."""
        active = (
            rule.action.channel
            for rule in sheet.feedback_rules
            if self._feedback.get(rule.id, RuleState()).active
        )
        return frozenset(active)

    async def _align(
        self, tick: _Tick, stage: StageRuntime, now: float, held: frozenset[Channel], care: bool
    ) -> None:
        """Bring each channel to what its (care or timed) schedule says at ``now``."""
        sheet = stage.run_sheet
        if care:
            levels, kind, right = sheet.care_levels(now), "care", stage.care_right
            actions = care_steps(sheet)
        else:
            levels, kind = sheet.expected_levels(now), "experiment_action"
            right, actions = stage.right_number, list(sheet.timed_actions)
        for channel, level in levels.items():
            if channel in held or self._applied.get(channel) == level:
                continue
            action, back = due_action(actions, channel, sheet.local_minute(now))
            slot = slot_day(sheet, now, back)
            target = RuleAction(channel=channel, level=level)
            await self._write(tick, stage, right, kind, target, f"{kind}:{action.id}", slot)

    async def _feedback_rules(self, tick: _Tick, stage: StageRuntime, mono: float) -> None:
        sheet = stage.run_sheet
        readings = {reading.sensor: reading for reading in self.control.readings()}
        judged = []
        for rule in sheet.feedback_rules:
            old = self._feedback.get(rule.id, RuleState())
            reading = readings.get(rule.sensor)
            decision = evaluate_feedback(rule, reading, old, mono, sheet.sampling.max_gap_seconds)
            judged.append((rule, old, decision))
        chosen = resolve([(rule, decision) for rule, _, decision in judged])
        for rule, old, decision in judged:
            state = await self._apply_decision(tick, stage, rule.id, old, decision, chosen)
            self._feedback = {**self._feedback, rule.id: state}
        paused = [rule.id for rule, _, decision in judged if decision.pause]
        if paused:
            await self._report(tick, stage, Kind.RULE_PAUSE, paused[0], {"rules": paused})

    async def _apply_decision(
        self,
        tick: _Tick,
        stage: StageRuntime,
        rule_id: str,
        old: RuleState,
        decision: Decision,
        chosen: Mapping[Channel, RuleAction],
    ) -> RuleState:
        """Write what a rule decided and return the rule's next state. A write that did not
        happen keeps the old state, so the rule acts again on the next tick."""
        action = decision.action
        if action is None:
            return decision.state
        outside = action.channel not in stage.run_sheet.host_channels()
        if outside or chosen.get(action.channel) != action:
            return decision.state  # not a channel the executor may move, or a rule won
        if self._applied.get(action.channel) == action.level:
            return decision.state
        holder = self._protecting().get(action.channel)
        if holder is not None:
            cause = f"rule:{rule_id}: {action.channel.value} held by protection {holder}"
            tick.denied.append(cause)
            # the reading was seen: a long hold must not look like a gap that restarts the timer
            return old.model_copy(update={"last_seen": decision.state.last_seen})
        since = old.since if old.since is not None else self.clock.monotonic()
        slot = str(int(since * 1000))
        cause = f"rule:{rule_id}"
        record = await self._write(
            tick, stage, stage.right_number, "experiment_action", action, cause, slot
        )
        confirmed = record is not None and record.state is ActionState.CONFIRMED
        return decision.state if confirmed else old

    async def _end_condition(self, tick: _Tick, stage: StageRuntime, now: float) -> bool:
        if stage.started_at is None or now - stage.started_at < stage.run_sheet.duration_seconds:
            return False
        await self._report(tick, stage, Kind.END_CONDITION_MET, "duration")
        return True

    # --- 7. end actions -----------------------------------------------------------------------

    async def _finish(self, tick: _Tick, stage: StageRuntime) -> None:
        if not stage.end_pending or stage.right_number is None:
            return
        hosted = stage.run_sheet.host_channels()
        actions = [
            a
            for a in stage.run_sheet.end_actions
            if a.channel in hosted and a.channel is not Channel.PUMP
        ]
        protecting = self._protecting()
        held = [a.channel for a in actions if a.channel in protecting]
        tick.denied.extend(f"end:{c.value}: held by protection {protecting[c]}" for c in held)
        results = [
            await self._end_action(tick, stage, action)
            for action in actions
            if action.channel not in protecting
        ]
        if any(result is None for result in results):
            return  # refused or held back: try again next tick
        confirmed = all(results)  # a held end action counts as done: the stage ends on time
        key = "confirmed" if confirmed else "unconfirmed"
        detail = {"confirmed": confirmed, **({"held": [c.value for c in held]} if held else {})}
        await self._report(tick, stage, Kind.END_ACTIONS, key, detail)

    async def _end_action(
        self, tick: _Tick, stage: StageRuntime, action: RuleAction
    ) -> bool | None:
        """True when confirmed, False when the device did not take it, None when not sent."""
        if self._applied.get(action.channel) == action.level:
            return True
        cause = f"end:{action.channel.value}"
        record = await self._write(
            tick, stage, stage.right_number, "experiment_action", action, cause, "end"
        )
        if record is None:
            return None
        return record.state is ActionState.CONFIRMED

    # --- 5. care ------------------------------------------------------------------------------

    async def _care(self, tick: _Tick, stage: StageRuntime, now: float | None) -> None:
        """Care rules keep running; with an untrusted clock ``now`` is derived from monotonic."""
        if stage.care_right is None or now is None:
            return
        await self._align(tick, stage, now, self._protected(), care=True)

    # --- 6. longest wait ----------------------------------------------------------------------

    async def _max_wait(
        self, tick: _Tick, stage: StageRuntime, now: float | None, mono: float
    ) -> None:
        if stage.paused_at is None:
            return
        elapsed = mono - self._phase_mono if now is None else now - stage.paused_at
        if elapsed > stage.run_sheet.max_wait_seconds:
            await self._report(tick, stage, Kind.MAX_WAIT_EXPIRED, "max-wait")

    # --- writing and reporting ----------------------------------------------------------------

    async def _write(
        self,
        tick: _Tick,
        stage: StageRuntime | None,
        right: int | None,
        kind: WriteKind,
        action: RuleAction,
        cause: str,
        slot: str,
    ) -> ActionRecord | None:
        """Submit one deterministic write; ``None`` when it was refused or held back."""
        if right is None:
            return None
        if action.channel is Channel.PUMP and action.level != 0:
            tick.denied.append(f"{cause}: the executor never switches the pump on")
            return None
        if self._allow is not None and not self._allow(kind):
            tick.denied.append(f"{cause}: storage guard blocks {kind}")
            return None
        if kind != "protection" and self._failed.get(action.channel, 0) >= MAX_FAILED_WRITES:
            tick.denied.append(
                f"{cause}: readback keeps failing; left alone until the phase changes"
            )
            return None
        owner = "device" if stage is None else f"{stage.stage_id}.v{stage.run_sheet.version}"
        base = f"{owner}:{cause}:{action.channel.value}:{action.level}:{slot}"
        request_id, replaced = self._free_id(base)
        request = ActionRequest(
            request_id=request_id,
            right_number=right,
            channel=action.channel,
            level=action.level,
            trigger=cause,
            experiment_id=None if stage is None else stage.experiment_id,
            stage_id=None if stage is None else stage.stage_id,
            supersedes=replaced,
        )
        try:
            record = await self.control.submit(request)
        except Denied as error:
            tick.denied.append(f"{request_id}: {error.code}")
            return None
        tick.writes.append(request_id)  # the id was unused, so this call created the receipt
        await self._note_outcome(tick, stage, action, record)
        return record

    async def _note_outcome(
        self, tick: _Tick, stage: StageRuntime | None, action: RuleAction, record: ActionRecord
    ) -> None:
        """Baseline a confirmed level; count failed readbacks and give up after a few."""
        channel = action.channel
        if record.state is ActionState.CONFIRMED and record.confirmed_level == action.level:
            self._applied = {**self._applied, channel: action.level}
            self._failed = {k: v for k, v in self._failed.items() if k is not channel}
        elif record.state is ActionState.FAILED:
            count = self._failed.get(channel, 0) + 1
            self._failed = {**self._failed, channel: count}
            if count >= MAX_FAILED_WRITES and stage is not None:
                detail = {"channel": channel.value, "level": action.level, "failed": count}
                await self._report(tick, stage, Kind.EXTERNAL_CHANGE, "stuck", detail)

    def _free_id(self, base: str) -> tuple[str, str | None]:
        """The first unused id for this target, derived from the ledger, not from memory.

        Earlier receipts (also from before a restart) are never answered as if they were a new
        write; a failed or voided latest attempt is superseded.
        """
        replaced, generation = None, 0
        while (found := self.control.receipt(request_id := f"{base}.g{generation}")) is not None:
            replaced = request_id if found.state in RETRYABLE else None
            generation += 1
        return request_id, replaced

    async def _report(
        self,
        tick: _Tick,
        stage: StageRuntime,
        kind: Kind,
        key: str,
        detail: dict | None = None,
    ) -> None:
        """Report once per phase: the same event id advances the stage at most once."""
        event_id = f"{kind.value}:{stage.stage_id}:{key}:{int(self._phase_mono * 1000)}"
        if event_id in self._sent:
            return
        detail = dict(detail or {})
        if stage.state is StageState.RUNNING:
            detail["right_number"] = stage.right_number  # lets the workflow drop stale events
        event = StageEvent(
            event_id=event_id,
            kind=kind,
            stage_id=stage.stage_id,
            at=self.clock.now(),
            detail=detail,
        )
        await self.stages.report(event)
        self._sent = self._sent | {event_id}
        tick.reported.append(kind)
