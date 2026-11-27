# 设备测试面板：实验前在现场点一下，确认设备能动：设计

**日期：** 2026-11-27 · **状态：** 待批准 · **前置：** 多用户与温室锁定（`2026-11-16-multi-user-locks-design.md`）、空舱交接（`2026-11-24-empty-chamber-handover-design.md`）

标注：**[用户]** = 用户明确表态；**[设计方]** = 设计方的决定，审阅时可推翻；未标注 = 由现有代码直接推出。

## 1. 意图

使用者在实验开始前到温室现场，想当场确认灯、排风、风扇、水泵真的能动 **[用户]**。每个设备点一下，短暂运行后自动恢复，不持续运行（例如灯亮 10 秒）**[用户]**。使用场景固定：使用者先锁定温室，舱里可能是空的，实验还没开始 **[用户]**。

现状下工作台（`auto_research = true`）里做不到这件事：

- 普通控制台的设备写入在工作台模式下关闭（`api.py` `writes_closed` → `use_workbench`）。
- 工作台只在阶段运行中经"接管"（takeover → MANUAL 写入权）写设备，接管记为对实验的干预。没有运行中的阶段时，没有任何写入口。

## 2. 目标、非目标、反目标

**目标**

- G1 温室持有者在该温室"空闲"时，可在工作台对每个可控设备发起一次测试；设备开到测试值，持续固定时长后**整段设置原样还原**（模式、定时、电平），对使用者如同未动过 **[用户选整段还原]**。
- G2 计时和还原由服务端完成：浏览器关闭、断网都不影响还原 **[用户选服务端计时]**。
- G3 持有者能在温室页看到这个温室最近的测试及结果；管理员另在锁定日志里看到 **[设计方]**。

**非目标**

- 实验运行中（有当前阶段时）的测试：那时走现有的接管流程 **[用户]**。
- 单用户工作台（`multi_user = false`）：那里没有温室锁和温室页，用户描述的流程以锁定为前提 **[设计方]**。
- 让使用者自选测试值或时长 **[设计方]**。
- 插座 5 及其他未映射到通道的插座 **[设计方]**。
- 自动判断设备"是否真的运转"：回读只能确认设定生效，转没转、亮没亮由现场的人看 **[设计方]**。
- 普通控制台（非工作台模式）：那里已有设备控制，不改。

**反目标**（做成这样就算失败）

- 测试结束后设备停在测试值上，或某一路从控制器自己的程序（非手动模式）被悄悄改成手动。
- 还原失败后没有提示，或者在无人确认的情况下照常启动实验。
- 测试期间执行器的空闲电平把测试值改回去，或测试与空闲写入、保护写入互相抢通道。
- 有当前阶段的温室、别人锁定的温室、本安装不驱动的温室可以发起测试。
- 水泵测试突破 `max_pump_seconds` 或 `pump_cooldown_seconds`。
- `controls_enabled = false` 时仍写设备。

## 3. 约束（由现有代码决定）

- **只在 `auto_research` 与 `multi_user` 同为真时存在**：锁、`Access`、`access.local_device`、`/wb/greenhouses` 路由与温室页都只在此时组装（`runtime_access.py` `build_access`）。
- **可控设备只有四个通道**（`archive/models.py` `Channel`、`LEVEL_RANGES`）：灯 light 0–100、排风 exhaust 0–100、风扇 fan 0–10、水泵 pump 0/1。灯、排风、风扇是 AC5 的设备模块（`light`、`blower`、`fan`），水泵是一个插座（`pump_outlet`）（`control/device.py`）。
- **每次写入都把该路强制为手动**：`params()` 深拷贝该模块的配置块后改 `modeType=0, mOnOff, mLevel`（排风还改 `maxSpeed`）。水泵插座经 `outlet_params` 同理。模块的原配置块（含模式和控制器自身的定时）可从 `bridge.configuration()` 读到。
- **"空闲"沿用 `IdleCare._due` 的判据**（不含"配置了空闲电平"这一条）：该设备从未启动过阶段，或最近启动的阶段已 `care_released`。
- **执行器在空闲时按空闲电平对齐设备**（`executor/engine.py` `_idle`），并用 `_applied` 缓存跳过它认为已对齐的通道；阶段键变化时 `_applied` 清空、重新对齐。保护规则在空闲时也运行，哪些通道正被保护只存在执行器内存里（`_protected()`）。
- **所有写入都经 `ControlService._authorize`**：`controls_enabled`、写入权有效、范围、闸门状态、连接状态。水泵只能经 `irrigate()` 打开，自带时长上限、冷却、OFF 确认和互锁；`_may_irrigate` 目前只放行 MANUAL 和计划内的 STAGE 写入权。
- **服务重启会吊销所有写入权**（`startup` → `revoke_all`），但不改设备当前设定。
- **无阶段的动作回执只有管理员可见**（`sees_receipt`），无范围的告警也只有管理员可见（`sees_alert`）。

## 4. 方案

**怎么计时**

