# 术语表

[English](../en/Glossary.md)

这一页写给所有读者。它把 Wiki 里用到的每个术语，对应到[架构设计文档](../../diagri-agent-architecture.zh-CN.md)里的中文说法、英文版 Wiki 的说法，以及代码里的标识符。

标识符在哪里查：数据模型在 [`archive/models.py`](../../../src/growbridge/archive/models.py)，服务之间的契约在 [`ports.py`](../../../src/growbridge/ports.py)，状态名在 [`workflow/states.py`](../../../src/growbridge/workflow/states.py)。

## 项目

| 术语 | English | 代码中 | 含义 |
| --- | --- | --- | --- |
| DiAGRI | DiAGRI | `growbridge` 下的子包，包括 `agents/`、`workflow/`、`control/`、`executor/`、`observer/`、`archive/`、`research/` 等 | 整个项目：面向植物生长研究的 AI Agent 平台。它设计实验，在种植设备上执行已批准的方案，留下记录，分析结果并出报告。 |
| GrowBridge | GrowBridge | 软件包和命令 `growbridge`；`transport.py`、`service.py`、`store.py`、`api.py`、`mcp_server.py`、`web/` | DiAGRI 的设备桥接部分：通过蓝牙读取并控制 Spider Farmer AC5。它可以单独运行。 |
| DiAGRI 模式 | DiAGRI mode | `auto_research = true` | 程序运行整个平台。桥接部分自带的写入路由和写入工具会被拒绝，所有对设备的写入都经过控制服务。 |
| 仅桥接模式 | bridge-only mode | `auto_research = false`（默认） | 程序只运行 GrowBridge：控制台、本地 HTTP 接口和 MCP 工具。 |

## 研究流程

| 术语 | English | 代码中 | 含义 |
| --- | --- | --- | --- |
| 研究轮次 | research round | `RoundState` | 从研究目标到报告交付归档的一次完整推进。 |
| 系列 | series | `ResearchProtocol.rounds`、`.blocks`、`.allocations` | 设计需要跨轮重复时，协议登记的那一组轮次。例如单顶帐篷里先后做不同处理。 |
| 阶段 | stage | `StageState`、`StageRuntime` | 运行单定义的执行区段，例如育苗期或处理期。 |
| 生长期 | growth period | 无 | 作物自身的发育期。它不是阶段。 |
| 变量目录 | variable catalog | `Catalog`、`packaged_catalog()` | 协议、测量、快照和留出集共同使用的标准变量 ID 清单（含单位、方法、允许范围）。只追加；见[变量目录](Variable-Catalog.md)。 |
| 研究协议 | research protocol | `ResearchProtocol` | 问题与假设、处理和对照、实验单位、分配方式、随机化种子、主要终点和分析约定。按版本保留。 |
| 运行单 | run sheet | `RunSheet` | 一个阶段的可执行方案，也是操作员审批的对象。任何修改都生成新版本。 |
| 审批 | approval | `Approval` | 操作员对运行单或其他请求做出的、留有记录的决定。 |
| 研究任务 | research task | `ResearchTask`、`TaskState`、`TaskBoard` | 交给模型角色的一项工作。它有自己的状态机和调用预算。 |
| 人工作业 | manual task | `ManualTask` | 运行单里由人动手完成的工作，例如灌溉。 |
| 暂停、停止、中止 | pause, stop, abort | `StageState.PAUSED`、`StageState.STOPPED`、`RoundState.ABORTED` | 暂停后可以续跑。停止结束一个阶段。中止结束整轮。三者都留下归档记录。 |

## 控制与安全

