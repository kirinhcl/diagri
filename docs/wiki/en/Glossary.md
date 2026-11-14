# Glossary

[简体中文](../zh-CN/Glossary.md)

This page is for every reader. It maps each term used in this wiki to the Chinese term in the [architecture document](../../diagri-agent-architecture.zh-CN.md) and to the identifier in the code.

Where to look up an identifier: data models are in [`archive/models.py`](../../../src/growbridge/archive/models.py), the contracts between services in [`ports.py`](../../../src/growbridge/ports.py), and state names in [`workflow/states.py`](../../../src/growbridge/workflow/states.py).

## The project

| Term | 中文 | In code | Meaning |
| --- | --- | --- | --- |
| DiAGRI | DiAGRI | sub-packages of `growbridge`, among them `agents/`, `workflow/`, `control/`, `executor/`, `observer/`, `archive/`, `research/` | The project: an AI agent platform for plant-growth research. It designs an experiment, runs the approved plan on growing hardware, records it, analyzes it and reports. |
| GrowBridge | GrowBridge | the package and command `growbridge`; `transport.py`, `service.py`, `store.py`, `api.py`, `mcp_server.py`, `web/` | DiAGRI's device bridge: the part that reads and controls a Spider Farmer AC5 over Bluetooth. It can run on its own. |
| DiAGRI mode | DiAGRI 模式 | `auto_research = true` | The daemon runs the whole platform. The bridge's own write routes and write tools are refused, and every device write passes the control service. |
| bridge-only mode | 仅桥接模式 | `auto_research = false`, the default | The daemon runs GrowBridge alone: the dashboard, the local HTTP API and the MCP tools. |

## Research workflow

| Term | 中文 | In code | Meaning |
| --- | --- | --- | --- |
| research round | 研究轮次 | `RoundState` | One complete pass from a research goal to a delivered and archived report. |
| series | 系列 | `ResearchProtocol.rounds`, `.blocks`, `.allocations` | The rounds a protocol needs when a design has to repeat across rounds, for example treatments run one after another in a single tent. |
| stage | 阶段 | `StageState`, `StageRuntime` | An execution segment defined by a run sheet, for example the seedling period or the treatment period. |
| growth period | 生长期 | none | The crop's own developmental phase. It is not a stage. |
| research protocol | 研究协议 | `ResearchProtocol` | Question and hypothesis, treatments and control, experimental unit, allocation, randomization seed, primary endpoint and analysis plan. Kept by version. |
| run sheet | 运行单 | `RunSheet` | The executable plan of one stage, and the object the operator approves. Any change creates a new version. |
| approval | 审批 | `Approval` | An operator's recorded decision on a run sheet or another request. |
| research task | 研究任务 | `ResearchTask`, `TaskState`, `TaskBoard` | A unit of work handed to a model role. It has its own state machine and call budget. |
| manual task | 人工作业 | `ManualTask` | Work a person does by hand as part of a run sheet, for example irrigation. |
| pause, stop, abort | 暂停、停止、中止 | `StageState.PAUSED`, `StageState.STOPPED`, `RoundState.ABORTED` | A paused stage can continue. Stop ends one stage. Abort ends the whole round. All three leave archive records. |

## Control and safety

