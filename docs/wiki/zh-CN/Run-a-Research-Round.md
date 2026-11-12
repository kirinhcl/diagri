# 运行一轮研究

[English](../en/Run-a-Research-Round.md)

这一页写给跟着一个研究轮次从目标走到报告交付的操作员。每一步都写明：谁在动作，操作员用哪个工作台请求或命令，这一步之后轮次和阶段各处于什么状态。

> **状态。** 操作员可以通过 `/wb` 发起并掌控一轮研究：创建项目、研究协议和轮次，设置模型调用预算，提出目标，批准之前读取运行单，阶段停止后做选择，以及中止轮次。这条路径只在测试里跑过：模拟的 AC5、脚本化的模型、进程内的 HTTP 客户端（[`test_e2e_http_round.py`](../../../tests/e2e/test_e2e_http_round.py)）。它没有对着 `serve` 进程、真实模型或真实设备跑过。这些步骤没有网页，也没有 CLI 命令。有些读取仍然没有路由，文中标为**无路由**，页尾会再列一遍。见[状态与已知限制](Status-and-Known-Limitations.md)。

## 工作台是什么

工作台是 `/wb` 下的一组 JSON 路由，定义在 [`workbench/api.py`](../../../src/growbridge/workbench/api.py) 和 [`workbench/rounds.py`](../../../src/growbridge/workbench/rounds.py)。它没有网页：`/` 上的控制台是仅桥接模式的那一个，从不调用 `/wb`。请求要自己发，用任何能保存 Cookie 的 HTTP 客户端都行。

每个请求都遵守这几条：

1. 发到入口地址：在现场用 `http://YOUR_LAN_HOST:LAN_PORT`，经覆盖网络用 `https://YOUR_OVERLAY_HOST`。发到别的地址会被拒绝，拒绝码 `entry`。
2. 先用 `POST /wb/login` 登录一次，请求体 `{"name": "YOUR_OPERATOR", "secret": "..."}`。响应会设置 Cookie `growbridge_operator`，有效 8 小时，并且只在签发它的那个入口上有效。
3. 除 `GET` 以外的请求都要带两个请求头：`Origin`（和你正在用的地址一致）和 `x-growbridge-ui: 1`。
4. 审批、续跑、接管、批准安全配置和设置调用预算，要求最近 300 秒内重新认证过。登录本身算一次。之后需要先发 `POST /wb/reauth`，请求体 `{"secret": "..."}`。
5. 被拒绝时，响应体是 `{"detail": {"code": "...", "message": "..."}}`。`state` 对应状态码 `409`，`session` 对应 `401`，`locked` 对应 `429`，其余拒绝码都是 `403`。请求体格式不对是 `422`。

用 `curl` 的话，开头几个请求是这样的。`login.json` 里放登录请求体，注意保密，用完删掉。

```sh
BASE=http://YOUR_LAN_HOST:9443
curl -s -c wb.cookies -H "Origin: $BASE" -H 'x-growbridge-ui: 1' \
  -H 'Content-Type: application/json' -d @login.json "$BASE/wb/login"
curl -s -b wb.cookies "$BASE/wb/stages/STAGE_ID"
curl -s -b wb.cookies -X POST -H "Origin: $BASE" -H 'x-growbridge-ui: 1' \
  "$BASE/wb/stages/STAGE_ID/approve"
```

这几条命令没有对着运行中的 `serve` 验证过：[`tests/workbench/`](../../../tests/workbench/) 里的测试是通过进程内的测试客户端发送同样的请求。

## 一轮的全貌

| 步骤 | 谁在动作 | 操作员的请求 | 之后的轮次状态 | 之后的阶段状态 |
| --- | --- | --- | --- | --- |
| 1. 提出目标 | 操作员，然后是编排 Agent | `POST /wb/projects`、`/wb/protocols`、`/wb/rounds`、`/wb/projects/PROJECT_ID/budget`、`/wb/goals` | `designing` | 还没有阶段 |
| 2. 计划送审 | 计划 Agent | `GET /wb/rounds/ROUND_ID`、`GET /wb/stages/STAGE_ID/run-sheet` | `stage_review` | `pending_review` |
| 3. 批准运行单 | 操作员 | `POST /wb/stages/STAGE_ID/approve` | `stage_review` | `pending_review` |
| 4. 启动阶段 | 操作员 | `POST /wb/stages/STAGE_ID/start` | `stage_running` | `running` |
| 5. 阶段执行 | 执行 Agent、观察与通知 Agent | 读取类路由，`pause`、`resume`、`takeover` | `stage_running` | `running`，之后 `ended` |
| 6. 数据核验 | 研究 Agent | `POST /wb/measurements`、`POST /wb/goals` | `data_verification`，之后 `analysis` | `ended` |
| 7. 分析 | 研究 Agent | `GET /wb/rounds/ROUND_ID` | `analysis` | `ended` |
| 8. 报告交付 | 研究 Agent | `GET /wb/rounds/ROUND_ID` | `delivered` | `ended` |

