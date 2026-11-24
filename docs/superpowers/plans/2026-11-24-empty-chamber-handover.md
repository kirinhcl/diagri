# Empty-Chamber Hand-over Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A greenhouse is released only once its holder confirms the plants are gone; after a release it has no current stage, and while it has none the device is held at configured idle levels.

**Architecture:** `GreenhouseLocks.release` refuses a holder's release without `plants_removed`. `WorkflowStore.active()` treats a stage whose care a release ended as no current stage, so ingest, daily reports, observers and the executor all see `None`. A new `workflow/idle.py` keeps one care-kind write right for the configured idle levels while there is no current stage; the executor aligns the device to those levels on ticks without a stage, and a stage start hands the right back together with the care rights.

**Tech Stack:** Python 3.12, pydantic, FastAPI, SQLite, pytest (asyncio), plain ES modules + `node --test` for the console.

**Spec:** `docs/superpowers/specs/2026-11-24-empty-chamber-handover-design.md`

## Global Constraints

- Idle levels: only `light` (0–100), `exhaust` (0–100), `fan` (0–10); `pump` in an idle mapping is a configuration error. Omitted = idle off.
- Example used in docs and tests: `idle = { light = 0, exhaust = 10, fan = 0 }`.
- The executor never writes the pump on; idle never writes the pump at all.
- Idle writes skip channels a protection rule holds (`ExecutorEngine._protected()`).
- No idle write may land after a stage starts (the start hands the idle right back).
- With no idle levels configured, nothing writes the device after a release.
- An administrator's forced release needs no plant confirmation.
- New refusal reason: `plants_not_removed`, coarse code `state`, params `("greenhouse_id",)`.
- `workflow/store.py` and `workflow/service.py` are over 800 lines: add only the few delegating lines named below; new logic goes in `workflow/idle.py`. Functions ≤ 30 lines.
- Python tests: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`. `tests/e2e` and `tests/observer` are run in separate pytest invocations (their conftests clash). Lint: `.venv/bin/ruff check -q src tests && .venv/bin/ruff format --check -q src tests`.

## Review Focus

1. A release while the BLE link is down: idle levels must land once the link is back, without any operator action → Task 5 `test_idle_waits_for_the_link`.
2. A process restart with no current stage: the old idle right is void after `revoke_all`; a new one must be granted and the device re-aligned → Task 4 `test_restore_after_restart_grants_a_new_right`, Task 5 `test_idle_realigns_under_a_new_right`.
3. A stage start racing queued idle writes: nothing idle may land after the start → Task 4 `test_start_hands_the_idle_right_back`.
4. A refused start after the idle right was handed back: the greenhouse must not stay un-idled → Task 4 `test_a_revoked_right_is_replaced`.
5. Between two stages of one round on a held greenhouse (no release): no idle, care keeps running → Task 2 `test_ended_stage_without_release_is_still_current`.

---

### Task 1: Idle levels in the configuration

**Files:**
- Modify: `src/growbridge/config.py` (`Greenhouse`, `Settings`, `greenhouse_registry`)
- Test: `tests/test_config_greenhouses.py`

**Interfaces:**
- Produces: `Greenhouse.idle: dict[Channel, int] | None = None`; `Settings.idle: dict[Channel, int] | None = None`; `Settings.local_idle() -> tuple[RuleAction, ...]` — the local device's idle levels as `RuleAction`s in `Channel` order (`light`, `exhaust`, `fan`), `()` when none.

- [ ] **Step 1: Write the failing tests**

```python
def test_idle_levels_on_a_greenhouse(base):
    house = Greenhouse(id="gh-01", name="One", device_id=base.device,
                       idle={"light": 0, "exhaust": 10, "fan": 0})
    settings = base.model_copy(update={"greenhouses": [house]})
    assert settings.local_idle() == (
        RuleAction(channel=Channel.LIGHT, level=0),
        RuleAction(channel=Channel.EXHAUST, level=10),
        RuleAction(channel=Channel.FAN, level=0),
    )

def test_idle_refuses_the_pump_and_out_of_range_levels():
    for idle in ({"pump": 0}, {"fan": 11}, {"light": -1}):
        with pytest.raises(ValidationError):
            Greenhouse(id="gh-01", name="One", device_id="AC5", idle=idle)

def test_top_level_idle_is_for_the_implicit_greenhouse_only(base):
    assert base.model_copy(update={"idle": {"light": 0}}).local_idle() == (
        RuleAction(channel=Channel.LIGHT, level=0),)
    house = Greenhouse(id="gh-01", name="One", device_id=base.device)
    with pytest.raises(ValidationError):
        Settings.model_validate({**base.model_dump(), "idle": {"light": 0}, "greenhouses": [house.model_dump()]})

