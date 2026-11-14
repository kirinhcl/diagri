# 三项安全补强 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 DiAGRI 加三项确定性安全补强：意外开泵看门狗、读数冻结检测、控制闸门两级优先。

**Architecture:**
- 闸门：`control/priority_gate.py` 的两级锁替换 `ControlService.gate` 的 `asyncio.Lock`，各调用点显式传级别。
- 看门狗：`executor/watchdog.py` 的 `PumpWatchdog`，在执行 Agent 的 tick 里紧跟联锁运行，只经 `ControlService.pump_off(trigger="watchdog")` 关泵；告警由运行时晚绑定注入；干预记录走 `StagePort.record_intervention`，再由已有的 `InterventionMirror` 抄进档案库。
- 冻结检测：纯函数在 `observer/frozen.py`，有状态的检查在 `observer/frozen_watch.py`，由 `Observer.tick` 调用；冻结时段写进档案库的只追加表 `frozen_marks`；门槛放在 `SafetyConfig.frozen`。

**Tech Stack:** Python 3.11+、asyncio、SQLite（JSON1）、pydantic、pytest；工作台前端原生 ES 模块，Node 22 的 `node:test`。

**Spec:** `docs/superpowers/specs/2026-11-14-greenhouse-safety-design.md`（已批准）。实现者每个任务都要先读 spec 里对应的小节。

## Global Constraints

- 只用模拟设备和假时钟测试；不连网络、不连蓝牙、不用真实凭据。
- 原始样本不改、不删；`frozen_marks` 只插入，不更新、不删除。
- 每次设备写入都有账本记录；任何代码都不能让水泵自动打开。
- 不新增依赖。
- 文件不超过 800 行，函数少于 50 行；先写失败的测试，再实现。
- 每个任务结束前通过：`.venv/bin/ruff check src tests scripts`、`.venv/bin/ruff format --check src tests scripts`、`.venv/bin/pytest -q`；动了前端的任务再加 `node --test tests/web/*.test.mjs`。
- Wiki 英文（`docs/wiki/en/`）和中文（`docs/wiki/zh-CN/`）同一个提交里一起改；`tests/docs/` 的链接检查要通过。
- 提交信息格式 `<type>: <description>`；不加 Co-Authored-By 行；命令行里不要让 `git commit` 和 `-n` 同时出现。
- 读文件先 grep 定位，再每次读 30–60 行。

## Review Focus

spec 隐含、但最容易漏测的五种情况。每一条的测试已经加到对应任务里。

1. 操作员人工接管中、但没在灌溉时，面板把泵打开：仍然算意外，要关泵（Task 5）。
2. 设备断开时：看门狗不写设备、不告警（Task 5）。
3. 冻结时段还开着时，新批准的安全配置把这个传感器从 `frozen.minutes` 里去掉：时段结束、告警关闭，不能永远挂着（Task 9）。
4. 样本里没有 `sensor` 块或它不是对象（连接刚建立时可能出现）：当作无效点跳过，不报错（Task 8、Task 9）。
5. 阶段处于暂停状态时，面板把泵打开：照样关泵、写干预记录，阶段仍是暂停（Task 5）。

---

### Task 1: 两级优先锁

**Files:**
- Create: `src/growbridge/control/priority_gate.py`
- Test: `tests/control/test_priority_gate.py`

**Interfaces:**
- Produces: `URGENT: Final = 0`、`NORMAL: Final = 1`；`class PriorityGate`，`acquire(self, priority: int) -> AbstractAsyncContextManager[None]`（没有默认值），`locked(self) -> bool`。

- [ ] **Step 1: 写失败的测试**

```python
async def take(gate, order, name, priority):
    async with gate.acquire(priority):
        order.append(name)

async def test_urgent_waiter_goes_before_earlier_normal_waiters():
    gate, order = PriorityGate(), []
    async with gate.acquire(NORMAL):
        tasks = [asyncio.create_task(take(gate, order, n, p))
                 for n, p in (("a", NORMAL), ("b", NORMAL), ("c", URGENT))]
        await asyncio.sleep(0)
    await asyncio.gather(*tasks)
    assert order == ["c", "a", "b"]
```

同一文件再写：
- `test_same_level_is_first_come_first_served`：三个 `NORMAL`，结果 `["a", "b", "c"]`。
- `test_cancelled_waiter_is_skipped`：持锁时排 a、b，取消 a，放锁后 `order == ["b"]`，最后 `gate.locked() is False`。
- `test_waiter_cancelled_right_after_being_granted_hands_the_gate_on`：用 `cm = gate.acquire(NORMAL); await cm.__aenter__()` 持锁，排 a、b，`await asyncio.sleep(0)`，`await cm.__aexit__(None, None, None)` 之后**立刻** `a.cancel()`；`gather(a, b, return_exceptions=True)` 后 `order == ["b"]`，`gate.locked() is False`。
- `test_error_inside_releases_the_gate`：块里抛 `RuntimeError`，之后 `gate.locked() is False`，再次 `acquire(NORMAL)` 能进。
- `test_priority_must_be_given`：`gate.acquire()` 抛 `TypeError`。

- [ ] **Step 2: 运行，确认失败**

Run: `.venv/bin/pytest tests/control/test_priority_gate.py -q`
Expected: FAIL，`ModuleNotFoundError: growbridge.control.priority_gate`

- [ ] **Step 3: 实现 `PriorityGate`**

不抢占；同级先来先服务。算法（取消处理是关键，照这个写）：

```
状态：_held: bool；_waiters: 堆，元素 (priority, seq, future)；_seq 递增计数
acquire(priority):
  若 not _held：_held = True
  否则：future 入堆；await future
        捕获 CancelledError：若 future.done() 且没被取消（刚被授予锁），先 _release() 交出去，再 raise
  try: yield  finally: _release()
_release():
  从堆里依次弹出，跳过已 done 的 future；遇到第一个未 done 的：set_result(None) 后返回（_held 保持 True）
  堆空：_held = False
```