状态名取自 [`workflow/states.py`](../../../src/growbridge/workflow/states.py)。状态为什么这样划分，见[工作流与状态机](Workflow-and-State-Machines.md)。

## 1. 提出目标

操作员设计这一轮，给项目定下模型调用预算，然后提出目标。目标会成为编排 Agent 的一个研究任务，编排 Agent 再把设计工作交给计划 Agent。

**创建项目、协议和轮次。**

```http
POST /wb/projects

{"name": "lettuce light series"}
```

响应是 `{"project_id": "..."}`。把这个 ID 填进研究协议，然后保存协议：

```http
POST /wb/protocols

{"protocol": { ... }}
```

协议是 [`archive/models.py`](../../../src/growbridge/archive/models.py) 里的 `ResearchProtocol`：问题、假设、作物、批次、处理、分配、分析计划、阶段名称，以及轮数和区组数。[`sim/fixtures.py`](../../../src/growbridge/sim/fixtures.py) 里的 `make_protocol` 给出一份完整的例子。响应是 `{"protocol_id": "...", "version": 1, "digest": "..."}`。已保存的版本不会被覆盖：要改协议，就用更高的 `version` 再发一次。协议里有 NaN 或无穷大的数、`version` 不在 1 到 1000000 之间、或者某个 ID 超过 100 个字符，都会被拒绝，状态码 `422`。然后创建轮次，它使用协议最新保存的版本。

```http
POST /wb/rounds

{"project_id": "PROJECT_ID", "protocol_id": "PROTOCOL_ID"}
```

响应是 `{"round_id": "...", "state": "designing"}`。这些 ID 要自己记下来：没有路由能列出项目或轮次。

**设置调用预算。** 没有预算时，每次模型运行都会被拒绝，拒绝码 `budget`。这个请求需要最近重新认证过。

```http
POST /wb/projects/PROJECT_ID/budget

{"max_calls": 50, "max_cost": 100.0}
```

`max_calls` 是模型调用次数，`max_cost` 的单位是美元，按 token 数和一个标价估算。响应重复这两个上限，并给出 `remaining_calls` 和 `remaining_cost`。再设一次只改上限，已经记下的用量保留。上限设为 `0`，这个项目就不再发起模型调用，新的目标也会被拒绝。

**提出目标。**

```http
POST /wb/goals

{"project_id": "PROJECT_ID", "round_id": "ROUND_ID", "goal": "Does more light speed up canopy growth?"}
```

响应是 `{"task_id": "...", "state": "in_progress", "reused": false}`。目标现在是一个归编排 Agent 所有的研究任务。配置了 `roles` 并且模型客户端建得起来时，`serve` 每 30 秒运行一次未完成的模型任务，见[启用 DiAGRI](Enable-DiAGRI.md)。可选字段有 `round_id`、`constraints`（一组短文本）和 `request_id`（8 到 100 个字母、数字、`_` 或 `-`）。同样的请求带着同一个 `request_id` 再发一次，会返回第一次建的任务并带上 `"reused": true`，不会新建任务。不带 `request_id` 时，每次请求都新建一个任务。

| 拒绝码 | 怎么办 |
| --- | --- |
| `budget` | 项目还没有调用预算，或者预算已经用完。先设置或提高预算，再提一次目标。 |
| `state` | 项目或轮次不存在，轮次属于别的项目，协议的这个版本已经存在而内容不同，或者这个 `request_id` 已经用过、而当时的目标文本、轮次或约束条件和这次不一样。 |
| `reauth_required` | 只有设置预算会要求。先发 `POST /wb/reauth`，再重复请求。 |

随时可以读取轮次：

```http
GET /wb/rounds/ROUND_ID
```

响应里有 `state`、`awaiting_choice`、`stages_done`、`stage_total`、协议的 ID 和版本、`snapshot_id`、`report_artifact_id`，以及 `stages`：一组 `{"stage_id": "...", "state": "..."}`。新建的轮次处于 `designing`，还没有阶段。

真实模型拿到目标后会怎么做，没有验证过。测试用的是脚本化的模型，见 [`test_e2e_http_round.py`](../../../tests/e2e/test_e2e_http_round.py)。