def test_no_idle_by_default(base):
    assert base.local_idle() == ()
```

(`base` = the module's existing valid `Settings`; reuse its fixture or construction.)

- [ ] **Step 2: Run** `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_config_greenhouses.py` — Expected: FAIL (`idle` is an unexpected field).

- [ ] **Step 3: Implement.** A shared field validator: keys must be `Channel` other than `PUMP`, values pass `archive.models.check_level`. `Settings._registry_fits` also rejects a top-level `idle` together with a non-empty `greenhouses`. `greenhouse_registry()` passes `idle=self.idle` to the implicit greenhouse. `local_idle()` reads the registry entry whose `device_id == self.device`.

- [ ] **Step 4: Run** the same command — Expected: PASS.

- [ ] **Step 5: Commit** `feat: greenhouses can name idle levels for the device`

---

### Task 2: No current stage after a release

**Files:**
- Modify: `src/growbridge/workflow/store.py:470-478` (`WorkflowStore.active`)
- Modify: `src/growbridge/ports.py:240-243` (`StagePort.active_stage` docstring)
- Test: `tests/workflow/test_workflow_locks.py`

**Interfaces:**
- Produces: `WorkflowStore.active()` returns `None` when the latest started stage of an undelivered round has `care_released`; `WorkflowService.active_stage()` follows.

- [ ] **Step 1: Write the failing tests** (in `test_workflow_locks.py`, reusing `_ended_with_care`)

```python
async def test_a_released_greenhouse_has_no_current_stage(world, locks):
    await _ended_with_care(world)
    locks.lock("alice", ["gh-01"])
    await locks.release("gh-01", "alice", plants_removed=True)
    assert world.svc.active_stage() is None

async def test_ended_stage_without_release_is_still_current(world, locks):
    stage = await _ended_with_care(world)
    assert world.svc.active_stage().stage_id == stage
```

(`plants_removed=True` comes from Task 3; until then call without it, and add it in Task 3.)

- [ ] **Step 2: Run** `.venv/bin/python -m pytest -q -p no:cacheprovider tests/workflow/test_workflow_locks.py` — Expected: the first test FAILS (the old stage is returned).

- [ ] **Step 3: Implement.** In `active()`, after fetching the row: `None` when `care_released`. Do not fall back to an older stage. Then read each caller and confirm it wants `None` after a release (record the outcome in the commit message body): `runtime.py` `_ingest` / daily report / line ~520, `runtime_agents.py:116`, `agents/handlers_orchestrator.py:131`, `workbench/environment.py:82`, `workflow/recovery.py:53` (`restore_care` already skips released stages), `observer/stage_checks.py:47`, `observer/frozen_watch.py:175,189`, `observer/service.py:63`, `executor/engine.py:163,353`.

- [ ] **Step 4: Run** `.venv/bin/python -m pytest -q -p no:cacheprovider tests/workflow tests/workbench`, then `... tests/e2e`, then `... tests/observer tests/executor` — Expected: PASS.

- [ ] **Step 5: Commit** `fix: a released greenhouse has no current stage, so later readings and reports belong to no experiment`

---

### Task 3: A holder's release needs the plants gone

**Files:**
- Modify: `src/growbridge/workflow/locks.py` (`release`, module docstring)
- Modify: `src/growbridge/workbench/greenhouses.py` (`ReleaseIn`, route)
- Modify: `src/growbridge/denial_codes.py` (register `plants_not_removed` under `state`)
- Modify: `src/growbridge/web/workbench/i18n/denials.en.js`, `denials.zh.js`
- Regenerate: `tests/web/fixtures/message-codes.json` via `.venv/bin/python scripts/export_message_codes.py` (read the script for its output argument)
- Modify every existing holder release call in tests (`tests/workflow/test_workflow_locks.py`, `tests/workbench/test_workbench_greenhouses.py`, `tests/workbench/test_workbench_multi_user_inbox.py`, `tests/e2e/test_e2e_multi_user.py`) to pass the confirmation
- Test: `tests/workflow/test_workflow_locks.py`, `tests/workbench/test_workbench_greenhouses.py`

**Interfaces:**
- Produces: `GreenhouseLocks.release(greenhouse_id: str, actor: str, *, force: bool = False, note: str = "", plants_removed: bool = False) -> None`; `POST /wb/greenhouses/{id}/release` body `{"plants_removed": bool}` (default `false`).

- [ ] **Step 1: Write the failing tests**

```python
async def test_release_needs_the_plants_gone(world, locks):
    stage = await _ended_with_care(world)
    locks.lock("alice", ["gh-01"])
    with pytest.raises(Denied) as denied:
        await locks.release("gh-01", "alice")
    assert denied.value.reason == "plants_not_removed"
    assert denied.value.params == {"greenhouse_id": "gh-01"}
    assert locks.holder_of_device(DEVICE) == "alice"
    assert world.svc.store.stage(stage).care_right is not None  # nothing handed over
    assert world.control.handovers == []