| Term | 中文 | In code | Meaning |
| --- | --- | --- | --- |
| channel | 通道 | `Channel` | One controllable output of the AC5: `light`, `exhaust`, `fan`, `pump`. |
| channel ownership | 通道归属 | `Ownership` | Who controls a channel. Device-managed (`device`): the AC5 runs its own timer and DiAGRI only reads. Host-controlled (`host`): the executor writes it. |
| write right and its number | 写入权与编号 | `WriteRight`, `RightKind`, `right_number` | Permission to write to the device, registered by the control service. Every grant gets a new number, and a revoked number can never write again. |
| stage write right | 阶段写入权 | `RightKind.STAGE` | Used by automatic control while a stage is running. |
| manual write right | 人工写入权 | `RightKind.MANUAL` | Held by an operator during a manual takeover. |
| care write right | 养护写入权 | `RightKind.CARE` | Only executes the care rules of an approved run sheet. |
| protection write right | 保护规则的写入权 | `RightKind.PROTECTION` | Belongs to the separately approved safety configuration. |
| recovery number | 恢复编号 | `recovery_number()`, `bump_recovery()` | Goes up by one after a restore from backup or a change of write host. All earlier write rights, approvals and sessions become void. |
| write host | 写入主机 | `register_host()`, `host_registered()` | The one machine registered as allowed to write to the device. Writes from any other machine are refused with `host_unregistered`. |
| timed action | 定时动作 | `TimedAction` | A scheduled level change in a run sheet. |
| feedback rule | 反馈规则 | `FeedbackRule` | A run-sheet rule that changes a channel when a sensor stays past a threshold, and releases it when the reading recovers. |
| care rule | 养护规则 | `CareRule` | A run-sheet rule that keeps basic conditions while a stage is paused, between stages and after the end, for example keeping the light schedule. |
| protection rule | 保护规则 | `ProtectionRule`, `SafetyConfig` | An action in the safety configuration that only moves towards lower risk, on host-controlled channels only. It is not revoked together with the stage write right. |
| action ledger | 动作账本 | `ActionRecord`, `ActionState` | The record of every write: planned value, trigger, request id, write right number, operator, send and read-back times, confirmed value. |
| read-back | 回读 | `read_state()`, `differences()` | Reading the device state after a write, or periodically, and comparing it with what was expected. |
| result unknown | 结果未知 | `ActionState.UNKNOWN`, `StageEventKind.RESULT_UNKNOWN` | A write whose effect could not be confirmed by read-back. |
| recovery check | 待核对 | `StageState.RECOVERY_CHECK` | The device state or the result of an in-flight action is unknown. Ordinary writes are blocked. With a live connection, protection rules and pump-off still run. |
| pump interlock | 关泵联锁 | `interlocked()`, `pump_off()` | While pump-off is unconfirmed, ordinary writes are refused with `interlock` and the executor keeps trying to switch the pump off. |
| manual takeover, handback | 人工接管、交还 | `StageState.MANUAL`, `handover()` | An operator takes over writing from the automatic stage, and later hands it back. |
| old-write-stop confirmation | 旧传输停止确认 | `WriteTransport.halt()`, `confirm_transport_stopped()` | Proof that the previous write path can no longer write. A timeout does not count as confirmation. |
| entry | 入口 | `Entry` | The listener a request arrived on. LAN entry (`lan`): on site. Overlay entry (`overlay`): over the overlay network. Starting the pump (irrigation) is offered on the LAN entry only; switching it off is allowed on both. |
| denial | 拒绝 | `Denied(code)` | A refusal by a permission or control check, with a machine-readable code. See [Denial codes and stage events](Denial-Codes-and-Events.md). |
| stage event | 阶段事件 | `StageEvent`, `StageEventKind` | What the executor reports to the workflow service. The same event id advances a stage at most once. |

## Roles and services

| Term | 中文 | In code | Meaning |
| --- | --- | --- | --- |
| operator | 操作员 | `Actor(kind="operator")`, `Operators` | An authenticated person. Only operators approve, take over and irrigate. |
| model role | 模型角色 | `RoleModel`, `ROLES` | An agent backed by a language model. It reads data and hands in drafts, and has no device or stage control tools. |
| orchestrator | 编排 Agent | role `orchestrator` | Single entry point for the user's goal. Creates research tasks and hands them to the other model roles. |
| planner | 计划 Agent | role `planner` | Designs the experiment and drafts protocols and run sheets. |
| researcher | 研究 Agent | role `researcher` | Reads literature and data, runs analyses and delivers conclusions. |
| executor | 执行 Agent | `ExecutorEngine` | Deterministic program that carries out the approved run sheet. It never calls a model. |
| frozen reading | 冻结读数 | `FrozenWatch`, `frozen_reading` alert | A sensor value that stays exactly the same for longer than its threshold. It opens a frozen period in the archive and an alert; it pauses a running stage only if one of the stage's rules depends on the sensor. |
| observer and notifier | 观察与通知 Agent | `Observer` | Deterministic program for metrics, daily reports, alerts and notifications. It never calls a model. |
| workflow service | 工作流服务 | `WorkflowService` | The only owner of round, stage and task state. |
| control service | 控制服务 | `ControlService` | The single checkpoint for every BLE write. |
| project archive | 项目档案 | `Archive` | The owner of records: samples, actions, snapshots and artifacts. |
| compute service | 计算服务（远程计算） | `ComputeService` | Reserves quota and tracks jobs meant for CSC. `serve` starts it only when it is fully configured; the remote calls have not been verified against CSC. |
| workbench | 工作台 | `create_workbench()`, routes under `/wb` | The operator's HTTP interface: JSON routes under `/wb`. The operator console at `/workbench` is its web page. |
| dashboard | 控制台 | `growbridge dashboard`, files in `web/` | GrowBridge's local web page. In DiAGRI mode its controls are refused and it only shows data. |
| runtime | 运行时 | `Runtime` | Wires all services together in one process. |

