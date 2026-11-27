# Device Test Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A lock holder can, on the workbench Greenhouses page, run a short on-site test of light, exhaust, fan or pump on an idle greenhouse; the server times it and writes the channel's whole AC5 configuration block back afterwards.

**Architecture:** A new `RightKind.TEST` write right and two control-layer calls (`snapshot`, `restore`) carry the device side. A new `workflow/device_test.py` (`DeviceTests`) owns the flow, its table, the unsettled-test rules and the restart retry; it pauses `IdleCare` and asks the executor which channels are protected. Workbench routes under `/wb/greenhouses/{id}/test…` and a section on the Greenhouses page expose it. Only built when `auto_research` and `multi_user` are both on.

**Tech Stack:** Python 3.12, FastAPI, SQLite (`archive.db.Database`), pytest + pytest-asyncio, vanilla ES modules with `node --test`.

**Spec:** `docs/superpowers/specs/2026-11-27-device-test-panel-design.md`

## Global Constraints

- Test values and durations (module constants in `workflow/device_test.py`): light 100 / 10 s, exhaust 100 / 10 s, fan 10 / 10 s, pump on for `min(3, settings.max_pump_seconds)` s.
- Channels: exactly `light`, `exhaust`, `fan`, `pump`; no other outlet.
- Exists only when `settings.auto_research and settings.multi_user`; with either off, nothing new is built and behaviour is unchanged.
- Idle = `store.last_started_on(device_id)` is `None` or has `care_released` (same as `IdleCare._due`, without the "levels configured" condition).
- Test record states: `running`, `done`, `restore_failed`, `settled_onsite`. Results returned to the page: `restored`, `restore_failed`, `protected`.
- Unsettled = a record in `running` or `restore_failed`. While one exists for a device: new tests, stage starts and the holder's own release on that device are refused with `device_test_unsettled`; an administrator's forced release settles it.
- Refusal reasons: reuse `greenhouse_not_held` (coarse `not_lock_holder`) for "caller does not hold the lock" (the spec's `device_test_not_holder`, folded into the existing reason); new, coarse `state`: `device_test_not_local` (`greenhouse_id`), `device_test_not_idle` (`greenhouse_id`), `device_test_running` (`greenhouse_id`, `channel`), `device_test_unsettled` (`greenhouse_id`, `test_id`), `device_test_protected` (`greenhouse_id`, `channel`). `controls_disabled`, `irrigation_too_soon` etc. pass through unchanged.
- Alert: kind and code `device_test_restore_failed`, severity `critical`, scope `("device", device_id)` (already visible to the holder via `Access.sees_device`), params `("greenhouse_id", "channel", "test_id")`; resolved when the record leaves the unsettled states.
- Lock-log events: `action = "test"` (note `"<channel>: <result>"`) and `action = "test_settled"` (note = the operator's note).
- History endpoint returns the latest 20 records of the greenhouse.
- Code limits for touched code: function ≤ 30 lines, nesting ≤ 3, ≤ 3 branches; new files ≤ 800 lines. `runtime.py` (791) and `workflow/service.py` (888) are already at/over the limit: add at most the few lines named in the tasks.
- Gate before every commit: `ruff check src tests scripts && ruff format --check src tests scripts`; the task's tests pass. Run from repo root with `.venv/bin/`.

## Review Focus

1. **The AC5 rewrites a block on its own between snapshot and restore** (e.g. its timer flips `mOnOff`): restore must still write the snapshot block and confirm by `modeType` (+ level only when the snapshot mode is 0), not by full-block equality. Test in Task 2: `test_restore_confirms_mode_not_every_field`.
2. **The HTTP client disconnects mid-test** (phone locks, page closed): the test still restores. Test in Task 6: `test_client_disconnect_still_restores` (cancel the request task, assert the record ends `done`).
3. **Two clicks in quick succession** (same or another channel): the second is refused with `device_test_running`, the first finishes normally. Test in Task 4: `test_second_test_while_one_runs_is_refused`.
4. **The device link drops right after the test value was written**: restore fails → `restore_failed`, alert raised, stage start refused until retry or settle. Test in Task 5: `test_restore_failure_blocks_stage_start_until_settled`.
5. **The holder releases the greenhouse while a test runs**: refused with `device_test_unsettled`; the test still restores. Test in Task 5: `test_release_refused_while_test_running`.

---

### Task 1: `RightKind.TEST` in the control layer

**Files:**
- Modify: `src/growbridge/archive/models.py` (`RightKind`), `src/growbridge/control/rights.py`, `src/growbridge/control/service.py` (`_may_irrigate`)
- Test: `tests/control/test_control_test_right.py`

**Interfaces:**
- Produces: `RightKind.TEST = "test"`; `rights.ORDINARY_KINDS == (STAGE, MANUAL, TEST)`; a TEST right needs a non-blank operator (reason `right_needs_operator`, same as MANUAL); `_may_irrigate` returns True for TEST.

- [ ] **Step 1: Write the failing tests** (use the `rig` fixture of `tests/control/conftest.py`; add a `test_right(channels, operator="alice")` helper to `Rig` next to `manual_right`)

```python
async def test_test_right_writes_its_channel(rig): ...      # submit light 100 → CONFIRMED, record.right_number is the TEST right
async def test_test_right_refuses_other_channels(rig): ...  # scope light only, submit fan → Denied (existing scope reason)
def test_test_right_needs_an_operator(rig): ...             # grant with operator=None → Denied reason "right_needs_operator"
async def test_test_right_may_irrigate(rig): ...            # irrigate 1 s under TEST right on pump → CONFIRMED, pump OFF confirmed
def test_test_right_refused_while_a_stage_right_is_held(rig): ...  # stage_right() then grant TEST → reason of refusals.right_held
async def test_protection_still_overrides_a_test_right(rig): ...   # mirror the MANUAL case in test_control_priority.py
```

- [ ] **Step 2: Run** `.venv/bin/pytest tests/control/test_control_test_right.py -q` — Expected: FAIL (`RightKind` has no `TEST`).
- [ ] **Step 3: Implement.** Add the enum value; extend `ORDINARY_KINDS`; make the operator check `kind in (RightKind.MANUAL, RightKind.TEST)`; `_may_irrigate` accepts TEST. Grep `RightKind.MANUAL` in `src/growbridge/control/` and `src/growbridge/archive/` and treat TEST the same wherever the meaning is "operator-bound ordinary right"; leave `workflow/` alone.
- [ ] **Step 4: Run** the new file plus `tests/control -q` — Expected: all PASS.
- [ ] **Step 5: Commit** `feat: TEST write right kind for on-site device tests`

### Task 2: Channel snapshot and whole-block restore

**Files:**
- Modify: `src/growbridge/ports.py` (new `ChannelSnapshot`; `ControlPort.snapshot/restore`), `src/growbridge/control/device.py`, `src/growbridge/control/service.py`, `src/growbridge/sim/control.py`
- Test: `tests/control/test_control_snapshot.py`, `tests/control/test_fake_control_port.py`

**Interfaces:**
- Produces:
  - `class ChannelSnapshot(Model): channel: Channel; block: dict[str, Any]; level: int | None; mode: int | None; digest: str` — `block` is the deep copy of `config["device"][module]` (or `config["outlet"][f"O{pump_outlet}"]`), `level` the instant read-back level, `digest = content_digest({"channel": …, "block": …})`.
  - `async def ControlService.snapshot(self, channel: Channel) -> ChannelSnapshot` — read only, no right; raises `BridgeError`/`ConnectionError` when the device cannot be read.
  - `async def ControlService.restore(self, request: ActionRequest, snapshot: ChannelSnapshot) -> ActionRecord` — `request.level` must equal `snapshot.level or 0`; refuses (new refusal in `control/refusals.py`, reason `restore_invalid`, coarse `param`, registered in `denial_codes.py`) when the right is not TEST, when `content_digest` of the snapshot does not match `digest`, or when `request.channel != snapshot.channel`. Otherwise the same `_authorize` → intent → `_save` → gate → `_send` path as `submit`, but the write is `device.write_block(...)`.
  - `async def AC5Device.write_block(self, channel: Channel, block: dict, level: int | None) -> Outcome` — `setConfigField` with `{"keyPath": [...], key: block}`, then `confirm_block`.
  - `async def AC5Device.confirm_block(self, channel, block, level) -> Outcome` — CONFIRMED when the read-back `modeType` equals `block["modeType"]` and, if that mode is 0, the instant level equals `level`; same FAILED/UNKNOWN codes as `confirm` (`readback_mode`, `readback_level`, `readback_unavailable`).
  - `sim/control.py`: `FakeControl.snapshot/restore` raise `NotImplementedError` like `submit`; new `class WritingFakeControl(FakeControl)` whose `submit`, `irrigate`, `snapshot`, `restore` record into `self.levels`, `self.blocks: dict[Channel, dict]`, append to `self.log`, and honour `self.fail_restore: bool` (restore returns a FAILED record) and `self.unreadable: bool` (snapshot raises `ConnectionError`).
- [ ] **Step 1: Write the failing tests** (real `ControlService` on `SimulatedTransport` via `rig`)

```python
async def test_snapshot_copies_the_module_block(rig): ...         # rig.sim.config["device"]["light"]["modeType"] = 2 → snapshot.block["modeType"] == 2, snapshot.mode == 2
async def test_restore_writes_back_a_non_manual_block(rig): ...   # snapshot (mode 2) → submit light 100 under TEST → restore → sim config light modeType == 2, record CONFIRMED
async def test_restore_writes_back_the_pump_outlet_block(rig): ... # outlet block with modeType 1 restored after irrigate
async def test_restore_refuses_a_tampered_snapshot(rig): ...      # block edited after snapshot → Denied reason "restore_invalid", no setConfigField sent
async def test_restore_refuses_a_non_test_right(rig): ...         # MANUAL right → Denied "restore_invalid"
async def test_restore_confirms_mode_not_every_field(rig): ...    # sim changes an unrelated field of the block after the write → still CONFIRMED
def test_fake_control_port_has_snapshot_and_restore(): ...        # extend the existing protocol-conformance test
```

- [ ] **Step 2: Run** `.venv/bin/pytest tests/control/test_control_snapshot.py -q` — Expected: FAIL (`snapshot` missing).
- [ ] **Step 3: Implement** the interfaces above. `SimulatedTransport` already stores `config`; if its `setConfigField` handler drops unknown keys or forces mode 0, extend it so a written block is stored as sent.
- [ ] **Step 4: Run** `.venv/bin/pytest tests/control -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: snapshot and whole-block restore of an AC5 channel`

### Task 3: Idle care pause and the executor's protected channels

**Files:**
- Modify: `src/growbridge/workflow/idle.py`, `src/growbridge/executor/engine.py`
- Test: `tests/workflow/test_workflow_idle.py`, `tests/executor/test_executor_protection.py`

**Interfaces:**
- Produces:
  - `IdleCare.paused(self) -> AsyncContextManager[None]` (`contextlib.asynccontextmanager`): on entry increments `_starts` (so `_due()` is False) and, if the held idle right is valid, `await self.control.handover(self._right, "device test")`; on exit decrements. `restore()` re-grants on the next tick as today.
  - `ExecutorEngine.protected_channels(self) -> frozenset[Channel]` — public alias of `_protected()`.
- [ ] **Step 1: Write the failing tests**

```python
async def test_paused_hands_back_the_idle_right_and_grants_none(world): ...  # restore(); async with paused(): right revoked, runtime() is None, restore() grants nothing
async def test_restore_grants_a_fresh_right_after_the_pause(world): ...      # after exit: restore() → new number != old
def test_protected_channels_lists_active_protection(...): ...                # reuse the active-rule setup of test_executor_protection.py
```

- [ ] **Step 2: Run** both files — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `.venv/bin/pytest tests/workflow/test_workflow_idle.py tests/executor -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: idle care can pause; executor exposes protected channels`

### Task 4: `DeviceTests` — the test flow

**Files:**
- Create: `src/growbridge/workflow/device_test.py`, `src/growbridge/workflow/device_test_denials.py` (refusal functions, one per reason, reason literal at the `Denied(...)` call as `workflow/denials.py` does)
- Modify: `src/growbridge/denial_codes.py` (register the five new reasons), `src/growbridge/workflow/locks.py` (public `note_event(greenhouse_id, action, actor, note)` wrapping `_record` in a transaction)
- Test: `tests/workflow/test_device_test.py`

**Interfaces:**
- Consumes: Task 1 `RightKind.TEST`; Task 2 `snapshot`, `restore`, `WritingFakeControl`; Task 3 `IdleCare.paused`, `protected_channels`.
- Produces:
  - Table (namespace `device_tests`, migration `STEPS` like `workflow/locks.py`): `device_tests(test_id TEXT PRIMARY KEY, greenhouse_id, device_id, channel, operator, state, result TEXT, snapshot TEXT /*JSON*/, right_number INTEGER, started_at REAL, ended_at REAL, note TEXT NOT NULL DEFAULT '')`.
  - `class TestRecord(Model)` mirroring the row (snapshot as `ChannelSnapshot | None`).
  - `class DeviceTests.__init__(self, db, clock, control: ControlPort, locks: GreenhouseLocks, access: Access, store: WorkflowStore, idle: IdleCare | None, *, sleep=asyncio.sleep)` plus late-bound attributes `protected: Callable[[], frozenset[Channel]] = lambda: frozenset()` and `alert: Callable[..., None]` / `resolve: Callable[[str, str, Scope], object]` (no-ops by default).
  - `async def run(self, greenhouse_id: str, channel: Channel, actor: Actor) -> dict` → `{"test_id", "channel", "test_level", "seconds", "result", "actions"}`.
  - `def unsettled(self, device_id: str) -> TestRecord | None`, `def running(self, device_id: str) -> TestRecord | None`, `def history(self, greenhouse_id: str, limit: int = 20) -> list[TestRecord]`, `def testable(self, row: dict, actor: Actor) -> bool`.
- Flow of `run` (spec 5.4): checks in this order with no `await` between the last check and the `running` insert — holder (`greenhouse_not_held`), local device (`device_test_not_local`), idle (`device_test_not_idle`), running/unsettled (`device_test_running` / `device_test_unsettled`), protected (`device_test_protected`); then insert `running`; `snapshot` (on any error: delete the row, write nothing, re-raise — the route maps it like other link failures); `async with idle.paused()`; grant TEST (scope = this channel only, operator = actor.id); store snapshot + right number; write (`submit` level per Global Constraints, or `irrigate(pump seconds)`); `await sleep(seconds)` (not for pump); if `channel in protected()` → result `protected`, else `restore(...)` → `restored` / `restore_failed`; `finally`: handover TEST right, set state (`done` for restored/protected, `restore_failed` otherwise), `ended_at`, lock event `test`, alert on `restore_failed`. Request ids: `f"test-{test_id}-on"`, `f"test-{test_id}-restore"`; trigger `f"device_test:{test_id}"`.
- [ ] **Step 1: Write the failing tests** (`world` fixture from `tests/workflow/conftest.py` but with `WritingFakeControl`; real `GreenhouseLocks` + `Access` built as in `tests/workflow/access_support.py`; `sleep` = a recorder that returns immediately)

```python
async def test_light_test_writes_100_waits_10_and_restores(rig): ...   # control.log: grant TEST, submit light 100, restore; slept == [10]; result "restored"; state "done"
async def test_pump_test_irrigates_min_3_and_limit(rig): ...           # max_pump_seconds=2 → irrigate seconds == 2; no sleep; restore called with pump snapshot
async def test_refused_when_not_holder(rig): ...                       # reason "greenhouse_not_held"
async def test_refused_when_greenhouse_not_local(rig): ...             # "device_test_not_local"
async def test_refused_when_a_stage_has_started(rig): ...              # world.running() on that device → "device_test_not_idle"
async def test_second_test_while_one_runs_is_refused(rig): ...         # sleep blocks on an Event; second run → "device_test_running"; release event; first ends "done"
async def test_refused_on_a_protected_channel(rig): ...                # protected = lambda: {LIGHT} → "device_test_protected", nothing written
async def test_protection_during_the_wait_skips_restore(rig): ...      # protected flips inside sleep → result "protected", no restore in log
async def test_idle_right_is_handed_back_and_regranted(rig): ...       # with idle levels: handover reason "device test"; after run, idle.restore() grants anew
async def test_restore_failure_raises_an_alert(rig): ...               # fail_restore → result "restore_failed", alert kind "device_test_restore_failed", scope ("device", DEVICE)
async def test_unreadable_device_writes_nothing(rig): ...              # unreadable → error surfaces, no row left, no grant
async def test_lock_log_records_the_test(rig): ...                     # locks.events()[0] action "test", note "light: restored"
```

- [ ] **Step 2: Run** `.venv/bin/pytest tests/workflow/test_device_test.py -q` — Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `device_test.py` and the denials; register reasons; keep each method ≤ 30 lines (split `run` into `_check`, `_begin`, `_exercise`, `_finish`).
- [ ] **Step 4: Run** `.venv/bin/pytest tests/workflow tests/workbench/test_denial_codes.py -q` — Expected: PASS. The denial-code tests require console text for every registered reason: add `msg.denial.<reason>` and `.action` for the five new reasons (and `restore_invalid` from Task 2) to `denials.en.js` / `denials.zh.js` in this task.
- [ ] **Step 5: Commit** `feat: device tests run, time and restore a channel on an idle greenhouse`

### Task 5: Unsettled tests — retry, settle, restart, release and stage start

**Files:**
- Modify: `src/growbridge/workflow/device_test.py`, `src/growbridge/workflow/locks.py` (`release`), `src/growbridge/workflow/service.py` (`start_stage`: ≤ 3 added lines)
- Test: `tests/workflow/test_device_test_unsettled.py`

**Interfaces:**
- Consumes: Task 4.
- Produces:
  - `async def retry(self, greenhouse_id: str, test_id: str, actor: Actor) -> dict` — holder only; record must be `restore_failed`; pause idle, grant TEST, `restore(stored snapshot)`, handover, state `done` + resolve alert, or stays `restore_failed`.
  - `def settle(self, greenhouse_id: str, test_id: str, actor: Actor, note: str) -> TestRecord` — holder only; a blank note raises `ValueError` here and is refused earlier at the route by the body model (Task 6); state `settled_onsite`, lock event `test_settled`, resolve alert.
  - `async def resume(self) -> None` — called every runtime tick; for each `running` row not owned by an in-process run: when `control.connected()` and `control.transport_stopped()` and not `control.interlocked()`, do one restore attempt as `retry` does (operator = the row's operator) → `done` or `restore_failed` + alert.
  - `def settle_for_release(self, device_id: str, actor: str, note: str) -> None` — sets unsettled rows of the device to `settled_onsite`.
  - `GreenhouseLocks.tests: DeviceTests | None = None` (late-bound). In `release`: non-forced and `tests.unsettled(device)` or `tests.running(device)` → `device_test_unsettled`; forced → `tests.settle_for_release(...)` before `_finish_release`.
  - `WorkflowService.device_tests: DeviceTests | None = None`; `start_stage` refuses with `device_test_unsettled` when `device_tests` reports a running or unsettled test on the stage's device.
- [ ] **Step 1: Write the failing tests**

```python
async def test_restore_failure_blocks_stage_start_until_settled(world): ...  # fail_restore → start_stage Denied "device_test_unsettled"; settle(note="checked") → start_stage proceeds
async def test_retry_restores_and_resolves_the_alert(world): ...             # fail_restore then fail_restore=False → retry → "done", resolve called
async def test_settle_needs_a_note(world): ...
async def test_settle_only_by_holder(world): ...                              # bob → "greenhouse_not_held"
async def test_release_refused_while_test_running(world): ...                # during the blocked sleep: locks.release(...) → "device_test_unsettled"; test ends "done"
async def test_forced_release_settles_unsettled_tests(world): ...            # admin force → row "settled_onsite", lock released
async def test_resume_restores_a_test_left_running(world): ...               # insert a running row with a snapshot (simulated restart: new DeviceTests on the same db) → resume() → "done"
async def test_resume_waits_for_the_link(world): ...                          # connected False → resume() leaves "running", no write
```

- [ ] **Step 2: Run** the new file — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `.venv/bin/pytest tests/workflow -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: unsettled device tests block the device until retried or settled on site`

### Task 6: Wiring and workbench routes

**Files:**
- Modify: `src/growbridge/runtime_access.py` (`AccessParts.tests`; build `DeviceTests`; set `locks.tests`, `workflow.device_tests`; new `wire_device_tests(parts, executor, runtime)`), `src/growbridge/runtime.py` (one call to `wire_device_tests` after the runtime exists; one `await` of `tests.resume()` in `tick` when `access_parts` is set — net ≤ 6 lines), `src/growbridge/workbench/greenhouses.py`, `src/growbridge/workbench/api.py` (pass `tests` through), `src/growbridge/codes.py` (alert code `device_test_restore_failed` with its params), `tests/web/fixtures/message-codes.json` (regenerate)
- Modify: `tests/workbench/workbench_support.py` (Bench with `multi_user=True` builds `DeviceTests` on a `WritingFakeControl`-backed control with `sleep` recorder)
- Test: `tests/workbench/test_workbench_device_tests.py`

**Interfaces:**
- Consumes: Tasks 3–5.
- Produces (routes on the `/wb` router, all `Operator`):
  - `POST /wb/greenhouses/{greenhouse_id}/test/{channel}` → body of `DeviceTests.run`; channel validated as `Channel` (422 otherwise). The handler runs `run` inside `asyncio.shield`.
  - `POST /wb/greenhouses/{greenhouse_id}/tests/{test_id}/retry` → body of `retry`.
  - `POST /wb/greenhouses/{greenhouse_id}/tests/{test_id}/settle` with body model `SettleIn(note: str)` — stripped, 1–500 chars, else 422 → `{"settled": test_id}`.
  - `GET /wb/greenhouses/{greenhouse_id}/tests` → `{"tests": [{test_id, channel, operator, state, result, started_at, ended_at}]}`; holder or admin, else `greenhouse_not_held`.
  - `GET /wb/greenhouses` rows gain `testable`, `test_running` (channel or null), `test_unsettled` (`{test_id, channel, state}` or null) — for rows the caller holds; null/false otherwise.
- [ ] **Step 1: Write the failing tests** (`Bench(tmp_path, multi_user=True)` as in `test_workbench_greenhouses.py`)

```python
def test_holder_runs_a_light_test_over_http(bench): ...       # lock gh-01 → POST test/light → 200, result "restored"; GET tests lists it
def test_rows_show_testable_only_for_own_idle_local(bench): ... # alice holds gh-01 (local) and gh-02 (not local): testable True/False; bob sees False
def test_unknown_channel_is_422(bench): ...
def test_other_user_cannot_read_history(bench): ...          # bob → 403 code "not_lock_holder"
def test_settle_over_http_clears_test_unsettled(bench): ...   # fail_restore → row test_unsettled set → settle → null
async def test_client_disconnect_still_restores(bench): ...   # call the route coroutine, cancel it during sleep, release sleep → record "done"
def test_single_user_workbench_has_no_test_routes(tmp_path): ... # Bench(multi_user=False) → POST test/light 404
```

- [ ] **Step 2: Run** the new file — Expected: FAIL.
- [ ] **Step 3: Implement**; then `PYTHONPATH=src .venv/bin/python scripts/export_message_codes.py` to refresh the fixture.
- [ ] **Step 4: Run** `.venv/bin/pytest -q` (whole suite) — Expected: PASS; `wc -l src/growbridge/runtime.py` ≤ 800.
- [ ] **Step 5: Commit** `feat: workbench routes for device tests`

### Task 7: Greenhouses page — the test section

**Files:**
- Create: `src/growbridge/web/workbench/pages/greenhouse-tests.js` (section builder, keeps `greenhouses.js` small)
- Modify: `src/growbridge/web/workbench/pages/greenhouses.js` (append the section under each row the caller holds), `src/growbridge/web/workbench/i18n/en.js`, `zh.js`, `codes.en.js`, `codes.zh.js`, `messages.en.js`, `messages.zh.js`, `denials.en.js`, `denials.zh.js` (if not done in Task 4), `src/growbridge/web/workbench/pages.css`
- Test: `tests/web/greenhouses-page.test.mjs`

**Interfaces:**
- Consumes: Task 6 routes and row fields.
- Produces: `export function testSection(ctx, row, history) -> HTMLElement`.
- Behaviour (spec 5.8): four buttons with labels from i18n (`greenhouses.test.light` "Test light (10 s)" / "测试灯光 10 秒", … pump "Test pump (3 s)" / "测试水泵 3 秒" — pump seconds come from the server reply / settings, not hard-coded in the label key's default); pump uses `confirmedButton` with the line "Water will flow. Have something to catch it." / "会出水，请准备接水。"; while a request is in flight all four are disabled and a local countdown shows; the result line shows `greenhouses.test.result.restored|restore_failed|protected`; `test_unsettled` replaces the buttons with the warning and two buttons (retry; settle with a required note field); a row with a current stage (not `testable`, no unsettled) shows `greenhouses.test.busy` "A round is running here; tests are unavailable." / "实验进行中，测试不可用。"; history list "Recent tests" / "最近测试" (time, operator, channel, result).
- [ ] **Step 1: Write the failing tests** in `greenhouses-page.test.mjs` with the file's existing fake `ctx`/api:

```js
test("own testable row shows four test buttons", ...);              // 4 buttons, pump label contains "3"
test("a running test disables every button until the reply", ...);  // click light → all disabled; resolve → enabled, result text "restored" key
test("unsettled test shows retry and settle instead", ...);
test("settle needs a note", ...);                                   // empty note → no POST
test("rows not held show no test section", ...);
```

- [ ] **Step 2: Run** `node --test tests/web/greenhouses-page.test.mjs` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `for f in src/growbridge/web/app.js $(find src/growbridge/web/workbench -name '*.js'); do node --check "$f" || exit 1; done && node --test tests/web/*.test.mjs` — Expected: PASS (includes the i18n key-parity and leaks tests).
- [ ] **Step 5: Commit** `feat: device test section on the workbench Greenhouses page`

### Task 8: Docs and the full gate

**Files:**
- Modify: `docs/wiki/en/` and `docs/wiki/zh-CN/` (the page that covers greenhouse locks — find it with `grep -ril "lock" docs/wiki/*/ | head`): add a section "Test the devices before a round" / "实验前测试设备": who can, when, what each button does, pump water warning, what "not restored" means and the two ways out.
- Test: whole suite.

- [ ] **Step 1: Write the two wiki sections** (plain language; no commit/branch words).
- [ ] **Step 2: Run the full gate** from repo root: `.venv/bin/ruff check src tests scripts && .venv/bin/ruff format --check src tests scripts && .venv/bin/pytest -q && node --test tests/web/*.test.mjs` — Expected: all PASS. Redirect long output to a file and read the summary lines.
- [ ] **Step 3: Manual run on the simulator**: `.venv/bin/python scripts/dev_workbench.py` with multi-user on (check its flags with `--help`), lock gh-01, run each of the four tests, confirm the page result lines and the history; set the simulated light block to a non-manual mode first and confirm it is back after the test.
- [ ] **Step 4: Commit** `docs: wiki section on testing devices before a round`