async def test_confirmed_release_is_logged(locks):
    locks.lock("alice", ["gh-02"])
    await locks.release("gh-02", "alice", plants_removed=True)
    assert locks.events()[0]["note"] == "plants removed"

async def test_forced_release_needs_no_confirmation(locks):
    locks.lock("alice", ["gh-02"])
    await locks.release("gh-02", "root", force=True, note="left for the summer")
    assert locks.holder_of_device("AC5-2") is None
```

Route test in `test_workbench_greenhouses.py`: posting `{}` answers 409 with reason `plants_not_removed` and the lock stays; posting `{"plants_removed": true}` answers 200 `{"released": "gh-01"}`.

- [ ] **Step 2: Run** `.venv/bin/python -m pytest -q -p no:cacheprovider tests/workflow/test_workflow_locks.py tests/workbench/test_workbench_greenhouses.py` — Expected: FAIL.

- [ ] **Step 3: Implement.** The check runs after `_check_release` (a non-holder still gets `greenhouse_not_held`) and before any hand-over: `not force and not plants_removed` → `Denied("state", "confirm the plants have been removed before releasing", reason="plants_not_removed", params={"greenhouse_id": ...})`. A confirmed holder release records note `"plants removed"`. i18n copy:
  - en: `"msg.denial.plants_not_removed": "Confirm that your plants have been taken out before releasing this greenhouse."`, `.action`: `"Take your plants out, then tick the confirmation and release again."`
  - zh: `"msg.denial.plants_not_removed": "释放前要先确认植物已经搬走。"`, `.action`: `"把植物搬走后，勾选确认再释放。"`

- [ ] **Step 4: Run** the Python command above, then `node --test tests/web/` and `.venv/bin/python -m pytest -q -p no:cacheprovider tests/workbench/test_message_codes.py` — Expected: PASS.

- [ ] **Step 5: Commit** `feat: releasing a greenhouse needs the holder to confirm the plants are gone`

---

### Task 4: The idle write right

**Files:**
- Create: `src/growbridge/workflow/idle.py`
- Modify: `src/growbridge/ports.py` (add `IdleRuntime`)
- Modify: `src/growbridge/workflow/service.py` (attribute, `idle_runtime`, start hand-over: ~5 lines)
- Modify: `src/growbridge/workflow/recovery.py` (`restore_care` also restores idle: 2 lines)
- Test: `tests/workflow/test_workflow_idle.py`

**Interfaces:**
- Consumes: `Settings.local_idle()` (Task 1); `WorkflowStore.active()` (Task 2).
- Produces:
  - `ports.IdleRuntime(Model)`: `right: int`, `levels: tuple[RuleAction, ...]`.
  - `workflow.idle.IdleCare(store: WorkflowStore, control: ControlPort, device_id: str, levels: tuple[RuleAction, ...])` with `right: int | None` (property, the held number), `restore() -> None`, `runtime() -> IdleRuntime | None`.
  - `WorkflowService.idle_care: IdleCare | None = None` (set at assembly, like `access`); `WorkflowService.idle_runtime() -> IdleRuntime | None` (`None` when `idle_care` is `None`).

- [ ] **Step 1: Write the failing tests** (use the `world` fixture of `tests/workflow`; `IDLE = (RuleAction(channel=Channel.LIGHT, level=0), RuleAction(channel=Channel.EXHAUST, level=10))`)

```python
def test_restore_grants_a_care_right_for_the_idle_levels(world):
    idle = attach(world, IDLE)          # helper: IdleCare(..., DEVICE, IDLE) set on world.svc
    idle.restore()
    right = world.control.right(idle.right)
    assert right.kind is RightKind.CARE and right.levels == IDLE and right.stage_id is None
    assert world.svc.idle_runtime() == IdleRuntime(right=idle.right, levels=IDLE)

def test_no_right_without_levels_or_with_a_current_stage(world): ...
    # levels () -> right stays None; a running stage -> restore() grants nothing, runtime() is None

def test_restore_waits_for_the_old_path_and_the_interlock(world): ...
    # transport not confirmed stopped, or interlocked -> no right (same gate as restore_care)