| 术语 | English | 代码中 | 含义 |
| --- | --- | --- | --- |
| 通道 | channel | `Channel` | AC5 上一路可控的输出：`light`（灯）、`exhaust`（排风）、`fan`（循环风扇）、`pump`（水泵）。 |
| 通道归属 | channel ownership | `Ownership` | 每个通道由谁控制。设备自管（`device`）：AC5 自己定时，DiAGRI 只读。主机控制（`host`）：由执行 Agent 写入。 |
| 写入权与编号 | write right and its number | `WriteRight`、`RightKind`、`right_number` | 控制服务登记的写设备资格。每次授予都带一个新编号，编号作废后不能再写。 |
| 阶段写入权 | stage write right | `RightKind.STAGE` | 阶段执行期间由自动控制使用。 |
| 人工写入权 | manual write right | `RightKind.MANUAL` | 人工接管期间由操作员持有。 |
| 养护写入权 | care write right | `RightKind.CARE` | 只执行已批准运行单里的养护规则。 |
| 保护规则的写入权 | protection write right | `RightKind.PROTECTION` | 属于单独审批的安全配置。 |
| 恢复编号 | recovery number | `recovery_number()`、`bump_recovery()` | 从备份恢复或更换写入主机后加一。此前的写入权、审批和会话全部失效。 |
| 写入主机 | write host | `register_host()`、`host_registered()` | 登记为可以写设备的那一台机器。其他机器的写入会被拒绝，拒绝码是 `host_unregistered`。 |
| 定时动作 | timed action | `TimedAction` | 运行单里按时间执行的档位变化。 |
| 反馈规则 | feedback rule | `FeedbackRule` | 运行单里的规则：传感器读数持续越过阈值时改变某个通道，读数恢复后释放。 |
| 养护规则 | care rule | `CareRule` | 运行单里的规则：在阶段暂停、阶段之间和结束后维持基础条件，例如按原日程开关灯。 |
| 保护规则 | protection rule | `ProtectionRule`、`SafetyConfig` | 安全配置里只朝降低风险方向的动作，只写主机控制的通道。它不随阶段写入权一起撤销。 |
| 动作账本 | action ledger | `ActionRecord`、`ActionState` | 每一次写入的记录：计划值、触发证据、请求编号、写入权编号、操作者、下发与回读时间、确认值。 |
| 回读 | read-back | `read_state()`、`differences()` | 写入之后或定期读取设备状态，并和预期值比较。 |
| 结果未知 | result unknown | `ActionState.UNKNOWN`、`StageEventKind.RESULT_UNKNOWN` | 一次写入的效果无法通过回读确认。 |
| 待核对 | recovery check | `StageState.RECOVERY_CHECK` | 设备状态或在途动作的结果未知。普通写入被阻止。连接有效时，保护规则和关泵仍可执行。 |
| 关泵联锁 | pump interlock | `interlocked()`、`pump_off()` | 关泵未得到确认期间，普通写入被拒绝（拒绝码 `interlock`），执行 Agent 持续尝试关泵。 |
| 人工接管、交还 | manual takeover, handback | `StageState.MANUAL`、`handover()` | 操作员从自动阶段手里接过写入，之后再交还。 |
| 旧传输停止确认 | old-write-stop confirmation | `WriteTransport.halt()`、`confirm_transport_stopped()` | 证明此前的写入通路已经不能再写。超时不算确认。 |
| 入口 | entry | `Entry` | 请求是从哪个监听端口进来的。局域网入口（`lan`）：在现场。覆盖网络入口（`overlay`）：经覆盖网络远程访问。开泵（灌溉）只在局域网入口提供，关泵在两个入口都可以。 |
| 拒绝 | denial | `Denied(code)` | 权限或控制检查的一次拒绝，带一个机器可读的拒绝码。见[拒绝码与事件类型](Denial-Codes-and-Events.md)。 |
| 阶段事件 | stage event | `StageEvent`、`StageEventKind` | 执行 Agent 向工作流服务报告的事件。同一个事件 ID 最多推进阶段一次。 |

## 角色与服务

| 术语 | English | 代码中 | 含义 |
| --- | --- | --- | --- |
| 操作员 | operator | `Actor(kind="operator")`、`Operators` | 通过认证的人。只有操作员可以审批、接管和灌溉。 |
| 模型角色 | model role | `RoleModel`、`ROLES` | 由语言模型驱动的 Agent。它读数据、交草稿，没有任何设备或阶段控制工具。 |
| 编排 Agent | orchestrator | 角色 `orchestrator` | 用户目标的统一入口。创建研究任务，并交给其他模型角色。 |
| 计划 Agent | planner | 角色 `planner` | 设计实验，起草研究协议和运行单。 |
| 研究 Agent | researcher | 角色 `researcher` | 查文献、读数据、跑分析，交付结论。 |
| 执行 Agent | executor | `ExecutorEngine` | 确定性程序，执行已批准的运行单。从不调用模型。 |
| 监察 Agent | auditor | 角色 `auditor` | 读取阶段记录并与运行单对照的模型角色。它只能提出建议性的 `audit_finding` 告警。 |
| 阶段检查 | stage checks | `StageChecks`，告警 `task_missed`、`measurement_missing`、`measurement_outside_window` | 挂在观察者 tick 上的确定性检查：人工任务过了截止时间仍无记录、测量任务已完成却没有测量、测量的时间会让快照把它排除。只发警告，从不暂停阶段。 |
| 冻结读数 | frozen reading | `FrozenWatch`、`frozen_reading` 告警 | 传感器的数值在超过门槛的时间里完全不变。它会在档案里开一个冻结时段并发出告警；只有阶段的规则依赖该传感器时，才会暂停正在执行的阶段。 |
| 观察与通知 Agent | observer and notifier | `Observer` | 确定性程序，负责指标、日报、告警和通知。从不调用模型。 |
| 工作流服务 | workflow service | `WorkflowService` | 轮次、阶段和任务状态的唯一所有者。 |
| 控制服务 | control service | `ControlService` | 所有 BLE 写入的唯一关口。 |
| 项目档案 | project archive | `Archive` | 记录的所有者：样本、动作、快照和产物。 |
| 计算服务（远程计算） | compute service | `ComputeService` | 为准备提交到 CSC 的作业预留额度并跟踪状态。`serve` 只在配置齐全时才启动它；远端调用没有对 CSC 验证过。 |
| 工作台 | workbench | `create_workbench()`，路由在 `/wb` 下 | 操作员使用的 HTTP 接口：`/wb` 下的一组 JSON 路由。`/workbench` 的操作员控制台就是它的网页。 |
| 控制台 | dashboard | `growbridge dashboard`，文件在 `web/` 下 | GrowBridge 的本地网页。在 DiAGRI 模式下，它的控制操作会被拒绝，只用来看数据。 |
| 运行时 | runtime | `Runtime` | 在一个进程里把所有服务装配起来。 |

