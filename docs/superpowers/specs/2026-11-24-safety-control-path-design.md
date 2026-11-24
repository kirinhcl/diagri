# Design: protection priority on every write path, and a safe handback

Date: 2026-11-24. Size: a small change (three related fixes, one PR).

## Intent

The architecture document says that protection rules take priority over the experiment's timing and its regular feedback, and that conflicts at the same level are resolved before approval (§7.4), and that the safety configuration is checked when a stage starts (§7.5). A code review on 2026-11-19 found three places where the code does not hold to this:

1. The executor keeps the timed schedule and care rules off a channel that an active protection rule holds, but feedback rules and end actions still write it. Protection puts the channel back on the next tick, so the device sees the experiment's level for up to a second, and the feedback rule may write again on its next decision.
2. The planning check that blocks a feedback rule contradicting a protection rule looks only at the rule's `action`, not at its `release` action, and runs only when a run sheet is validated. A safety configuration approved after the run sheet is never compared with it.
3. `handback` returns a manual stage to `running` without the checks `resume_stage` makes (a valid approval, a clear pump interlock, no unsettled actions). Taking over a paused stage and handing it back skips them.

## Goals

- No write path of the executor writes a channel that an active protection rule holds.
- A run sheet whose feedback rule, through its action or its release, contradicts a protection rule on the same reading cannot start, whichever was approved first.
- A stage reaches `running` only through checks at least as strict as `resume_stage`'s.

## Non-goals

- Blocking feedback rules on other sensors, or end actions, that write a protection channel. These are conflicts across levels, which the design document resolves by priority at run time; with goal 1 they cannot reach the device while protection holds.
- The protection re-send rate when a protection write's own read-back fails (audit finding A4), the bridge health flag (A6) and the transport halt on start-up (A7): separate changes.
- Fixes B (tick and event loop) and F (isolation): their own PRs.

## Approaches considered

- **Executor: one check in the write path** (chosen). The engine already computes the protected channels (`_protected()`) and passes them to `_align` for the timed schedule and care. Feedback decisions and end actions skip a protected channel in the same way. Considered and rejected: refusing protected channels in the control service, which does not know which protection rule is active (the executor owns rule state), and would turn a planned hold-back into a refusal recorded as a failure.
- **End action on a protected channel: skip it and end on time** (the user chose this on 2026-11-24). The stage ends at its planned time; the end event records which channels protection held. After the stage ends, care rules move the channel once protection releases (care already respects protection). Rejected: waiting for protection to release (the stage could overrun without bound if a sensor sticks high, and the experiment keeps running past its duration), and treating the end as unconfirmed (it would send the stage to `recovery_check` although nothing is unknown).
- **Planning: extend the existing contradiction check** to the `release` action, using the rule's `recover` condition, and run the same check in `start_stage`. Rejected: blocking every rule that writes a protection channel (it would refuse sound designs, e.g. a light rule driven by PPFD next to a temperature protection on the light).
- **Handback: the same checks as `resume_stage`, in the same order**, before the hand-over, so that a refusal leaves the stage in `manual` with its manual right. The operator can still stop the stage. The differences from the run sheet stay listed and are accepted as an intervention as today.

## Decided behaviour

1. `ExecutorEngine`: a feedback decision whose action channel is protected is not written; the rule's state is not advanced, so it acts once protection releases. The hold-back is reported in `TickReport.denied` with the protection rule's id.
2. `ExecutorEngine._finish`: an end action on a protected channel is not written and counts as done; the `END_ACTIONS` event carries `held` (the channels skipped) and the workflow keeps it in the event's detail.
3. `planning/validate.py` `_check_safety_conflicts`: also blocks when a rule's `release` exists, its channel is the protection's channel, its level differs and `rule.recover` can overlap the protection's trigger, on the same sensor. Finding code `safety_conflict` with a variant for the release.
4. `WorkflowService.start_stage`: runs the contradiction check against the safety configuration in force and refuses with the existing `safety_conflict` denial when it finds one.
5. `WorkflowService.handback`: before the hand-over it checks the approval (`_check_approval`), the interlock (`pump_unconfirmed`) and unsettled actions (`unsettled_actions`), in that order, like `resume_stage`; a refusal changes nothing.

## Left to the builder

The exact names of new parameters and helper functions; whether the release clash is a variant of the existing finding or a new parameter; how `start_stage` gets the contradiction check (a function in `planning/validate.py` reused by the workflow's `validate` callable or called directly).

## Tests

Each fix starts from a failing test built from the 2026-11-19 probes: a feedback rule and a protection rule on the light under overheating (the light must stay at the protection level on every tick), an end condition met while protection holds (the stage ends on time with the channel recorded as held), a release that contradicts a protection, a safety configuration approved after the run sheet, and a paused stage with a void approval that is taken over and handed back (refused, stays `manual`).