async def test_restore_after_restart_grants_a_new_right(world):
    idle = attach(world, IDLE); idle.restore(); old = idle.right
    await world.control.startup()       # a restart revokes every right (use the fixture's restart helper if it has one)
    idle.restore()
    assert idle.right != old

def test_a_revoked_right_is_replaced(world):
    # revoke via control.handover(idle.right, "x"); runtime() is None; restore() grants a new one

async def test_start_hands_the_idle_right_back(world):
    idle = attach(world, IDLE); idle.restore(); number = idle.right
    await world.running("stage-1")
    assert (number, "next stage starts") in world.control.handovers
    assert world.svc.idle_runtime() is None
```

(Use the `FakeControl` hand-over record format the existing lock tests use; adjust the reason string to what `Plan.reason` passes.)

- [ ] **Step 2: Run** `.venv/bin/python -m pytest -q -p no:cacheprovider tests/workflow/test_workflow_idle.py` — Expected: FAIL (module missing).

- [ ] **Step 3: Implement.**
  - `restore()`: nothing when `levels == ()`, `store.active()` is not `None`, `not control.transport_stopped()` or `control.interlocked()`, or the held right is still valid. Valid = `control.right(n)` exists, `revoked_at is None`, `recovery_number == control.recovery_number()`. Otherwise `control.grant(RightKind.CARE, RightScope(device_id=device_id, levels=levels))`.
  - `runtime()`: `IdleRuntime` when levels are set, there is no current stage and the held right is valid; else `None`.
  - `start_stage`: add `self.idle_care.right if self.idle_care else None` to the `held(...)` of its `handover`.
  - `StageRecovery.restore_care`: at its end (and on its early returns), call `self.idle_care.restore()` when set — put the call in a wrapper so the early returns stay simple.

- [ ] **Step 4: Run** `.venv/bin/python -m pytest -q -p no:cacheprovider tests/workflow` — Expected: PASS.

- [ ] **Step 5: Commit** `feat: the workflow keeps an idle write right while a greenhouse has no current stage`

---

### Task 5: The executor holds the idle levels

**Files:**
- Modify: `src/growbridge/executor/engine.py` (`__init__`, `_tick`, `_enter_phase`, new `_idle`)
- Modify: `tests/executor/executor_helpers.py` (`build_rig(..., idle_levels=())` wires `IdleCare` and passes `idle=workflow.idle_runtime`)
- Test: `tests/executor/test_executor_idle.py`

**Interfaces:**
- Consumes: `IdleRuntime`, `WorkflowService.idle_runtime` (Task 4).
- Produces: `ExecutorEngine(control, stages, clock, allow=None, idle: Callable[[], IdleRuntime | None] | None = None)`.

- [ ] **Step 1: Write the failing tests** (`IDLE = {light: 20, exhaust: 10, fan: 0}` so the light differs from protection's 0)

```python
async def test_idle_levels_reach_the_device_when_no_stage_exists(make_rig):
    rig = await make_rig(idle_levels=IDLE)
    await rig.restore_idle()            # rig helper: svc.restore_care()
    await rig.tick()
    levels = await rig.levels()
    assert (levels[Channel.LIGHT], levels[Channel.EXHAUST], levels[Channel.FAN]) == (20, 10, 0)
    assert all(r.trigger.startswith("idle:") and r.experiment_id is None for r in rig.records())

