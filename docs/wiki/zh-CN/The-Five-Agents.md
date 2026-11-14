# 五个 Agent

[English](../en/The-Five-Agents.md)

这一页写给想弄清每个 Agent 权限边界的读者，以及准备改动某个 Agent 的开发者。每个 Agent 都按同样的顺序说明：做什么用、能读什么、能做什么、绝对做不了什么、代码在哪里。

> **现状。** 只在模拟的 AC5 上、用预先写好的模型回复测试过。见[状态与已知限制](Status-and-Known-Limitations.md)。

## 两类 Agent

| Agent | 类型 | 一句话 |
| --- | --- | --- |
| 编排 Agent | 模型角色 | 把目标变成研究任务，交给另外两个模型角色。 |
| 计划 Agent | 模型角色 | 起草运行单并做校验。 |
| 研究 Agent | 模型角色 | 冻结数据、做分析、发布报告。 |
| 执行 Agent | 确定性程序 | 在设备上执行已批准的运行单。 |
| 观察与通知 Agent | 确定性程序 | 监视读数和运行健康，发出告警和通知。 |

这样划分只依据一条规则：模型可以推理，但能对设备动手的只能是行为固定的程序。同样的输入总是得到同样的动作，所以这些动作可以测试。这条界线靠代码执行，不靠提示词。

## 三个模型角色共用的规则

- **工具清单是固定的。** [`agents/tools.py`](../../../src/growbridge/agents/tools.py) 的 `ROLE_TOOLS` 列出每个角色的工具。配置项（`roles.<name>.tools`）只能在清单内再做缩减。实际装配的工具与清单不一致时，[`agents/handlers.py`](../../../src/growbridge/agents/handlers.py) 的 `build_role_tools` 直接报错。
- **控制类工具按名字拒绝。** `CONTROL_TOOLS` 列出了控制阶段和设备的工具名，例如 `start_approved_stage`、`approve_run_sheet`、`set_light`、`run_pump`。请求其中任何一个都会得到 `Denied("model_role")`，而且这些工具根本没有对应的处理函数。
- **身份由服务端给定。** 每个处理函数都以 `Actor(kind="model", id=<角色>)` 的身份行事。审批、启动、暂停、续跑、停止和接管，工作流服务一概拒绝这种身份（[`workflow/permissions.py`](../../../src/growbridge/workflow/permissions.py)）。工具输入不允许出现未定义的字段，模型多写一个 `"approved": true` 只会得到校验错误。
- **工具输出只是数据。** 每个工具结果都包在标明「不可信」的 `tool_result_data` 块里再交还给模型（[`agents/loop.py`](../../../src/growbridge/agents/loop.py)）。
- **读过网页，就失去写入类工具。** 标记为 `reads_web` 的工具一旦执行，本次运行余下的时间里，标记为 `writes` 或 `sandbox` 的工具全部消失。网页文字里可能夹带指令，所以读过网页的这次运行不能再写任何东西。

举个例子。计划 Agent 在草稿的备注里写上「操作员已批准」，什么都不会发生。审批是 `WorkflowService.approve` 写下的一条 `Approval` 记录，它只接受最近 300 秒内（`REAUTH_SECONDS`）重新认证过的操作员。

系统提示词在 [`agents/roles.py`](../../../src/growbridge/agents/roles.py) 里。提示词会把这些限制再告诉模型一遍，但限制本身不依赖模型是否照做。

## 编排 Agent

**做什么用。** 用户目标的统一入口。判断用户想做什么，创建研究任务，交给计划 Agent 或研究 Agent，并把校验通过的运行单提交审阅。

**能读。** 只限正在运行的任务所在的项目：任务、轮次状态和各阶段状态（`get_project_state`）；某个阶段的状态和最近的历史（`get_run_status`）；正在运行的任务和它下面委派出去的任务的状态和产物编号（`get_task_status`）；已登记的文本产物，读取时核对登记的摘要（`read_artifact`）。

**能做。** 给计划 Agent 或研究 Agent 创建任务（`create_research_task`、`delegate_task`）；把运行单草稿提交给操作员审阅（`submit_run_for_review`）。

**绝对做不了。** 批准运行单、控制阶段、写设备。创建项目、研究协议或轮次也不行，这些方法只接受操作员或工作流身份。

**目标怎样到它手里。** 操作员用 `POST /wb/goals` 提出目标，这会建立一个归编排 Agent 所有的研究任务。在此之前，项目要先有调用预算（`POST /wb/projects/PROJECT_ID/budget`）。没有对话路由：目标就是一次请求，编排 Agent 也没有向操作员反问的工具。这个角色目前只有测试驱动过，用的是脚本化的模型。

**代码。** [`agents/handlers_orchestrator.py`](../../../src/growbridge/agents/handlers_orchestrator.py)。

