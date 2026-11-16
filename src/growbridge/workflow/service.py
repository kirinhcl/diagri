"""Workflow service: the only owner of round and stage state (architecture doc §5.2, §7.7, App. B).

Every stage change is a ``Plan``: which state to enter, which write rights to hand over first,
which to grant afterwards, and what else to record. ``_apply`` awaits the hand-overs, re-reads
the stage, issues the new rights and then saves state, history and follow-up records in one
transaction. Nothing is awaited inside a transaction; a stale revision raises ``Denied("state")``.
"""

import logging
from collections.abc import Callable, Sequence
from typing import Any, Literal

from growbridge.archive.clock import Clock
from growbridge.archive.db import Database
from growbridge.archive.ids import new_id
from growbridge.archive.models import (
    Approval,
    ResearchProtocol,
    RightKind,
    RunSheet,
)
from growbridge.planning.treatment import check_treatment
from growbridge.ports import (
    Actor,
    ControlPort,
    Denied,
    Difference,
    Finding,
    StageEvent,
    StageEventKind,
    StageRuntime,
)
from growbridge.workflow.permissions import require_kind, require_operator
from growbridge.workflow.recovery import StageRecovery
from growbridge.workflow.states import ROUND_TERMINAL, STAGE_TERMINAL, RoundState, StageState
from growbridge.workflow.store import (
    DuplicateEvent,
    Grant,
    Hook,
    Plan,
    RoundRow,
    StageRow,
    WorkflowStore,
    care_if_missing,
    describe,
    end_actions_plan,
    expiry_plan,
    held,
    pause_plan,
    recovery_plan,
    right_scope,
)

S = StageState
K = StageEventKind
DESIGNERS = ("operator", "workflow")
DRAFTERS = ("operator", "workflow", "model")
MODEL_DRAFTER = "planner"  # the one model role that files run sheets (``agents/roles.py``)
PAUSE_KINDS = frozenset(
    {
        K.DISCONNECT_AFFECTS,
        K.READINGS_STALE,
        K.EXTERNAL_CHANGE,
        K.CLOCK_ANOMALY,
        K.RESULT_UNKNOWN,
        K.ALERT_PAUSE,
        K.RULE_PAUSE,
    }
)
UNCONFIRMED_KINDS = frozenset({K.PUMP_OFF_UNCONFIRMED, K.TRANSPORT_UNCONFIRMED})
log = logging.getLogger(__name__)
Choice = Literal["redo", "next", "verify", "abort"]