## Data and science

| Term | 中文 | In code | Meaning |
| --- | --- | --- | --- |
| experimental unit | 实验单位 | `Allocation.unit` | What a treatment is actually applied to. For treatments controlled by the AC5, such as light, it is the whole tent. |
| independent replicate | 独立重复 | none | A separate experimental unit, or a separate round of the same unit, that received the same treatment. |
| block | 区组 | `Allocation.block` | A group of rounds that are compared with each other. |
| primary endpoint | 主要终点 | `AnalysisPlan.primary_endpoint` | The one outcome the confirmatory analysis is about, fixed before the experiment starts. |
| locked variable | 锁定变量 | none | An environmental variable the protocol requires to stay the same across treatments. A concept of the architecture document; it has no field of its own. |
| evidence card | 证据卡 | `EvidenceCard` | A recorded source for a setpoint: the citation, the claim it supports, value and unit, and whether it has been verified. A setpoint with neither an evidence card nor user input gets a `no_evidence` hint, which does not block the run sheet. |
| data snapshot | 数据快照 | `Snapshot`, `snapshot.freeze()` | A frozen, verifiable copy of the data an analysis uses. |
| holdout data | 留出数据 | `HoldoutRegistry` | Data registered before model development and used only for formal evaluation. |
| confirmatory, exploratory | 确认性、探索性 | `ConfirmatoryRunner`, `classify()` | A confirmatory analysis runs once, on a script and a snapshot frozen beforehand. Everything else is exploratory. |
| honest downgrade | 如实降级 | `classify()` | Lowering the grade of a conclusion when independent replicates are missing, too much data is missing, or treatment and time cannot be separated. |

## Observation

| Term | 中文 | In code | Meaning |
| --- | --- | --- | --- |
| daily report | 日报 | `render_daily_report()`, `ReportStore` | The once-a-day summary of readings, actions and open issues. |
| alert | 告警 | `AlertBook` | A condition that needs attention, tracked until it is resolved. |
| heartbeat | 心跳 | `ExternalMonitor`, `HeartbeatChannel` | A regular signal to an outside monitor, so that silence itself raises an alarm. |

## State values

State values appear in the API, the databases and the logs. The Chinese label is the one in `LABELS` in [`workflow/states.py`](../../../src/growbridge/workflow/states.py).

| Round state (`RoundState`) | 中文 |
| --- | --- |
| `designing` | 设计中 |
| `stage_review` | 阶段待审 |
| `stage_running` | 阶段进行中 |
| `data_verification` | 数据核验 |
| `analysis` | 研究分析 |
| `delivered` | 已交付归档 |
| `aborted` | 已中止归档 |

| Stage state (`StageState`) | 中文 |
| --- | --- |
| `pending_review` | 待审 |
| `running` | 执行中 |
| `paused` | 已暂停 |
| `manual` | 人工接管 |
| `recovery_check` | 恢复待核对 |
| `ended` | 已结束 |
| `stopped` | 已停止 |

| Task state (`TaskState`) | 中文 |
| --- | --- |
| `in_progress` | 进行中 |
| `remote_queued` | 远程排队 |
| `computing` | 计算中 |
| `fetching` | 产物回收 |
| `reconcile` | 待对账 |
| `needs_attention` | 待处理 |
| `needs_review` | 待复核 |
| `done` | 完成 |
| `ended` | 已结束 |

| Action state (`ActionState`) | 中文 |
| --- | --- |
| `pending` | 待发送 |
| `maybe_sent` | 可能已发送 |
| `confirmed` | 已回读确认 |
| `unknown` | 结果未知 |
| `failed` | 失败 |
| `void` | 作废 |

## See also

- [Workflow and state machines](Workflow-and-State-Machines.md)
- [Control and safety model](Control-and-Safety-Model.md)
- [Denial codes and stage events](Denial-Codes-and-Events.md)