## 2. 计划送审

计划 Agent 先用 `validate_run_sheet` 检查运行单，再用 `save_plan_draft` 提交。带有阻断性问题的运行单不会被保存。保存成功后，阶段以 `pending_review` 状态建立，轮次进入 `stage_review`。到这里为止，设备上没有发生任何写入。

守护进程之外的模型角色，或者操作员本人，也可以经 HTTP 提交运行单：

```http
POST /wb/drafts/run-sheet

{"round_id": "ROUND_ID", "run_sheet": { ... }}
```

响应是 `{"stage_id": "...", "findings": [...]}`。请求体里写“已批准”之类的话不起任何作用：草稿永远不等于审批。运行单里有 NaN 或无穷大的数时，请求以 `422` 被拒绝，什么都不保存。

操作员能做的：`GET /wb/rounds/ROUND_ID` 的 `stages` 里会出现这个新阶段，状态是 `pending_review`。先读一下要你批准的内容：

```http
GET /wb/stages/STAGE_ID/run-sheet
```

响应里有完整的 `run_sheet`、它的 `run_sheet_version` 和 `run_sheet_digest`、此刻的校验结果 `findings`，以及 `blocking`：有阻断性问题、批准会被拒绝时为 `true`。读取不改变任何东西。模型角色调不了这个路由。读取已保存的研究协议**无路由**。

## 3. 批准运行单

```http
POST /wb/stages/STAGE_ID/approve
```

应该得到审批记录，其中有 `operator`、`run_sheet_version`、`run_sheet_digest` 和 `recovery_number`。把 `run_sheet_digest` 和第 2 步读到的那个对一下：不一样的话，说明中间有人提交了新版本，你批准的是新版本。阶段仍然是 `pending_review`：批准不会启动阶段。

| 拒绝码 | 怎么办 |
| --- | --- |
| `reauth_required` | 先发 `POST /wb/reauth`，再批准一次。 |
| `approval_invalid` | 运行单有阻断性问题，需要提交新版本。 |
| `state` | 阶段不在 `pending_review`。先读一下它的状态。 |

批准之后如果又提交了运行单的新版本，原来的审批作废。

## 4. 启动阶段

```http
POST /wb/stages/STAGE_ID/start
```

应该得到 `"state": "running"` 和一个 `right_number`；运行单有养护规则时，还有 `care_right`。轮次进入 `stage_running`。

| 拒绝码 | 怎么办 |
| --- | --- |
| `approval_invalid` | 没有有效的审批，或者批准之后运行单、设备能力或恢复编号变了。重新批准。 |
| `safety_conflict` | 某条保护规则要动的通道，在运行单里是设备自管的。需要改运行单或安全配置。 |
| `interlock` | 关泵未确认。见[故障处理手册](Troubleshooting-Runbook.md)。 |
| `state` | 这台设备上还有别的阶段没结束，或者正在核对。 |

## 5. 阶段执行

执行 Agent 大约每秒按运行单评估一次：定时动作、反馈规则、保护规则。观察与通知 Agent 负责告警和日报。这里不涉及模型，所以模型角色没启用时阶段照样执行。

| 要做什么 | 发送 |
| --- | --- |
| 读取阶段 | `GET /wb/stages/STAGE_ID` |
| 读取未解决的告警，把某条标为已读 | `GET /wb/alerts`、`POST /wb/alerts/EVENT_ID/read` |
| 读取某次写入的回执 | `GET /wb/receipts/REQUEST_ID` |
| 记录一次人工测量 | `POST /wb/measurements` |
| 暂停 | `POST /wb/stages/STAGE_ID/pause`，请求体可选 `{"reason": "..."}` |
| 续跑 | `POST /wb/stages/STAGE_ID/resume`（需要重新认证） |
| 人工接管 | [人工接管、灌溉与交还](Manual-Takeover-and-Irrigation.md) |

测量的请求体包含 `experiment_id`、`batch`、`plant_id`、`layout_version`、`measured_at`（UTC 秒）、`position`、`method`、`metric`、`value` 和 `unit`。要更正以前的一条测量，加上 `corrects` 并填那条记录的 ID；原记录会保留。

系统可能自己把阶段暂停，例如 BLE 中断影响了执行，或者有人在设备面板上改了设置。各种情况见[故障处理手册](Troubleshooting-Runbook.md)。设备状态和运行单不一致，或者有写入结果未知时，`resume` 会被拒绝，拒绝码 `state`。

