# Auto Research Agent System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按 v1.5 架构文档，在 GrowBridge 里搭出五个 Agent（编排、计划、执行、观察与通知、研究）和支撑它们的工作流、控制、归档、计算服务，并用模拟 AC5 把附录 C 能在本机验证的条目测完。

**Architecture:** 第一版是一个进程（`growbridge serve`，`auto_research = true` 时启用），按职责分包、按所有者分库。各服务只依赖 `src/growbridge/ports.py` 里的协议和 `src/growbridge/archive/models.py` 里的共享模型，不互相导入实现类；`runtime.py` 负责装配。工作流服务是阶段状态的唯一所有者，控制服务是 BLE 写入的唯一关口，模型角色没有任何设备或阶段控制工具。

**Tech Stack:** Python ≥3.11、标准库 `sqlite3`/`zoneinfo`/`statistics`、Pydantic 2、FastAPI、pytest + pytest-asyncio + pytest-cov、ruff；可选依赖 `anthropic`（模型）、`pyfirecrest`（CSC）。

**Spec:** `docs/diagri-agent-architecture.zh-CN.md`（下文 § 和“附录”都指它）。

## Global Constraints

- 合同文件已写好并通过测试，**只读不改**：`src/growbridge/ports.py`、`archive/models.py`、`archive/db.py`、`archive/ids.py`、`archive/clock.py`、`workflow/states.py`、`sim/device.py`、`sim/clock.py`、`sim/fixtures.py`、`config.py`、`pyproject.toml`、`tests/conftest.py`。需要改合同时，在汇报里说明，不要自己改。
- 每个任务只改自己“Files”里列出的文件；测试放在自己的 `tests/<area>/`，文件名 `test_<area>_*.py`，目录内不建 `__init__.py`，可以有自己的 `conftest.py`。
- 先写失败的测试并运行确认失败，再写实现（TDD）。测试用 `FakeClock`、`SimulatedTransport`、`make_run_sheet()`、`tmp_path`；**不得**访问网络、蓝牙或真实凭据；不得用真实时间等待超过 1 秒。
- 模型一律不可变（`Model` 基类：frozen、`extra="forbid"`）；修改用 `model_copy(update=...)`。函数 < 50 行，文件 < 800 行，嵌套 ≤ 4 层。
- 数据库：每个服务用 `Database.migrate("<namespace>", STEPS)` 登记自己的表；所有 SQL 用参数绑定；**不要在 `db.transaction()` 里 `await`**；原始记录只追加，更正写成带 `corrects`/`supersedes` 的新记录。
- 时间：存 UTC epoch 秒；持续时间和最小切换间隔用 `clock.monotonic()`；日历触发用 `clock.now()`，`clock.synced` 为假时不触发。
- 拒绝一律抛 `ports.Denied(code, message)`，`code` 取自 `Denied` 文档串里的列表（需要新 code 时在汇报里列出）。
- 凭据只从环境变量读取，不写进源码、配置或测试；模型输出里的身份/权限字段只当输入数据。
- 兼容：`auto_research = false`（默认）时守护进程行为、8 个 MCP 工具、31 个旧测试都不变。
- 风格：`ruff check` 与 `ruff format --check` 通过（行宽 100，规则 E,F,I,B,UP）；只用 Python 3.11 语法。
- 读文件分小块读（每次 30–60 行，先 `grep -n` 定位）。
- 不提交（用户未要求）。每个任务最后一步是跑本任务测试 + ruff，而不是 commit。
- 门禁钩子：新建文件的第一次 Write 会被 “Fact-Forcing Gate” 拒绝，按提示陈述四项事实（调用方、无重复文件、数据格式、用户指令原文“继续未完成的任务”）后重试即可。

## Review Focus

1. NTP 把系统时钟拨动时，规则的“持续 N 秒”不能被一次跳变凑满或清零 → Task 3 `test_rules_duration_ignores_wall_clock_jump`。
2. 同一 `request_id` 重试：参数相同返回原回执且不重发，参数不同拒绝 → Task 2 `test_control_retry_returns_original_receipt`、`test_control_reused_request_id_with_other_arguments_is_denied`。
3. 运行单把动作写到设备自管通道或水泵 → Task 3 `test_planning_action_on_device_managed_channel_blocks`、`test_planning_pump_start_blocks`；Task 2 `test_control_write_outside_scope_is_denied`。
4. 数据出现缺口后，旧读数不能继续触发反馈、保护或报警 → Task 3 `test_rules_gap_breaks_continuity`；Task 7 `test_observer_stale_data_marks_gap_and_stops_threshold_alerts`。
5. 进程在“意图已落盘、回执未落盘”之间崩溃：重启后该动作是“结果未知”、普通写入被挡、不重放 → Task 2 `test_control_restart_marks_in_flight_action_unknown_and_blocks_writes`。

---

## 文件与分工

