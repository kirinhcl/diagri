# Protection Priority and Safe Handback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** No executor write path writes a channel an active protection rule holds; a contradicting release or a late safety configuration cannot start a stage; `handback` checks what `resume_stage` checks.

**Architecture:** The executor gets one map of protected channels to the protection rule holding them and consults it in the feedback and end-action paths, as `_align` already does for timed and care writes. Planning's contradiction check also covers a rule's `release` and becomes a public function the workflow calls again in `start_stage`. `handback` runs `resume_stage`'s three checks before its hand-over.

**Tech Stack:** Python 3.12+, pytest with pytest-asyncio, the existing `rig` executor fixture and workflow fakes; the console's message files are plain ES modules tested with `node --test`.

**Spec:** `docs/superpowers/specs/2026-11-24-safety-control-path-design.md`

## Global Constraints

- Protection rules take priority over the experiment's timing and regular feedback (architecture doc §7.4); same-level conflicts are resolved before approval.
- An end action on a protected channel is skipped and the stage ends on time (user decision, 2026-11-24).
- Rules on other sensors and end actions that write a protection channel are NOT blocked at planning time (spec, Non-goals).
- Finding and denial codes: reuse `safety_conflict`; the release clash is the variant `release` (code key `safety_conflict.release`, same params as `safety_conflict`).
- Every new finding variant has console text in English and Chinese, and `tests/web/fixtures/message-codes.json` is regenerated with `scripts/export_message_codes.py`.
- Do not edit `docs/wiki/` (the docs branch updates the Internals pages after merge). Commit messages are public: say what changed and why, not how to trigger the old fault.
- Functions under 50 lines, no mutation of shared state outside the patterns the engine already uses (`self._feedback = {**self._feedback, ...}`).

## Review Focus

1. A feedback rule's `release` (not only its `action`) on a protected channel: it must be held back too. Pinned in Task 1.
2. Every end action's channel protected at once: the stage still ends, confirmed, with all channels listed as held. Pinned in Task 1.
3. Protection releasing while a feedback rule's decision was held back: the rule writes on the next tick without needing its trigger to re-fire. Pinned in Task 1.
4. A refused `handback` must leave the stage `manual` with its manual right, and `stop_stage` must still work from there. Pinned in Task 4.
5. A protection on a different sensor writing the same channel as a feedback rule: no blocking finding at planning or start. Pinned in Task 2.

---

### Task 1: Protection holds the channel against feedback rules and end actions

