# 拒绝码与事件类型

[English](../en/Denial-Codes-and-Events.md)

这一页写给需要看懂一次拒绝、一个阶段事件或一个动作状态的操作员和开发者。它列出全部拒绝码、全部阶段事件类型和全部动作状态，并说明各自从哪里来。

这些条件是从代码和测试里读出来的，而测试只在模拟的 AC5 上运行，见[状态与已知限制](Status-and-Known-Limitations.md)。

## 拒绝码

一次拒绝就是 [`ports.py`](../../../src/growbridge/ports.py) 里的异常 `Denied(code, message)`。`Denied` 的文档字符串列了 38 个拒绝码，代码里抛出的也正好是这 38 个。工作台把拒绝转成 HTTP 响应：`state`、`lock_taken` 和 `greenhouse_busy` 是 409，`session` 是 401，`locked` 是 429，其余都是 403，见 [HTTP、工作台与 MCP 接口](API-Reference.md#工作台路由)。

| 拒绝码 | 含义 | 由谁抛出 | 调用方该怎么做 |
| --- | --- | --- | --- |
| `host_unregistered` | 本机不是这台设备登记的写入主机，或者已经登记了另一台主机。 | 控制服务（[`control/service.py`](../../../src/growbridge/control/service.py)）；[`runtime.py`](../../../src/growbridge/runtime.py) 的 `register_write_host` | 从已登记的主机上写入。`growbridge host register` 可以登记本机；已经登记了别的主机时会被拒绝。 |
| `controls_disabled` | 配置文件里 `controls_enabled` 是 `false`。 | 控制服务 | 设置 `controls_enabled = true` 并重启守护进程。 |
| `right_invalid` | 写入权不存在、已撤销，或属于更早的恢复编号；人工写入权没有绑定操作员；灌溉请求用的不是人工写入权；或者排队中的动作在发送前被作废。 | 控制服务、[`control/rights.py`](../../../src/growbridge/control/rights.py) | 不要重复同一个请求。通过工作流重新取得写入权（启动、恢复或接管阶段），再发新的请求。 |
| `right_held` | 这台设备的阶段写入权已被持有，此时又申请阶段写入权或人工写入权。 | 控制服务 | 先把持有写入权的阶段暂停、停止或接管。 |
| `scope` | 请求超出了写入权或调用方的范围：不是这台设备，通道或档位不在写入权列出的范围里，阶段、实验或操作员对不上，灌溉时间过长或不是"开泵"。对模型工具来说：任务编号不是这次运行所对应的任务，在调度运行之外发起调用，任务、阶段、轮次、实验、数据快照、产物或计算作业属于其他项目或其他角色，实验被两个项目同时占用，或者快照里含有留出数据的结果。对工作流来说：运行单的 `experiment_id` 属于另一个项目。对人工测量来说：`experiment_id` 没有任何阶段拥有（`POST /wb/measurements`）。 | 控制服务、`control/rights.py`、计算服务、工作流服务（`WorkflowService.submit_run_sheet`）、模型工具的处理函数（[`agents/`](../../../src/growbridge/agents)） | 修改请求。原样重发还会被拒绝。 |
| `pump_on_forbidden` | 一次普通写入试图开泵。 | `control/rights.py`；[`workbench/api.py`](../../../src/growbridge/workbench/api.py) 的 `POST /wb/manual/{channel}` | 在局域网入口上使用 `POST /wb/irrigation`。 |
| `interlock` | 关泵联锁生效：关泵没有得到确认。普通写入被拒绝，阶段也不能启动或恢复。 | 控制服务；工作流服务（[`workflow/service.py`](../../../src/growbridge/workflow/service.py)） | 到现场检查水泵，然后用 `POST /wb/stages/{stage_id}/onsite-check` 记录现场核对。执行 Agent 会持续尝试关泵。 |
| `not_connected` | 没有有效的 BLE 连接，或者读不到设备状态。 | 控制服务 | 等连接恢复后重新发送请求。 |
| `stale` | 最新样本比 `stale_seconds` 更旧。阶段写入和人工写入都要求数据新鲜。 | 控制服务 | 等到有新样本（`GET /health` 里可以看到 `stale`），再重新发送请求。 |
| `request_id_reused` | 这个 `request_id` 已经用于另一组参数。 | 控制服务 | 新动作用新的 `request_id`。只有重发完全相同的请求时才复用 ID。 |
| `not_operator` | 调用方既不是操作员也不是模型角色，或者操作员名字为空。 | [`workflow/permissions.py`](../../../src/growbridge/workflow/permissions.py)；控制服务（`onsite_check`）；`AlertBook.mark_read` | 以已登录的操作员身份重做这个操作。 |
| `model_role` | 模型角色请求了阶段、审批或控制类操作；给角色配置了不属于它的工具；该角色不是模型角色；或者没有为它配置模型。 | `workflow/permissions.py`；[`agents/tools.py`](../../../src/growbridge/agents/tools.py)；[`agents/dispatch.py`](../../../src/growbridge/agents/dispatch.py) | 模型角色对此无能为力，需要操作员来做。如果是配置文件里的 `tools` 引起的，去掉那个工具名。 |
| `reauth_required` | 这个操作要求最近 300 秒内重新认证过。 | `workflow/permissions.py` | 调用 `POST /wb/reauth`，然后重发请求。 |
| `entry` | 请求不是从已登记的入口进来的，没有通过 `Origin` 和 `X-GrowBridge-UI` 检查，进来的入口和会话所属的入口不一致，或者该操作只在局域网入口提供。 | `workbench/api.py` | 使用 `lan_hosts` 或 `overlay_hosts` 里的地址和对应的端口，并带上这两个请求头。灌溉要从局域网入口发起。 |
| `approval_invalid` | 阶段没有有效审批；审批已经对不上（运行单内容或版本、阶段、实验、设备、能力版本或恢复编号变了）；运行单有阻断性问题；或者安全配置没有审批人，或给设备没有的传感器设了冻结读数门槛。 | 工作流服务；控制服务（`approve_safety`） | 解决校验发现的问题，再重新审批这个阶段；安全配置则改正后重新批准。 |
| `state` | 对象不存在，当前状态不允许这个操作，或者在请求处理期间发生了变化。对证据来说：核实一张不存在的卡。对分析来说：协议版本下已有阶段启动之后还要冻结脚本，没有冻结脚本就要运行，或者运行一份被后来的更正作废的快照。对报告来说：脚本已冻结，而引用的某份快照的运行还没有结束。对留出集来说：项目里已经记录了留出批次的结局，那些数据可能已经被看过。对计算尝试来说：结算一个已经是终态或不存在的尝试（`POST /wb/compute/attempts/{attempt_id}/settle`），重试一个没有失败的尝试，或者下载一个已由操作员了结（包括在下载过程中被了结）的尝试的输出。另外：冻结脚本时已经有快照或测量，或者快照背后的阶段或测量早于冻结。对安全配置来说：版本不高于这台设备以前批准过的最高版本，不论那个版本是否仍然生效（`safety_version_not_above`）。 | 工作流服务、[`workflow/store.py`](../../../src/growbridge/workflow/store.py)、[`workflow/tasks.py`](../../../src/growbridge/workflow/tasks.py)、`workbench/api.py`、[`workbench/analysis.py`](../../../src/growbridge/workbench/analysis.py)、计算服务、留出数据登记、`AlertBook`、模型工具的处理函数、控制服务（`approve_safety`） | 先读取当前状态，例如 `GET /wb/stages/{stage_id}`，再决定怎么做。 |
| `safety_conflict` | 已批准的安全配置里有保护规则要动某个通道，而运行单没有把这个通道设为主机控制。 | 工作流服务，依据 `ControlService.safety_conflicts` | 修改运行单（生成新版本）或安全配置，然后重新审批。 |
| `budget` | 项目的调用预算或费用预算用完了，或者从未设置；或者任务超过了修订次数上限或委派深度上限。 | [`agents/budget.py`](../../../src/growbridge/agents/budget.py)；`workflow/tasks.py` | 停下来。这个任务需要人来决定。操作员用 `POST /wb/projects/PROJECT_ID/budget` 设置或提高项目的预算；已经进入 `needs_attention` 的任务不会因此恢复。 |
| `session` | 没有会话，或者会话无效、已过期、早于当前恢复编号；名字或密码不对；或者角色令牌不匹配。 | `workbench/api.py`、[`workbench/auth.py`](../../../src/growbridge/workbench/auth.py) | 用 `POST /wb/login` 重新登录。 |
| `member` | 提交者没有对应到 CSC 项目成员。 | 计算服务（[`compute/service.py`](../../../src/growbridge/compute/service.py)） | 只在配置了计算服务时才会出现，见下面的说明。 |
| `quota` | 没有登记任务预算或项目余额；作业会超出任务预算、服务上限或项目余额；或者达到了模板的重试上限。对模型工具来说：一个计划任务已经提议了 20 张证据卡。 | 计算服务、[`agents/handlers_evidence.py`](../../../src/growbridge/agents/handlers_evidence.py) | 计算相关的情况只在配置了计算服务时才会出现：请通过工作台录入余额和任务预算（[启用 DiAGRI](Enable-DiAGRI.md)第 5 步）。提议数量的上限：请操作员自己录入这张卡。 |
| `param` | 计算作业的模板或模板版本不存在，参数未知或缺失，取值的类型或范围不对（浮点数不是有限的、文本太长、含控制字符，或者不匹配模板里的 pattern），结算请求没有写原因，或者输入不是它所在快照里可用的文件或文件夹（或没有输入根目录或输入检查：带输入的作业此时一律被拒绝）。对证据来说：模型提议 `local` 卡（只有操作员才能记录本地测量）。对报告来说：同一个实验被列进两个轮次，处理不存在，或者测量数据和分配对不上。对冻结的分析脚本来说：脚本为空，或者编译不过（语法错误或含 NUL 字节）。对报告来说：引用的快照来自不止一个协议版本，或者来自别的协议。 | 计算服务；[`agents/handlers_report.py`](../../../src/growbridge/agents/handlers_report.py)、[`agents/handlers_evidence.py`](../../../src/growbridge/agents/handlers_evidence.py) | 改正输入后重新发送。 |
| `clock_unsynced` | 时钟没有同步，数据不能冻结。 | [`archive/snapshot.py`](../../../src/growbridge/archive/snapshot.py) | 等时钟同步后再冻结。 |
| `script_hash` | 分析脚本和研究协议里的哈希不一致，或者和这个协议版本已经冻结的脚本不一致（路由 `POST /wb/protocols/{protocol_id}/analysis`）。 | [`research/analysis.py`](../../../src/growbridge/research/analysis.py) | 使用已冻结的脚本。 |
| `snapshot_incomplete` | 数据快照被标记为不完整，或者它的文件和清单对不上。 | `research/analysis.py`；[`agents/handlers_researcher.py`](../../../src/growbridge/agents/handlers_researcher.py)；`agents/handlers_report.py` | 重新冻结一个快照，改用新的。 |
| `already_run` | 这个快照上已经跑过确认性分析，或者正在跑（路由 `POST /wb/analysis/runs`）。 | `research/analysis.py` | 不要再跑；确认性分析只运行一次。 |
| `batches` | 登记留出数据时，开发批次少于 2 个，没有留出批次，同一个批次同时在两边，或者批次名为空或重复（路由 `POST /wb/holdouts`）。 | [`research/holdout.py`](../../../src/growbridge/research/holdout.py) | 登记时至少提供 2 个开发批次和 1 个留出批次。 |
| `model_unregistered` | 评估之前，模型没有在这份留出数据上登记，或者给出的模型哈希不是登记过的那个。 | `research/holdout.py` | 先登记模型、特征和预处理方式。 |
| `sandbox_unavailable` | 当前平台没有隔离后端，所以不会运行任何分析脚本。 | [`research/sandbox.py`](../../../src/growbridge/research/sandbox.py) | 换到有沙箱的平台上运行分析（这份代码里是 macOS）。 |
| `unsettled` | 控制服务还没有启动完；旧传输停止还没有得到确认；或者之前有动作结果未知。 | 控制服务 | 等启动完成。其他情况下，要先通过回读或现场核对把结果确定下来，普通写入才能继续。 |
| `cooldown` | 有一次灌溉正在进行，或者距上一次开始还不到 `pump_cooldown_seconds`。 | 控制服务 | 等一等，再重新发送灌溉请求。 |
| `unavailable` | 某个可选后端没有配置：搜索、计算服务、沙箱或留出数据登记。 | [`agents/handlers_common.py`](../../../src/growbridge/agents/handlers_common.py) | 调用方无法解决；守护进程构建时就没有这个后端。 |
| `locked` | 15 分钟内登录失败次数过多：同一名字从同一地址失败 5 次，或者同一名字从所有地址累计失败 25 次。 | `workbench/auth.py` | 等到这些失败记录超过 15 分钟。 |
| `lock_taken` | 要锁定的温室里有已被别人锁定的，这次一个也没锁上（多用户）。 | `workflow/locks.py` | 去掉被占用的温室后重新锁定。 |
| `greenhouse_busy` | 温室上还有没结束的阶段，不能释放（多用户）。 | `workflow/locks.py` | 先停止或结束阶段（或中止轮次），再释放。 |
| `not_owner` | 管理员试图操作别人的项目；管理员对别人的阶段只能暂停和停止（多用户）。 | `workflow/access.py` | 请所有者操作，或先停用其账号再把项目转出。 |
| `not_lock_holder` | 项目所有者没有锁定阶段或运行单用到的温室（多用户）。 | `workflow/access.py`、`workbench/api.py` | 先锁定这个温室。 |
| `admin_only` | 只有管理员能做（多用户）。 | `workflow/access.py` | 请联系管理员。 |

关于哪些拒绝码实际会出现。`member`、`quota`，以及 `param`、`scope`、`state` 和 `snapshot_incomplete` 里和计算有关的情况，只在守护进程配置了计算服务时才会出现。后三者来自对计算输入的检查：别的项目的快照或含有留出结果的快照（`scope`）、已被作废的快照（`state`）、校验不通过的快照（`snapshot_incomplete`）。`batches` 只由 `HoldoutRegistry.register` 抛出，而 `src/` 里没有任何地方调用它。`script_hash` 和 `already_run` 来自 `ConfirmatoryRunner.freeze_analysis` 和 `run_frozen`，经由工作台的两个分析路由出现。另外，工作台在 HTTP 422 的响应体里也用了 `param` 这个词作为 code，那不是 `Denied`。

请求在刚提交时被拒绝，动作账本里不会留下记录，所以同一个 `request_id` 可以再发一次。如果是在发送前的复核环节被拒绝，这个动作会以 `void` 状态存下来；之后用同一个 `request_id` 只会拿回这条记录，所以需要换一个新的 ID。

| 谁收到这次拒绝 | 它看到什么 |
| --- | --- |
| 工作台的 HTTP 客户端 | 上面说的状态码，以及响应体 `{"detail": {"code": "<code>", "message": "<text>"}}`。 |
| 操作员控制台（`/workbench`） | 38 个拒绝码各有一条中文或英文的白话提示，并说明下一步该做什么。控制台自己还有三个服务器不会发出的码：`validation`（表单没通过自己的检查，或服务器返回 `422`）、`network`（连不上服务器）和 `reauth_failed`（重新认证对话框里的口令不对）。见 [`web/workbench/`](../../../src/growbridge/web/workbench) 里的 `denials.js`。 |
| 模型角色（在工具调用里） | 一条错误的工具结果 `Error: denied (<code>): <message>`，最多 500 个字符。 |
| 调度器（工具调用之外，例如 `budget`） | 任务转为 `needs_attention`，原因是 `<code>: <message>`。 |
| 执行 Agent | 这一拍跳过这次写入，并把 `<request_id>: <code>` 记入 `TickReport.denied`。之后的 tick 会再试。 |
| 工作流服务（处理阶段事件时） | `state` 表示阶段已经往前走了，事件被忽略。其他拒绝码会抛回给上报方。 |
| `growbridge host register` | 提示信息，退出码 2。 |

## 阶段事件

`ports.py` 的 `StageEventKind` 有 12 个成员。其中 11 个由执行 Agent（[`executor/engine.py`](../../../src/growbridge/executor/engine.py)）上报，`alert_pause` 由观察与通知 Agent（[`observer/service.py`](../../../src/growbridge/observer/service.py)）上报。两者都调用 `WorkflowService.report`。

| 类型 | 由谁上报 | 条件 | `detail` 字段 | 工作流服务怎么处理 |
| --- | --- | --- | --- | --- |
| `disconnect_affects` | 执行 Agent | 在发现连接恢复的那一拍，阶段处于 `running`，并且至少有一条原因成立：`due_action`、`device_differs`、`unknown_result`、`gap_too_long`。 | `reasons`、`seconds`、`state_unreadable` | 暂停阶段 |
| `readings_stale` | 执行 Agent | 阶段处于 `running`，连接正常，但在运行单的 `sampling.max_gap_seconds` 之内没有收到有效读数。 | 无 | 暂停阶段 |
| `readings_stale` | 执行 Agent | 阶段处于 `running`，读数是新鲜的，但回读设备状态持续失败，时间超过了 `sampling.max_gap_seconds`。 | `reason` = `"state_unreadable"`、`seconds` | 暂停阶段 |
| `external_change` | 执行 Agent | 阶段处于 `running`，设备状态和执行 Agent 在本时段最后确认的值不一致。 | `differences`：由 `channel`、`field`、`expected`、`actual` 组成的列表 | 暂停阶段 |
| `external_change` | 执行 Agent | 阶段处于 `running`，同一个通道上连续 3 次写入以 `failed` 告终。 | `channel`、`level`、`failed` | 暂停阶段 |
| `clock_anomaly` | 执行 Agent | 阶段处于 `running`，而墙上时钟不可信：主机时间没有同步，或者时钟跳变超过 5 秒。 | 无 | 暂停阶段 |
| `result_unknown` | 执行 Agent | 阶段处于 `running`，控制服务里有结果未知且尚未确定的动作。 | `request_ids` | 暂停阶段 |
| `pump_off_unconfirmed` | 执行 Agent | 关泵联锁生效，有活动阶段，并且这一拍的关泵没有得到确认。 | 无 | 把阶段转入 `recovery_check` |
| `transport_unconfirmed` | 执行 Agent | 阶段处于 `running`、`paused` 或 `manual`，而旧传输停止还没有得到确认。 | 无 | 把阶段转入 `recovery_check` |
| `end_condition_met` | 执行 Agent | 阶段处于 `running`，`end_pending` 为 false，并且从 `started_at` 起已经过了 `duration_seconds`。 | 无 | 保持 `running`，并设置 `end_pending` |
| `end_actions` | 执行 Agent | `end_pending` 为 true，并且主机控制通道上的每个结束动作都已发出。水泵不在其中。 | `confirmed` | `confirmed` 为 true：结束阶段。`confirmed` 为 false：把阶段转入 `recovery_check`。 |
| `alert_pause` | 观察与通知 Agent | 一条带 `pause_stage` 的告警规则触发且有活动阶段；或者运行中的阶段所依赖的传感器读数冻结（这时 `rule` 是 `frozen:<传感器>`，`period` 是冻结时段）。 | `rule`、`alert`（冻结引起的暂停还有 `period`；只有存在未解决的告警时才有 `alert`） | 暂停阶段 |
| `rule_pause` | 执行 Agent | 阶段处于 `running`，一条 `on_missing = "pause"` 的反馈规则拿不到它那个传感器的有效读数。 | `rules` | 暂停阶段 |
| `max_wait_expired` | 执行 Agent | 阶段处于 `paused` 的时间超过了运行单的 `max_wait_seconds`。 | 无 | `on_expiry = "stop"`：停止阶段。否则保持 `paused`，并把到期这件事写入历史。 |

执行 Agent 为处于 `running` 的阶段上报的每个事件，还会带上 `detail.right_number`，也就是观察到该事件时所持阶段写入权的编号。被采纳的事件，其 `detail` 会随阶段历史一起保存（`wf_history.detail`）。事件让阶段暂停或进入 `recovery_check` 时，运行时会产生告警 `stage_waiting`，写明事件名和这份 `detail`；见[故障处理手册](Troubleshooting-Runbook.md)。`runtime.py` 的 `DEFAULT_ALERT_RULES` 是空的，所以守护进程里没有能上报 `alert_pause` 的告警规则。

| 工作流服务里的结果 | 什么情况 | 效果 |
| --- | --- | --- |
| 忽略 | 阶段不存在，或者这个事件 ID 已经处理过。 | 无 |
| 丢弃 | `detail.right_number` 不是阶段现在持有的阶段写入权；或者阶段当前的状态不适用这个事件。 | 事件记录为 `dropped`。 |
| 暂停阶段 | 事件属于七种暂停类型之一，并且阶段处于 `running`。 | 状态变为 `paused`，阶段写入权被撤销，记下 `paused_at`。 |
| 把阶段转入 `recovery_check` | 阶段处于 `running`、`paused` 或 `manual`；对 `end_actions` 来说，是处于 `running` 且 `end_pending`。 | 状态变为 `recovery_check`；阶段、人工和养护写入权都被撤销；`prior_state` 保留之前的状态。 |
| 结束阶段 | `end_actions` 且 `confirmed` 为 true，阶段处于 `running` 且 `end_pending`。 | 状态变为 `ended`，阶段写入权被撤销。还有阶段没跑时，轮次转到 `stage_review`，否则转到 `data_verification`。 |
| 停止阶段 | `max_wait_expired`，阶段处于 `paused`，且运行单写的是 `on_expiry = "stop"`。 | 状态变为 `stopped`。轮次随后等待一个选择（`awaiting_choice`）。 |

被采纳的事件会和状态变化在同一个事务里记录为 `applied`。同一个事件 ID 最多推进阶段一次。执行 Agent 生成的 ID 形如 `<kind>:<stage_id>:<key>:<phase start>`，每个 ID 在一个时段里只上报一次；一个时段指阶段、阶段状态和阶段写入权三者的一种组合。

## 动作状态

[`archive/models.py`](../../../src/growbridge/archive/models.py) 的 `ActionState` 有 6 个成员。动作账本里的每条记录都处于其中一种状态。中文标签见[术语表](Glossary.md#状态值)。

| 状态 | 含义 | 什么时候进入 |
| --- | --- | --- |
| `pending` | 动作已记入账本，还什么都没有发送。 | 控制服务受理请求时。 |
| `maybe_sent` | 写入正在发往设备。 | 写入发出之前的那一刻。 |
| `confirmed` | 回读显示设备处于计划的档位，并且是手动模式。此时会记下 `confirmed_at` 和 `confirmed_level`。 | 写入之后的回读对上了。 |
| `unknown` | 结果未知：无法确定这次写入有没有生效。在它被确定下来（`settled_at`）之前，普通写入会以 `unsettled` 被拒绝。 | 没有收到回执，发送时连接断开，无法回读，进程在动作处于 `maybe_sent` 时停止，或者灌溉后的关泵没有得到确认。 |
| `failed` | 写入没有生效。 | 写入发不出去，设备拒绝，回读的档位不一致，或者回读的模式不是手动。 |
| `void` | 动作排了队，但从未发送。 | 启动时，它的写入权被交接时，恢复编号变化时，同一通道上的保护写入作废了它，或者发送前的复核拒绝了它。 |

`unknown` 的动作通过三种方式确定下来：回读设备状态（水泵除外），关泵得到确认（针对水泵），或者现场核对。对 `failed` 或 `void` 的动作，执行 Agent 会发一个新请求来替代，并在 `supersedes` 里写上旧请求的 ID。

## 另见

- [HTTP、工作台与 MCP 接口](API-Reference.md)
- [控制与安全模型](Control-and-Safety-Model.md)
- [工作流与状态机](Workflow-and-State-Machines.md)
- [故障处理手册](Troubleshooting-Runbook.md)
- [术语表](Glossary.md)
