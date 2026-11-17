"""Recovery check of the workflow service (architecture doc App. B).

After a restart or a recovery number change every live stage enters ``recovery_check``. A stage
leaves it once the old write path is confirmed stopped, the pump interlock is off, no action has
an unknown result and the device matches the run sheet, or once an operator checked on site.

``StageRecovery`` is a mixin of ``WorkflowService``: it uses the service's ``store``, ``control``
and ``clock`` and its ``_apply``, ``_voider``, ``_sheet``, ``_grant`` and ``_runtime`` helpers.
"""

from typing import Any

from growbridge.archive.clock import Clock
from growbridge.archive.models import RightKind, RunSheet
from growbridge.ports import Actor, ControlPort, Denied, StageRuntime
from growbridge.workflow.permissions import require_operator
from growbridge.workflow.states import STAGE_TERMINAL, StageState
from growbridge.workflow.store import Grant, Plan, StageRow, WorkflowStore, care_if_missing

S = StageState


class StageRecovery:
    store: WorkflowStore
    control: ControlPort
    clock: Clock

    async def on_restart(self) -> None:
        """Process start: every live stage needs checking and every old write right is void."""
        await self._enter_recovery("restart", void_approvals=False)

    async def on_recovery_bump(self) -> None:
        """Restore or host change: the approvals that were given for the old number are void."""
        await self._enter_recovery("recovery_bump", void_approvals=True)

    async def _enter_recovery(self, event: str, void_approvals: bool) -> None:
        waiting = (S.PENDING_REVIEW, S.RUNNING, S.PAUSED, S.MANUAL, S.RECOVERY_CHECK)
        for stage in self.store.stages_in(waiting):
            prior = stage.prior_state if stage.state is S.RECOVERY_CHECK else stage.state
            updates = {"prior_state": prior, "right_number": None, "manual_right": None}
            updates |= {"care_right": None, "onsite_checked": False}
            void = self._voider(stage.stage_id) if void_approvals else None
            await self._apply(stage, Plan(S.RECOVERY_CHECK, event, updates, extra=void))
        for stage in self.store.stages_in((S.ENDED, S.STOPPED)):
            if stage.care_right is not None:
                self.store.update_stage(stage, care_right=None)
        await self.restore_care()

    async def restore_care(self) -> None:
        """Re-issue the care right of the last finished stage once old writes are confirmed gone."""
        stage = self.store.active()
        if stage is None or stage.care_right is not None:
            return
        finished = stage.state in STAGE_TERMINAL
        recovering = stage.state is S.RECOVERY_CHECK and stage.prior_state is not S.MANUAL
        if not (finished or recovering) or stage.recovery_number != self.control.recovery_number():
            return
        if not self.control.transport_stopped() or self.control.interlocked():
            return
        numbers: dict[str, int] = {}
        self._grant(stage, self._sheet(stage), Grant(RightKind.CARE, "care_right"), numbers)
        if numbers:
            self.store.update_stage(stage, **numbers)

    def recovering_stages(self) -> tuple[str, ...]:
        """Ids of every stage in recovery check, started or not."""
        return tuple(stage.stage_id for stage in self.store.stages_in((S.RECOVERY_CHECK,)))

    async def try_exit_recovery(self, stage_id: str) -> StageRuntime:
        stage = self.store.stage(stage_id)
        if stage.state is not S.RECOVERY_CHECK:
            return self._runtime(stage)
        await self.restore_care()
        stage = self.store.stage(stage_id)
        if not await self._may_exit(stage, self._sheet(stage)):
            return self._runtime(stage)
        plan = self._exit_plan(stage)
        if plan is None:
            return self._runtime(stage)
        return self._runtime(await self._apply(stage, plan))

    async def _may_exit(self, stage: StageRow, sheet: RunSheet) -> bool:
        if stage.onsite_checked:
            return True
        control = self.control
        if not control.transport_stopped() or control.interlocked():
            return False
        if await control.reconcile_unsettled():
            return False
        if stage.prior_state in (S.RUNNING, S.PAUSED):
            return not await control.differences(sheet.expected_levels(self.clock.now()))
        return True

    def _exit_plan(self, stage: StageRow) -> Plan | None:
        updates: dict[str, Any] = {"prior_state": None, "onsite_checked": False}
        if stage.recovery_number != self.control.recovery_number():
            safety = self.control.safety()
            if safety is None or safety.approved_by is None:
                return None  # the safety config has to be confirmed again first
            return Plan(
                S.PENDING_REVIEW,
                "recovery_exit",
                updates,
                round_effect="to_review",
                extra=self._voider(stage.stage_id),
            )
        if stage.prior_state is S.MANUAL:
            grant = Grant(RightKind.MANUAL, "manual_right", stage.manual_operator or "unknown")
            return Plan(S.MANUAL, "recovery_exit", updates, grants=(grant,))
        if stage.prior_state is S.PENDING_REVIEW:
            return Plan(S.PENDING_REVIEW, "recovery_exit", updates)
        updates["paused_at"] = self.clock.now()
        return Plan(S.PAUSED, "recovery_exit", updates, grants=care_if_missing(stage))

    async def record_onsite_check(self, stage_id: str, actor: Actor, note: str) -> StageRuntime:
        require_operator(actor, self.clock.now())
        stage = self.store.stage(stage_id)
        if stage.state not in (S.RECOVERY_CHECK, S.PAUSED, S.MANUAL):
            raise Denied(
                "state",
                f"stage {stage_id} is {stage.state.value}; no check is open",
                reason="no_check_open",
                params={"stage_id": stage_id, "state": stage.state.value},
            )
        await self.control.onsite_check(actor.id, note)
        recovering = stage.state is S.RECOVERY_CHECK
        plan = Plan(
            stage.state,
            "onsite_check",
            updates={"onsite_checked": True} if recovering else {},
            detail={"note": note, "by": actor.id},
        )
        row = await self._apply(stage, plan)
        return await self.try_exit_recovery(stage_id) if recovering else self._runtime(row)