## 数据与科研

| 术语 | English | 代码中 | 含义 |
| --- | --- | --- | --- |
| 实验单位 | experimental unit | `Allocation.unit` | 处理实际施加在什么上面。由 AC5 控制的处理（例如光照）作用于整顶帐篷。 |
| 独立重复 | independent replicate | 无 | 接受同一处理的另一个实验单位，或同一单位的另一轮。 |
| 区组 | block | `Allocation.block` | 相互比较的一组轮次。 |
| 主要终点 | primary endpoint | `AnalysisPlan.primary_endpoint` | 确认性分析针对的那一个结果指标，实验开始前就固定下来。 |
| 锁定变量 | locked variable | 无 | 协议规定在各处理之间保持一致的环境变量。这是架构文档里的概念，代码里没有单独的字段。 |
| 证据卡 | evidence card | `EvidenceCard` | 一个设定值的来源记录：引用出处、它支持的论断、数值与单位，以及是否经过复核。既没有证据卡、也没有用户输入的设定值会得到 `no_evidence` 提示，但运行单不会因此被拦下。 |
| 数据快照 | data snapshot | `Snapshot`、`snapshot.freeze()` | 一次分析所用数据的冻结副本，可以校验。 |
| 留出数据 | holdout data | `HoldoutRegistry` | 模型开发前登记、只用于正式评估的数据。 |
| 确认性、探索性 | confirmatory, exploratory | `ConfirmatoryRunner`、`classify()` | 确认性分析只跑一次，脚本和快照都事先冻结。其余分析都是探索性的。 |
| 如实降级 | honest downgrade | `classify()` | 缺少独立重复、缺失过多，或者处理和时间分不开时，降低结论的等级。 |

## 观察

| 术语 | English | 代码中 | 含义 |
| --- | --- | --- | --- |
| 日报 | daily report | `render_daily_report()`、`ReportStore` | 每天一次的汇总：读数、动作和未解决的问题。 |
| 告警 | alert | `AlertBook` | 需要关注的状况，持续跟踪直到解决。 |
| 心跳 | heartbeat | `ExternalMonitor`、`HeartbeatChannel` | 定期发给外部监控的信号。信号中断本身就会触发报警。 |

## 状态值

状态值会出现在接口、数据库和日志里。中文标签取自 [`workflow/states.py`](../../../src/growbridge/workflow/states.py) 里的 `LABELS`。

| 轮次状态（`RoundState`） | 中文 |
| --- | --- |
| `designing` | 设计中 |
| `stage_review` | 阶段待审 |
| `stage_running` | 阶段进行中 |
| `data_verification` | 数据核验 |
| `analysis` | 研究分析 |
| `delivered` | 已交付归档 |
| `aborted` | 已中止归档 |

| 阶段状态（`StageState`） | 中文 |
| --- | --- |
| `pending_review` | 待审 |
| `running` | 执行中 |
| `paused` | 已暂停 |
| `manual` | 人工接管 |
| `recovery_check` | 恢复待核对 |
| `ended` | 已结束 |
| `stopped` | 已停止 |

| 任务状态（`TaskState`） | 中文 |
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

| 动作状态（`ActionState`） | 中文 |
| --- | --- |
| `pending` | 待发送 |
| `maybe_sent` | 可能已发送 |
| `confirmed` | 已回读确认 |
| `unknown` | 结果未知 |
| `failed` | 失败 |
| `void` | 作废 |

## 另见

- [工作流与状态机](Workflow-and-State-Machines.md)
- [控制与安全模型](Control-and-Safety-Model.md)
- [拒绝码与事件类型](Denial-Codes-and-Events.md)