class WorkflowService(StageRecovery):
    """Implements ``ports.StagePort``. The recovery check is in ``workflow/recovery.py``."""

    def __init__(
        self,
        db: Database,
        clock: Clock,
        control: ControlPort,
        validate: Callable[[RunSheet], Sequence[Finding]] | None = None,
        on_intervention: Callable[[dict], None] | None = None,
        check_treatments: bool = True,
    ):
        self.db = db
        self.clock = clock
        self.control = control
        self.validate = validate
        # whether a sheet must apply its round's treatment; off only in tests whose fixture
        # sheets ignore the fixture protocol's treatments
        self.check_treatments = check_treatments
        self.on_intervention = on_intervention  # hands each recorded intervention on, once saved
        self.store = WorkflowStore(db)
        self._unsent: list[dict] = []  # saved in a transaction, not yet handed on

    # --- design --------------------------------------------------------------------------------

    def create_project(self, name: str, actor: Actor) -> str:
        require_kind(actor, DESIGNERS)
        if not name.strip():
            raise Denied("state", "a project needs a name")
        project_id = new_id("project")
        self.store.add_project(project_id, name, self.clock.now())
        return project_id

    def save_protocol(self, protocol: ResearchProtocol, actor: Actor) -> ResearchProtocol:
        require_kind(actor, DESIGNERS)
        if not self.store.has_project(protocol.project_id):
            raise Denied("state", f"unknown project {protocol.project_id}")
        saved = self.store.protocol(protocol.id, protocol.version)
        if saved is None:
            self.store.put_protocol(protocol, self.clock.now())
            return protocol
        if saved.digest() != protocol.digest():
            raise Denied(
                "state", f"protocol {protocol.id} v{protocol.version} exists: bump version"
            )
        return saved

    def create_round(self, project_id: str, protocol_id: str, actor: Actor) -> str:
        require_kind(actor, DESIGNERS)
        protocol = self.store.latest_protocol(protocol_id, project_id)
        if protocol is None:
            raise Denied("state", f"no protocol {protocol_id} saved for project {project_id}")
        round_id = new_id("round")
        row = RoundRow(
            id=round_id,
            project_id=project_id,
            protocol_id=protocol.id,
            protocol_version=protocol.version,
            state=RoundState.DESIGNING,
        )
        self.store.add_round(row, self.clock.now())
        return round_id

    def submit_run_sheet(
        self, round_id: str, run_sheet: RunSheet, actor: Actor
    ) -> tuple[Finding, ...]:
        require_kind(actor, DRAFTERS)
        if actor.kind == "model" and actor.id != MODEL_DRAFTER:
            raise Denied("model_role", f"only the {MODEL_DRAFTER} files run sheets")
        rnd = self.store.round(round_id)
        if rnd.state not in (RoundState.DESIGNING, RoundState.STAGE_REVIEW) or rnd.awaiting_choice:
            raise Denied("state", f"round is {rnd.state.value}; no run sheet can be submitted")
        owner = (run_sheet.project_id, run_sheet.protocol_id, run_sheet.protocol_version)
        if owner != (rnd.project_id, rnd.protocol_id, rnd.protocol_version):
            raise Denied("state", "run sheet does not belong to this round's project and protocol")
        self._check_experiment_owner(run_sheet)
        findings = self._findings(run_sheet, round_id)
        if any(finding.blocking for finding in findings):
            return findings
        stage = self.store.find_stage(run_sheet.stage_id)
        with self.db.transaction():
            if stage is None:
                self._add_stage(rnd, run_sheet)
            else:
                self._replace_run_sheet(rnd, stage, run_sheet)
            if rnd.state is RoundState.DESIGNING:
                self.store.update_round(round_id, state=RoundState.STAGE_REVIEW)
        return findings

    def _check_experiment_owner(self, sheet: RunSheet) -> None:
        """An experiment id belongs to one project; its data is scoped by that ownership."""
        for stage in self.store.stages_in(S):
            if stage.experiment_id == sheet.experiment_id and stage.project_id != sheet.project_id:
                raise Denied(
                    "scope", f"experiment {sheet.experiment_id} belongs to another project"
                )

    def _findings(self, run_sheet: RunSheet, round_id: str) -> tuple[Finding, ...]:
        """The program checks, and whether the sheet applies the treatment of ``round_id``."""
        own = tuple(self.validate(run_sheet)) if self.validate else ()
        if not self.check_treatments:
            return own
        rnd = self.store.round(round_id)  # the round's protocol, whatever the sheet names
        protocol = self.store.protocol(rnd.protocol_id, rnd.protocol_version)
        if protocol is None:  # a round is only created for a saved protocol
            raise Denied("state", f"protocol {rnd.protocol_id} is not saved")
        return (*own, *check_treatment(run_sheet, protocol, self.store.round_number(round_id)))

    def _add_stage(self, rnd: RoundRow, sheet: RunSheet) -> None:
        if self.store.run_sheet_digest(sheet.id, sheet.version) is not None:
            raise Denied("state", f"run sheet {sheet.id} v{sheet.version} is already in use")
        now = self.clock.now()
        self.store.put_run_sheet(sheet, rnd.id, now)
        self.store.add_stage(
            StageRow(
                stage_id=sheet.stage_id,
                round_id=rnd.id,
                project_id=sheet.project_id,
                experiment_id=sheet.experiment_id,
                device_id=sheet.device_id,
                run_sheet_id=sheet.id,
                run_sheet_version=sheet.version,
                state=S.PENDING_REVIEW,
                state_at=now,
                recovery_number=self.control.recovery_number(),
            )
        )

    def _replace_run_sheet(self, rnd: RoundRow, stage: StageRow, sheet: RunSheet) -> None:
        """A new version while waiting for review voids the approval of the old one (App. B)."""
        if stage.round_id != rnd.id or stage.state is not S.PENDING_REVIEW:
            raise Denied("state", f"stage {stage.stage_id} is {stage.state.value}; use a switch")
        bound = (stage.project_id, stage.experiment_id, stage.device_id)
        if (sheet.project_id, sheet.experiment_id, sheet.device_id) != bound:
            # rights follow the sheet's device while checks read the stage row: keep them equal
            raise Denied(
                "state", "a replacement run sheet keeps the stage's project, experiment and device"
            )
        current = self._sheet(stage)
        if sheet.version == current.version:
            if sheet.digest() != current.digest():
                raise Denied("state", "same run sheet version with other content: bump version")
            return
        if sheet.version < current.version:
            raise Denied("state", f"run sheet v{sheet.version} is older than v{current.version}")
        if self.store.run_sheet_digest(sheet.id, sheet.version) is not None:
            raise Denied("state", f"run sheet {sheet.id} v{sheet.version} is already in use")
        now = self.clock.now()
        self.store.put_run_sheet(sheet, rnd.id, now)
        self.store.void_approvals(stage.stage_id, now)
        self.store.update_stage(stage, run_sheet_id=sheet.id, run_sheet_version=sheet.version)

    def revalidate(self, stage_id: str) -> tuple[Finding, ...]:
        """Re-check a stage waiting for review; an approval that no longer fits is voided."""
        stage = self.store.stage(stage_id)
        if stage.state is not S.PENDING_REVIEW:
            raise Denied("state", f"stage {stage_id} is {stage.state.value}")
        sheet = self._sheet(stage)
        findings = self._findings(sheet, stage.round_id)
        approval = self.store.valid_approval(stage_id)
        broken = any(finding.blocking for finding in findings)
        if approval is not None and (broken or self._approval_problem(approval, stage, sheet)):
            self.store.void_approvals(stage_id, self.clock.now())
        return findings

    # --- approval ------------------------------------------------------------------------------

    def approve(self, stage_id: str, actor: Actor, expected_digest: str | None = None) -> Approval:
        """Approve the stage's run sheet; when the caller names the digest it reviewed, only that
        sheet is approved."""
        now = self.clock.now()
        require_operator(actor, now, recent=True)
        stage = self.store.stage(stage_id)
        if stage.state is not S.PENDING_REVIEW:
            raise Denied("state", f"stage {stage_id} is {stage.state.value}; nothing to approve")
        sheet = self._sheet(stage)
        if expected_digest is not None and expected_digest != sheet.digest():
            raise Denied("state", "the run sheet changed since it was reviewed")
        if any(finding.blocking for finding in self._findings(sheet, stage.round_id)):
            raise Denied("approval_invalid", "the run sheet has blocking findings")
        approval = self._approval_for(sheet, actor, now)
        with self.db.transaction():
            self.store.void_approvals(stage_id, now)
            self.store.add_approval(approval)
            self.store.update_stage(stage, recovery_number=approval.recovery_number)
        return approval

    def _approval_for(self, sheet: RunSheet, actor: Actor, now: float) -> Approval:
        return Approval(
            id=new_id("approval"),
            run_sheet_id=sheet.id,
            run_sheet_version=sheet.version,
            run_sheet_digest=sheet.digest(),
            project_id=sheet.project_id,
            experiment_id=sheet.experiment_id,
            stage_id=sheet.stage_id,
            device_id=sheet.device_id,
            capability_version=self.control.capabilities().version,
            recovery_number=self.control.recovery_number(),
            operator=actor.id,
            approved_at=now,
        )

    def revoke_approval(self, stage_id: str, actor: Actor) -> None:
        """Revoking stops a stage that has not started. A running stage goes through stop_stage,
        which has to hand over its write rights first."""
        require_operator(actor, self.clock.now())
        stage = self.store.stage(stage_id)
        if stage.state is not S.PENDING_REVIEW:
            raise Denied("state", f"stage {stage_id} is {stage.state.value}; stop it instead")
        plan = Plan(
            S.STOPPED, "revoke_approval", round_effect="stopped", extra=self._voider(stage_id)
        )
        self._commit(stage, plan, None, {})

    def _voider(self, stage_id: str) -> Hook:
        return lambda _row: self.store.void_approvals(stage_id, self.clock.now())

    def _approval_problem(self, approval: Approval, stage: StageRow, sheet: RunSheet) -> str:
        """Why the approval no longer fits this stage; empty when it still does."""
        capability = self.control.capabilities().version
        checks = (
            (approval.run_sheet_digest != sheet.digest(), "run sheet content changed"),
            (approval.run_sheet_version != sheet.version, "run sheet version changed"),
            (approval.stage_id != stage.stage_id, "approved for another stage"),
            (approval.experiment_id != stage.experiment_id, "approved for another experiment"),
            (approval.device_id != sheet.device_id, "approved for another device"),
            (approval.capability_version != capability, "device capabilities changed"),
            (approval.recovery_number != self.control.recovery_number(), "recovery number changed"),
        )
        return next((message for broken, message in checks if broken), "")

    def _check_approval(self, stage: StageRow, sheet: RunSheet) -> None:
        approval = self.store.valid_approval(stage.stage_id)
        if approval is None:
            raise Denied("approval_invalid", "no valid approval for this stage")
        problem = self._approval_problem(approval, stage, sheet)
        if problem:
            with self.db.transaction():
                self.store.void_approvals(stage.stage_id, self.clock.now())
            raise Denied("approval_invalid", problem)

    # --- stage control -------------------------------------------------------------------------

    async def start_stage(self, stage_id: str, actor: Actor) -> StageRuntime:
        if actor.kind != "workflow":
            require_operator(actor, self.clock.now())
        stage = self.store.stage(stage_id)
        if stage.state is S.RUNNING:
            return self._runtime(stage)
        if stage.state is not S.PENDING_REVIEW:
            raise Denied("state", f"stage {stage_id} is {stage.state.value}; it cannot start")
        sheet = self._sheet(stage)
        self._check_approval(stage, sheet)
        self._check_startable(stage, sheet)
        holders = self.store.other_care_holders(stage.device_id, stage_id)
        plan = Plan(
            S.RUNNING,
            "start",
            updates={"started_at": self.clock.now(), "right_number": None},
            handover=held(stage.care_right, *(holder.care_right for holder in holders)),
            grants=(Grant(RightKind.STAGE, "right_number"), Grant(RightKind.CARE, "care_right")),
            reason="next stage starts",
            round_effect="started",
            extra=lambda _row: self._release_care(holders),
        )
        return self._runtime(await self._apply_once(stage, plan, S.RUNNING))

    def _check_startable(self, stage: StageRow, sheet: RunSheet) -> None:
        if conflicts := self.control.safety_conflicts(sheet):
            raise Denied("safety_conflict", "; ".join(conflicts))
        if self.control.interlocked():
            raise Denied("interlock", "the pump interlock is on; check the device on site")
        if self.store.device_busy(stage.device_id, stage.stage_id):
            raise Denied("state", "another stage on this device is still live or being checked")

    def _release_care(self, holders: tuple[StageRow, ...]) -> None:
        for holder in holders:
            self.store.update_stage(self.store.stage(holder.stage_id), care_right=None)

    async def pause_stage(self, stage_id: str, actor: Actor, reason: str) -> StageRuntime:
        require_kind(actor, ("operator", "observer"))
        stage = self.store.stage(stage_id)
        if stage.state is S.PAUSED:
            return self._runtime(stage)
        if stage.state is not S.RUNNING:
            raise Denied("state", f"stage {stage_id} is {stage.state.value}; it cannot pause")
        plan = Plan(
            S.PAUSED,
            "pause",
            updates={"right_number": None, "paused_at": self.clock.now()},
            handover=held(stage.right_number),
            reason=reason,
            detail={"by": actor.id},
        )
        return self._runtime(await self._apply(stage, plan))

    async def resume_stage(self, stage_id: str, actor: Actor) -> StageRuntime:
        require_operator(actor, self.clock.now())
        stage = self.store.stage(stage_id)
        if stage.state is S.RUNNING:
            return self._runtime(stage)
        if stage.state is not S.PAUSED:
            raise Denied("state", f"stage {stage_id} is {stage.state.value}; it cannot resume")
        sheet = self._sheet(stage)
        self._check_approval(stage, sheet)
        if self.control.interlocked():
            raise Denied("interlock", "the pump interlock is on; check the device on site")
        if await self.control.reconcile_unsettled():
            raise Denied("state", "actions with unknown results must be settled first")
        diffs = await self.control.differences(sheet.expected_levels(self.clock.now()))
        if diffs:
            raise Denied("state", f"device differs from the run sheet: {describe(diffs)}")
        plan = Plan(
            S.RUNNING,
            "resume",
            updates={"paused_at": None},
            grants=(Grant(RightKind.STAGE, "right_number"), *care_if_missing(stage)),
            detail={"by": actor.id},
        )
        return self._runtime(await self._apply(stage, plan))

    async def stop_stage(self, stage_id: str, actor: Actor) -> StageRuntime:
        require_operator(actor, self.clock.now())
        stage = self.store.stage(stage_id)
        if stage.state in STAGE_TERMINAL:
            raise Denied("state", f"stage {stage_id} is already {stage.state.value}")
        plan = Plan(
            S.STOPPED,
            "stop",
            updates={"right_number": None, "manual_right": None, "prior_state": None},
            handover=held(stage.right_number, stage.manual_right),
            reason="stopped by operator",
            detail={"by": actor.id},
            round_effect="stopped",
        )
        row = await self._apply(stage, plan)
        await self.restore_care()
        return self._runtime(self.store.stage(row.stage_id))

    async def takeover(self, stage_id: str, actor: Actor) -> StageRuntime:
        require_operator(actor, self.clock.now())
        stage = self.store.stage(stage_id)
        if stage.state is S.MANUAL:
            return self._runtime(stage)
        if stage.state not in (S.RUNNING, S.PAUSED):
            raise Denied("state", f"stage {stage_id} is {stage.state.value}; cannot take over")
        await self.control.reconcile_unsettled()  # settle what can be settled before manual writes
        plan = Plan(
            S.MANUAL,
            "takeover",
            updates={"right_number": None, "care_right": None, "manual_operator": actor.id},
            handover=held(stage.right_number, stage.care_right),
            grants=(Grant(RightKind.MANUAL, "manual_right", actor.id),),
            reason="operator takeover",
            detail={"by": actor.id},
            extra=self._intervention(stage, "takeover", actor, {}),
        )
        return self._runtime(await self._apply(stage, plan))

    async def handback(
        self, stage_id: str, actor: Actor, accept_as_intervention: bool
    ) -> tuple[StageRuntime, tuple[Difference, ...]]:
        """Return a manual stage to automation; the differences to the run sheet's target at
        this moment are listed, and recorded as an intervention when the operator accepts them."""
        require_operator(actor, self.clock.now())
        stage = self.store.stage(stage_id)
        if stage.state is not S.MANUAL or stage.manual_right is None:
            raise Denied("state", f"stage {stage_id} is {stage.state.value}; nothing to hand back")
        sheet = self._sheet(stage)
        # read first: if the device cannot be read the stage keeps its manual right
        diffs = await self.control.differences(sheet.expected_levels(self.clock.now()))
        self._require_unchanged(stage)  # stopped meanwhile: handing over would end irrigation
        await self.control.handover(stage.manual_right, "handback")
        detail = {"differences": [diff.model_dump(mode="json") for diff in diffs]}
        record = self._intervention(stage, "accepted", actor, detail)
        plan = Plan(
            S.RUNNING,
            "handback",
            updates={"manual_right": None, "manual_operator": None, "paused_at": None},
            grants=(Grant(RightKind.STAGE, "right_number"), Grant(RightKind.CARE, "care_right")),
            detail={**detail, "accepted": accept_as_intervention, "by": actor.id},
            extra=record if accept_as_intervention and diffs else None,
        )
        return self._runtime(await self._apply(stage, plan)), diffs

    def _intervention(
        self, stage: StageRow, kind: str, actor: Actor, detail: dict[str, Any]
    ) -> Hook:
        def record(_row: StageRow) -> None:
            args = (stage.experiment_id, stage.stage_id, self.clock.now(), kind, actor.id)
            self.store.add_intervention(*args, detail)
            names = ("experiment_id", "stage_id", "at", "kind", "operator")
            self._unsent.append({**dict(zip(names, args, strict=True)), "detail": detail})

        return record

    def record_intervention(self, stage_id: str, kind: str, detail: dict[str, Any]) -> None:
        """A system intervention (no operator), e.g. the pump watchdog's; handed on after commit."""
        with self.db.transaction():
            stage = self.store.stage(stage_id)
            args = (stage.experiment_id, stage_id, self.clock.now(), kind, None)
            self.store.add_intervention(*args, detail)
            names = ("experiment_id", "stage_id", "at", "kind", "operator")
            self._unsent.append({**dict(zip(names, args, strict=True)), "detail": detail})
        self._hand_on_interventions()

    def _hand_on_interventions(self) -> None:
        """After the commit: a failing receiver is logged and never undoes the transition."""
        sent, self._unsent = self._unsent, []
        if self.on_intervention is None:
            return
        for item in sent:
            try:
                self.on_intervention(item)
            except Exception:
                log.exception("intervention %s could not be handed on", item["kind"])

    async def switch_run_sheet(
        self, stage_id: str, run_sheet: RunSheet, actor: Actor
    ) -> StageRuntime:
        """Operator approval of a new version of a live stage's run sheet (App. B, 执行中)."""
        now = self.clock.now()
        require_operator(actor, now, recent=True)
        stage = self.store.stage(stage_id)
        if stage.state not in (S.RUNNING, S.PAUSED):
            raise Denied("state", f"stage {stage_id} is {stage.state.value}; cannot switch")
        self._check_switch(stage, run_sheet)
        approval = self._approval_for(run_sheet, actor, now)

        def record(_row: StageRow) -> None:
            self.store.put_run_sheet(run_sheet, stage.round_id, now)
            self.store.void_approvals(stage_id, now)
            self.store.add_approval(approval)

        stage_right = (Grant(RightKind.STAGE, "right_number"),) if stage.state is S.RUNNING else ()
        plan = Plan(
            stage.state,
            "switch_run_sheet",
            updates={
                "run_sheet_id": run_sheet.id,
                "run_sheet_version": run_sheet.version,
                "right_number": None,
                "care_right": None,
            },
            handover=held(stage.right_number, stage.care_right),
            grants=(*stage_right, Grant(RightKind.CARE, "care_right")),
            reason="run sheet switched",
            detail={"version": run_sheet.version, "digest": run_sheet.digest(), "by": actor.id},
            sheet=run_sheet,
            extra=record,
        )
        return self._runtime(await self._apply(stage, plan))

    def _check_switch(self, stage: StageRow, sheet: RunSheet) -> None:
        owner = (sheet.stage_id, sheet.experiment_id, sheet.project_id, sheet.device_id)
        if owner != (stage.stage_id, stage.experiment_id, stage.project_id, stage.device_id):
            raise Denied("state", "the new run sheet belongs to another stage or device")
        rnd = self.store.round(stage.round_id)
        if (sheet.protocol_id, sheet.protocol_version) != (rnd.protocol_id, rnd.protocol_version):
            raise Denied("state", "the new run sheet belongs to another protocol than the round")
        if sheet.version <= stage.run_sheet_version:
            raise Denied("state", "the new run sheet needs a higher version")
        if self.store.run_sheet_digest(sheet.id, sheet.version) is not None:
            raise Denied("state", f"run sheet {sheet.id} v{sheet.version} is already in use")
        if stage.recovery_number != self.control.recovery_number():
            raise Denied("approval_invalid", "recovery number changed; the stage needs review")
        if any(finding.blocking for finding in self._findings(sheet, stage.round_id)):
            raise Denied("approval_invalid", "the new run sheet has blocking findings")
        if conflicts := self.control.safety_conflicts(sheet):
            raise Denied("safety_conflict", "; ".join(conflicts))

    # --- events from the executor and the observer ---------------------------------------------

    def active_stage(self) -> StageRuntime | None:
        row = self.store.active()
        return None if row is None else self._runtime(row)

    async def report(self, event: StageEvent) -> None:
        stage = self.store.find_stage(event.stage_id)
        if stage is None or self.store.event_seen(event.event_id):
            return
        plan = self._plan_event(stage, event)
        if plan is None:
            self._drop(event, stage)
            return
        try:
            await self._apply(stage, plan, event)
        except DuplicateEvent:
            return
        except Denied as error:
            if error.code != "state":  # "state" means the stage moved on: the event is stale
                raise

    def _drop(self, event: StageEvent, stage: StageRow) -> None:
        args = (event.event_id, stage.stage_id, stage.round_id, event.kind.value, event.at)
        try:
            self.store.record_event(*args, "dropped")
        except DuplicateEvent:
            return

    def _plan_event(self, stage: StageRow, event: StageEvent) -> Plan | None:
        claimed = event.detail.get("right_number")
        if claimed is not None and claimed != stage.right_number:
            return None  # observed under a write right the stage no longer holds: stale
        kind, state = event.kind, stage.state
        if kind in PAUSE_KINDS:
            return pause_plan(stage, kind.value, self.clock.now()) if state is S.RUNNING else None
        if kind in UNCONFIRMED_KINDS:
            live = state in (S.RUNNING, S.PAUSED, S.MANUAL)
            return recovery_plan(stage, kind.value) if live else None
        if kind is K.END_CONDITION_MET:
            running = state is S.RUNNING and not stage.end_pending
            return Plan(S.RUNNING, kind.value, updates={"end_pending": True}) if running else None
        if kind is K.END_ACTIONS:
            return end_actions_plan(stage, event)
        if kind is K.MAX_WAIT_EXPIRED and state is S.PAUSED:
            return expiry_plan(S.STOPPED if self._sheet(stage).on_expiry == "stop" else S.PAUSED)
        return None

    # --- rounds --------------------------------------------------------------------------------

    async def choose_after_stop(self, round_id: str, choice: Choice, actor: Actor) -> RoundState:
        require_operator(actor, self.clock.now())
        rnd = self.store.round(round_id)
        if rnd.awaiting_choice is None or rnd.state in ROUND_TERMINAL:
            raise Denied("state", "no stopped stage is waiting for a choice")
        if choice == "abort":
            return await self.abort_round(round_id, actor)
        changes: dict[str, Any] = {"awaiting_choice": None, "state": RoundState.STAGE_REVIEW}
        if choice == "verify":
            changes["state"] = RoundState.DATA_VERIFICATION
        elif choice == "next":
            if rnd.stages_done + 1 >= self.store.stage_total(rnd):
                raise Denied("state", "no stage is left to move on to; verify the data instead")
            changes["stages_done"] = rnd.stages_done + 1
        elif choice != "redo":
            raise Denied("state", f"unknown choice {choice!r}")
        return self.store.update_round(round_id, **changes).state

    async def abort_round(self, round_id: str, actor: Actor) -> RoundState:
        require_operator(actor, self.clock.now())
        rnd = self.store.round(round_id)
        if rnd.state in ROUND_TERMINAL:
            raise Denied("state", f"round is already {rnd.state.value}")
        for stage in self.store.stages_of_round(round_id):
            for number in held(stage.right_number, stage.manual_right, stage.care_right):
                await self.control.handover(number, "round aborted")
        with self.db.transaction():
            fresh = self.store.round(round_id)
            if fresh.state in ROUND_TERMINAL:
                raise Denied("state", f"round is already {fresh.state.value}")
            for stage in self.store.stages_of_round(round_id):
                self.store.abort_stage(stage, self.clock.now())
            changes = {"state": RoundState.ABORTED, "awaiting_choice": None}
            return self.store.update_round(round_id, **changes).state

    def mark_snapshot_frozen(self, round_id: str, snapshot_id: str, event_id: str) -> RoundState:
        changes = {"snapshot_id": snapshot_id}
        args = (RoundState.DATA_VERIFICATION, RoundState.ANALYSIS)
        now = self.clock.now()
        return self.store.mark_round(round_id, event_id, "snapshot_frozen", args, changes, now)

    def mark_report_published(self, round_id: str, artifact_id: str, event_id: str) -> RoundState:
        changes = {"report_artifact_id": artifact_id}
        args = (RoundState.ANALYSIS, RoundState.DELIVERED)
        now = self.clock.now()
        return self.store.mark_round(round_id, event_id, "report_published", args, changes, now)

    # --- queries -------------------------------------------------------------------------------

    def stage(self, stage_id: str) -> StageRuntime:
        return self._runtime(self.store.stage(stage_id))

    def round_state(self, round_id: str) -> RoundState:
        return self.store.round(round_id).state

    def approvals(self, stage_id: str) -> tuple[Approval, ...]:
        return self.store.approvals(stage_id)

    def interventions(self, experiment_id: str) -> tuple[dict, ...]:
        return self.store.interventions(experiment_id)

    def history(self, stage_id: str) -> tuple[dict, ...]:
        return self.store.history(stage_id)

    def waiting_stages(self) -> tuple[dict, ...]:
        """Every stage that is paused or in recovery check, with the history entry that put it
        there: ``stage_id``, ``state``, and the entry's ``entry`` id, ``at``, ``event`` and
        ``detail``."""
        found = []
        for stage in self.store.stages_in((S.PAUSED, S.RECOVERY_CHECK)):
            entry = self.store.entered(stage.stage_id, stage.state)
            if entry is not None:
                found.append({"stage_id": stage.stage_id, "state": stage.state.value, **entry})
        return tuple(found)

    def _sheet(self, stage: StageRow) -> RunSheet:
        return self.store.run_sheet(stage.run_sheet_id, stage.run_sheet_version)

    def _runtime(self, stage: StageRow) -> StageRuntime:
        return StageRuntime(
            stage_id=stage.stage_id,
            experiment_id=stage.experiment_id,
            project_id=stage.project_id,
            state=stage.state,
            run_sheet=self._sheet(stage),
            prior_state=stage.prior_state,
            right_number=stage.right_number,
            care_right=stage.care_right,
            manual_right=stage.manual_right,
            started_at=stage.started_at,
            paused_at=stage.paused_at,
            end_pending=stage.end_pending,
            # a terminal state never changes, so its state_at is when the stage ended
            ended_at=stage.state_at if stage.state in STAGE_TERMINAL else None,
        )

    # --- applying a plan -----------------------------------------------------------------------

    async def _apply_once(self, stage: StageRow, plan: Plan, winner: StageState) -> StageRow:
        """Apply ``plan``; if a concurrent identical request got there first, return its result."""
        try:
            return await self._apply(stage, plan)
        except Denied as error:
            current = self.store.stage(stage.stage_id)
            if error.code == "state" and current.state is winner:
                return current
            raise

    async def _apply(
        self, stage: StageRow, plan: Plan, event: StageEvent | None = None
    ) -> StageRow:
        for number in plan.handover:
            self._require_unchanged(stage)  # a late hand-over would end the device's irrigation
            await self.control.handover(number, plan.reason or plan.event)
        numbers: dict[str, int] = {}
        try:
            updated = self._commit(stage, plan, event, numbers)
        except Exception:
            self._unsent.clear()
            for number in numbers.values():  # rights issued for a change that was not saved
                await self.control.handover(number, "state change rolled back")
            raise
        self._hand_on_interventions()
        return updated

    def _require_unchanged(self, stage: StageRow) -> StageRow:
        """The stage as stored, refused when it changed since ``stage`` was read."""
        fresh = self.store.stage(stage.stage_id)
        if fresh.rev != stage.rev:
            raise Denied("state", f"stage {stage.stage_id} changed while the request was running")
        return fresh

    def _commit(
        self, stage: StageRow, plan: Plan, event: StageEvent | None, numbers: dict[str, int]
    ) -> StageRow:
        """No awaits from here to the end: the revision check and the save are one step."""
        fresh = self._require_unchanged(stage)
        sheet = plan.sheet or self._sheet(fresh)
        for grant in plan.grants:
            self._grant(fresh, sheet, grant, numbers)
        now = self.clock.now()
        changes: dict[str, Any] = {**plan.updates, **numbers, "state": plan.state}
        if plan.state is not fresh.state:
            changes["state_at"] = now
        with self.db.transaction():
            if event is not None:
                args = (event.event_id, fresh.stage_id, fresh.round_id, event.kind.value, event.at)
                self.store.record_event(*args, "applied")
            updated = self.store.update_stage(fresh, **changes)
            # What the reporter saw (differences, reasons, request ids) is the only record of
            # why the stage changed. It never replaces what this service decided, except that
            # the reporter's own ``reason`` is more specific than the name of the event.
            seen = event.detail if event is not None else {}
            detail = {**seen, **plan.detail}
            reason = seen.get("reason") or plan.reason
            if reason:
                detail["reason"] = reason
            args = (fresh.stage_id, now, fresh.state.value, plan.state.value)
            self.store.add_history(*args, plan.event, detail)
            if plan.round_effect is not None:
                self.store.round_effect(updated, plan.round_effect)
            if plan.extra is not None:
                plan.extra(updated)
        return updated

    def _grant(
        self, stage: StageRow, sheet: RunSheet, grant: Grant, numbers: dict[str, int]
    ) -> None:
        scope = right_scope(stage, sheet, grant.kind)
        if scope is not None:
            numbers[grant.column] = self.control.grant(grant.kind, scope, grant.operator)