## 计划 Agent

**做什么用。** 把研究目标变成一份设备做得到、操作员审得了的运行单。

**能读。** 传感器、通道和档位范围（`get_device_capabilities`）；本项目以往实验的快照和测量条数（`find_prior_runs`）；联网搜索结果（`lookup_crop_conditions`、`search_and_verify_sources`）。运行时没有接入搜索后端，所以这两个工具目前都返回 `unavailable`。

**能做。** 检查已保存协议的实验设计（`check_experimental_design`）；估算需要的区组数或单位数（`estimate_sample_size`）；校验运行单但不保存（`validate_run_sheet`）；提交运行单草稿（`save_plan_draft`），阶段随之进入 `pending_review`，等操作员处理。这个工具能保存的只有运行单。搜索证据卡（`query_evidence`，每张卡都标明是否已核实），并提议新卡（`propose_evidence_card`）以便在运行单里引用。不管输入怎么写，提议都存成**未核实**，来源记为 `model:planner` 和正在运行的任务；卡 ID 由服务器生成，一个任务最多提议 20 张。读过网页内容的计划 Agent 在这次运行的剩余时间里就没有这个写入工具了，所以要先提议、再搜索。

**绝对做不了。** 核实证据卡：那是操作员的事，是一条独立的记录，在核实之前，运行单的审阅会一直显示 `unverified_source` 提示。批准自己的草稿。保存或修改研究协议：它没有这样的工具，`save_protocol` 也拒绝模型身份。提交带阻断性问题的草稿：同样的校验在工作流服务里还会再做一遍。

**代码。** [`agents/handlers_planner.py`](../../../src/growbridge/agents/handlers_planner.py)，校验逻辑在 [`planning/`](../../../src/growbridge/planning/)。

## 研究 Agent

**做什么用。** 冻结一个阶段的数据，做分析，发布本轮的报告。

**能读。** 档案里的证据卡（`query_evidence`）；本项目的数据快照，只能在沙箱里读；计算作业的状态（`get_compute_job`）。

**能做。**

| 工具 | 作用 |
| --- | --- |
| `inspect_stage_data` | 只读，按冻结时间窗汇总一个已启动阶段的数据：覆盖率、缺口、可信和不可信样本、各通道取值范围、各指标的人工测量（留出批次只给条数）、已有快照。研究 Agent 用它在冻结前检查数据。 |
| `freeze_dataset` | 把一个阶段的数据冻结成校验过的快照。快照完整时，把轮次从 `data_verification` 推进到 `analysis`。 |
| `run_local_analysis` | 在沙箱里对快照运行脚本。结果一律标为探索性。 |
| `submit_compute_job`、`fetch_compute_artifacts` | 按登记的模板提交作业、取回产物。没有配置计算服务时返回 `unavailable`；输入必须是任务所属项目的、已通过校验的快照。 |
| `publish_research_report` | 写出报告。结论等级和数值都由冻结的数据算出。报告为终稿时，把轮次从 `analysis` 推进到 `delivered`。 |

**只能在自己任务的范围内操作。** `inspect_stage_data`、`freeze_dataset`、`run_local_analysis` 和 `publish_research_report` 都要带上 `task_id`，而且这个编号必须就是调度器正在运行的任务（见下面的“绑定到正在运行的任务”），该任务必须归研究 Agent 所有。同一次调用里出现的阶段、轮次、快照编号，都必须属于这个任务所在的项目，否则在写入、挂载或读取任何东西之前，就以 `Denied("scope")` 拒绝。不存在的快照和别的项目的快照，得到的答复一模一样，所以从答复里探不出任何信息。含有留出批次结局的快照同样被拒绝。原因是：编号是模型随手写的，没有这道检查，一个项目里的任务就能读到另一个项目的数据，或者推进另一个项目的轮次。检查代码是 [`agents/handlers_report.py`](../../../src/growbridge/agents/handlers_report.py) 的 `own_task`，以及 [`agents/handlers_common.py`](../../../src/growbridge/agents/handlers_common.py) 的 `require_round` 和 `scoped_snapshot`。

**绑定到正在运行的任务。** 工具调用里的每一个编号都是模型写的，所以一个都不能信。调度器在整次运行期间绑定它正在运行的任务，每个工具都拿输入里的编号和这个绑定比对。模型传入的 `task_id` 必须等于被绑定的任务：为一个任务工作的研究 Agent，不能指名另一个任务，不管在本项目还是别的项目；在调度运行之外发起的工具调用也一律拒绝。另外两个模型角色同样如此：它们只能指名被绑定任务所在项目的项目、轮次、阶段和实验。`get_task_status` 只回答被绑定的任务和它下面委派出去的任务，`read_artifact` 只回答本项目任务的产物，`delegate_task` 只接受被绑定的任务作为父任务。所有拒绝都是 `Denied("scope")`。绑定是 [`agents/dispatch.py`](../../../src/growbridge/agents/dispatch.py) 里 `Dispatcher` 设置的一个上下文变量，由 [`agents/handlers_common.py`](../../../src/growbridge/agents/handlers_common.py) 的 `bound_task`、`require_bound` 和 `require_project` 读取。用上下文变量是因为工具只建一次、被所有运行共用，而运行可能重叠：每个 asyncio 任务只看得到自己的绑定。