运行单规定的时长到了以后，执行 Agent 写入结束动作并回读。结束动作确认后，阶段进入 `ended`。协议里还有后续阶段时，轮次回到 `stage_review`；最后一个阶段结束后，轮次进入 `data_verification`。下一阶段等待审阅期间，已结束阶段的养护规则继续执行。

> **关于停止。** `POST /wb/stages/STAGE_ID/stop` 会让阶段以 `stopped` 结束。之后轮次等你做选择，选择没做之前不能提交新的运行单，见下一节。除非确实要结束这个阶段的工作，否则用暂停，不要用停止。

### 阶段停止之后，以及中止

轮次在等待时，`GET /wb/rounds/ROUND_ID` 的 `awaiting_choice` 里是被停止阶段的 ID。选择接下来怎么办：

```http
POST /wb/rounds/ROUND_ID/choice

{"choice": "redo"}
```

| `choice` | 结果 | 之后的轮次状态 |
| --- | --- | --- |
| `redo` | 这个阶段重做：可以提交新的运行单。 | `stage_review` |
| `next` | 被停止的阶段算作完成，可以提交协议里下一个阶段的运行单。协议里没有后续阶段时被拒绝，拒绝码 `state`。 | `stage_review` |
| `verify` | 用已经采到的数据进入数据核验。 | `data_verification` |
| `abort` | 等同于中止轮次。 | `aborted` |

轮次只要还不是 `delivered` 或 `aborted`，不管有没有被停止的阶段，都可以中止：

```http
POST /wb/rounds/ROUND_ID/abort
```

这一轮的每个阶段交回它持有的写入权。还没结束的阶段变成 `stopped`，它们的审批作废。轮次变成 `aborted`，不能再打开。此后结束动作不会执行，这一轮的养护规则也停了，设备停留在最后一次写入之后的样子。唯一的例外是还在进行的水泵周期：它会被提前结束，关泵照常写入。安全配置里的保护规则不属于某一轮，继续有效。这两个请求都不要求重新认证。没有可选的东西，或者轮次已经是终态时，它们被拒绝，拒绝码 `state`。

## 6. 数据核验

研究 Agent 用 `freeze_dataset` 工具冻结这个阶段的数据快照。快照完整（覆盖率不低于 0.9）并且通过校验时，轮次进入 `analysis`；否则停在 `data_verification`。

人工测量必须在快照冻结之前用 `POST /wb/measurements` 记录进去。

研究 Agent 要有一个研究任务才会做这件事。端到端测试里，操作员用 `POST /wb/goals` 提出第二个目标，脚本化的编排 Agent 把它交给研究 Agent。真实模型是否也这样做，没有验证过。

快照让轮次往前走之后，`GET /wb/rounds/ROUND_ID` 会给出 `snapshot_id`。查看快照的内容或覆盖率**无路由**。

## 7 和 8. 分析与报告

研究 Agent 分析冻结的快照，然后调用 `publish_research_report`。报告保存为数据目录下 `agent_work/reports/` 里的 `research_report_<artifact id>.json`，并在项目档案里登记为 `research_report` 类型的产物。正式报告会让轮次进入 `delivered`。需要复核的报告会让轮次留在 `analysis`。`GET /wb/rounds/ROUND_ID` 给出轮次状态；报告发布后，还给出它的 `report_artifact_id`。

读取报告、读取或列出研究任务、处理 `needs_review` 或 `needs_attention` 的任务，都**无路由**。`GET /wb/alerts` 里类型为 `agent_task` 的告警，说明某个模型任务失败了或者需要处理。

## 目前没有路由或命令的步骤

- 列出项目或轮次，读取已保存的研究协议。
- 只读取调用预算而不设置它。
- 读取某个研究任务，或列出一个项目的任务。
- 读取阶段历史或暂停原因。
- 撤销审批，给执行中的阶段切换运行单。
- 添加证据卡。
- 读取日报、数据快照或研究报告。

其中大部分功能在服务里已经有对应的方法，不少在 [`workflow/service.py`](../../../src/growbridge/workflow/service.py) 里。路由和命令还没有。一轮研究的任何一步都没有 CLI 命令。

## 另见

- [启用 DiAGRI](Enable-DiAGRI.md)
- [人工接管、灌溉与交还](Manual-Takeover-and-Irrigation.md)
- [故障处理手册](Troubleshooting-Runbook.md)
- [工作流与状态机](Workflow-and-State-Machines.md)
- [HTTP、工作台与 MCP 接口](API-Reference.md)
- [拒绝码与事件类型](Denial-Codes-and-Events.md)