| Task | 包 / 文件 | 测试目录 | 波次 |
|---|---|---|---|
| 1 基础层（已完成） | `archive/{db,ids,clock,models}.py`、`workflow/states.py`、`ports.py`、`sim/{device,clock,fixtures}.py` | `tests/foundation/` | 0 |
| 2 控制服务 | `control/{__init__,service,rights,ledger,device}.py`；改 `service.py` | `tests/control/` | 1 |
| 3 规则与计划校验 | `executor/{__init__,rules}.py`、`planning/{__init__,validate,design}.py` | `tests/rules/`、`tests/planning/` | 1 |
| 4 工作流（阶段与轮次） | `workflow/{service,store,permissions}.py`、`sim/control.py` | `tests/workflow/` | 1 |
| 5 研究任务板与预算 | `workflow/tasks.py`、`agents/{__init__,budget}.py` | `tests/tasks/` | 1 |
| 6 项目档案 | `archive/{store,snapshot,export,backup,storage,source}.py`；改 `store.py` | `tests/archive/` | 1 |
| 7 研究分析 | `research/{__init__,stats,analysis,holdout,sandbox,report}.py` | `tests/research/` | 1 |
| 8 观察与通知 | `observer/{__init__,metrics,report,alerts,outbox,channels,health,service}.py` | `tests/observer/` | 1 |
| 9 CSC 计算 | `compute/{__init__,service,backend,firecrest}.py`、`sim/compute.py` | `tests/compute/` | 1 |
| 10 模型角色 | `agents/{llm,loop,tools,roles}.py`、`sim/llm.py` | `tests/agents/` | 1 |
| 11 传输层停止确认 | 改 `transport.py`、`native/BLEHelper.swift` | `tests/transport/` | 1 |
| 12 执行引擎 | `executor/engine.py` | `tests/executor/` | 2 |
| 13 工作台与入口 | `workbench/{__init__,auth,api}.py`；改 `api.py`、`mcp_server.py` | `tests/workbench/` | 2 |
| 14 装配与端到端 | `runtime.py`；改 `cli.py` | `tests/e2e/` | 3 |

每个任务的步骤相同，不再逐个重复：

- [ ] 读本任务引用的 § 小节和合同文件里用到的类型（分小块读）
- [ ] 为“Tests”里每一条写失败的测试，运行确认因缺实现而失败
- [ ] 按“Produces”的签名实现到通过
- [ ] `.venv/bin/python -m pytest tests/<area> -q` 全过；`.venv/bin/ruff check <本任务文件>` 与 `ruff format --check` 通过
- [ ] 汇报：做了什么、未覆盖什么、对合同的修改请求

---

### Task 2: 控制服务（§7.1–7.3、§7.5、§7.6、§7.8、§7.9）

**Files:** Create `src/growbridge/control/{__init__,service,rights,ledger,device}.py`；Modify `src/growbridge/service.py`（只做两件事：`Bridge.__init__` 增加可选 `clock`，样本时间戳与过期判断改用它，默认 `SystemClock()`；把 8 s 请求超时、0.5 s 回读间隔提成实例属性以便测试缩短）；Test `tests/control/`。

**Interfaces**
- Consumes: `Bridge.request/configuration/health`、`bridge.transport.halt()`、`Database`、`Clock`、`ports.*`、`RecordSink`。
- Produces: `class ControlService`，实现 `ports.ControlPort` 的全部方法，另加：
  - `__init__(self, bridge: Bridge, db: Database, clock: Clock, host_id: str, sink: RecordSink | None = None)`
  - `register_host(self) -> None`（把本机登记为该 AC5 的写入主机；已登记别的主机时 `Denied("host_unregistered")`）、`host_registered(self) -> bool`
  - `async startup(self) -> None`：先挡住普通写入 → 把上个进程留下的全部写入权落盘为“不得写入” → `MAYBE_SENT` 改 `UNKNOWN`、`PENDING` 改 `VOID` → `await bridge.transport.halt()` 记下结果 → 有未结清的水泵动作则进入联锁。
- 通道映射（`control/device.py`）：LIGHT→模块 `light`，EXHAUST→模块 `blower`，FAN→模块 `fan`，PUMP→插座 `O{settings.pump_outlet}`。写入强制 `modeType=0`；回读同时核对档位（`getDevSta`）和模式（`getConfigFile`）。
- `capabilities().version` = 插座映射、档位范围、传感器名、协议版本的 `content_digest` 前 16 位。
- 关口：一把 `asyncio.Lock`，`handover` 与每次下发都经过它；入队和下发各查一次（主机登记、恢复编号、写入权未撤销、范围、有效期）。
- `grant`：同一设备同时只有一个 STAGE 权（第二个 `Denied("right_held")`）；有 STAGE 权时不发 MANUAL 权；CARE/PROTECTION 权必须带 `scope.levels`，只能写列出的通道和值。
- `submit` 的结果：发送前落盘意图（PENDING），发送前改 MAYBE_SENT；回读一致 → CONFIRMED；设备拒绝或回读不一致 → FAILED；无回执或发送中断连 → UNKNOWN。`submit` 永远不开泵（`Denied("pump_on_forbidden")`）；只有 `irrigate` 能开泵，且要求 MANUAL 权、`settings.max_pump_seconds` 与冷却时间。
- 联锁（§7.8）：关泵未确认 → 普通写入（STAGE/MANUAL）`Denied("interlock")`；PROTECTION 权照常；CARE 权在非水泵通道上、且 `transport_stopped()` 为真时照常。`pump_off()` 是专用路径，暂停时也能用。
- 安全配置：`approve_safety` 落盘并发 PROTECTION 权（旧的撤销）；`safety_conflicts(run_sheet)` 列出作用在设备自管通道上的保护规则。
- `bump_recovery`：编号 +1，撤销全部写入权，`safety()` 需要重新批准后才有 PROTECTION 权。

