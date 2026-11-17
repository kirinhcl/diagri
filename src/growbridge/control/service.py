"""Control service: the single checkpoint for every BLE write (spec 7.1-7.3, 7.5, 7.6, 7.8, 7.9).

One two-level priority gate serialises hand-overs and every dispatch. Protection writes, the
pump-off at the end of an irrigation and hand-overs go before queued ordinary writes (they never
preempt the write already on its way). A protection write also voids the ordinary writes
queued on its own channel. A request is checked
when it is queued and again, inside the gate, right before it is sent. The intent is persisted
before sending and again as "maybe sent" just before the bytes leave, so a crash in between is
recovered as "result unknown" and never replayed.
"""

import asyncio
import logging
import math
from collections.abc import Mapping
from typing import Any

from growbridge.archive.clock import Clock
from growbridge.archive.db import Database
from growbridge.archive.ids import content_digest, new_id
from growbridge.archive.models import (
    ActionRecord,
    ActionState,
    Channel,
    Ownership,
    RightKind,
    RunSheet,
    SafetyConfig,
    WriteRight,
)
from growbridge.control import refusals, rights
from growbridge.control.device import SENSORS, DeviceIO, Outcome
from growbridge.control.ledger import (
    FLAG_INTERLOCK,
    FLAG_TRANSPORT_STOPPED,
    META_LAST_IRRIGATION,
    META_RECOVERY,
    Ledger,
)
from growbridge.control.priority_gate import NORMAL, URGENT, PriorityGate
from growbridge.ports import (
    ActionRequest,
    Capabilities,
    Denied,
    DeviceState,
    Difference,
    PumpOffTrigger,
    PumpReading,
    Reading,
    RecordSink,
    RightScope,
)
from growbridge.service import Bridge, BridgeError

log = logging.getLogger(__name__)
PUMP_OFF_TRIES = 2