**Files:**
- Modify: `src/growbridge/executor/engine.py` (`_protected`, `_apply_decision`, `_finish`)
- Modify: `src/growbridge/workflow/store.py` (`end_actions_plan` keeps `held` in the plan's detail)
- Test: `tests/executor/test_executor_protection.py`, `tests/workflow/test_workflow_stage.py` (or the file that already tests `end_actions_plan`; grep it)

**Interfaces:**
- Produces: `ExecutorEngine._protecting(self) -> dict[Channel, str]` (channel → id of the active protection rule holding it); `_protected()` becomes `frozenset(self._protecting())`. `END_ACTIONS` event detail: `{"confirmed": bool}` plus `"held": [channel values]` only when at least one end action was skipped.

- [ ] **Step 1: Write the failing tests** in `tests/executor/test_executor_protection.py`, reusing `overheat(rig)` and `humidity_rule` from `growbridge.sim.fixtures` as `.local` probe `probe_feedback_vs_protection.py` does (feedback rule `warm-light` on `temp`, trigger `> 30`, recover `< 20`, duration 40 s, action light 80, release light 60, `min_switch_seconds=0`):
  - `test_executor_protection_holds_the_light_against_a_feedback_rule`: after `overheat(rig)` and six further `pass_time(10)` + `tick()` rounds, `levels()[LIGHT] == 0` after every tick and no write in `rig.written()` after the protection's first write sets the light to 80; the last report's `denied` contains `"held by protection"`.
  - `test_executor_feedback_rule_acts_once_protection_releases`: overheat with the rule active, then `set_sensor("temp", 32)` (above the rule's trigger, below protection's 35) and tick past the protection's recovery; the light reaches 80 on the next tick.
  - `test_executor_feedback_release_is_held_while_protection_holds`: the rule's release (light 60) is not written while protection holds the light.
  - `test_executor_end_action_on_a_protected_channel_is_skipped`: a run sheet with an end action light 100 and a short duration; overheat so protection holds the light when the end condition is met; the stage reaches `ended` (not `recovery_check`), the light stays 0, and the `END_ACTIONS` event detail has `"held": ["light"]` and `"confirmed": True`.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/executor/test_executor_protection.py -q`. Expected: the four new tests FAIL (the light goes to 80; the end action is written).
- [ ] **Step 3: Implement** `_protecting()`; in `_apply_decision`, before any write, when `decision.action.channel` is in `_protecting()`: append `f"rule:{rule_id}: {channel} held by protection {holder}"` to `tick.denied` and return `False` (the old rule state is kept, so the rule retries each tick). In `_finish`, split the hosted non-pump end actions into protected and unprotected; write only the unprotected ones; report `END_ACTIONS` with `held` when non-empty. Update the `_protected` docstring so it states that schedules, care, feedback rules and end actions all leave these channels alone.
- [ ] **Step 4: Make `end_actions_plan` keep `held`** in its `detail` (`{"confirmed": True, "held": [...]}` when the event carries it); add a store-level test that the stage history row's detail lists it.
- [ ] **Step 5: Run** `.venv/bin/python -m pytest tests/executor tests/workflow -q`. Expected: all pass.
- [ ] **Step 6: Commit** `fix: protection keeps its channel against feedback rules and end actions`.

### Task 2: The contradiction check covers the release, and is public

**Files:**
- Modify: `src/growbridge/planning/validate.py` (`_check_safety_conflicts` → public `safety_contradictions`)
- Modify: `src/growbridge/codes.py` (add `"safety_conflict.release"`)
- Modify: `src/growbridge/web/workbench/i18n/messages.en.js`, `messages.zh.js` (texts for the variant)
- Regenerate: `tests/web/fixtures/message-codes.json`
- Test: `tests/planning/test_planning_validate.py`

**Interfaces:**
- Produces: `safety_contradictions(sheet: RunSheet, safety: SafetyConfig | None) -> tuple[Finding, ...]` in `growbridge.planning.validate`; blocking findings with code `safety_conflict`, variant `""` for the action and `"release"` for the release, params `rule, protection, channel, level, protection_level`.

- [ ] **Step 1: Write the failing tests:**
  - `test_validate_blocks_a_release_that_contradicts_a_protection`: feedback rule on `temp`, trigger `> 25`, recover `< 38`, release light 60; protection on `temp`, trigger `> 35`, light 0. `validate_run_sheet(...)` has a blocking finding with code `safety_conflict`, variant `release`, params `{"rule": ..., "protection": ..., "channel": "light", "level": 60, "protection_level": 0}`.
  - `test_validate_allows_a_release_that_cannot_meet_the_protection`: same with recover `< 20`: no `safety_conflict` finding.
  - `test_validate_allows_a_rule_on_another_sensor_on_the_protected_channel`: feedback rule on `ppfd` writing the light, protection on `temp` writing the light: no `safety_conflict` finding (spec Non-goals).
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/planning/test_planning_validate.py -q`. Expected: the first test FAILS, the other two pass (they pin existing behaviour).
- [ ] **Step 3: Implement** `safety_contradictions`: for each feedback rule and protection on the same sensor, check the pair `(rule.trigger, rule.action)` with variant `""` and, when `rule.release` is set, `(rule.recover, rule.release)` with variant `"release"`; a clash is same channel, different level and `_can_overlap(condition, protection.trigger)`. `validate_run_sheet` uses it in place of `_check_safety_conflicts`. Add `"safety_conflict.release": Code(("rule", "protection", "channel", "level", "protection_level"))` to `CODES["finding"]`. Add `msg.finding.safety_conflict.release` and `.release.action` in both message files (English: "Rule {rule} releases {channel} to {level} while protection {protection} can still hold it at {protection_level}." / "Change the release level or the recovery condition so the two cannot meet."; Chinese in the same style as the neighbouring `safety_conflict` text). Run `.venv/bin/python scripts/export_message_codes.py` to regenerate the fixture.
- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/planning tests/workbench/test_message_codes.py -q` and `node --test tests/web`. Expected: all pass.
- [ ] **Step 5: Commit** `fix: a feedback rule's release may not contradict a protection rule`.

### Task 3: `start_stage` checks the contradiction against the safety configuration in force

**Files:**
- Modify: `src/growbridge/workflow/service.py` (`_check_startable`)
- Test: `tests/workflow/test_workflow_stage.py`

**Interfaces:**
- Consumes: `safety_contradictions` from Task 2; `ControlPort.safety()`; `denials.safety_conflict(stage_id, conflicts: Sequence[str])`.

- [ ] **Step 1: Write the failing test** `test_start_refuses_a_sheet_that_contradicts_a_later_safety_configuration`: approve a stage whose sheet has a feedback rule on `temp` → light 80 (trigger `> 30`), then give the fake control a safety configuration with a protection on `temp` `> 35` → light 0, then `start_stage` raises `Denied` with code `safety_conflict` and the stage stays `pending_review`.
- [ ] **Step 2: Run** it. Expected: FAIL (the stage starts).
- [ ] **Step 3: Implement**: in `_check_startable`, after `control.safety_conflicts(sheet)`, `if found := safety_contradictions(sheet, self.control.safety()): raise denials.safety_conflict(stage.stage_id, [f.message for f in found])`.
- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/workflow -q`. Expected: all pass.
- [ ] **Step 5: Commit** `fix: a stage does not start against a safety configuration that contradicts its rules`.

### Task 4: `handback` makes `resume_stage`'s checks

**Files:**
- Modify: `src/growbridge/workflow/service.py` (`handback`)
- Test: `tests/workflow/test_workflow_stage.py`

**Interfaces:**
- Consumes: `_check_approval`, `ControlPort.interlocked()`, `ControlPort.reconcile_unsettled()`, `denials.pump_unconfirmed`, `denials.unsettled_actions`.

- [ ] **Step 1: Write the failing tests:**
  - `test_handback_refuses_a_stage_whose_approval_is_no_longer_valid`: start, pause, change the fake control's capability version (as the existing approval tests do), take over, then `handback` raises `Denied` with code `approval_invalid` (reason as `resume_stage` gives), and the stage is still `manual` with its `manual_right`; then `stop_stage` succeeds.
  - `test_handback_refuses_while_the_pump_interlock_is_set`: code `pump_unconfirmed`, stage stays `manual`.
  - `test_handback_refuses_with_unsettled_actions`: code `unsettled_actions`, stage stays `manual`.
- [ ] **Step 2: Run** them. Expected: FAIL (the stage returns to `running`).
- [ ] **Step 3: Implement**: in `handback`, after the `stage_not_in_manual` check and `sheet = self._sheet(stage)`, run `self._check_approval(stage, sheet)`, the interlock check and the unsettled check, in `resume_stage`'s order, before reading the differences. Update the docstring to say so.
- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/workflow tests/workbench -q`. Expected: all pass (fix any existing test that relied on handing back a stage with a void approval only if it asserted the old behaviour on purpose; otherwise give it a valid approval).
- [ ] **Step 5: Commit** `fix: handback checks the approval, the interlock and unsettled actions`.

### Task 5: Whole-branch check

- [ ] **Step 1:** `.venv/bin/python -m pytest -q` (the croissant test needs the dev extra `mlcroissant`; install `.[dev]` if missing), `.venv/bin/ruff check src tests`, `.venv/bin/ruff format --check src tests`, `node --test tests/web`. Expected: all pass.
- [ ] **Step 2:** Turn the `.local/audit` probes for A1–A3 into a final check that they now show the fixed behaviour (run them; do not commit them).
- [ ] **Step 3:** List which Internals wiki statements change (for the docs branch): executor feedback/end actions, the planning contradiction check, `start_stage`, `handback`.