**Tests（除 Review Focus 2、3、5 外）**
- 未登记主机不能发权、不能写；登记后可以。
- 两个阶段争写入权只有一个得到；`handover` 后旧编号写入被拒、它排队未发的动作变 VOID。
- 写入后回读档位和 `modeType=0`；设备确认但状态没变 → FAILED；`lose_replies` → UNKNOWN 且 `unsettled_actions()` 非空。
- 联锁期间：STAGE 写入被拒、PROTECTION 能把灯调暗、CARE 能写排风；`halt_confirmed=False` 时 CARE 也被拒。
- `irrigate`：关泵失败 → 联锁；`pump_off()` 成功后解除。执行路径上 `submit(PUMP, 1)` 被拒。
- `differences`：面板把灯改成定时模式或改了档位都能查出。
- 恢复编号递增后旧写入权全部失效。

### Task 3: 规则与计划校验（§6、§7.4、§9.2 的设计部分）

**Files:** Create `src/growbridge/executor/{__init__,rules}.py`、`src/growbridge/planning/{__init__,validate,design}.py`；Test `tests/rules/`、`tests/planning/`。全部是纯函数，不做 I/O。

**Produces（`executor/rules.py`）**
- `class RuleState(Model)`: `active: bool = False`、`since: float | None`、`last_switch: float | None`、`last_seen: float | None`（都是单调时钟）。
- `class Decision(Model)`: `rule_id`、`action: RuleAction | None`、`state: RuleState`、`pause: bool = False`、`reason: str`。
- `valid_reading(reading: Reading | None, unit: str, validity_seconds: float, now_mono: float) -> bool`（非空、有值、`quality == "ok"`、单位一致、未过期）。
- `evaluate_feedback(rule: FeedbackRule, reading: Reading | None, state: RuleState, now_mono: float, max_gap_seconds: float) -> Decision`：触发条件连续成立满 `duration_seconds` 且距上次切换满 `min_switch_seconds` → `action`；已激活且恢复条件连续成立满同样时长 → `release`；读数无效：`hold` 保持并清零计时，`pause` 置 `pause=True`；相邻有效读数间隔超过 `max_gap_seconds` 清零计时。
- `evaluate_protection(rule: ProtectionRule, reading, state, now_mono, max_gap_seconds) -> Decision`（无效读数不动作）。
- `resolve(decisions: Sequence[tuple[FeedbackRule, Decision]]) -> dict[Channel, RuleAction]`（同一通道取 `priority` 最高）。

**Produces（`planning/validate.py`）**
- `validate_run_sheet(run_sheet: RunSheet, capabilities: Capabilities, safety: SafetyConfig | None = None) -> tuple[Finding, ...]`。阻断类 code：`unknown_sensor`、`unit_mismatch`、`device_owned_write`、`pump_action`（任何动作把水泵打开）、`humidity_exhaust_only`、`rule_conflict`（同通道同优先级不同档位）、`safety_conflict`、`sampling`、`duration`、`wait`；提示类：`missing_tolerance`、`manual_task`。
- `check_evidence(run_sheet: RunSheet, cards: Mapping[str, EvidenceCard]) -> tuple[Finding, ...]`：`no_evidence`、`unverified_source`（需逐项确认）、`uncalibrated`（“未校准”），都不阻断。

**Produces（`planning/design.py`）**
- `randomize_series(treatment_ids: Sequence[str], blocks: int, seed: int, unit: str = "tent-1") -> tuple[Allocation, ...]`（单帐篷串行：每个区组含每个处理一次，组内顺序由种子决定，同种子结果相同）。
- `randomize_tents(treatment_ids: Sequence[str], units: Sequence[str], rounds: int, seed: int) -> tuple[Allocation, ...]`（多帐篷：每轮内随机分配，轮次作区组）。
- `make_up_allocation(protocol: ResearchProtocol, failed_round: int) -> Allocation`（同区组、同处理、新轮次号，其余顺序不变）。
- `check_experimental_design(protocol: ResearchProtocol) -> tuple[Finding, ...]`：`no_replication`、`unbalanced_block`、`confounded_with_time`、`unknown_treatment`、`missing_control`、`seed_mismatch`。
- `estimate_sample_size(effect: float, sd: float, alpha: float = 0.05, power: float = 0.8, design: Literal["paired_block", "two_group"] = "paired_block") -> int`（正态近似，向上取整，至少 2）。

**Tests（除 Review Focus 1、3、4 外）**：缺字段读数按 `hold`/`pause` 处理；最小切换间隔；同通道冲突被查出；湿度反馈改灯被阻断；`make_run_sheet()` 无阻断项；`make_protocol()` 的处理与区组可估计（`check_experimental_design` 无阻断）；全部轮次同一处理 → `no_replication`；先全做 A 再全做 B → `confounded_with_time`。

### Task 4: 工作流——阶段与轮次（§5.2、§7.7、附录 B）

**Files:** Create `src/growbridge/workflow/{service,store,permissions}.py`、`src/growbridge/sim/control.py`（`FakeControl`：内存实现的 `ControlPort`，供本任务测试用）；Test `tests/workflow/`。