| 方案 | 做法 | 取舍 |
|---|---|---|
| **A 服务端计时还原**（选定 **[用户]**） | 后端授予临时写入权，暂停空闲对齐，写测试值，服务端等待后还原，交还写入权 | 浏览器断开也能还原；后端改动最多 |
| B 浏览器计时 | 网页发"开"，倒计时后发"关" | 简单；页面关闭或断网时设备停在测试值上 |
| C 工作台模式下重开普通控制台面板 | 放开 `/control`、`/pump` 给持有者 | 改动最少；没有自动还原，绕开锁和记录 |

**还原什么**

| 方案 | 做法 | 取舍 |
|---|---|---|
| **A 整段原样还原**（选定 **[用户]**） | 测试前保存该路完整配置块，测完原样写回 | 控制器自己的定时程序不受影响；控制层要新增"写回整段配置"入口 |
| B 非手动模式时拒绝测试 | 提示先在 App 里切手动 | 简单；现场用起来麻烦 |
| C 照测，提前提醒会停在手动 | 使用者自己决定 | 简单；容易把控制器自己的程序弄丢 |

## 5. 设计

### 5.1 测试值与时长 [设计方]

| 通道 | 测试值 | 时长 |
|---|---|---|
| light | 100 | 10 s |
| exhaust | 100 | 10 s |
| fan | 10 | 10 s |
| pump | 开 | `min(3, max_pump_seconds)` s |

时长写成模块常量（测试里可注入时钟），不进配置文件。水泵空舱里也会真的出水，面板上明示。

### 5.2 写入权：新增 `RightKind.TEST` [设计方]

- 不复用 MANUAL：MANUAL 在工作流里与阶段绑定（`workflow/store.py` 按阶段处理 `manual_right`），复用会让"无阶段的 MANUAL"在多处成为特例；独立种类也让记录直接显示"测试"。
- 与 MANUAL 一样绑定操作者（`build_right` 要求 `operator` 非空），按通道限定（只含被测通道），归入 `ORDINARY_KINDS`。
- `_may_irrigate` 放行 TEST，水泵其余检查不变。
- `_check_gate_state` 对 TEST 与 MANUAL 同等对待；保护写入权照旧优先。

### 5.3 控制层：配置块快照与还原

`ControlService` 新增两个方法（`ControlPort` 与 `sim/control.py` 同步）：

- `snapshot(channel) -> ChannelSnapshot`：读 `bridge.configuration()`，返回该路的原始配置块（模块块或水泵插座块）的深拷贝及其回读电平。只读，不需写入权。
- `restore(request, snapshot) -> ActionRecord`：在 TEST 写入权下把快照块原样写回（`setConfigField` 同一 keyPath），经回读确认模式与电平都与快照一致。和普通写入一样过 `_authorize`、进台账（动作记录电平为快照电平，另记 `restored_mode`）。只接受 TEST 写入权，且只接受由 `snapshot` 产生、未被篡改的块（快照带摘要）。

`AC5Device` 相应增加"写整段块"与"按块确认"的实现；模拟设备记住模块块，便于测试模式还原。

### 5.4 一次测试的流程（服务端）

新增 `workflow/device_test.py`（`DeviceTests`），由工作台路由调用：

1. **前置检查**，任一不满足即拒绝（5.7）：调用者持有该温室锁；温室的 `device_id` 是 `access.local_device`；温室空闲（3 节判据）；本设备没有进行中或未了结的测试（5.5）；该通道当前不在保护中（执行器 `_protected()` 经一个只读入口暴露给 `DeviceTests`）；`controls_enabled`。
2. **快照**该路配置块。读不到则拒绝，不写。
3. **让空闲对齐让路**：`IdleCare` 增加与 `held_back()` 同语义的入口，测试期间不授予也不使用空闲写入权，并交还当前空闲写入权。
4. **授予 TEST 写入权**（仅该通道），在工作流数据库写一条测试记录：通道、快照（块与摘要）、写入权号、操作者、开始时间、状态 `running`。
5. **写测试值**（`control.submit`）；水泵走 `control.irrigate(seconds)`，返回前已关泵并确认 OFF。
6. **等待**时长（水泵跳过）。
7. **还原**：若该通道此时已在保护中，跳过还原，记 `result = protected`（交给保护规则）；否则 `control.restore(snapshot)`。水泵也做这一步，把插座块（含模式）写回。
8. **收尾**：交还 TEST 写入权；还原成功则记录状态改 `done`，失败则改 `restore_failed` 并发告警（5.5）；结束让路。下一次 tick 空闲写入权重新授予，`_applied` 清空，执行器按空闲电平重新对齐（如有配置）。

第 3–8 步包在 `try/finally` 里，任何一步失败都执行收尾。整个流程在 `asyncio.shield` 下运行，HTTP 请求断开不取消测试。

### 5.5 未了结的测试 [设计方]

测试记录状态为 `running`（服务重启时遗留）或 `restore_failed` 时，这台设备：