文件头注释写明：不抢占，最多等正在持锁的那一个；思路参考 agentic-greenhouse 的 `prioritylock.py`，代码是独立写的。

- [ ] **Step 4: 运行，确认通过**

Run: `.venv/bin/pytest tests/control/test_priority_gate.py -q`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add src/growbridge/control/priority_gate.py tests/control/test_priority_gate.py
git commit -m "feat: add a two-level priority gate"
```

### Task 2: 控制服务按级别进闸门

**Files:**
- Modify: `src/growbridge/control/service.py`（`:1-7` 文件头、`:69`、`handover` `:154-165`、`submit` `:310-322`、`_run_cycle` `:435-463`、`reconcile_unsettled` `:516-539`）
- Modify: `docs/wiki/en/Control-and-Safety-Model.md`、`docs/wiki/zh-CN/Control-and-Safety-Model.md`、`docs/wiki/en/Design-Decisions.md`、`docs/wiki/zh-CN/Design-Decisions.md`（讲到闸门的段落）
- Test: `tests/control/test_control_priority.py`

**Interfaces:**
- Consumes: Task 1 的 `PriorityGate`、`URGENT`、`NORMAL`。
- Produces: `ControlService.gate: PriorityGate`。级别：`submit` 在写权是 `RightKind.PROTECTION` 时 `URGENT`，否则 `NORMAL`；`handover` `URGENT`；`_run_cycle` 开泵 `NORMAL`、`finally` 里关泵 `URGENT`；`reconcile_unsettled` `NORMAL`。`pump_off()` 仍不进闸门。

- [ ] **Step 1: 写失败的测试**

用 `tests/control/conftest.py` 的 `rig`，以及 `tests/control/test_control_hardening.py:163` 那种"替换 `rig.sim.send`、用 `asyncio.Event` 卡住第一条 `setConfigField`"的写法。发送顺序从 `rig.sink.actions` 里状态为 `ActionState.MAYBE_SENT` 的记录读（进闸门后、发送前才存这个状态）。

- `test_protection_write_overtakes_queued_ordinary_writes`：阶段写权发 a（灯 50）并卡住；再排 b（排风 40）、c（风扇 30）；用 `rig.service.approve_safety(make_safety(), "alice")` 后的 `rig.service.protection_right()` 发 p（灯 0）；放行。断言 `MAYBE_SENT` 的请求编号顺序是 `["a", "p", "b", "c"]`。
- `test_irrigation_pump_off_overtakes_queued_writes`：手动写权（水泵和灯）启动灌溉（秒数取 0.05）；灌溉等待期间发灯写入 a 并卡住，再排 b、c；等灌溉计时结束后放行。断言放行后记下的 `setConfigField` 命令里，水泵插座 `O4` 的关泵命令紧跟在 a 之后，排在 b、c 之前。
- `test_handover_waits_only_for_the_write_in_flight`：阶段写权发 a 并卡住；照料写权（`RightKind.CARE`）排 b；任务里调 `handover(<阶段写权>, "test")`；放行。断言 `handover` 返回时 b 还没到 `MAYBE_SENT`。
- `test_protection_and_irrigation_off_use_urgent`：把 `rig.service.gate.acquire` 换成记录级别的包装，跑一次保护写入、一次灌溉；断言记到 `URGENT` 的是保护写入和关泵，开泵是 `NORMAL`。

- [ ] **Step 2: 运行，确认失败**

Run: `.venv/bin/pytest tests/control/test_control_priority.py -q`
Expected: 前三个 FAIL（先来先服务的顺序），第四个 FAIL（`asyncio.Lock` 没有 `acquire(priority)`）

- [ ] **Step 3: 改 `control/service.py`**

`self.gate = PriorityGate()`；五处 `async with self.gate:` 换成 `async with self.gate.acquire(<级别>):`，级别照 Interfaces。`_recheck` 仍是进闸门后的第一句。文件头注释改成"一个两级优先闸门……保护写入、灌溉结束时的关泵和交接排在普通写入前面"。

- [ ] **Step 4: 运行控制服务的全部测试**

Run: `.venv/bin/pytest tests/control -q`
Expected: 全部通过（含已有的 `test_control_hardening.py`、`test_control_interlock.py`）

- [ ] **Step 5: 更新 Wiki**

两种语言的 Control-and-Safety-Model 和 Design-Decisions 里描述闸门的地方：改成两级优先，写明哪些是紧急、不抢占、`pump_off` 不进闸门。

- [ ] **Step 6: 提交**

```bash
git add src/growbridge/control/service.py tests/control/test_control_priority.py docs/wiki
git commit -m "feat: let protection writes, irrigation pump-off and hand-over go first through the gate"
```

### Task 3: 运行单不能把水泵交给设备

**Files:**
- Modify: `src/growbridge/planning/validate.py`（新增检查，接进 `validate_run_sheet` `:221`）
- Modify: `docs/wiki/en/Design-Decisions.md`、`docs/wiki/zh-CN/Design-Decisions.md`（列发现代码的地方）
- Test: `tests/planning/test_planning_validate.py`

**Interfaces:**
- Produces: 阻断型发现，代码 `pump_device_owned`。

- [ ] **Step 1: 写失败的测试**（用文件里已有的 `sheet_with_plan`、`codes`、`CAPS`）

```python
def test_pump_owned_by_device_blocks():
    sheet = sheet_with_plan(Channel.PUMP, ownership=Ownership.DEVICE)
    assert "pump_device_owned" in codes(validate_run_sheet(sheet, CAPS), blocking=True)

def test_other_device_owned_channels_do_not_trip_the_pump_check():
    sheet = sheet_with_plan(Channel.FAN, ownership=Ownership.DEVICE)
    assert "pump_device_owned" not in codes(validate_run_sheet(sheet, CAPS))