async def test_idle_never_touches_the_pump(make_rig): ...          # no pump write in rig.written()
async def test_idle_skips_a_channel_protection_holds(make_rig): ... # overheat -> light stays 0
async def test_idle_waits_for_the_link(make_rig): ...              # sim disconnected: no write; reconnect: levels land
async def test_idle_realigns_under_a_new_right(make_rig): ...      # restart: new right, writes again
async def test_no_idle_while_a_stage_is_current(make_rig): ...     # rig.start(): only stage writes
async def test_nothing_without_idle_levels(make_rig): ...          # idle_levels=(): no writes at all
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest -q -p no:cacheprovider tests/executor/test_executor_idle.py` — Expected: FAIL.

- [ ] **Step 3: Implement.**
  - `_tick`: where it now returns on `stage is None`, first `await self._idle(tick)` when `online`.
  - `_enter_phase`: with no stage the key is `("idle", <idle right or None>)`, so a new idle right resets `_applied` and `_failed`.
  - `_idle(tick)`: `runtime = self._idle_source() if set`; for each level not in `self._protected()`, not the pump, not already `_applied`: `await self._write(tick, None, runtime.right, "care", action, f"idle:{action.channel.value}", str(runtime.right))`.

- [ ] **Step 4: Run** `.venv/bin/python -m pytest -q -p no:cacheprovider tests/executor` — Expected: PASS.

- [ ] **Step 5: Commit** `feat: the executor holds a greenhouse without a current stage at its idle levels`

---

### Task 6: Wiring, end to end, documentation

**Files:**
- Modify: `src/growbridge/runtime.py` (near line 637–649: set `flow.idle_care`, pass `idle=flow.idle_runtime`; keep the file ≤ 800 lines)
- Test: `tests/e2e/test_e2e_multi_user.py`
- Modify: `docs/multi-user-adaptation.md` (item 6 done and how; the post-release samples limitation resolved; release confirmation; both languages)
- Modify: `docs/wiki/en/Configuration-Reference.md`, `docs/wiki/zh-CN/Configuration-Reference.md` (`idle` on `[[greenhouses]]` and top level, the example)
- Modify: `docs/wiki/en/API-Reference.md`, `docs/wiki/zh-CN/API-Reference.md` (release body)
- Modify: `docs/wiki/en/Status-and-Known-Limitations.md`, `docs/wiki/zh-CN/Status-and-Known-Limitations.md` (remove the post-release samples limitation if listed; add: readings received in the seconds before a release but stored after it belong to no experiment)

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the failing e2e test**

```python
async def test_a_released_chamber_goes_idle_and_keeps_no_one_s_readings(world, site):
    # settings: gh-01 has idle {"light": 0, "exhaust": 10, "fan": 0}
    # alice runs and stops a stage on gh-01; releasing without the confirmation answers 409
    # plants_not_removed; with it, 200. After a few runtime ticks: the device shows the idle
    # levels; samples ingested after the release carry no experiment_id; no daily report is
    # saved for alice's project after the release. Bob locks gh-01, runs a stage: its samples
    # carry bob's experiment and alice's experiment holds none of them.
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest -q -p no:cacheprovider tests/e2e/test_e2e_multi_user.py` — Expected: FAIL (no idle levels on the device).

- [ ] **Step 3: Wire** `IdleCare(flow.store, control, settings.device, settings.local_idle())` and the executor's `idle=`; write the docs.

- [ ] **Step 4: Run** the whole suite — `.venv/bin/python -m pytest -q -p no:cacheprovider --ignore=tests/e2e --ignore=tests/observer`, then `... tests/e2e`, then `... tests/observer`, then `node --test tests/web/`, then the lint line — Expected: all PASS.

- [ ] **Step 5: Commit** `feat: a released chamber goes to its idle levels; docs for idle and release confirmation`

---

### Task 7: The console asks for the confirmation

**Files:**
- Modify: `src/growbridge/web/workbench/ui/dialog.js` (new `confirmWithTick`)
- Modify: `src/growbridge/web/workbench/pages/greenhouses.js` (`releaseButton`)
- Modify: `src/growbridge/web/workbench/i18n/en.js`, `zh.js`
- Test: `tests/web/greenhouses-page.test.mjs`, `tests/web/dialogs.test.mjs`

**Interfaces:**
- Produces: `confirmWithTick(t, { title, lines = [], tickLabel, confirmLabel }) -> Promise<boolean>` — like `confirmAction`, plus one required checkbox; the confirm button is disabled until it is ticked; resolves `true` only when confirmed with the box ticked.

- [ ] **Step 1: Write the failing tests** — dialogs: the confirm button starts disabled, ticking enables it, confirming resolves `true`, cancelling resolves `false`. Greenhouses page: releasing (dialog confirmed with the box ticked) posts `/greenhouses/gh-01/release` with body `{ plants_removed: true }`. Follow how `dialogs.test.mjs` drives `confirmAction`.

- [ ] **Step 2: Run** `node --test tests/web/dialogs.test.mjs tests/web/greenhouses-page.test.mjs` — Expected: FAIL.

- [ ] **Step 3: Implement.** Strings:
  - `greenhouses.releaseLine` en: `"Care rules stop and the device goes to the greenhouse's idle settings; readings from then on belong to no experiment. A greenhouse with an unfinished stage cannot be released."` zh: `"释放后养护规则停止，设备转为温室的空闲设置；之后的读数不再记入任何实验。温室上还有未结束的阶段时不能释放。"`
  - `greenhouses.releaseTick` en: `"My plants have been taken out and the chamber is empty."` zh: `"我的植物已经搬走，舱已清空。"`

- [ ] **Step 4: Run** `node --test tests/web/` — Expected: PASS.

- [ ] **Step 5: Commit** `feat: the console asks the holder to confirm the plants are gone before releasing`
