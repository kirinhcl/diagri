# 设计决策记录

[English](../en/Design-Decisions.md)

这一页写给想问“为什么要这样做”的开发者和评审者。它记录了 DiAGRI 背后的十二项设计决策。每条记录说明当时面对的问题、做出的决定、由此带来的后果，以及落实这项决定的代码文件。

节号指的是[架构设计文档](../../diagri-agent-architecture.zh-CN.md)里的章节，那里有更完整的论证。下面每一条都对照代码和测试核对过，但全部只在模拟的 AC5 上运行过，见[状态与已知限制](Status-and-Known-Limitations.md)。

## 1. 模型角色拿不到设备和阶段控制工具

- **背景。** 语言模型会出错，也可能被它在网上读到的文字带偏。如果它能启动阶段或切换通道，一次错误的回答就会直接作用到植物上。
- **决定。** 每个模型角色有一份固定的工具清单（`ROLE_TOOLS`）。另有一份 `CONTROL_TOOLS`，列出阶段和设备控制类工具，不管配置怎么写，任何角色都拿不到。配置只能缩减角色的清单。调用者身份由处理函数自己构造成 `Actor(kind="model")`，输入里出现 `approved` 这类字段会直接校验失败。工作流服务遇到模型身份，以 `model_role` 拒绝。
- **后果。** 模型只交草稿和报告。审批、启动、暂停和接管只能由操作员来做。开启 `auto_research` 之后，共享的 API 令牌和 MCP 服务也都变成只读。
- **落实在。** [`agents/tools.py`](../../../src/growbridge/agents/tools.py)、[`agents/handlers_common.py`](../../../src/growbridge/agents/handlers_common.py)、[`workflow/permissions.py`](../../../src/growbridge/workflow/permissions.py)。架构文档 4.7、5.2 节和第 10 节。

## 2. 所有 BLE 写入只过一个关口

- **背景。** 写入来自定时动作、反馈规则、养护规则、保护规则和操作员。如果每条路径各做各的检查，这些检查迟早会不一致。
- **决定。** 只有控制服务会写设备，入口是 `submit`、`irrigate` 和 `pump_off`。一把锁（代码里叫 gate）让交接和写入排成同一个先后顺序，并分两级优先：保护写入、灌溉结束时的关泵和交接排在普通写入前面，但不抢占已经在途的那次写入；`pump_off()` 不进这把锁。请求在入队时检查一次，在锁内、临发送前再检查一次。
- **后果。** 每一次普通写入都要过同一份清单：控制已启用、本机是登记的写入主机、写入权有效、没有超出写入权的范围、不会启动水泵、没有结果未知的动作、连接有效且读数新鲜。养护规则和保护规则的写入有意跳过其中几项，这样阶段暂停或待核对时它们仍然能执行。BLE 连接本身也只在登记的写入主机上建立。
- **落实在。** [`control/service.py`](../../../src/growbridge/control/service.py)（`_authorize`、`_recheck`），[`ports.py`](../../../src/growbridge/ports.py) 里的 `ControlPort`。架构文档 7.1、7.3 节。

## 3. 先保存意图，再发送

- **背景。** 进程可能正好停在“决定写入”和“得知结果”之间。这时如果不加判断地重发，同一条指令可能生效两次。
- **决定。** 动作在发送之前先存为 `pending`，字节发出去的前一刻再存为 `maybe_sent`。启动时，所有 `maybe_sent` 的动作改为 `unknown`，所有 `pending` 的动作改为 `void`，一律不重放。同一个 `request_id` 带着相同参数再来，返回已保存的记录；带着不同参数再来，则被拒绝（`request_id_reused`）。
- **后果。** 崩溃之后，账本能说清哪些写入可能已经到达设备。在回读或现场核对把它们结清之前，普通写入一直被阻止（`unsettled`）。
- **落实在。** [`control/service.py`](../../../src/growbridge/control/service.py)（`submit`、`_send`、`_close_unfinished`）。架构文档 7.9 节。

## 4. 写入权带编号，恢复之后恢复编号加一

- **背景。** 人工接管之后，自动阶段排着队的旧指令仍然可能发出去，盖掉操作员的设置。从备份恢复之后，旧的审批描述的是一顶可能已经变了样的帐篷。
- **决定。** 每次授予写入权都发一个新编号，每个请求都带着编号。编号已撤销，或者编号属于更早的恢复编号，都不能再写（`right_invalid`）。交接时先撤销编号，作废它名下排队的动作，再等在途的那一条走完。阶段写入权还在的时候，不再授予第二个阶段写入权或人工写入权（`right_held`）。`bump_recovery` 把恢复编号加一，并撤销所有写入权。
- **后果。** 从备份恢复或更换写入主机之后，要先停掉守护进程，再执行 `growbridge recovery bump --reason ...`。进行中的阶段转入待核对，审批作废，绑定在旧编号上的操作员会话被登出。
- **落实在。** [`control/rights.py`](../../../src/growbridge/control/rights.py)、[`control/service.py`](../../../src/growbridge/control/service.py)（`handover`、`bump_recovery`）、[`workbench/auth.py`](../../../src/growbridge/workbench/auth.py)。架构文档 4.1、4.6、7.1 节。