def test_host_owned_pump_does_not_trip_the_pump_check():
    sheet = sheet_with_plan(Channel.PUMP, ownership=Ownership.HOST)
    assert "pump_device_owned" not in codes(validate_run_sheet(sheet, CAPS))
```

- [ ] **Step 2: 运行，确认失败**

Run: `.venv/bin/pytest tests/planning/test_planning_validate.py -q -k pump`
Expected: 第一个 FAIL

- [ ] **Step 3: 实现 `_check_pump_ownership(sheet: RunSheet) -> list[Finding]`**

水泵通道的计划归属是 `Ownership.DEVICE` 时返回 `_block("pump_device_owned", "the pump may not be left to the device timer")`；加进 `validate_run_sheet` 的结果。

- [ ] **Step 4: 运行，确认通过**

Run: `.venv/bin/pytest tests/planning -q`
Expected: 全部通过

- [ ] **Step 5: 更新 Wiki 并提交**

两种语言的 Design-Decisions 里列出 `pump_device_owned` 和原因（水泵永远不交给 AC5 定时器）。

```bash
git add src/growbridge/planning/validate.py tests/planning/test_planning_validate.py docs/wiki
git commit -m "feat: refuse run sheets that leave the pump to the device timer"
```

### Task 4: 控制服务的水泵状态接口

**Files:**
- Modify: `src/growbridge/ports.py`（新增 `PumpReading`；`ControlPort` 增加下面四个方法）
- Modify: `src/growbridge/control/device.py`（`levels_from` 附近）
- Modify: `src/growbridge/control/service.py`（`__init__`、`_run_cycle` 的 `finally`、`pump_off` `:479-515`）
- Test: `tests/control/test_control_pump_state.py`

**Interfaces:**
- Produces:
  - `ports.PumpReading(Model)`：`on: bool | None`、`at: float`（收到这份状态的主机时间）、`mono: float`（单调时间；还没收到状态时为 `0.0`）。
  - `ports.PumpOffTrigger = Literal["interlock", "watchdog"]`。
  - `DeviceIO.pump_on(self, data: dict[str, Any]) -> bool | None`：`data["outlet"]["O<n>"]["on"]` 能读出时返回 `bool`，没有这个插座或格式不对时返回 `None`。
  - `ControlService.irrigating(self) -> bool`、`pump_reading(self) -> PumpReading`、`last_cycle_end(self) -> float | None`（最近一次灌溉关泵之后的单调时间）、`last_pump_off_id(self) -> str | None`。
  - `ControlService.pump_off(self, trigger: PumpOffTrigger = "interlock") -> bool`：记录的 `trigger` 用这个值；`ledger.event("pump_off", ...)` 的内容加上 `trigger`。

- [ ] **Step 1: 写失败的测试**

- `test_pump_on_reads_the_pump_outlet`：桩 bridge（`settings.pump_outlet = 4`）上的 `DeviceIO`：`{"outlet": {"O4": {"on": 1}}}` → `True`；`{"outlet": {"O4": {"on": 0}}}` → `False`；`{"outlet": {}}`、`{"outlet": {"O4": "x"}}`、`{}` → `None`。
- `test_pump_reading_follows_the_panel`：`rig.sim.external_change("outlet", "O4", mOnOff=1)`，`await rig.refresh()`；`reading.on is True`，`reading.mono == rig.bridge.received_monotonic`，`reading.at == rig.bridge.received_at`。
- `test_irrigating_is_true_only_during_a_cycle` 和 `test_last_cycle_end_is_set_once_the_pump_is_off`：灌溉前 `irrigating() is False`、`last_cycle_end() is None`；等待期间 `irrigating() is True`；结束后 `irrigating() is False`，`last_cycle_end()` 不为 `None` 且不大于 `rig.clock.monotonic()`。
- `test_pump_off_records_its_trigger`：`await rig.service.pump_off(trigger="watchdog")` 后 `rig.service.receipt(rig.service.last_pump_off_id()).trigger == "watchdog"`；不传参数时是 `"interlock"`。

- [ ] **Step 2: 运行，确认失败**

Run: `.venv/bin/pytest tests/control/test_control_pump_state.py -q`
Expected: FAIL（`ImportError: PumpReading` / `AttributeError`）

- [ ] **Step 3: 实现**

`pump_reading()` 用 `self.bridge.data`、`self.bridge.received_at`、`self.bridge.received_monotonic` 和 `DeviceIO.pump_on`；`received_monotonic` 为 0 时返回 `PumpReading(on=None, at=0.0, mono=0.0)`。`last_cycle_end` 在 `_run_cycle` 的 `finally` 里关泵之后、清 `self._cycle` 之前记下 `self.clock.monotonic()`。`pump_off` 记下这次的 `request_id` 供 `last_pump_off_id()` 返回。

- [ ] **Step 4: 运行，确认通过**

Run: `.venv/bin/pytest tests/control -q`
Expected: 全部通过

- [ ] **Step 5: 提交**

```bash
git add src/growbridge/ports.py src/growbridge/control/device.py src/growbridge/control/service.py tests/control/test_control_pump_state.py
git commit -m "feat: expose the pump read-back, irrigation state and pump-off trigger"
```

### Task 5: 意外开泵看门狗

**Files:**
- Create: `src/growbridge/executor/watchdog.py`
- Modify: `src/growbridge/executor/engine.py`（`__init__` `:92-118`、`_tick` `:142-164`）
- Modify: `src/growbridge/ports.py`（`StagePort` 加 `record_intervention`）
- Modify: `src/growbridge/workflow/service.py`（实现 `record_intervention`，靠近 `_intervention` `:438`）
- Modify: `src/growbridge/runtime.py`（`Runtime` 加 `resolve_alert`；`build_runtime` 里绑定，靠近 `:702`）
- Modify: 两种语言的 `Control-and-Safety-Model.md`、`Overview.md`、`The-Five-Agents.md`、`Status-and-Known-Limitations.md`
- Test: `tests/executor/test_watchdog.py`（假控制服务）、`tests/executor/test_executor_watchdog.py`（模拟设备）

**Interfaces:**
- Consumes: Task 4 的全部接口。
- Produces:
  - `StagePort.record_intervention(self, stage_id: str, kind: str, detail: dict[str, Any]) -> None`。`WorkflowService` 的实现：在事务里调 `self.store.add_intervention(experiment_id, stage_id, now, kind, None, detail)`，加进 `_unsent`，再 `_hand_on_interventions()`，让已有的 `InterventionMirror` 抄进档案库。
  - `class PumpWatchdog`：`__init__(self, control: ControlPort, stages: StagePort, clock: Clock)`；属性 `alert: Callable[[str, str, str, Severity], None] | None = None`（参数顺序 kind、key、message、severity，与 `Runtime._alert` 一致）、`resolve: Callable[[str, str], None] | None = None`，两者为 `None` 时跳过告警这一步、照常关泵（测试里的执行 Agent 不绑定它们）；`async def step(self, stage: StageRuntime | None) -> None`。
  - `ExecutorEngine.watchdog: PumpWatchdog`；`_tick` 里在 `await self._interlock(tick, stage)` 之后：`if online: await self.watchdog.step(stage)`。
  - `Runtime.resolve_alert(self, kind: str, key: str) -> None`；`build_runtime` 里 `executor.watchdog.alert = runtime._alert`、`executor.watchdog.resolve = runtime.resolve_alert`。

`step` 的判断顺序（照这个写，spec 4.2–4.4）：

```
未连接，或 control.interlocked()：返回
r = control.pump_reading()；r.mono <= 0：返回（还没收到状态）
r.on is None：alert("pump_unreadable", "pump", <文字>, "warning")；返回
resolve("pump_unreadable", "pump")
control.irrigating()：返回
end = control.last_cycle_end()；end 不为 None 且 r.mono <= end：返回
上次动作时间 acted 不为 None 且 r.mono <= acted：返回
r.on 为 False：resolve("pump_unexpected", "pump")；返回
动作：acted = clock.monotonic()；confirmed = await control.pump_off(trigger="watchdog")（Denied 当作 False）
      alert("pump_unexpected", "pump", <文字>, "critical")
      stage 不为 None：stages.record_intervention(stage.stage_id, "unexpected_watering",
          {"status_at": r.at, "off_confirmed": confirmed,
           "off_confirmed_at": clock.now() if confirmed else None,
           "request_id": control.last_pump_off_id()})