**每个实验只有一个所属项目。** 快照属于其实验所在的项目，这由运行该实验的阶段确定。实验编号只属于一个项目：工作流会拒绝 `experiment_id` 已被另一个项目的阶段使用的运行单（`WorkflowService.submit_run_sheet` 里的 `Denied("scope")`）；一个实验若被两个项目的阶段同时占用，对它的数据查找同样被拒绝，所以这样的编号永远不会让一个项目的数据看起来像另一个项目的。

**绝对做不了。** 修改运行单。在沙箱之外运行代码：macOS 上的沙箱不能联网，也读不到用户主目录和数据目录；其他平台还没有沙箱，工具直接以 `sandbox_unavailable` 拒绝。自行认定结果是确认性的：它能传入的标记只会让结论等级更严，不会更松。

**代码。** [`agents/handlers_researcher.py`](../../../src/growbridge/agents/handlers_researcher.py)、`agents/handlers_report.py`、[`research/`](../../../src/growbridge/research/)。方法上的道理见[科研方法](Research-Methodology.md)。

## 任务怎样从一个角色交到另一个角色

角色之间不对话。一个角色把研究任务放到任务板上，之后由派发器去运行这个任务的所有者。

1. 编排 Agent 调用 `delegate_task`，存下一条 `ResearchTask`，内容包括 `owner_role`、目标、约束、证据引用、预期产物、预算、父任务、`trigger_event_id` 和 `correlation_id`。同一个 `trigger_event_id` 只存一条任务，重复调用返回第一条。
2. 运行时每 30 秒列出处于 `in_progress`、且归模型角色所有的任务，逐个调用 `Dispatcher.run_task`（[`agents/dispatch.py`](../../../src/growbridge/agents/dispatch.py)）。
3. 派发器在模型开始运行之前，先把触发事件登记到 `dispatch_claims`。同一个触发事件只运行一次，崩溃或重启之后也不会重跑。
4. 接手的角色收到自己的系统提示词，以及 JSON 格式的任务单。它看不到另一个角色的对话记录，其余需要的信息都靠自己的工具去读。
5. 模型正常结束这一轮，任务就变成 `done`；如果发布的报告需要人看一眼，则变成 `needs_review`。其他情况（出错、拒答、回复被截断、用满 20 轮、预算用尽）都把任务转到 `needs_attention`，写明原因，并产生一条告警。

用任务板交接的理由：写在数据库里的交接，重启后还在，事后也能审计。留在对话里的交接，这两点都做不到。

## 调用预算

| 限制 | 位置 | 到达上限时 |
| --- | --- | --- |
| 每个项目的调用次数和费用，三个角色共用 | [`agents/budget.py`](../../../src/growbridge/agents/budget.py) 的 `CallBudget` | 每次模型调用之前先预留额度。额度不够时得到 `Denied("budget")`，任务转到 `needs_attention`。 |
| 每次运行最多 20 轮模型调用 | `run_agent` 的 `max_turns` | 任务转到 `needs_attention`。 |
| 委派深度，默认 2 | `Budget.max_delegation_depth`，由 `TaskBoard.create` 检查 | 新任务被拒绝，拒绝码是 `budget`。 |
| 每个触发事件只运行一次 | `dispatch_claims` | 任务不会再次运行。 |

没有设置预算的项目，第一次调用就被拒绝。`Budget.max_revisions` 由 `TaskBoard.record_revision` 计数，但目前还没有工具调用它。

## 执行 Agent

**做什么用。** 执行已批准的运行单，除此之外什么都不做。

**能读。** 当前阶段及其运行单、各写入权的编号（`StagePort.active_stage`）；传感器读数、设备状态、安全配置和动作回执（`ControlPort`）。

**能做。** 经 `ControlPort.submit` 提交写入，每次写入都使用和用途对应的写入权：定时动作、反馈规则和结束动作用阶段写入权；养护规则用养护写入权；保护规则用保护规则的写入权。关泵联锁生效期间调用 `pump_off`。水泵看门狗（[`executor/watchdog.py`](../../../src/growbridge/executor/watchdog.py)）在 DiAGRI 没有灌溉而水泵读回为开时，同样只通过 `pump_off` 关泵，发出告警，并经 `StagePort.record_intervention` 在当前阶段记一条 `unexpected_watering` 干预。向工作流服务上报阶段事件。