- 拒绝新的测试（`device_test_unsettled`）和阶段启动（`device_test_unsettled`）。
- 温室页显示"未还原"，给持有者两个按钮：
  - **重试还原**：按 5.4 第 3、4、7、8 步再走一遍（新的 TEST 写入权）。
  - **我已在现场处理**：要求填一句备注，记录状态改 `settled_onsite`，记入锁定日志。之后不再阻挡。
- 管理员强制释放温室时，未了结的测试一并改为 `settled_onsite`（备注沿用强制释放的备注）。

**服务重启**：工作流启动后，若有 `running` 的记录，待控制服务 `ready` 且设备可读时自动重试还原一次；成功则 `done`，失败则 `restore_failed` 并告警。水泵的 OFF 由现有的未结泵动作互锁保证，还原只负责写回插座块。

告警以该温室为范围，持有者与管理员都能看到（需在 `sees_alert` 里为该范围放行持有者）。

### 5.6 与阶段启动互斥

测试进行中或未了结时，同一设备上的阶段启动被拒绝（5.5）。有当前阶段时，测试在 5.4 第 1 步被拒绝。

### 5.7 接口

- `POST /wb/greenhouses/{greenhouse_id}/test/{channel}`，`channel ∈ {light, exhaust, fan, pump}`，`Operator` 身份（不要求重新认证）。测试结束后返回：
  ```json
  {"test_id": "...", "channel": "light", "test_level": 100, "seconds": 10,
   "result": "restored" | "restore_failed" | "protected", "actions": ["<request_id>", "..."]}
  ```
- `POST /wb/greenhouses/{greenhouse_id}/tests/{test_id}/retry`：重试还原。
- `POST /wb/greenhouses/{greenhouse_id}/tests/{test_id}/settle`，body `{"note": "..."}`：现场处理。
- `GET /wb/greenhouses` 每行新增 `testable: bool`（"mine"、本机驱动、空闲、无未了结测试）、`test_running: str | null`、`test_unsettled: {test_id, channel, state} | null`。
- `GET /wb/greenhouses/{greenhouse_id}/tests`：该温室最近 20 次测试（时间、操作者、通道、结果），持有者与管理员可见。

新增拒绝码（登记在 `denial_codes.py`，中英文文案）：`device_test_not_holder`、`device_test_not_idle`、`device_test_not_local`、`device_test_running`、`device_test_unsettled`、`device_test_protected`。其余沿用现有的（`controls_disabled`、`irrigation_too_soon` 等）。

### 5.8 网页

温室页（`web/workbench/pages/greenhouses.js`）上，持有者自己的、本机驱动的行下方展开"设备测试"区：

```
温室 1 · 我的 · 本机驱动
┌ 设备测试 ─────────────────────────────────────────────┐
│ 点一下，设备短暂运行后自动恢复原来的设置。请在现场观察。   │
│ [测试灯光 10 秒] [测试排风 10 秒] [测试风扇 10 秒]         │
│ [测试水泵 3 秒]  ⚠ 会出水，请准备接水                     │
│ 灯光：已开到 100，倒计时 7 秒…                            │
│ 排风：已恢复原设置，控制器已确认 ✓                         │
│                                                          │
│ 最近测试                                                  │
│ 11-27 10:02  dev  风扇  已恢复                             │
│ 11-27 10:01  dev  排风  已恢复                             │
└──────────────────────────────────────────────────────┘
```

- 有未了结测试时，按钮区换成"未还原"提示与"重试还原"、"我已在现场处理"两个按钮。
- 测试进行中，同一温室所有测试按钮禁用；倒计时网页本地显示，结果以接口返回为准。
- 水泵按钮先弹确认框（`confirmedButton`）。
- 有当前阶段时，该区只显示一行"实验进行中，测试不可用"。
- 文案进 `i18n` 中英文。

### 5.9 记录

- 每个写入照常进动作台账（right kind = `test`）。
- `greenhouse_lock_events` 追加 `action = "test"` / `"test_settled"`，`note` 写通道与结果，管理员在锁定日志里看到。
- 测试记录表本身即 G3 的数据源。

## 6. 测试

- 控制层：TEST 写入权的授予、范围、操作者绑定；`_may_irrigate` 放行 TEST；保护写入权仍可覆盖；`snapshot`/`restore` 写回非手动模式块后回读确认，摘要不符时拒绝。
- 工作流：六种拒绝；正常流程；还原失败 → `restore_failed`、告警、阻挡阶段启动；重试与现场处理；强制释放了结；测试期间空闲不写、结束后重新对齐；中途进入保护 → 跳过还原；重启后自动重试。
- 接口与网页：路由返回结构、温室行新字段、测试历史可见性；`node --check` 通过；用模拟 AC5（`sim/`）跑一次端到端，覆盖"原本为非手动模式"的一路。

## 7. 留给实现者

- `DeviceTests` 与 `IdleCare`、`GreenhouseLocks`、执行器保护状态的接线位置（`runtime*.py` 现有组装处）。
- 测试记录表结构与迁移步骤（参照 `greenhouse_locks` 的 `STEPS`）。
- 告警种类名与文案。
- 文档：`docs/wiki` 中英文各补一节"实验前测试设备"。