```

告警文字要说明：水泵在 DiAGRI 没有灌溉时开着，已关闭，设备上的水泵插座模式已重置为手动；没确认时改说"关泵未确认，已设联锁"（英文文字里含 `unconfirmed`）。

- [ ] **Step 1: 写失败的单元测试**（`tests/executor/test_watchdog.py`）

在测试文件里写一个 `FakeControl`：可设的 `connected`、`interlocked`、`irrigating`、`reading: PumpReading`、`cycle_end`，`pump_off(trigger)` 记下调用并返回可设的结果，`last_pump_off_id()` 返回 `"pumpoff-1"`；一个 `FakeStages` 记下 `record_intervention` 调用；`alert`、`resolve` 绑到记录列表。测试：

- `test_switches_off_a_pump_found_on`：`reading=PumpReading(on=True, at=100.0, mono=10.0)` → `pump_off` 被调一次，`trigger == "watchdog"`；告警 `("pump_unexpected", "pump", "critical")`；干预记录种类 `"unexpected_watering"`，`detail["status_at"] == 100.0`，`detail["request_id"] == "pumpoff-1"`。
- `test_quiet_while_irrigating`、`test_quiet_on_a_status_from_before_the_cycle_ended`（`cycle_end=10.0`，`mono=10.0`）、`test_quiet_before_the_first_status`（`mono=0.0`）、`test_quiet_when_disconnected`、`test_quiet_when_interlocked`：都没有 `pump_off` 调用、没有告警。
- `test_waits_for_a_status_after_its_own_switch_off`：动作后同一份 `reading` 再 `step` 一次，`pump_off` 仍只调了一次；换成 `mono` 更大、`on=True` 的状态，再调一次。
- `test_off_status_closes_the_alert`：动作后给 `mono` 更大、`on=False` 的状态 → `resolve("pump_unexpected", "pump")`。
- `test_unreadable_outlet_warns_and_does_not_switch`：`on=None, mono=5.0` → 告警 `("pump_unreadable", "pump", "warning")`，没有 `pump_off`；之后读得出 → `resolve("pump_unreadable", "pump")`。
- `test_no_intervention_without_a_stage`：`step(None)` 照样关泵、告警，没有干预记录。
- `test_unconfirmed_switch_off_is_reported`：`pump_off` 返回 `False` → critical 告警文字里有 `unconfirmed`，`detail["off_confirmed"] is False`。

- [ ] **Step 2: 写失败的集成测试**（`tests/executor/test_executor_watchdog.py`，用 `tests/executor/conftest.py` 的 `rig`）

面板开泵统一写成 `rig.sim.external_change("outlet", "O4", mOnOff=1)`，然后 `await rig.pass_time(5)`、`await rig.tick()`。

- `test_panel_pump_on_is_switched_off_and_recorded`：`await rig.start()` 后面板开泵 → `(await rig.levels())[Channel.PUMP] == 0`；`rig.control.receipt(rig.control.last_pump_off_id()).trigger == "watchdog"`；`rig.svc.interventions(<活动阶段的 experiment_id>)` 里有一条 `kind == "unexpected_watering"`、`operator is None`；`rig.state() == "running"`。
- `test_panel_pump_on_during_manual_takeover_is_switched_off`（Review Focus 1）：人工接管、不灌溉时面板开泵 → 关泵。
- `test_panel_pump_on_while_paused_is_switched_off`（Review Focus 5）：`await rig.svc.pause_stage(STAGE, rig.op, "test")` 后面板开泵 → 关泵、有干预记录、`rig.state() == "paused"`。
- `test_disconnected_device_is_left_alone`（Review Focus 2）：`rig.sim.drop()` 后 tick → `last_pump_off_id()` 不变。
- `test_unconfirmed_switch_off_hands_over_to_the_interlock`：`rig.sim.fail_off = True` 时面板开泵 → `rig.control.interlocked()`；下一次 tick 新的关泵记录 `trigger == "interlock"`。
- `test_watchdog_runs_without_a_stage`：不启动阶段，面板开泵 → 关泵。

- [ ] **Step 3: 运行，确认失败**

Run: `.venv/bin/pytest tests/executor/test_watchdog.py tests/executor/test_executor_watchdog.py -q`
Expected: FAIL（`ModuleNotFoundError: growbridge.executor.watchdog`）

- [ ] **Step 4: 实现** `executor/watchdog.py`、`StagePort.record_intervention` 和 `WorkflowService.record_intervention`、`ExecutorEngine.watchdog` 和 `_tick` 的接入、`Runtime.resolve_alert` 和 `build_runtime` 的绑定。

- [ ] **Step 5: 运行，确认通过**

Run: `.venv/bin/pytest tests/executor tests/workflow -q`
Expected: 全部通过

- [ ] **Step 6: 更新 Wiki**

两种语言：Control-and-Safety-Model 里"不管的事"中关于面板和 App 开泵的那段，改成看门狗会关泵并记干预；Overview "系统绝不会做的事"最后一段同步；The-Five-Agents 的执行 Agent 加上看门狗；Status-and-Known-Limitations 写明插座读回在真机上没验证过。

- [ ] **Step 7: 全部测试后提交**

Run: `.venv/bin/pytest -q`
Expected: 全部通过

```bash
git add src/growbridge/executor/watchdog.py src/growbridge/executor/engine.py src/growbridge/ports.py src/growbridge/workflow/service.py src/growbridge/runtime.py tests/executor docs/wiki
git commit -m "feat: switch off a pump found on while DiAGRI is not irrigating"
```

### Task 6: 安全配置里的冻结门槛

**Files:**
- Modify: `src/growbridge/archive/models.py`（`SafetyConfig` `:196` 之前加 `FrozenCheck`）
- Modify: `src/growbridge/web/workbench/pages/safety-skeleton.js`、`src/growbridge/web/workbench/pages/safety.js`、`src/growbridge/web/workbench/i18n/en.js`、`src/growbridge/web/workbench/i18n/zh.js`
- Create: `src/growbridge/web/workbench/pages/safety-frozen.js`
- Modify: `tests/web/config-pages.test.mjs`
- Modify: 两种语言的 `Configuration-Reference.md`、`API-Reference.md`
- Test: `tests/archive/test_frozen_config.py`、`tests/web/safety-frozen.test.mjs`

**Interfaces:**
- Produces:
  - `DEFAULT_FROZEN_MINUTES = {"temp": 120.0, "humi": 60.0, "co2": 60.0, "tempSoil": 240.0}`。
  - `class FrozenCheck(Model)`：`minutes: dict[str, float]`（默认是上面的副本）、`max_gap_seconds: float = 600.0`；每个分钟数和 `max_gap_seconds` 都必须是有限正数。
  - `SafetyConfig.frozen: FrozenCheck`，默认 `FrozenCheck()`。
  - JS：`frozenRows(frozen) -> Array<[string, number]>`，按传感器名排序；`frozen` 缺失或不是对象时返回 `[]`。

- [ ] **Step 1: 写失败的测试**

```python
def test_old_safety_config_without_frozen_loads_with_defaults():
    stored = make_safety().model_dump(mode="json")
    stored.pop("frozen", None)
    config = SafetyConfig.model_validate_json(json.dumps(stored))
    assert config.frozen.minutes == {"temp": 120.0, "humi": 60.0, "co2": 60.0, "tempSoil": 240.0}
    assert config.frozen.max_gap_seconds == 600.0