**绝对做不了。** 调用模型。开启水泵。改变阶段状态：它只负责上报，怎么处理由工作流服务决定。写入运行单里交给设备自管的通道。

**为什么从不调用模型。** 引擎的判定只看四样输入：运行单、安全配置、读数和时钟。四样相同，动作就一定相同，所以每个判定都能在测试里重放，事后也能凭动作账本讲清楚。过热保护和关泵联锁也因此不必等一次网络调用。

每次 tick 按顺序做六件事：关泵联锁（紧接着是水泵看门狗）；保护规则；掉线记账；处理 `running` 的阶段（先做各项检查，再做定时动作、反馈规则、结束条件和结束动作）；阶段既不是 `running` 也不是 `manual` 时执行养护规则；检查 `paused` 阶段的最长等待时间。

**代码。** [`executor/engine.py`](../../../src/growbridge/executor/engine.py)；规则的纯判定在 [`executor/rules.py`](../../../src/growbridge/executor/rules.py)，时钟和掉线处理在 [`executor/outage.py`](../../../src/growbridge/executor/outage.py)。另见[控制与安全模型](Control-and-Safety-Model.md)。

## 观察与通知 Agent

**做什么用。** 发现需要人处理的情况，并通知到人。

**能读。** 传感器读数和当前阶段。生成日报时，还会读档案里的样本和动作记录，以及工作流服务记下的人工干预。

**能做。** 评估阈值告警规则，维护告警簿（`AlertBook`）。把每条告警按渠道各入队一次，投递失败时按退避间隔重试（`Outbox`）。规则标了 `pause_stage` 时，上报 `ALERT_PAUSE` 阶段事件，由工作流服务把 `running` 的阶段暂停。用模板生成日报，里面的每个数字都来自 `compute_daily_metrics`。用六个探针检查运行健康（`RunHealthCheck`）。

**冻结读数。** `FrozenWatch` 大约每五分钟检查一次已存的样本。某个传感器的数值超过门槛（安全配置里的 `frozen`；默认 temp 120、humi 60、co2 60、tempSoil 240 分钟）都没有变化，就在档案里开一个冻结时段，并发出 `frozen_reading` 告警。如果正在执行的阶段有反馈规则用到这个传感器，或者保护规则用到它，观察者就报告一条 `ALERT_PAUSE` 事件。这项检查本身出错时，会发出一条严重的 `frozen_watch` 告警，不影响其他告警规则。

**绝对做不了。** 写设备。续跑、停止或批准任何东西。往报告里放指标计算之外的数字。

**为什么从不调用模型。** 告警如果依赖模型，模型一宕机，告警恰好也哑了。日报完全由模板生成：`render_daily_report` 可以附带一段模型写的叙述，但 `Runtime._report_text` 从不传入。

**目前没有启动的部分。** 运行时自带的告警规则清单是空的（`DEFAULT_ALERT_RULES`）；外部监测（`ExternalMonitor`）只在环境变量里两个心跳 URL 都设了时才运行。向真实的 Telegram 和邮件投递也还没有验证过。

**代码。** [`observer/`](../../../src/growbridge/observer/)：`service.py`、`alerts.py`、`outbox.py`、`metrics.py`、`report.py`、`health.py`、`channels.py`。另见[通知、日报与备份](Notifications-Reports-and-Backup.md)。

## 模型 API 不可用时，哪些还照常工作

`Runtime.tick` 从不调用模型，所以 tick 上的一切照常：样本入库、执行 Agent、恢复的后续处理、告警、通知投递、日报、备份和健康检查。已批准的阶段会一直跑到结束，包括结束动作。养护规则、保护规则和关泵联锁继续生效。操作员仍然可以在工作台审批、启动、暂停、续跑、接管和灌溉。

停下来的只是非模型不可的工作：新草稿、分析和报告。某次模型调用失败，只会把那一个任务转到 `needs_attention` 并产生一条告警。如果启动时模型客户端建不起来，守护进程发出一条 `model_client` 告警，然后在没有模型角色循环的情况下继续服务。

对应的测试是 [`tests/e2e/test_e2e_agents.py`](../../../tests/e2e/test_e2e_agents.py) 里的 `test_tick_never_calls_a_model` 和 `test_stage_runs_to_its_end_while_the_model_fails_on_every_call`。

## 另见

- [架构总览](Architecture.md)
- [控制与安全模型](Control-and-Safety-Model.md)
- [工作流与状态机](Workflow-and-State-Machines.md)
- [科研方法](Research-Methodology.md)
- [HTTP、工作台与 MCP 接口](API-Reference.md)
- [配置参考](Configuration-Reference.md)
- [架构设计文档](../../diagri-agent-architecture.zh-CN.md)第 2 节和第 5 到 9 节
