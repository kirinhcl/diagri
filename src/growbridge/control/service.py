"""Control service: the single checkpoint for every BLE write (spec 7.1-7.3, 7.5, 7.6, 7.8, 7.9).

One two-level priority gate serialises hand-overs and every dispatch. Protection writes, the
pump-off at the end of an irrigation and hand-overs go before queued ordinary writes (they never
preempt the write already on its way). A request is checked
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
from growbridge.control import rights
from growbridge.control.device import DeviceIO, Outcome
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
        self.ready = False  # False until ``startup`` has finished: ordinary writes are blocked

    @property
    def device_id(self) -> str:
        return str(self.bridge.settings.device)

    # --- host, recovery number, simple reads --------------------------------------------------

    def register_host(self) -> None:
        if not self.ledger.register_host(self.device_id, self.host_id, self.clock.now()):
            raise Denied("host_unregistered", "another host is registered for this device")

    def host_registered(self) -> bool:
        return self.ledger.host_of(self.device_id) == self.host_id

    def _require_host(self) -> None:
        if not self.host_registered():
            raise Denied("host_unregistered", "this host is not the registered write host")

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
            voided = self._void_queued("recovery number changed")
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
            raise Denied("not_connected", str(error)) from error

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
            raise Denied("scope", f"{scope.device_id} is not the controlled device")
        with self.db.transaction():
            recovery = self.ledger.recovery()
            right = rights.build_right(kind, scope, operator, recovery, self.clock.now())
            held = self.ledger.active_rights(self.device_id, recovery, RightKind.STAGE)
            if held and kind in rights.ORDINARY_KINDS:
                raise Denied("right_held", "a stage write right is already held for this device")
            return self.ledger.add_right(right)

    def right(self, number: int) -> WriteRight | None:
        return self.ledger.right(number)

    async def handover(self, number: int, reason: str) -> None:
        now = self.clock.now()
        self._end_cycle()
        with self.db.transaction():
            self.ledger.revoke(number, now)
            voided = self._void_queued(f"hand-over: {reason}", right_number=number)
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

    def protection_right(self) -> int | None:
        if self.safety() is None:
            return None
        active = self.ledger.active_rights(
            self.device_id, self.ledger.recovery(), RightKind.PROTECTION
        )
        return active[-1].number if active else None

    def approve_safety(self, config: SafetyConfig, operator: str) -> int:
        if not operator.strip():
            raise Denied("approval_invalid", "the safety configuration needs an approver")
        self._require_host()
        now = self.clock.now()
        approved = config.model_copy(update={"approved_by": operator, "approved_at": now})
        with self.db.transaction():
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
            changed.append(record.model_copy(update={"state": ActionState.UNKNOWN, "error": note}))
            self.ledger.update_action(changed[-1])
        changed.extend(self._void_queued("process stopped before the action was sent"))
        return changed

    def _void_queued(self, why: str, right_number: int | None = None) -> list[ActionRecord]:
        voided = []
        for record in self.ledger.actions_in(ActionState.PENDING, right_number=right_number):
            voided.append(record.model_copy(update={"state": ActionState.VOID, "error": why}))
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
            raise Denied("not_operator", "an on-site check needs an identified operator")
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
            self._end_cycle()  # a protection write must not wait for a pump run to finish
        record = rights.intent(request, right, request.level, self.clock.now())
        self._save(record, fingerprint)
        urgent = right.kind is RightKind.PROTECTION
        async with self.gate.acquire(URGENT if urgent else NORMAL):
            self._recheck(record, request)
            return await self._send(record)

    async def irrigate(self, request: ActionRequest, seconds: float) -> ActionRecord:
        self._check_irrigation(request, seconds)
        fingerprint = content_digest({"request": request.model_dump(mode="json"), "s": seconds})
        known = self._known(request.request_id, fingerprint)
        if known is not None:
            return known
        right = self._authorize(request, starts_pump=True)
        self._check_cooldown()
        record = rights.intent(request, right, 1, self.clock.now())
        self._save(record, fingerprint)
        return await self._run_cycle(record, request, seconds)

    def _check_irrigation(self, request: ActionRequest, seconds: float) -> None:
        limit = self.bridge.settings.max_pump_seconds
        valid = isinstance(seconds, (int, float)) and not isinstance(seconds, bool)
        if not valid or not math.isfinite(seconds) or not 0 < seconds <= limit:
            raise Denied("scope", f"irrigation must run for more than 0 and at most {limit} s")
        if request.channel is not Channel.PUMP or request.level != 1:
            raise Denied("scope", "irrigation switches the pump on (channel pump, level 1)")

    def _check_cooldown(self) -> None:
        last = self.ledger.meta(META_LAST_IRRIGATION)
        cooldown = self.bridge.settings.pump_cooldown_seconds
        if self._cycle is not None:
            raise Denied("cooldown", "an irrigation is already running")
        if last and self.clock.now() - float(last) < cooldown:
            raise Denied("cooldown", f"the pump needs {cooldown} s between irrigations")

    def _known(self, request_id: str, fingerprint: str) -> ActionRecord | None:
        found = self.ledger.action(request_id)
        if found is None:
            return None
        if found[1] != fingerprint:
            raise Denied("request_id_reused", f"{request_id} was used for other arguments")
        return found[0]

    def _authorize(self, request: ActionRequest, starts_pump: bool = False) -> WriteRight:
        """Every check that must hold when an action is queued and again when it is sent."""
        if not self.bridge.settings.controls_enabled:
            raise Denied("controls_disabled", "controls are disabled in the local configuration")
        self._require_host()
        right = rights.check_valid(
            self.ledger.right(request.right_number), self.device_id, self.ledger.recovery()
        )
        if starts_pump and right.kind is not RightKind.MANUAL:
            raise Denied("right_invalid", "irrigation needs a manual write right")
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
            raise Denied("unsettled", "the control service has not finished starting up")
        if self.interlocked():
            if kind is RightKind.CARE and channel is not Channel.PUMP and self.transport_stopped():
                return
            raise Denied("interlock", "pump off is unconfirmed; ordinary writes are blocked")
        if not self.transport_stopped():
            raise Denied("unsettled", "the old write path is not confirmed stopped")
        if kind in rights.ORDINARY_KINDS and self.ledger.unsettled():
            raise Denied("unsettled", "an earlier action has an unknown result")

    def _check_link(self, kind: RightKind) -> None:
        if not self.bridge.connected:
            raise Denied("not_connected", "no live BLE connection")
        if kind in rights.ORDINARY_KINDS and self.bridge.health()["stale"]:
            raise Denied("stale", "fresh device telemetry is required before an ordinary write")

    def _recheck(
        self, record: ActionRecord, request: ActionRequest, starts_pump: bool = False
    ) -> None:
        current = self.receipt(record.request_id)
        if current is None or current.state is not ActionState.PENDING:
            raise Denied("right_invalid", "the queued action was voided before it was sent")
        try:
            self._authorize(request, starts_pump)
            if starts_pump:
                self._check_cooldown()
        except Denied as error:
            self._save(current.model_copy(update={"state": ActionState.VOID, "error": str(error)}))
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
            return Outcome(ActionState.UNKNOWN, f"{type(error).__name__}: {error}")

    def _settle(self, record: ActionRecord, outcome: Outcome) -> ActionRecord:
        update: dict[str, Any] = {"state": outcome.state, "error": outcome.error}
        if outcome.state is ActionState.CONFIRMED:
            update.update(confirmed_at=self.clock.now(), confirmed_level=record.planned_level)
        return self._save(record.model_copy(update=update))

    # --- pump (7.6, 7.8) ----------------------------------------------------------------------

    def _end_cycle(self) -> None:
        if self._cycle is not None:
            self._cycle.set()

    async def _run_cycle(
        self, record: ActionRecord, request: ActionRequest, seconds: float
    ) -> ActionRecord:
        """ON under the gate, wait outside it, OFF under the gate; OFF always runs (7.6, 7.8)."""
        cycle = None
        try:
            async with self.gate.acquire(NORMAL):
                self._recheck(record, request, starts_pump=True)
                now = self.clock.now()
                self.ledger.set_meta(META_LAST_IRRIGATION, str(now))
                cycle = self._cycle = asyncio.Event()
                update = {"state": ActionState.MAYBE_SENT, "sent_at": now}
                sent = self._save(record.model_copy(update=update))
                on = await self._write(Channel.PUMP, 1)
            if on.state is ActionState.CONFIRMED:
                try:
                    await asyncio.wait_for(cycle.wait(), timeout=seconds)
                except TimeoutError:
                    pass
        finally:
            if cycle is not None:
                async with self.gate.acquire(URGENT):
                    off = await self._switch_pump_off()
                self._cycle = None
                if off.state is not ActionState.CONFIRMED:
                    self._set_interlock(sent.request_id)
        if off.state is not ActionState.CONFIRMED:
            on = Outcome(ActionState.UNKNOWN, "pump off unconfirmed; interlock set")
        return self._settle(sent, on)

    def _set_interlock(self, request_id: str) -> None:
        self.ledger.set_flag(FLAG_INTERLOCK, True)
        self.ledger.event("interlock", {"request_id": request_id}, self.clock.now())

    async def _switch_pump_off(self) -> Outcome:
        outcome = Outcome(ActionState.UNKNOWN, "no attempt")
        for attempt in range(PUMP_OFF_TRIES):
            outcome = await self._write(Channel.PUMP, 0)
            if outcome.state is ActionState.CONFIRMED:
                break
            if attempt + 1 < PUMP_OFF_TRIES:
                await asyncio.sleep(self.bridge.readback_interval)
        return outcome

    async def pump_off(self) -> bool:
        """Dedicated interlock path: only the pump outlet, only off, usable while paused.

        It is recorded in the ledger under the system right 0 (trigger ``interlock``) and links
        the pump action it follows through ``supersedes``."""
        self._require_host()
        if not self.bridge.connected:
            return False
        self._end_cycle()
        now = self.clock.now()
        pending = [item for item in self.ledger.unsettled() if item.channel is Channel.PUMP]
        record = ActionRecord(
            request_id=new_id("pumpoff"),
            state=ActionState.MAYBE_SENT,
            channel=Channel.PUMP,
            planned_level=0,
            right_number=0,
            right_kind=RightKind.PROTECTION,
            trigger="interlock",
            created_at=now,
            sent_at=now,
            supersedes=pending[-1].request_id if pending else None,
        )
        self._save(record, "system:pump_off")
        outcome = await self._switch_pump_off()
        confirmed = outcome.state is ActionState.CONFIRMED
        self._settle(record, outcome)
        self.ledger.event("pump_off", {"confirmed": confirmed}, self.clock.now())
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
                note = f"settled by read-back: {verdict} (level {level}, mode {mode})"
                error = f"{record.error}; {note}" if record.error else note
                update = {"settled_at": self.clock.now(), "error": error}
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