```

同一文件再写：`test_frozen_rejects_non_positive_or_non_finite_minutes`（`0`、`-5`、`nan`、`inf` 都抛 `ValidationError`）、`test_frozen_rejects_a_non_positive_gap`、`test_frozen_round_trips`、`test_default_minutes_are_not_shared_between_configs`（改一个实例拿到的 dict 不影响新实例）。

JS：`config-pages.test.mjs` 的骨架测试加一行 `assert.deepEqual(sorted(Object.keys(skeleton.frozen)), sorted(fieldsOf("FrozenCheck")))`；`safety-frozen.test.mjs` 测 `frozenRows({minutes: {temp: 120, co2: 60}})` 等于 `[["co2", 60], ["temp", 120]]`，`frozenRows(undefined)` 等于 `[]`。

- [ ] **Step 2: 运行，确认失败**

Run: `.venv/bin/pytest tests/archive/test_frozen_config.py -q && node --test tests/web/*.test.mjs`
Expected: FAIL

- [ ] **Step 3: 实现**

模型照 Interfaces。骨架加 `frozen: { minutes: null, max_gap_seconds: null }`（"每个值都是 null"的测试仍成立）。安全页"当前配置"里加一张冻结门槛表（传感器、分钟）和一行最大空档秒数，数据来自 `frozenRows`；新文案加进 `en.js`、`zh.js`。不用 `innerHTML`。

- [ ] **Step 4: 运行，确认通过**

Run: `.venv/bin/pytest -q && node --test tests/web/*.test.mjs`
Expected: 全部通过

- [ ] **Step 5: 更新 Wiki 并提交**

两种语言的 Configuration-Reference（字段、默认值、校验、没批准时用默认值）和 API-Reference（`/wb/safety` 的返回和批准请求里多了 `frozen`）。

```bash
git add src/growbridge/archive/models.py src/growbridge/web tests/archive/test_frozen_config.py tests/web docs/wiki
git commit -m "feat: add frozen-reading thresholds to the safety configuration"
```

### Task 7: 冻结判定的纯函数

**Files:**
- Create: `src/growbridge/observer/frozen.py`
- Test: `tests/observer/test_frozen_rules.py`

**Interfaces:**
- Produces:
  - `DERIVED: dict[str, tuple[str, ...]] = {"vpd": ("temp", "humi")}`。
  - `@dataclass(frozen=True) class FlatRun`：`value: float`、`first_at: float`、`last_at: float`。
  - `flat_tail(points: Sequence[tuple[float, object]], max_gap_seconds: float) -> FlatRun | None`：从最后一个点往回，值完全相同、相邻间隔在 `[0, max_gap_seconds]` 内、每个点都有效的最长一段。最后一个点无效时返回 `None`。
  - `first_change(points: Sequence[tuple[float, object]], value: float) -> float | None`：第一个有效、且值不等于 `value` 的点的时间；无效点跳过。
  - `sensors_used(sensors: Iterable[str]) -> frozenset[str]`：加上 `DERIVED` 里的源头传感器。
  - "有效"：`int` 或 `float`（不含 `bool`），而且是有限数。

- [ ] **Step 1: 写失败的测试**

```python
def series(values, start=0.0, step=60.0):
    return [(start + i * step, v) for i, v in enumerate(values)]

def test_flat_tail_covers_the_whole_unchanged_stretch():
    assert flat_tail(series([24.0] * 121), 600) == FlatRun(24.0, 0.0, 7200.0)
```

同一文件再写：
- `test_flat_tail_starts_after_the_last_change`：`[23.9, 24.0, 24.0]` → `FlatRun(24.0, 60.0, 120.0)`。
- `test_a_gap_longer_than_the_limit_breaks_the_run`：点 `(0, 24.0), (601, 24.0), (661, 24.0)`，上限 600 → `first_at == 601.0`。
- `test_time_going_backwards_breaks_the_run`：`(100, 24.0), (50, 24.0), (110, 24.0)` → `first_at == 50.0`。
- `test_invalid_last_point_gives_none`：最后一个点是 `None`、`float("nan")`、`"x"`、`True` 时都返回 `None`。
- `test_first_change_skips_invalid_points`：`first_change([(0, None), (60, nan), (120, 24.0), (180, 24.1)], 24.0) == 180.0`；没有变化时 `None`。
- `test_sensors_used_expands_vpd`：`sensors_used({"vpd"}) == {"vpd", "temp", "humi"}`；`sensors_used({"co2"}) == {"co2"}`。
- `test_ints_and_floats_compare_equal`：`[750, 750.0, 750]` 是一段。

- [ ] **Step 2: 运行，确认失败**

Run: `.venv/bin/pytest tests/observer/test_frozen_rules.py -q`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现** `observer/frozen.py`。

- [ ] **Step 4: 运行，确认通过**

Run: `.venv/bin/pytest tests/observer/test_frozen_rules.py -q`
Expected: 全部通过

- [ ] **Step 5: 提交**

```bash
git add src/growbridge/observer/frozen.py tests/observer/test_frozen_rules.py
git commit -m "feat: add pure rules for finding frozen readings"
```

### Task 8: 档案库的冻结时段记录

**Files:**
- Modify: `src/growbridge/archive/store.py`（`STEPS` 末尾追加两步；`Archive` 新增方法）
- Modify: `src/growbridge/archive/models.py`（新增 `FrozenPeriod`）
- Modify: `src/growbridge/archive/snapshot.py`（`_collect` `:55-79`）
- Modify: 两种语言的 `Data-Archive-and-Traceability.md`
- Test: `tests/archive/test_archive_frozen_marks.py`

**Interfaces:**
- Produces:
  - `STEPS` 末尾追加：`"CREATE INDEX samples_by_time ON samples(at)"`；`"CREATE TABLE frozen_marks(seq INTEGER PRIMARY KEY AUTOINCREMENT, period_id TEXT NOT NULL, event TEXT NOT NULL CHECK (event IN ('opened', 'closed')), sensor TEXT NOT NULL, value REAL, sample_at REAL NOT NULL, recorded_at REAL NOT NULL, UNIQUE (period_id, event))"`。
  - `FrozenPeriod(Model)`：`period_id: str`、`sensor: str`、`value: float`、`first_at: float`、`opened_at: float`。
  - `Archive.sensor_points(self, since: float) -> tuple[tuple[float, dict[str, Any]], ...]`：`at >= since` 的样本，按 `at, id` 排序，返回 `(at, data["sensor"])`；`sensor` 缺失或不是对象时给 `{}`。不按实验过滤。
  - `Archive.open_frozen(self, sensor: str, value: float, first_at: float) -> str`：插入 `opened` 行，返回新的 `period_id`（`new_id("frozen")`）。
  - `Archive.close_frozen(self, period_id: str, sensor: str, last_at: float) -> None`：插入 `closed` 行；同一时段重复关闭不报错，也不多插。
  - `Archive.open_frozen_periods(self) -> tuple[FrozenPeriod, ...]`：有 `opened`、没有 `closed` 的时段。
  - `Archive.frozen_periods(self, start: float, end: float) -> tuple[dict[str, Any], ...]`：与 `[start, end]` 重叠的时段，每个是 `{"period_id", "sensor", "value", "first_at", "last_at", "opened_at", "closed_at"}`，还开着的 `last_at` 和 `closed_at` 为 `None`。
  - 快照 `_collect` 多一项 `"frozen_periods": list(archive.frozen_periods(start, end))`，于是快照里多一个 `frozen_periods.jsonl`。

- [ ] **Step 1: 写失败的测试**

- `test_open_then_close_adds_two_rows_and_changes_none`：开、关之后 `frozen_marks` 有两行；`opened` 行的内容和关之前完全一样。
- `test_open_periods_leave_out_closed_ones`。
- `test_closing_twice_is_harmless`：第二次关闭不抛错，表里仍是两行。
- `test_frozen_periods_overlap_the_window`：时段 `[100, 200]`：窗口 `[150, 300]` 包含它，`[201, 300]` 不包含；还开着的时段对任何结束时间不早于 `first_at` 的窗口都包含。
- `test_sensor_points_are_in_time_order_across_experiments`：实验 `e1`、没有实验的样本各一条，都返回，按时间排序。
- `test_sensor_points_tolerate_samples_without_a_sensor_block`（Review Focus 4）：`data={}` 和 `data={"sensor": "x"}` 的样本返回 `{}`。
- `test_snapshot_lists_overlapping_frozen_periods`：用 `archive/snapshot.py` 的 `freeze` 做一次快照，`frozen_periods.jsonl` 里有这个时段。
- `test_samples_are_untouched`：开、关时段前后，`samples` 表每一行的 `body` 不变。

- [ ] **Step 2: 运行，确认失败**

Run: `.venv/bin/pytest tests/archive/test_archive_frozen_marks.py -q`
Expected: FAIL（`AttributeError: 'Archive' object has no attribute 'open_frozen'`）

- [ ] **Step 3: 实现**

`sensor_points` 用 `json_extract(body, '$.data.sensor')`。快照的文件写入和清单已经按 `data` 的键遍历，不用另改。

- [ ] **Step 4: 运行，确认通过**

Run: `.venv/bin/pytest tests/archive -q`
Expected: 全部通过

- [ ] **Step 5: 更新 Wiki 并提交**

两种语言的 Data-Archive-and-Traceability：新表只追加，快照多了 `frozen_periods.jsonl`。

```bash
git add src/growbridge/archive tests/archive/test_archive_frozen_marks.py docs/wiki
git commit -m "feat: record frozen-reading periods in the archive"
```

### Task 9: 观察者的冻结检查

**Files:**
- Create: `src/growbridge/observer/frozen_watch.py`
- Modify: `src/growbridge/observer/service.py`（`__init__` `:24-40`、`tick` `:71-88`）
- Modify: `src/growbridge/runtime.py`（`build_runtime` `:646` 附近）
- Modify: 两种语言的 `The-Five-Agents.md`、`Control-and-Safety-Model.md`、`Status-and-Known-Limitations.md`、`Glossary.md`（加"冻结读数"）
- Test: `tests/observer/test_frozen_watch.py`

**Interfaces:**
- Consumes: Task 6 的 `FrozenCheck`、`SafetyConfig.frozen`；Task 7 的 `flat_tail`、`first_change`、`sensors_used`；Task 8 的 `Archive` 方法。
- Produces:
  - `CHECK_SECONDS = 300.0`。
  - `class FrozenWatch`：`__init__(self, archive: Archive, book: AlertBook, stages: StagePort, safety: Callable[[], SafetyConfig | None], clock: Clock)`；`async def tick(self) -> None`：第一次调用就检查，之后距上次检查不到 `CHECK_SECONDS`（单调时间）就直接返回。
  - `Observer.__init__` 增加关键字参数 `frozen: FrozenWatch | None = None`；`tick` 在 `_queue_open_alerts()` 之前 `await self.frozen.tick()`。
  - `build_runtime`：`FrozenWatch(archive, book, flow, control.safety, clock)` 传给 `Observer(..., frozen=...)`。

一次检查（spec 5.2–5.7）：

```
settings = safety().frozen，safety() 为 None 时用 FrozenCheck()
open = {p.sensor: p for p in archive.open_frozen_periods()}
不在 settings.minutes 里、却还开着的时段：close_frozen（last_at 取它最后一个同值点的时间，没有就用 first_at），resolve 告警
since = now - max(minutes) * 60 - max_gap_seconds；points = archive.sensor_points(since)
对 settings.minutes 里的每个传感器：
  series = [(at, sensors.get(name)) for at, sensors in points]
  已有开着的时段：changed = first_change([p for p in series if p[0] > period.first_at], period.value)
      有变化：close_frozen(..., last_at=变化前最后一个同值点的时间)，resolve("frozen_reading", name)
  没有：run = flat_tail(series, max_gap_seconds)
      run 且 run.last_at - run.first_at >= minutes * 60：open_frozen(name, run.value, run.first_at)，raise_alert
告警：kind "frozen_reading"，key 传感器名；sensors_used(保护规则的传感器) 包含它时 "critical"，否则 "warning"
暂停：活动阶段的 state 是 StageState.RUNNING 时，used = sensors_used(保护规则传感器 ∪ 运行单 feedback_rules 传感器)；
      对每个开着、且传感器在 used 里的时段，report StageEvent(
          event_id=f"frozen_pause:{period_id}:{stage_id}", kind=StageEventKind.ALERT_PAUSE, stage_id=stage_id,
          at=clock.now(), detail={"rule": f"frozen:{sensor}", "alert": <告警的 event_id>, "period": period_id})
      本实例里已报过的 event_id 不再报（工作流本身也不接受重复的事件编号）
```

- [ ] **Step 1: 写失败的测试**

用真实的 `Archive`（临时目录里的数据库）、`tests/observer/conftest.py` 的 `make_sample` 和 `clock`、`AlertBook`，以及一个可设状态和运行单的假 `StagePort`。样本每 60 秒一条，`data={"sensor": {...}}`。

- `test_temp_flat_for_two_hours_opens_a_period_and_warns`：temp 121 条都是 24.0，humi、co2 一直在变 → 一个开着的 temp 时段；一条 `("frozen_reading", "temp")` warning 告警。
- `test_a_change_closes_the_period_and_the_alert`。
- `test_ppfd_vpd_and_unlisted_sensors_are_not_checked`：ppfd、vpd 和一个没列在 `minutes` 里的传感器 300 分钟不变 → 没有时段。
- `test_a_gap_before_opening_restarts_the_count`：中间空 601 秒 → 不开。
- `test_a_gap_after_opening_keeps_the_same_period`：开了之后空 900 秒，回来还是 24.0 → 仍是同一个 `period_id`，没有新告警。
- `test_a_new_watch_finds_open_periods_after_a_restart`：换一个 `FrozenWatch` 实例 → 不会重复开时段；值变了能关掉。
- `test_checks_at_most_every_five_minutes`：两次 `tick` 相隔 299 秒，第二次不读样本（给 `Archive.sensor_points` 套计数包装）。
- `test_pauses_once_when_a_feedback_rule_uses_the_sensor`：运行单有用 temp 的反馈规则 → 报一条 `ALERT_PAUSE`，`event_id == f"frozen_pause:{period_id}:st1"`；再检查一次不再报。
- `test_a_new_stage_is_paused_for_a_period_already_open`：时段开着时换成阶段 `st2` → 报 `frozen_pause:{period_id}:st2`。
- `test_a_stage_that_is_not_running_is_not_paused`：阶段是 `PAUSED` → 不报。
- `test_no_rule_no_pause`：没有规则用到 → 只有告警，没有暂停事件。
- `test_a_vpd_rule_counts_as_using_temp`：反馈规则用 vpd，temp 冻结 → 暂停。
- `test_critical_when_a_protection_rule_uses_the_sensor`：安全配置里的保护规则用 temp → 告警 critical。
- `test_defaults_apply_without_a_safety_config`：`safety` 返回 `None` → 仍按默认门槛检查 temp。
- `test_removing_a_sensor_from_the_thresholds_closes_its_period`（Review Focus 3）：时段开着时，`safety` 返回的配置不再列 temp → 时段关闭，告警关闭。
- `test_samples_without_sensor_blocks_do_not_break_the_check`（Review Focus 4）。
- `test_raw_samples_are_unchanged`：检查前后 `samples` 表的 `body` 不变。

再在 `tests/observer/test_observer_service.py` 加 `test_observer_tick_runs_the_frozen_watch`：传一个记录调用的假 `frozen`，`tick` 后它被调了一次；不传时 `tick` 照旧。

- [ ] **Step 2: 运行，确认失败**

Run: `.venv/bin/pytest tests/observer -q`
Expected: 新测试 FAIL（`ModuleNotFoundError: growbridge.observer.frozen_watch`）

- [ ] **Step 3: 实现** `observer/frozen_watch.py`、`Observer` 的接入、`build_runtime` 的接线。

- [ ] **Step 4: 运行全部测试**

Run: `.venv/bin/pytest -q && node --test tests/web/*.test.mjs`
Expected: 全部通过

- [ ] **Step 5: 更新 Wiki 并提交**

两种语言：The-Five-Agents 的观察者加上冻结检查；Control-and-Safety-Model 写明冻结读数怎么处理（规则用到才暂停）；Status-and-Known-Limitations 写明门槛来自 64 分钟的闲置数据，需要用真实实验数据再调；Glossary 加"冻结读数 / frozen reading"。

```bash
git add src/growbridge/observer src/growbridge/runtime.py tests/observer docs/wiki
git commit -m "feat: detect frozen readings and pause stages whose rules depend on them"
```

### Task 10: 日报列出冻结时段

spec 5.7："数据快照列出……报告里也列出来"。快照在 Task 8 做了，这里补日报。

**Files:**
- Modify: `src/growbridge/observer/report.py`（`ReportContext` `:20-27`、`render_daily_report` `:58-73`）
- Modify: `src/growbridge/runtime.py`（`_report_text`，约 `:496-525`）
- Modify: 两种语言的 `Notifications-Reports-and-Backup.md`
- Test: `tests/observer/test_observer_report.py`，以及运行时日报已有测试所在的文件（`grep -rn "Manual interventions" tests` 找）

**Interfaces:**
- Consumes: Task 8 的 `Archive.frozen_periods(start, end)`。
- Produces: `ReportContext.frozen_readings: tuple[str, ...] = ()`；日报在 "Manual interventions" 之后多一节 `Frozen readings`。每一项的格式：`f"{sensor} stuck at {value:g} from {HH:MM}"`，已结束的加 `f" to {HH:MM}"`，还开着的加 `" (still frozen)"`；时间按 `report_timezone` 显示。

- [ ] **Step 1: 写失败的测试**

- `test_report_lists_frozen_readings`：`ReportContext(..., frozen_readings=("temp stuck at 24 from 08:00 to 10:05",))` 渲染后含 `"Frozen readings:"` 和这一项；不传时含 `"Frozen readings: none"`。
- 运行时日报测试：档案库里有一段与那天重叠的 temp 冻结时段时，日报正文里有 `"temp stuck at 24 from"`。

- [ ] **Step 2: 运行，确认失败**

Run: `.venv/bin/pytest tests/observer/test_observer_report.py -q`
Expected: FAIL（`ValidationError`：`frozen_readings` 是多余字段）

- [ ] **Step 3: 实现** 字段、渲染一节，以及 `_report_text` 里用 `self.archive.frozen_periods(start, end)` 生成各项。

- [ ] **Step 4: 运行全部测试**

Run: `.venv/bin/pytest -q`
Expected: 全部通过

- [ ] **Step 5: 更新 Wiki 并提交**

两种语言的 Notifications-Reports-and-Backup：日报多了 "Frozen readings" 一节。

```bash
git add src/growbridge/observer/report.py src/growbridge/runtime.py tests docs/wiki
git commit -m "feat: list frozen readings in the daily report"
```