## 5. 规则按单调时钟计时，数据缺口打断连续性

- **背景。** “湿度高于 70 % 持续 60 秒”这样的规则，不能因为墙上时钟跳了一下就被满足或被清零，也不能把没有读数的那一分钟算进去。
- **决定。** 持续时长和最小切换间隔，都用每条读数自带的单调时间来算。读数要同时满足四个条件才能驱动规则：有数值、质量为 `ok`、单位与规则一致、收到的时间距现在不超过规则的 `validity_seconds`。两条有效读数之间的间隔超过运行单的 `max_gap_seconds`，计时重新开始。
- **后果。** 校时不会触发规则，也不会解除规则。出现缺口之后，条件必须重新持续满整个时长。没有有效读数时，反馈规则按自己的 `on_missing`（`hold` 或 `pause`）不动作或暂停阶段，保护规则不动作。
- **落实在。** [`executor/rules.py`](../../../src/growbridge/executor/rules.py)、[`archive/clock.py`](../../../src/growbridge/archive/clock.py)。架构文档 7.4 节。

## 6. 入口由接受连接的监听端口决定

- **背景。** 水泵操作只能在现场进行。守护进程的主端口前面有代理，而 `Host` 头里的名字客户端想写什么就能写什么。
- **决定。** 请求必须是在 `lan_port` 上接受的，并且 `Host` 在 `lan_hosts` 里，才算局域网入口。必须是在 `port` 上接受的，并且 `Host` 在 `overlay_hosts` 里，才算覆盖网络入口。只凭 `Host` 头什么也证明不了。其余情况都不属于任何入口，包括同时出现在两份列表里的地址。没有配置 `lan_port`，就根本没有局域网入口。会话只在创建它的那个入口上有效，请求体里自称的入口不予理会。
- **后果。** 远程用户伪造请求头也到不了只限局域网的操作。没有配置 `lan_port` 的部署，无法从工作台灌溉。
- **落实在。** [`workbench/auth.py`](../../../src/growbridge/workbench/auth.py) 的 `entry_for`，[`workbench/api.py`](../../../src/growbridge/workbench/api.py) 的 `find_entry` 和 `on_site`，以及[测试](../../../tests/workbench/test_workbench_entry.py)。架构文档第 10 节。

## 7. 每个所有者一个数据库文件，服务之间只共享契约和模型

- **背景。** 阶段状态、动作账本和档案记录各有各的规则，需要由一个服务来守。如果任何服务都能写任何一张表，就没有哪个服务守得住自己的规则。
- **决定。** `build_runtime` 为每个所有者建一个 SQLite 文件：`control`、`workflow`、`archive`、`observer`、`compute` 和 `agents`。服务只导入 `ports.py` 里的契约和 `archive/models.py` 里的模型，不导入其他服务的类。把它们连起来的是运行时和模型角色的工具处理函数。
- **后果。** 工作流服务是阶段状态的唯一所有者，控制服务是唯一的 BLE 写入方，项目档案是记录的所有者。每个文件单独备份。不过所有服务仍然跑在同一个进程、同一个系统账户下；架构文档第 10 节按系统账户隔离的做法属于部署步骤，代码本身不做这件事。负责装配的运行时为了生成日报，直接读了两张表。
- **落实在。** [`runtime.py`](../../../src/growbridge/runtime.py)（`DATABASES`、`build_runtime`）、[`ports.py`](../../../src/growbridge/ports.py)、[`archive/db.py`](../../../src/growbridge/archive/db.py)。架构文档第 10 节和 12.1 节。

## 8. 原始数据只追加，派生数据可重算

- **背景。** 一个结果在几个月之后还要能核对。如果算出它的那些行可以改，这一点就做不到。
- **决定。** 项目档案只做插入。更正是一条指向旧记录的新记录，用过旧值的快照和产物被标记为失效。分析读取的是冻结的数据快照，快照里每个文件都有指纹；重新冻结会生成新版本。
- **后果。** 存储只增不减。一次更正意味着重新冻结、重新发布。这条规则由 `Archive` 类保证，而不是由数据库保证，所以管不到直接打开文件的程序。
- **落实在。** [`archive/store.py`](../../../src/growbridge/archive/store.py)、[`archive/snapshot.py`](../../../src/growbridge/archive/snapshot.py)。架构文档 11.2、11.3 节。细节见[数据、档案与可追溯性](Data-Archive-and-Traceability.md)。

## 9. 确认性分析设关口，结论如实降级