**Produces**
- `permissions.REAUTH_SECONDS = 300`；`require_operator(actor: Actor, now: float, recent: bool = False) -> None`（模型身份 `Denied("model_role")`，其余非操作员 `Denied("not_operator")`，要求近期再认证而没有 `Denied("reauth_required")`）。
- `class WorkflowService`（实现 `ports.StagePort`）`__init__(self, db: Database, clock: Clock, control: ControlPort, validate: Callable[[RunSheet], Sequence[Finding]] | None = None)`：
  - 设计：`create_project(name, actor) -> str`、`save_protocol(protocol, actor) -> ResearchProtocol`（同 id 同版本内容不同 → `Denied("state")`，必须升版本）、`create_round(project_id, protocol_id, actor) -> str`、`submit_run_sheet(round_id, run_sheet, actor) -> tuple[Finding, ...]`（模型身份可以提交草稿；有阻断项则不进入待审）。
  - 审批：`approve(stage_id, actor) -> Approval`（操作员 + 近期再认证；绑定运行单版本与摘要、项目、实验、阶段、设备、`capabilities().version`、恢复编号）、`revoke_approval(stage_id, actor) -> None`。
  - 控制（都 `async`，返回 `StageRuntime`）：`start_stage(stage_id, actor)`（操作员，或 `Actor(kind="workflow")` 且有有效批准；启动前复查摘要、能力版本、恢复编号、`safety_conflicts`）、`pause_stage(stage_id, actor, reason)`（操作员或观察者）、`resume_stage`、`stop_stage`、`takeover`、`handback(stage_id, actor, accept_as_intervention: bool) -> tuple[StageRuntime, tuple[Difference, ...]]`、`switch_run_sheet(stage_id, run_sheet, actor)`、`record_onsite_check(stage_id, actor, note)`、`try_exit_recovery(stage_id)`、`on_restart() -> None`、`on_recovery_bump() -> None`。
  - 轮次：`choose_after_stop(round_id, choice: Literal["redo", "next", "verify", "abort"], actor) -> RoundState`、`mark_snapshot_frozen(round_id, snapshot_id, event_id) -> RoundState`、`mark_report_published(round_id, artifact_id, event_id) -> RoundState`、`abort_round(round_id, actor) -> RoundState`。
  - 查询：`stage(stage_id) -> StageRuntime`、`round_state(round_id) -> RoundState`、`approvals(stage_id) -> tuple[Approval, ...]`（旧确认保留供审计）、`interventions(experiment_id) -> tuple[dict, ...]`、`history(stage_id) -> tuple[dict, ...]`。
  - `StagePort`：`active_stage()`、`async report(event)`（同 `event_id` 只推进一次；过期事件丢弃）。
- 写入权规则：进入 RUNNING 发新的 STAGE 权；离开 RUNNING（暂停、接管、停止、结束、待核对）先 `await control.handover(...)`。运行单生效时发 CARE 权，接管时撤销、交还后重发。保存状态和登记后续动作在同一事务里。

**Tests**：附录 B 阶段表的每一行各一条（含 `END_CONDITION_MET` → `end_pending`、`END_ACTIONS` 确认/未确认、`MAX_WAIT_EXPIRED` 按 `on_expiry` 分两种、执行中切换运行单新版本）；轮次表每一行；旧批准（摘要或恢复编号变了）被拒；重复启动只生效一次；模型身份调用 `start_stage`/`approve` 被拒；接管交还时列出差异，接受为干预则记入 `interventions`；退出待核对的两种方式和四种去向（恢复编号变了一律回待审）。

### Task 5: 研究任务板与预算（§5、§5.2、附录 B 研究任务表）

**Files:** Create `src/growbridge/workflow/tasks.py`、`src/growbridge/agents/__init__.py`（空）、`src/growbridge/agents/budget.py`；Test `tests/tasks/`。

**Produces**
- `class TaskBoard`：`__init__(self, db: Database, clock: Clock)`；`create(task: ResearchTask) -> ResearchTask`（同 `trigger_event_id` 只建一次；委派深度超过父任务 `budget.max_delegation_depth` → `Denied("budget")`）；`transition(task_id, to: TaskState, event_id: str, reason: str = "") -> ResearchTask`（只允许附录 B 表里的转移，否则 `Denied("state")`；同 `event_id` 只处理一次）；`get(task_id)`；`list(project_id, state: TaskState | None = None)`；`expire(now: float) -> tuple[ResearchTask, ...]`（过了 `deadline` 的进行中任务转待处理）；`record_revision(task_id) -> int`（超过 `max_revisions` → `Denied("budget")`）。
- `class CallBudget`：`__init__(self, db, clock)`；`set(project_id, budget: Budget) -> None`；`reserve(project_id, calls: int = 1) -> None`（原子检查并扣减，超限 `Denied("budget")`）；`charge(project_id, cost: float) -> None`；`remaining(project_id) -> tuple[int, float]`。

**Tests**：研究任务表每一行；非法转移被拒；两个并发 `reserve` 不会超卖；待处理 → 用户放宽后回进行中或带原因结束；待对账的两个出口；待复核的两个出口。

### Task 6: 项目档案（§11.1–11.5）

**Files:** Create `src/growbridge/archive/{store,snapshot,export,backup,storage,source}.py`；Modify `src/growbridge/store.py`（`prune` 只删已归档且可删的缓存）；Test `tests/archive/`。