class ControlService:
    def __init__(
        self,
        bridge: Bridge,
        db: Database,
        clock: Clock,
        host_id: str,
        sink: RecordSink | None = None,
    ):
        self.bridge = bridge
        self.db = db
        self.clock = clock
        self.host_id = host_id
        self.sink = sink
        self.ledger = Ledger(db)
        self.device = DeviceIO(bridge)
        self.gate = PriorityGate()
        self._cycle: asyncio.Event | None = None  # set while an irrigation cycle is in flight
        # why the running cycle was ended before its time: (English text, code, params)
        self._cycle_ended: tuple[str, str, dict[str, Any]] | None = None
        self._last_cycle_end: float | None = None
        self._last_pump_off_id: str | None = None
        self.ready = False  # False until ``startup`` has finished: ordinary writes are blocked

    @property
    def device_id(self) -> str:
        return str(self.bridge.settings.device)

    def irrigating(self) -> bool:
        return self._cycle is not None

    def pump_reading(self) -> PumpReading:
        if not self.bridge.received_monotonic:
            return PumpReading(on=None, at=0.0, mono=0.0)
        return PumpReading(
            on=self.device.pump_on(self.bridge.data),
            at=self.bridge.received_at,
            mono=self.bridge.received_monotonic,
        )

    def last_cycle_end(self) -> float | None:
        return self._last_cycle_end

    def last_pump_off_id(self) -> str | None:
        return self._last_pump_off_id

    # --- host, recovery number, simple reads --------------------------------------------------

    def register_host(self) -> None:
        if not self.ledger.register_host(self.device_id, self.host_id, self.clock.now()):
            raise refusals.other_host_registered(self.device_id)

    def host_registered(self) -> bool:
        return self.ledger.host_of(self.device_id) == self.host_id

    def _require_host(self) -> None:
        if not self.host_registered():
            raise refusals.not_write_host(self.device_id)

    def recovery_number(self) -> int:
        return self.ledger.recovery()

    def bump_recovery(self, reason: str) -> int:
        """Restore or host change. Call it with no stage running: every right is revoked, queued
        actions are voided, and the old transport counts as unconfirmed until it is halted again.
        An action already on its way finishes (the gate re-checks the number before each send)."""
        now = self.clock.now()
        with self.db.transaction():
            number = self.ledger.recovery() + 1
            self.ledger.set_meta(META_RECOVERY, str(number))
            self.ledger.revoke_all(now)
            voided = self._void_queued("recovery number changed", code="void_recovery_changed")
            self.ledger.set_flag(FLAG_TRANSPORT_STOPPED, False)
            self.ledger.event("recovery_bump", {"number": number, "reason": reason}, now)
        self._publish(voided)
        return number

    def capabilities(self) -> Capabilities:
        return self.device.capabilities()

    def connected(self) -> bool:
        return bool(self.bridge.connected)

    def readings(self) -> tuple[Reading, ...]:
        return self.device.readings()

    async def read_state(self) -> DeviceState:
        try:
            return await self.device.read_state(self.clock.now())
        except (BridgeError, ConnectionError, OSError) as error:
            raise refusals.state_unreadable(self.device_id, error) from error

    async def differences(self, expected: Mapping[Channel, int]) -> tuple[Difference, ...]:
        state = await self.read_state()
        found = []
        for channel, level in expected.items():
            actual = state.levels.get(channel)
            if actual != level:
                found.append(
                    Difference(channel=channel, field="level", expected=level, actual=actual)
                )
            mode = state.modes.get(channel)
            if mode != 0:
                found.append(Difference(channel=channel, field="mode", expected=0, actual=mode))
        return tuple(found)

    # --- rights -------------------------------------------------------------------------------

    def grant(self, kind: RightKind, scope: RightScope, operator: str | None = None) -> int:
        self._require_host()
        if scope.device_id != self.device_id:
            raise refusals.unknown_device(scope.device_id)
        with self.db.transaction():
            recovery = self.ledger.recovery()
            right = rights.build_right(kind, scope, operator, recovery, self.clock.now())
            held = self.ledger.active_rights(self.device_id, recovery, RightKind.STAGE)
            if held and kind in rights.ORDINARY_KINDS:
                raise refusals.right_held(self.device_id, held[0].stage_id)
            return self.ledger.add_right(right)

    def right(self, number: int) -> WriteRight | None:
        return self.ledger.right(number)

    async def handover(self, number: int, reason: str) -> None:
        now = self.clock.now()
        self._end_cycle(f"hand-over: {reason}", code="handover")
        with self.db.transaction():
            self.ledger.revoke(number, now)
            voided = self._void_queued(
                f"hand-over: {reason}", code="void_handover", right_number=number
            )
            self.ledger.event("handover", {"right": number, "reason": reason}, now)
        self._publish(voided)
        # URGENT: waits only for the receipt of the action already on its way
        async with self.gate.acquire(URGENT):
            pass

    # --- safety configuration (7.5) -----------------------------------------------------------

    def safety(self) -> SafetyConfig | None:
        stored = self.ledger.latest_safety()
        if stored is None or stored[1] != self.ledger.recovery():
            return None
        return stored[0]

    def highest_safety_version(self) -> int | None:
        """The bar a new approval's version must clear, also when nothing is in force."""
        return self.ledger.highest_safety_version()

    def protection_right(self) -> int | None:
        if self.safety() is None:
            return None
        active = self.ledger.active_rights(
            self.device_id, self.ledger.recovery(), RightKind.PROTECTION
        )
        return active[-1].number if active else None

    def approve_safety(self, config: SafetyConfig, operator: str) -> int:
        if not operator.strip():
            raise refusals.safety_needs_approver()
        unknown = sorted(set(config.frozen.minutes) - set(SENSORS))
        if unknown:  # a misspelt name would silently switch that sensor's frozen check off
            raise refusals.safety_unknown_sensors(unknown)
        self._require_host()
        now = self.clock.now()
        approved = config.model_copy(update={"approved_by": operator, "approved_at": now})
        with self.db.transaction():  # the check and the insert are one step
            highest = self.ledger.highest_safety_version() or 0
            if config.version <= highest:  # each approved set keeps its own number
                raise refusals.safety_version_not_above(config.version, highest)
            recovery = self.ledger.recovery()
            self.ledger.save_safety(approved, recovery, operator, now)
            number = self._issue_protection(approved, recovery, now)
            self.ledger.event("safety_approved", {"version": config.version, "by": operator}, now)
        return number

    def _issue_protection(self, config: SafetyConfig, recovery: int, now: float) -> int:
        for old in self.ledger.active_rights(self.device_id, recovery, RightKind.PROTECTION):
            self.ledger.revoke(old.number, now)
        levels = tuple(rule.action for rule in config.rules)
        scope = RightScope(device_id=self.device_id, levels=levels)
        if levels:
            right = rights.build_right(RightKind.PROTECTION, scope, None, recovery, now)
        else:  # nothing to write: an empty right still marks the approval
            right = WriteRight(
                number=0,
                kind=RightKind.PROTECTION,
                device_id=self.device_id,
                recovery_number=recovery,
                granted_at=now,
            )
        return self.ledger.add_right(right)

    def safety_conflicts(self, run_sheet: RunSheet) -> tuple[str, ...]:
        config = self.safety()
        if config is None:
            return ()
        found = []
        for rule in config.rules:
            plan = run_sheet.plan(rule.action.channel)
            if plan is None or plan.ownership is not Ownership.HOST:
                found.append(
                    f"{rule.id}: {rule.action.channel.value} is not host-controlled in "
                    f"run sheet {run_sheet.id}"
                )
        return tuple(found)

    # --- startup, transport, interlock state --------------------------------------------------

    async def startup(self) -> None:
        self.ready = False  # ordinary writes stay blocked until everything below is done
        now = self.clock.now()
        with self.db.transaction():
            self.ledger.revoke_all(now)
            changed = self._close_unfinished()
            self.ledger.event("startup", {"actions": len(changed)}, now)
        self._publish(changed)
        await self._halt()
        if any(item.channel is Channel.PUMP for item in self.ledger.unsettled()):
            self.ledger.set_flag(FLAG_INTERLOCK, True)
        stored = self.ledger.latest_safety()
        if stored is not None and stored[1] == self.ledger.recovery():
            with self.db.transaction():
                self._issue_protection(stored[0], stored[1], self.clock.now())
        self.ready = True

    def _close_unfinished(self) -> list[ActionRecord]:
        note = "process stopped before the receipt was stored; not replayed"
        changed = []
        for record in self.ledger.actions_in(ActionState.MAYBE_SENT):
            update = {"state": ActionState.UNKNOWN, "error": note, "error_code": "lost_receipt"}
            changed.append(record.model_copy(update=update))
            self.ledger.update_action(changed[-1])
        changed.extend(
            self._void_queued("process stopped before the action was sent", code="void_restart")
        )
        return changed

    def _void_queued(
        self,
        why: str,
        code: str,
        params: dict[str, Any] | None = None,
        right_number: int | None = None,
        channel: Channel | None = None,
        spare: RightKind | None = None,
    ) -> list[ActionRecord]:
        """Void queued actions, optionally only on ``channel`` and sparing right kind ``spare``.
        ``code`` and ``params`` are the receipt message for ``why``."""
        voided = []
        for record in self.ledger.actions_in(ActionState.PENDING, right_number=right_number):
            if channel is not None and record.channel is not channel:
                continue
            if spare is not None and record.right_kind is spare:
                continue
            update = {
                "state": ActionState.VOID,
                "error": why,
                "error_code": code,
                "error_params": dict(params or {}),
            }
            voided.append(record.model_copy(update=update))
            self.ledger.update_action(voided[-1])
        return voided

    async def _halt(self) -> bool:
        transport = self.bridge.transport
        confirmed = False
        if transport is not None:
            try:
                confirmed = bool(await transport.halt())
            except Exception:
                log.exception("transport halt did not complete")
        self.ledger.set_flag(FLAG_TRANSPORT_STOPPED, confirmed)
        self.ledger.event("transport_halt", {"confirmed": confirmed}, self.clock.now())
        return confirmed

    async def confirm_transport_stopped(self) -> bool:
        return await self._halt()

    def transport_stopped(self) -> bool:
        return self.ledger.flag(FLAG_TRANSPORT_STOPPED)

    def interlocked(self) -> bool:
        return self.ledger.flag(FLAG_INTERLOCK)

    def unsettled_actions(self) -> tuple[ActionRecord, ...]:
        return tuple(self.ledger.unsettled())

    def receipt(self, request_id: str) -> ActionRecord | None:
        found = self.ledger.action(request_id)
        return None if found is None else found[0]

    async def onsite_check(self, operator: str, note: str) -> None:
        if not operator.strip():
            raise refusals.onsite_needs_operator()
        now = self.clock.now()
        with self.db.transaction():
            settled = self._settle_unknown(now)
            self.ledger.set_flag(FLAG_INTERLOCK, False)
            self.ledger.set_flag(FLAG_TRANSPORT_STOPPED, True)
            self.ledger.event("onsite_check", {"operator": operator, "note": note}, now)
        self._publish(settled)

    def _settle_unknown(self, now: float, pump_only: bool = False) -> list[ActionRecord]:
        settled = []
        for record in self.ledger.unsettled():
            if pump_only and record.channel is not Channel.PUMP:
                continue
            settled.append(record.model_copy(update={"settled_at": now}))
            self.ledger.update_action(settled[-1])
        return settled

    # --- writing ------------------------------------------------------------------------------

    async def submit(self, request: ActionRequest) -> ActionRecord:
        fingerprint = content_digest(request.model_dump(mode="json"))
        known = self._known(request.request_id, fingerprint)
        if known is not None:
            return known
        right = self._authorize(request)
        if right.kind is RightKind.PROTECTION:
            # a protection write must not wait for a pump run to finish
            self._end_cycle(
                f"protection write: {request.trigger}",
                code="protection_write",
                params={"channel": request.channel.value},
            )
            self._supersede_queued(request.channel)
        record = rights.intent(request, right, request.level, self.clock.now())
        self._save(record, fingerprint)
        urgent = right.kind is RightKind.PROTECTION
        async with self.gate.acquire(URGENT if urgent else NORMAL):
            self._recheck(record, request)
            return await self._send(record)

    def _supersede_queued(self, channel: Channel) -> None:
        """A protection write has the last word: ordinary writes queued ahead of it on its channel
        would otherwise run after it and undo it. The write already on its way is left alone."""
        why = f"superseded by a protection write on {channel.value}"
        with self.db.transaction():
            voided = self._void_queued(
                why,
                code="void_superseded",
                params={"channel": channel.value},
                channel=channel,
                spare=RightKind.PROTECTION,
            )
        self._publish(voided)

    async def irrigate(
        self, request: ActionRequest, seconds: float, planned: bool = False
    ) -> ActionRecord:
        """An operator-triggered pump run. ``planned``: a run sheet's irrigation task started by
        the operator from the stage page, under the stage right while the stage keeps running;
        otherwise a manual right is needed. Every other check is the same."""
        self._check_irrigation(request, seconds)
        content = {"request": request.model_dump(mode="json"), "s": seconds}
        fingerprint = content_digest({**content, "planned": True} if planned else content)
        known = self._known(request.request_id, fingerprint)
        if known is not None:
            return known
        right = self._authorize(request, starts_pump=True, planned=planned)
        self._check_cooldown()
        record = rights.intent(request, right, 1, self.clock.now())
        self._save(record, fingerprint)
        return await self._run_cycle(record, request, seconds, planned)

    def _check_irrigation(self, request: ActionRequest, seconds: float) -> None:
        limit = self.bridge.settings.max_pump_seconds
        valid = isinstance(seconds, (int, float)) and not isinstance(seconds, bool)
        if not valid or not math.isfinite(seconds) or not 0 < seconds <= limit:
            raise refusals.irrigation_seconds_range(seconds, limit)
        if request.channel is not Channel.PUMP or request.level != 1:
            raise refusals.irrigation_wrong_request()

    def _check_cooldown(self) -> None:
        last = self.ledger.meta(META_LAST_IRRIGATION)
        cooldown = self.bridge.settings.pump_cooldown_seconds
        if self._cycle is not None:
            raise refusals.irrigation_running(self.device_id)
        if last and self.clock.now() - float(last) < cooldown:
            raise refusals.irrigation_too_soon(cooldown, float(last), self.clock.now())

    def _known(self, request_id: str, fingerprint: str) -> ActionRecord | None:
        found = self.ledger.action(request_id)
        if found is None:
            return None
        if found[1] != fingerprint:
            raise refusals.request_id_reused(request_id)
        return found[0]

    def _authorize(
        self, request: ActionRequest, starts_pump: bool = False, planned: bool = False
    ) -> WriteRight:
        """Every check that must hold when an action is queued and again when it is sent."""
        if not self.bridge.settings.controls_enabled:
            raise refusals.controls_disabled()
        self._require_host()
        right = rights.check_valid(
            self.ledger.right(request.right_number),
            self.device_id,
            self.ledger.recovery(),
            request.right_number,
        )
        if starts_pump and not _may_irrigate(right, request, planned):
            raise refusals.right_wrong_kind(right.number)
        rights.check_scope(right, request)
        if not starts_pump:
            rights.check_pump_not_started(request)
        self._check_gate_state(right.kind, request.channel)
        self._check_link(right.kind)
        return right

    def _check_gate_state(self, kind: RightKind, channel: Channel) -> None:
        if kind is RightKind.PROTECTION:
            return
        if not self.ready:
            raise refusals.still_starting()
        if self.interlocked():
            if kind is RightKind.CARE and channel is not Channel.PUMP and self.transport_stopped():
                return
            raise refusals.pump_unconfirmed(self.device_id)
        if not self.transport_stopped():
            raise refusals.old_path_running()
        unsettled = self.ledger.unsettled() if kind in rights.ORDINARY_KINDS else []
        if unsettled:
            raise refusals.unknown_result(len(unsettled))

    def _check_link(self, kind: RightKind) -> None:
        if not self.bridge.connected:
            raise refusals.no_live_link(self.device_id)
        health = self.bridge.health() if kind in rights.ORDINARY_KINDS else None
        if health is not None and health["stale"]:
            raise refusals.stale(self.device_id, health["age_seconds"])

    def _recheck(
        self,
        record: ActionRecord,
        request: ActionRequest,
        starts_pump: bool = False,
        planned: bool = False,
    ) -> None:
        current = self.receipt(record.request_id)
        if current is None or current.state is not ActionState.PENDING:
            raise refusals.right_voided(request.right_number)
        try:
            self._authorize(request, starts_pump, planned)
            if starts_pump:
                self._check_cooldown()
        except Denied as error:
            update = {
                "state": ActionState.VOID,
                "error": str(error),
                "error_code": "void_denied",
                "error_params": {"denied_code": error.code},
            }
            self._save(current.model_copy(update=update))
            raise

    async def _send(self, record: ActionRecord) -> ActionRecord:
        update = {"state": ActionState.MAYBE_SENT, "sent_at": self.clock.now()}
        sent = self._save(record.model_copy(update=update))
        return self._settle(sent, await self._write(sent.channel, sent.planned_level))

    async def _write(self, channel: Channel, level: int) -> Outcome:
        try:
            return await self.device.write(channel, level)
        except Exception as error:
            log.exception("device write failed unexpectedly")
            return Outcome(
                ActionState.UNKNOWN,
                f"{type(error).__name__}: {error}",
                error_code="internal_error",
            )

    def _settle(self, record: ActionRecord, outcome: Outcome) -> ActionRecord:
        update: dict[str, Any] = {
            "state": outcome.state,
            "error": outcome.error,
            "error_code": outcome.error_code,
            "error_params": dict(outcome.error_params),
        }
        if outcome.state is ActionState.CONFIRMED:
            update.update(confirmed_at=self.clock.now(), confirmed_level=record.planned_level)
        return self._save(record.model_copy(update=update))

    # --- pump (7.6, 7.8) ----------------------------------------------------------------------

    def _end_cycle(
        self, reason: str, code: str = "other", params: dict[str, Any] | None = None
    ) -> None:
        """End the running cycle early; ``reason`` is the English text, ``code`` and ``params``
        the task_end message for it."""
        if self._cycle is not None and not self._cycle.is_set():
            self._cycle_ended = (reason, code, dict(params or {}))
            self._cycle.set()

    async def _hold(self, cycle: asyncio.Event, seconds: float) -> dict[str, Any]:
        """Keep the pump on for ``seconds`` or until the cycle is ended. The length is measured
        on the event loop's clock, the one the wait runs on."""
        loop = asyncio.get_running_loop()
        began = loop.time()
        try:
            await asyncio.wait_for(cycle.wait(), timeout=seconds)
        except TimeoutError:
            return {"ran_seconds": seconds, "ended_early": None}
        ran = min(seconds, loop.time() - began)
        if self._cycle_ended is None:
            return {
                "ran_seconds": ran,
                "ended_early": "ended early",
                "ended_early_code": "other",
                "ended_early_params": {},
            }
        reason, code, params = self._cycle_ended
        return {
            "ran_seconds": ran,
            "ended_early": reason,
            "ended_early_code": code,
            "ended_early_params": params,
        }

    async def _run_cycle(
        self, record: ActionRecord, request: ActionRequest, seconds: float, planned: bool = False
    ) -> ActionRecord:
        """ON under the gate, wait outside it, OFF under the gate; OFF always runs (7.6, 7.8)."""
        cycle = None
        try:
            async with self.gate.acquire(NORMAL):
                self._recheck(record, request, starts_pump=True, planned=planned)
                now = self.clock.now()
                self.ledger.set_meta(META_LAST_IRRIGATION, str(now))
                cycle = self._cycle = asyncio.Event()
                self._cycle_ended = None
                update = {"state": ActionState.MAYBE_SENT, "sent_at": now}
                sent = self._save(record.model_copy(update=update))
                on = await self._write(Channel.PUMP, 1)
            if on.state is ActionState.CONFIRMED:
                sent = sent.model_copy(update=await self._hold(cycle, seconds))
        finally:
            if cycle is not None:
                off = Outcome(
                    ActionState.UNKNOWN, "pump off did not run", error_code="pump_off_unconfirmed"
                )
                try:
                    async with self.gate.acquire(URGENT):
                        off = await self._switch_pump_off()
                        self._last_cycle_end = self.clock.monotonic()
                finally:
                    self._cycle = None
                    if off.state is not ActionState.CONFIRMED:
                        self._set_interlock(sent.request_id)
        if off.state is not ActionState.CONFIRMED:
            on = Outcome(
                ActionState.UNKNOWN,
                "pump off unconfirmed; interlock set",
                error_code="pump_off_unconfirmed",
            )
        return self._settle(sent, on)

    def _set_interlock(self, request_id: str) -> None:
        self.ledger.set_flag(FLAG_INTERLOCK, True)
        self.ledger.event("interlock", {"request_id": request_id}, self.clock.now())

    async def _switch_pump_off(self) -> Outcome:
        outcome = Outcome(ActionState.UNKNOWN, "no attempt", error_code="pump_off_unconfirmed")
        for attempt in range(PUMP_OFF_TRIES):
            outcome = await self._write(Channel.PUMP, 0)
            if outcome.state is ActionState.CONFIRMED:
                break
            if attempt + 1 < PUMP_OFF_TRIES:
                await asyncio.sleep(self.bridge.readback_interval)
        return outcome

    async def pump_off(self, trigger: PumpOffTrigger = "interlock") -> bool:
        """Dedicated interlock path: only the pump outlet, only off, usable while paused.

        It is recorded in the ledger under the system right 0 (trigger ``interlock`` or
        ``watchdog``) and links the pump action it follows through ``supersedes``."""
        self._require_host()
        if not self.bridge.connected:
            return False
        self._end_cycle(f"pump switched off ({trigger})", code=f"pump_off_{trigger}")
        now = self.clock.now()
        pending = [item for item in self.ledger.unsettled() if item.channel is Channel.PUMP]
        record = ActionRecord(
            request_id=new_id("pumpoff"),
            state=ActionState.MAYBE_SENT,
            channel=Channel.PUMP,
            planned_level=0,
            right_number=0,
            right_kind=RightKind.PROTECTION,
            trigger=trigger,
            created_at=now,
            sent_at=now,
            supersedes=pending[-1].request_id if pending else None,
        )
        self._last_pump_off_id = record.request_id
        self._save(record, "system:pump_off")
        outcome = await self._switch_pump_off()
        confirmed = outcome.state is ActionState.CONFIRMED
        self._settle(record, outcome)
        self.ledger.event(
            "pump_off", {"confirmed": confirmed, "trigger": trigger}, self.clock.now()
        )
        if not confirmed:
            self._set_interlock(record.request_id)
        elif self.transport_stopped():
            with self.db.transaction():
                settled = self._settle_unknown(self.clock.now(), pump_only=True)
                self.ledger.set_flag(FLAG_INTERLOCK, False)
            self._publish(settled)
        return confirmed

    async def reconcile_unsettled(self) -> tuple[ActionRecord, ...]:
        """Read the device back and settle unknown non-pump actions as applied or not applied."""
        if not self._can_reconcile():
            return self.unsettled_actions()
        try:
            state = await self.read_state()
        except Denied:
            return self.unsettled_actions()
        async with self.gate.acquire(NORMAL):
            settled = []
            for record in self.ledger.unsettled():
                if record.channel is Channel.PUMP:
                    continue
                level, mode = state.levels.get(record.channel), state.modes.get(record.channel)
                applied = level == record.planned_level and mode == 0
                verdict = "applied" if applied else "not applied"
                params = {"channel": record.channel.value, "level": level}
                if not applied:
                    params["mode"] = mode
                note = f"settled by read-back: {verdict} (level {level}, mode {mode})"
                error = f"{record.error}; {note}" if record.error else note
                update = {
                    "settled_at": self.clock.now(),
                    "error": error,
                    "error_code": "settled_applied" if applied else "settled_not_applied",
                    "error_params": params,
                }
                settled.append(record.model_copy(update=update))
                self.ledger.update_action(settled[-1])
        self._publish(settled)
        return self.unsettled_actions()

    def _can_reconcile(self) -> bool:
        if not any(item.channel is not Channel.PUMP for item in self.ledger.unsettled()):
            return False
        link = self.bridge.connected and not self.bridge.health()["stale"]
        return bool(link and self.transport_stopped())

    # --- records ------------------------------------------------------------------------------

    def _save(self, record: ActionRecord, fingerprint: str | None = None) -> ActionRecord:
        if fingerprint is None:
            self.ledger.update_action(record)
        else:
            self.ledger.insert_action(record, fingerprint)
        self._publish([record])
        return record

    def _publish(self, records: list[ActionRecord]) -> None:
        if self.sink is None:
            return
        for record in records:
            try:
                self.sink.append_action(record)
            except Exception:
                log.exception("record sink rejected action %s", record.request_id)


def _may_irrigate(right: WriteRight, request: ActionRequest, planned: bool) -> bool:
    """A manual right may irrigate; the stage right only for a planned irrigation of its stage."""
    if right.kind is RightKind.MANUAL:
        return True
    return (
        planned
        and right.kind is RightKind.STAGE
        and request.stage_id is not None
        and request.stage_id == right.stage_id
    )