- **背景。** 如果分析可以反复重跑、反复调整，直到结果好看为止，“已确认”三个字就没什么分量。而只有一顶帐篷时，多数设计本来就撑不起很强的结论。
- **决定。** 报告的标签由服务端根据研究协议和冻结的数据计算。要标为确认性，必须有按哈希冻结的脚本、完整且校验通过的快照，并且只运行一次。五条规则会把标签降为描述性或探索性。模型申报的内容只能让结果更严格。规模太小的实验，结论是 `uncertain`（不确定），绝不写“无效应”。
- **后果。** 单帐篷的报告往往是探索性或描述性的，并且会写明原因。当前代码里没有任何命令或工具能启动确认性运行，所以通过工具发布的报告最高只能是探索性。
- **落实在。** [`research/analysis.py`](../../../src/growbridge/research/analysis.py)、[`agents/handlers_report.py`](../../../src/growbridge/agents/handlers_report.py)、[`research/report.py`](../../../src/growbridge/research/report.py)。架构文档 4.8、6.5、9.3 节。细节见[科研方法](Research-Methodology.md)。

## 10. 执行 Agent 和观察与通知 Agent 是确定性程序

- **背景。** 模型 API 可能中断、变慢、变贵，同一个问题也不会每次给出同样的回答。而植物不管这些，光照日程必须照常执行。
- **决定。** `Runtime.tick` 从不调用模型。执行 Agent、观察与通知 Agent 和控制服务都不导入模型客户端。模型在另一个循环里运行，模型出错只会让任务转为待处理，并产生一条告警。
- **后果。** 已批准的阶段在完全没有模型客户端的情况下也能跑到结束。代价是方案不会自己调整：任何改动都需要新版本的运行单和新的审批。
- **落实在。** [`runtime.py`](../../../src/growbridge/runtime.py)、[`runtime_agents.py`](../../../src/growbridge/runtime_agents.py)、[`executor/engine.py`](../../../src/growbridge/executor/engine.py)。测试：[`test_e2e_runtime.py`](../../../tests/e2e/test_e2e_runtime.py)、[`test_e2e_agents.py`](../../../tests/e2e/test_e2e_agents.py)。架构文档第 2、7、8 节。

## 11. 读不到设备状态时，按最保守的情况处理

- **背景。** 连接看上去还在，回读却可能失败。如果把“读不到”当成“没有差异”，阶段就会在一个谁也没见过的状态上继续执行。
- **决定。** 执行 Agent 把“没有差异”和“读不到”分开处理。掉线恢复之后读不到状态，按有差异处理，阶段暂停。阶段执行期间读不到状态，在 `max_gap_seconds` 之内可以容忍，超过之后按读数过期上报，阶段暂停。保护规则要设的档位如果回读不到，不假定它已经生效，而是重新下发，每个通道最多每 30 秒一次。
- **后果。** 需要操作员处理的暂停会多一些，换来的是系统不凭猜测行动。同样的原则在别处也有体现：监听端口对不上就没有入口（第 6 条），前一个动作结果未知时不做普通写入（第 3 条）。
- **落实在。** [`executor/engine.py`](../../../src/growbridge/executor/engine.py)（`_differences`、`_state_unreadable`、`_verified`）和[测试](../../../tests/executor/test_executor_unreadable.py)。架构文档 4.4、7.7 节。

## 12. 水泵只能由操作员在局域网入口启动

- **背景。** 水泵运行时 BLE 连接如果断开，程序没有把握把它关上。
- **决定。** 运行单校验会拦下任何将要启动水泵的动作（`pump_action`）。运行单若把水泵交给 AC5 自带的定时器（归属 `device`），同样会被拦下（`pump_device_owned`）：水泵永远不交给设备定时器，因为 DiAGRI 从不让水泵自行启动，而水泵看门狗会关掉任何在 DiAGRI 未灌溉时仍开着的水泵。`submit` 从不开泵（`pump_on_forbidden`）。唯一能开泵的路径是 `irrigate`：需要人工写入权，时长不超过 `max_pump_seconds`，并遵守冷却时间 `pump_cooldown_seconds`。工作台只对局域网入口上的操作员开放这个功能。关泵另有专用路径；关泵没有得到确认期间，关泵联锁会阻止普通写入。
- **后果。** 这一版没有自动灌溉。浇水要么由人在现场触发，要么作为人工作业手工完成。
- **落实在。** [`planning/validate.py`](../../../src/growbridge/planning/validate.py)、[`control/rights.py`](../../../src/growbridge/control/rights.py)、[`control/service.py`](../../../src/growbridge/control/service.py)、[`workbench/api.py`](../../../src/growbridge/workbench/api.py)。架构文档 4.5、7.6、7.8 节。操作步骤见[人工接管、灌溉与交还](Manual-Takeover-and-Irrigation.md)。

## 另见

- [架构总览](Architecture.md)
- [控制与安全模型](Control-and-Safety-Model.md)
- [工作流与状态机](Workflow-and-State-Machines.md)
- [数据、档案与可追溯性](Data-Archive-and-Traceability.md)
- [科研方法](Research-Methodology.md)
- [拒绝码与事件类型](Denial-Codes-and-Events.md)