**Produces**
- `class Archive`（实现 `RecordSink`）`__init__(self, db: Database, root: Path, clock: Clock)`：`append_sample`、`append_action`（每次状态变化追加一行）、`ingest(source: SampleSource, device_id: str, context: Callable[[], tuple[str | None, str | None]], limit: int = 500) -> int`（记录 id = `f"{device_id}:{cursor}"`，进度与记录同事务落盘，按 id 去重）、`cursor(device_id) -> int`、`samples(experiment_id, start=None, end=None)`、`actions(experiment_id=None)`、`add_measurement`/`measurements(experiment_id, include_corrected=False)`、`add_evidence`/`evidence(ids=None)`、`add_artifact`/`artifact(id)`/`artifacts(task_id)`、`record_intervention(experiment_id, stage_id, kind, detail: dict, operator: str | None) -> str`/`interventions(experiment_id)`、`mark_dependents_invalid(record_id) -> tuple[str, ...]`（“依赖失效”）、`last_write_at() -> float | None`。
- `snapshot.freeze(archive, experiment_id, clock, start: float, end: float, expected_interval: float, max_gap: float, min_coverage: float = 0.9) -> Snapshot`（时钟未同步 `Denied("clock_unsynced")`；写 `root/snapshots/<id>/` 下的 jsonl 和 `manifest.json`；覆盖率按有效时长；不完整要标注；再次冻结产生新版本）、`snapshot.verify(archive, snapshot_id) -> bool`、`snapshot.load(archive, snapshot_id) -> Snapshot`。
- `export.export_miappe(archive, snapshot: Snapshot, protocol: ResearchProtocol, out: Path, licence: str, identifier: str) -> Path`。
- `backup.backup(db: Database, target: Path, clock: Clock) -> float`（SQLite 在线备份）、`backup.last_backup(db) -> float | None`。
- `class StorageGuard(root: Path, low_bytes: int, critical_bytes: int, usage=shutil.disk_usage)`：`level() -> Literal["ok", "low", "critical"]`；`allows(kind) -> bool`，`low` 时挡 `research_cache`/`bulk_transfer`/`unplanned_image`，`critical` 时再挡 `experiment_action`；`care`/`protection`/`sample` 永远放行。
- `source.LegacySampleSource(store: Store, clock: Clock)`（实现 `SampleSource`，游标是 `samples` 的 rowid）、`source.protect_history(store: Store, archived_cursor: Callable[[], int], clock: Clock) -> None`（之后 `store.prune` 只删 rowid ≤ 已归档游标的行，时钟未同步时不删）。

**Tests**：归档中途重启后续传不丢不重；超过 30 天的历史在未归档前不被清理、归档后可清；时钟未同步时暂停清理与冻结；快照校验和被改后 `verify` 为假；覆盖率不足标为不完整；更正写成新记录、原记录不变；磁盘压力两级降级；备份可恢复出相同记录。

### Task 7: 研究分析（§9.1–9.3）

**Files:** Create `src/growbridge/research/{__init__,stats,analysis,holdout,sandbox,report}.py`；Test `tests/research/`。不导入 Task 6 的实现类，用到档案处定义小协议。

**Produces**
- `stats.unit_means(measurements: Sequence[ManualMeasurement], allocations: Sequence[Allocation], metric: str, round_of: Mapping[str, int]) -> dict[tuple[int, str], float]`（键是（区组, 处理）；同一帐篷多株多天先平均成一个独立单元值）。
- `stats.paired_block_estimate(values: Mapping[tuple[int, str], float], control: str, treatment: str) -> BlockEstimate`（`effect`、`blocks`、精确符号翻转置换检验的 `p_value`、`estimable`、`note`；区组少于 2 时 `estimable=False`）。
- `analysis.AnalysisFacts(Model)`：`independent_replicates`、`confounded_with_time`、`missing_fraction`、`changed_after_outcomes`、`deviation_fraction`、`planned_sample_size`、`achieved_sample_size`、`early_terminated`。
- `analysis.classify(protocol: ResearchProtocol, facts: AnalysisFacts) -> AnalysisDecision`（`label: Label`、`reasons`；§9.2 五条降级规则）。
- `analysis.conclusion(estimate: BlockEstimate, facts: AnalysisFacts, alpha: float = 0.05) -> Literal["supported", "not_supported", "uncertain"]`（样本量未达计划时只能是 `uncertain`，不写“无效应”）。
- `class ConfirmatoryRunner(db, clock, sandbox: Sandbox, work_root: Path)`：`freeze_analysis(protocol, script: Path) -> str`（按系列登记脚本哈希）；`run(protocol, snapshot: Snapshot, snapshot_dir: Path, script: Path) -> AnalysisRun`（哈希不符 `Denied("script_hash")`；快照不完整 `Denied("snapshot_incomplete")`；同一协议 + 快照第二次运行 `Denied("already_run")`）。
- `class HoldoutRegistry(db, clock)`：`register(project_id, holdout_id, batch_ids, outcome_fields, development_batches: int) -> None`（开发批次少于 2 `Denied("batches")`）；`filter_development(holdout_id, rows: Sequence[dict]) -> list[dict]`（去掉留出批次的结局标签）；`register_model(holdout_id, model_sha, features_sha, preprocessing_sha) -> None`；`evaluate(holdout_id, reader: str) -> Label`（未登记模型 `Denied("model_unregistered")`；第一次 `confirmatory`，之后 `exploratory`；每次读取留日志）；`reads(holdout_id)`；`late_features(feature_times: Mapping[str, float], prediction_time: float) -> tuple[str, ...]`。
- `sandbox.Sandbox`（协议）`run(script: Path, snapshot_dir: Path, out_dir: Path, timeout: float) -> SandboxResult`；`SeatbeltSandbox`（macOS `sandbox-exec`：禁网络、快照只读、只能写 `out_dir`、环境变量清空）；`RefusingSandbox`（无隔离后端的平台：`Denied("sandbox_unavailable")`）；`make_sandbox() -> Sandbox`。
- `report.publish_research_report(sink: ArtifactSink, task_id, snapshot, decision, estimate, evidence_chain, limitations, next_round, unresolved: Sequence[str], out_dir: Path) -> tuple[Artifact, TaskState]`（确认性结论有未解问题 → `NEEDS_REVIEW`，否则 `DONE`）。

**Tests**：同帐篷多株多天不增加独立重复数；`make_protocol()` 的数据可估计出处理效应；脚本哈希不符拒绝；同一快照第二次确认性运行被拒；五条降级规则各一条；提前终止 → `uncertain`；留出集：通用读取看不到结局标签、预测时点之后的特征被列出、第二次评估标为探索性；沙箱里访问网络失败、写快照目录失败、读不到环境变量里的假凭据（仅 macOS，其它平台 `skip`）。

### Task 8: 观察与通知（§8）

**Files:** Create `src/growbridge/observer/{__init__,metrics,report,alerts,outbox,channels,health,service}.py`；Test `tests/observer/`。

**Produces**
- `metrics.compute_daily_metrics(samples: Sequence[SampleRecord], day: date, timezone: str, max_gap_seconds: float, ranges: Mapping[str, tuple[float, float]], ppfd_per_percent: float | None = None) -> DailyMetrics`（时间加权均值、DLI、超限时长、覆盖率、缺口列表；主动查询不改变权重；缺口处截断；时钟未同步或无效样本不计）。
- `report.render_daily_report(metrics: DailyMetrics, context: ReportContext, narrative: str | None = None) -> str`（数值全部来自模板；没有模型也能出）；`report.report_due(now: float, report_time: str, timezone: str, last_date: str | None) -> str | None`；`class ReportStore(db)`：`save(project_id, report_date, text) -> bool`（按项目 + 日期幂等）、`get`。
- `class AlertBook(db, clock)`：`raise_alert(kind, key, severity, message) -> Alert`（同一事件合并计数）、`resolve(kind, key)`、`open() -> tuple[Alert, ...]`、`mark_read(event_id, actor: Actor)`（仅操作员）。
- `alerts.evaluate_alert_rules(rules: Sequence[AlertRule], readings: Sequence[Reading], states: Mapping[str, RuleState], now_mono: float) -> AlertEvaluation`（数据无效时给出 `data_gap`，并停止用旧读数判断阈值）。
- `class Outbox(db, clock, base_seconds: float, cap_seconds: float)`：`queue_notification(event_id, channel, text) -> bool`（按 `event_id` + 渠道幂等）、`async deliver(channels: Mapping[str, NotifyChannel]) -> int`（记录 `accepted`/`unknown`/`failed`，指数退避到上限）、`oldest_undelivered() -> float | None`。
- `channels.NotifyChannel`（协议）`async send(text) -> Literal["accepted", "unknown", "failed"]`；`TelegramChannel`（令牌取自环境变量 `GROWBRIDGE_TELEGRAM_TOKEN`，只发给登记的 chat，不读入站消息）、`EmailChannel`、`HeartbeatChannel`（`ping()`、`fail()`）；HTTP 客户端可注入。
- `class RunHealthCheck(probes: Mapping[str, Callable[[], float | None]], limits: Mapping[str, float], clock)`：`check() -> RunHealth`（探针名：`growbridge_response`、`executor_evaluation`、`capture`、`archive_write`、`oldest_undelivered_alert`、`offsite_backup`）。
- `class ExternalMonitor(host: HeartbeatChannel, run: HeartbeatChannel, clock)`：`async beat(health: RunHealth, maintenance_until: float | None = None) -> None`（主机心跳照发；运行健康失败时发失败信号并停发它的心跳；维护期内不发失败信号，维护宽限到期仍异常要报警）。
- `class Observer(stages: StagePort, control_readings: Callable[[], Sequence[Reading]], book: AlertBook, outbox: Outbox, rules: Sequence[AlertRule], clock)`：`async tick() -> None`（规则带 `pause_stage` 时上报 `ALERT_PAUSE`）。

**Tests（除 Review Focus 4 外）**：时间加权均值不受加密查询影响；日报日期按项目时区；同一天日报只存一份；报警合并；通知按事件 ID 不重发、失败后退避重试、`unknown` 状态保留；主机在线但采集、投递或异地备份卡住 → 运行健康失败并发失败信号、停发心跳；维护期不发失败信号；邮件作第二渠道；Telegram 只发给登记的 chat。

### Task 9: CSC 计算（§9.4）

**Files:** Create `src/growbridge/compute/{__init__,service,backend,firecrest}.py`、`src/growbridge/sim/compute.py`（`FakeBackend`）；Test `tests/compute/`。

**Produces**
- `backend.JobTemplate(Model)`：`id`、`version`、`script`、`parameters: dict[str, ParamSpec]`、`max_cpu_hours`、`max_storage_gb`、`result_changing: tuple[str, ...]`。
- `backend.ComputeBackend`（协议）：`async submit(job_name, template, params, inputs) -> str`、`find_by_name(job_name) -> RemoteJob | None`、`status(job_id) -> RemoteJob`、`fetch(job_id, out_dir) -> dict[str, str]`、`cleanup(job_id)`、`cancel(job_id)`、`balance() -> float`（都 `async`）。
- `class ComputeService(db, clock, backend, templates: Sequence[JobTemplate], members: Mapping[str, str], service_cpu_cap: float, service_storage_cap: float)`：`set_task_budget(task_id, cpu_hours, storage_gb)`、`async refresh_balance()`、`async submit_compute_job(task_id, submitter, template_id, params, inputs) -> Attempt`、`async get_compute_job(attempt_id, submitter) -> Attempt`、`async reconcile(attempt_id) -> Attempt`、`async fetch_compute_artifacts(attempt_id, submitter, out_dir) -> dict[str, str]`、`async cancel(attempt_id, submitter)`、`async retry(attempt_id, adjustments: dict) -> tuple[Attempt, bool]`（第二项：是否产生新分析版本）。
- 规则：每个入口都查提交者 → CSC 成员映射（`Denied("member")`）；参数按模板校验；对任务预算、服务上限、最近记录的项目余额三个上限做原子“检查并预留”，计算与存储分开（`Denied("quota")`）；尝试 id 在提交前落盘并写进作业名 `gb-<attempt_id>`；回执丢失 → 状态 `reconcile` 且保留预留，重新提交前先按作业名对账；按实际用量结算；取回并校验产物后删除远端输入和中间文件。`Attempt.task_state` 映射到 `TaskState`。
- `firecrest.FirecrestBackend`：`pyfirecrest` 的薄适配，延迟导入，凭据取自环境变量；缺包或缺凭据时构造即报清楚的错。真实 Roihu 未验证。

**Tests**：成员权限；参数校验；并发预留不超卖（计算、存储各一条）；回执丢失后按作业名对账找回；对账无果释放预留；额度耗尽；取回后远端清理；校验和不符不清理；改动会影响科学结果的参数 → 新分析版本。

### Task 10: 模型角色（§4、§5、§11.6、§11.7）

**Files:** Create `src/growbridge/agents/{llm,loop,tools,roles}.py`、`src/growbridge/sim/llm.py`（`ScriptedClient`）；Test `tests/agents/`。（`agents/__init__.py`、`agents/budget.py` 属于 Task 5；本任务测试里用一个记账的假预算。）

**SDK 用法只能来自文档**：读 Claude Code 自带的 `claude-api` 技能里的 `python/claude-api/README.md` 和同目录 `tool-use.md`（分小块读），以及虚拟环境里已安装的 `anthropic` 2.7.0。要点：`anthropic.Anthropic()` 从环境取凭据；默认模型 `claude-opus-5-5`；不传 `temperature`/`top_p`/`top_k`；思考用 `{"type": "adaptive"}`，深度用 `output_config={"effort": ...}`；工具用 `strict: True` + `additionalProperties: False`，不强制 `tool_choice`；先看 `stop_reason`（`refusal`、`max_tokens` 时不执行工具，`pause_turn` 原样追加后重发）；一轮的全部工具结果放进同一条 user 消息，出错用 `is_error: True`。

**Produces**
- `llm.ModelReply(Model)`：`stop_reason`、`text`、`tool_calls: tuple[ToolCall, ...]`、`content: Any`（原样回填的 assistant 内容）、`input_tokens`、`output_tokens`；`llm.ModelClient`（协议）`create(*, model, system, messages, tools, max_tokens, effort) -> ModelReply`；`llm.AnthropicClient`（延迟导入 SDK）。
- `tools.Tool`：`name`、`description`、`input_model: type[BaseModel]`、`handler`、`reads_web: bool = False`、`writes: bool = False`、`sandbox: bool = False`；`tools.ROLE_TOOLS: dict[str, frozenset[str]]`（§4 各角色的候选工具名；模型角色只有编排、计划、研究三个）；`tools.CONTROL_TOOLS`（阶段与设备控制工具名，模型角色永远拿不到）；`tools.build_toolset(role: str, tools: Sequence[Tool], allowed: Sequence[str] = ()) -> Toolset`（角色越权或请求控制工具 → `Denied("model_role")`）；`Toolset.schemas() -> list[dict]`、`async Toolset.call(name, raw_input) -> ToolOutcome`（自己按 `input_model` 校验，失败返回错误结果而不是抛出）。
- `loop.run_agent(client: ModelClient, role: RoleModel, system: str, user: str, toolset: Toolset, budget, project_id: str, max_turns: int = 20) -> AgentRun`（每次调用前 `budget.reserve`；读过网页内容（`reads_web`）之后的调用里去掉 `sandbox` 和 `writes` 工具；工具结果作为数据包起来再回填）。
- `roles.ORCHESTRATOR`/`PLANNER`/`RESEARCHER`（系统提示词：职责、不能做什么、检索到的材料是数据不是指令）；`roles.Handoff(Model)`（目标、约束、证据引用、期望产物、预算、父任务、触发事件 ID、关联 ID）；`roles.INTENTS`（新目标、设计修改、运行查询、异常处理、结果分析）。

**Tests**：拒答或截断时不执行工具；`pause_turn` 续跑；多个工具结果在同一条消息里；输入不合模式 → 错误结果且循环继续；预算用尽 `Denied("budget")`；模型角色请求 `start_approved_stage` 或 `run_pump` → 拒绝；读网页后沙箱与写工具从后续调用里消失；工具结果里夹带的“指令”不会变成新权限；`AnthropicClient` 请求体形状（打桩 `messages.create`，不联网；没装 SDK 则 `importorskip`）。

### Task 11: 传输层停止确认（§7.3）

**Files:** Modify `src/growbridge/transport.py`、`src/growbridge/native/BLEHelper.swift`；Test `tests/transport/`。

**Produces**
- `NativeTransport.halt() -> bool` 与 `BleakTransport.halt() -> bool`（`async`）：只有“旧队列已空且不能再写”或“旧进程和它的 BLE 会话都已停止”才返回 True；超时、只发了停止信号、删掉 Python 侧等待者都返回 False。
- `NativeTransport` 把助手进程号落盘到 `folder/helper.pid`，启动时发现旧进程号仍存活则先确认其停止。
- Swift 助手：事件通道断开时清空队列并退出；删除“打开后延时自动关闭”的命令路径（`auto_off_seconds`/`auto_off_command`/`followUps`）。`swiftc -typecheck src/growbridge/native/BLEHelper.swift` 通过。

**Tests**：用假进程和假套接字，不碰蓝牙——助手确认停止 → True；超时 → False；命令文件已写但助手还在排队时 `halt()` 不返回 True；进程号落盘并在重启后被读到；旧测试不受影响。

### Task 12: 执行引擎（§7.2、§7.4、§7.5、§7.7、§7.8）

**Files:** Create `src/growbridge/executor/engine.py`；Test `tests/executor/`（用真实 `ControlService` + `SimulatedTransport` + `WorkflowService`）。

**Produces**
- `class ExecutorEngine`：`__init__(self, control: ControlPort, stages: StagePort, clock: Clock, allow: Callable[[str], bool] | None = None)`；`async tick(self) -> TickReport`；`heartbeat(self) -> float | None`。
- 一次 `tick` 的顺序：① 联锁中先 `pump_off()`；② 保护规则（连接着就评估，任何阶段状态）；③ 断连记账，重连后按 §7.7 四个条件判断是否影响执行，影响则上报 `DISCONNECT_AFFECTS`；④ RUNNING：外部改动检查、按 `run_sheet.expected_levels(now)` 对齐定时动作、反馈规则、结束条件；⑤ 非 RUNNING 且非 MANUAL：养护规则（时钟不可信时用最后可信时间 + 单调时钟推算）；⑥ PAUSED 超过 `max_wait_seconds` 上报 `MAX_WAIT_EXPIRED`；⑦ `end_pending` 时执行结束动作并上报 `END_ACTIONS`。
- `request_id` 由阶段、规则或动作 id、目标档位和时间槽确定，重复 `tick` 不重复写。引擎里没有任何开泵调用。

**Tests**：到点对齐灯光；错过定时后按当前时刻原计划对齐；设备自管通道从不写；湿度反馈只动排风；保护规则在暂停、接管、联锁时仍能关灯；时钟跳变时养护按单调时钟；断连期间有到期动作 → 暂停，没有则只记缺口继续；面板改动 → 上报并暂停；结果未知 → 上报；阶段结束后养护规则继续。

### Task 13: 工作台与入口（§5.2、§10）

**Files:** Create `src/growbridge/workbench/{__init__,auth,api}.py`；Modify `src/growbridge/api.py`（`auto_research` 时挂载工作台路由，并让旧写入端点对共享令牌及其换出的浏览器会话返回 403）、`src/growbridge/mcp_server.py`（`auto_research` 时只保留 3 个只读工具）；Test `tests/workbench/`。

**Produces**
- `class Operators(db, clock)`：`add(name, secret)`（`hashlib.scrypt`）、`login(name, secret, entry: Entry) -> str`、`reauthenticate(token, secret)`、`actor(token, recovery_number: int) -> Actor`（未知、过期或恢复编号变了 → `Denied("session")`）、`logout(token)`。通行密钥是部署项，这里用独立口令占位并在文档串里注明。
- `auth.entry_for(host: str, settings: Settings) -> Entry | None`（入口由服务器按到达地址判定）。
- `api.create_workbench(workflow, control, archive, operators, settings, role_tokens: Mapping[str, str]) -> APIRouter`，前缀 `/wb`：登录与再认证；阶段的批准/启动/暂停/续跑/停止/接管/交还；`POST /wb/manual/{channel}`；`POST /wb/irrigation`（只在 LAN 入口）；人工测量；安全配置批准；现场核对；`POST /wb/drafts/run-sheet`（模型角色令牌只能交草稿）；`GET /wb/receipts/{request_id}`；报警列表与标为已读。

**Tests**：共享令牌及其会话写入返回 403；模型令牌调用阶段端点 403、聊天里说“批准”不产生批准；批准/接管/续跑需要近期再认证；水泵只在 LAN 入口；恢复编号变化后旧会话失效；`auto_research` 关闭时路由不存在、MCP 仍是 8 个工具，开启时是 3 个；Origin 与可信主机检查覆盖两个入口地址。

### Task 14: 装配与端到端（§12、附录 C 端到端）

**Files:** Create `src/growbridge/runtime.py`；Modify `src/growbridge/cli.py`（`operator add`、`host register`、`simulate`）；Test `tests/e2e/`。

**Produces**：`build_runtime(settings, transport_factory=make_transport, clock=None, model_client=None, compute_backend=None, channels=None) -> Runtime`；`Runtime.start()/stop()/tick()`；未登记写入主机时不打开 BLE 连接。

**Tests**：一个开放问题走完一轮（“提高光照后，冠层增长是否加快？”）：目标 → 协议与运行单 → 批准 → 执行 → 接管与交还 → 阶段结束 → 冻结快照 → 分析 → 报告；模型不可用时已批准的阶段照常执行；进程重启后进入恢复待核对再续跑。
