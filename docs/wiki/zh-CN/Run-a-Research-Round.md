# 运行一轮研究

[English](../en/Run-a-Research-Round.md)

这一页写给跟着一个研究轮次从目标走到报告交付的操作员。每一步都写明：谁在动作，操作员用哪个工作台请求或命令，这一步之后轮次和阶段各处于什么状态。

> **状态。** 操作员可以通过 `/wb` 发起并掌控一轮研究：创建项目、研究协议和轮次，设置模型调用预算，提出目标，批准之前读取运行单，阶段停止后做选择，以及中止轮次。这条路径只在测试里跑过：模拟的 AC5、脚本化的模型、进程内的 HTTP 客户端（[`test_e2e_http_round.py`](../../../tests/e2e/test_e2e_http_round.py)）。它没有对着 `serve` 进程、真实模型或真实设备跑过。`/workbench` 的控制台为其中大部分步骤提供了表单；没有 CLI 命令。有些读取仍然没有路由，文中标为**无路由**，页尾会再列一遍。见[状态与已知限制](Status-and-Known-Limitations.md)。

## 工作台是什么

工作台是 `/wb` 下的一组 JSON 路由，定义在 [`workbench/api.py`](../../../src/growbridge/workbench/api.py) 和 [`workbench/rounds.py`](../../../src/growbridge/workbench/rounds.py)。`/` 上的控制台是仅桥接模式的那一个，从不调用 `/wb`；`/workbench` 的控制台才调用。你也可以自己发请求，用任何能保存 Cookie 的 HTTP 客户端都行。

每个请求都遵守这几条：

1. 发到入口地址：在现场用 `http://YOUR_LAN_HOST:LAN_PORT`，经覆盖网络用 `https://YOUR_OVERLAY_HOST`。发到别的地址会被拒绝，拒绝码 `entry`。
2. 先用 `POST /wb/login` 登录一次，请求体 `{"name": "YOUR_OPERATOR", "secret": "..."}`。响应会设置 Cookie `growbridge_operator`，有效 8 小时，并且只在签发它的那个入口上有效。
3. 除 `GET` 以外的请求都要带两个请求头：`Origin`（和你正在用的地址一致）和 `x-growbridge-ui: 1`。
4. 审批、续跑、接管、批准安全配置、设置调用预算、冻结分析脚本和启动分析运行，要求最近 300 秒内重新认证过。登录本身算一次。之后需要先发 `POST /wb/reauth`，请求体 `{"secret": "..."}`。
5. 被拒绝时，响应体是 `{"detail": {"code": "...", "message": "..."}}`。`state` 对应状态码 `409`，`session` 对应 `401`，`locked` 对应 `429`，其余拒绝码都是 `403`。请求体格式不对是 `422`。

用 `curl` 的话，开头几个请求是这样的。`login.json` 里放登录请求体，注意保密，用完删掉。

```sh
BASE=http://YOUR_LAN_HOST:9443
curl -s -c wb.cookies -H "Origin: $BASE" -H 'x-growbridge-ui: 1' \
  -H 'Content-Type: application/json' -d @login.json "$BASE/wb/login"
curl -s -b wb.cookies "$BASE/wb/stages/STAGE_ID"
curl -s -b wb.cookies "$BASE/wb/stages/STAGE_ID/run-sheet"   # read run_sheet_digest from the answer
curl -s -b wb.cookies -X POST -H "Origin: $BASE" -H 'x-growbridge-ui: 1' \
  -H 'Content-Type: application/json' -d '{"expected_digest": "DIGEST_YOU_READ"}' \
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
| 7. 分析 | 操作员、研究 Agent | `GET /wb/protocols/PROTOCOL_ID/analysis`、`POST /wb/analysis/runs`、`GET /wb/rounds/ROUND_ID` | `analysis` | `ended` |
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

测试用的是脚本化的模型，见 [`test_e2e_http_round.py`](../../../tests/e2e/test_e2e_http_round.py)。用真实模型时，这一步在模拟器上跑到了运行单待审，见[状态与已知限制](Status-and-Known-Limitations.md)。

## 在第一个阶段之前冻结分析脚本

只有分析方法在结局数据出现之前就已经定下来，结果才可以标为确认性（见[研究方法](Research-Methodology.md)）。在 DiAGRI 模式下，操作员用一个请求把它定下来，时间必须在这个协议的任何阶段启动之前。这个请求要求最近 300 秒内重新认证过。

```sh
curl -s -b wb.cookies -X POST -H "Origin: $BASE" -H 'x-growbridge-ui: 1' \
  -H 'Content-Type: application/json' \
  -d '{"project_id": "PROJECT_ID", "script": "print(\"analysis\")\n"}' \
  "$BASE/wb/protocols/PROTOCOL_ID/analysis"
```

响应是 `{"protocol_id": "...", "version": 1, "script_sha256": "...", "frozen_at": 1800000000.0, "note": "..."}`。其中的 `note` 说明：冻结之后脚本不能再更正。

- `script` 是 1 到 20 000 个字符的 UTF-8 文本。冻结时它只被编译，从不运行：有语法错误或含 NUL 字节的脚本以 `param` 被拒绝。**冻结之后脚本不能再更正**，只有新的协议版本才能再冻结另一份，所以发送之前请先读一遍。它连同冻结它的操作员的名字一起保存。名字来自会话，从不来自请求体。
- 它作用于协议最新保存的版本，也就是新建轮次所用的版本。要改分析，先把协议存成新版本。
- **冻结之前收集的数据永远不能是确认性的。** 因此，运行这个协议版本的某一轮里有阶段启动过，或者这样一轮所用的实验已经有快照或人工测量，冻结都会以 `state` 被拒绝。运行同样因此被拒绝（见下）。
- 只要运行这个协议版本的任何一轮里有任何一个阶段启动过，冻结就以 `state` 被拒绝：分析必须在能看到结局数据之前定下来（架构文档 6.5 节）。
- 在没有阶段启动之前，再次冻结同一份文本会得到同样的响应。同一版本换一份文本，以 `script_hash` 被拒绝。
- `GET /wb/protocols/PROTOCOL_ID/analysis?project_id=PROJECT_ID` 不要求重新认证。它给出 `started`、`frozen`（`null`，或者 `script_sha256`、`frozen_at`、`frozen_by` 和脚本原文 `script`）以及 `snapshots`：协议各轮的每一份数据快照的 `snapshot_id`、`experiment_id`、`complete` 和 `run_status`（`none`、`running`、`succeeded` 或 `failed`）。

## 在结局数据出现之前登记留出集

评价预测模型，需要它从没碰过的数据。操作员要在留出批次的任何结局测量被记录之前，先把这些批次登记下来。这个请求要求最近 300 秒内重新认证过。

```sh
curl -s -b wb.cookies -X POST -H "Origin: $BASE" -H 'x-growbridge-ui: 1' \
  -H 'Content-Type: application/json' \
  -d '{"project_id": "PROJECT_ID", "batch_ids": ["batch-3"], "development_batch_ids": ["batch-1", "batch-2"], "outcome_fields": ["yield_g"]}' \
  "$BASE/wb/holdouts"
```

响应里有服务端生成的 `holdout_id`、三个列表、`registered_at` 和 `registered_by`。留出批次和开发批次不能重叠，开发批次至少 2 个，名字不能为空或重复（`batches`；结局字段的问题是 `param`）。项目必须存在（`scope`）。

项目的任何实验里，只要已经有一条人工测量属于留出批次、又用了其中一个结局字段，登记就以 `state` 被拒绝：那些数据可能已经被看过。没有任何阶段运行、却带着这种测量的实验也一样，因为无法证明它属于别的项目。先登记，再采集。此后留出批次的结局不进入任何快照，模型工具也看不到。`GET /wb/holdouts?project_id=PROJECT_ID` 列出登记及其读取记录，不要求重新认证。目前没有任何流程用留出数据给模型打分（见[研究方法](Research-Methodology.md#预测模型与留出数据)）。

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

`findings` 里还有每个设定值（定时动作、反馈规则和养护步骤）的证据提示：`no_evidence` 表示它没有引用任何证据卡（引用了不存在的卡 ID 同样算没有，`user:...` 表示是你自己告诉计划 Agent 的）；`unverified_source` 表示这张卡还没有任何操作员核实（每个类别的卡都一样，包括 `local`：模型不能提议 `local` 卡，所以计划 Agent 提议的卡不会是 `local`；未核实的卡一律带这个提示）；`uncalibrated` 表示这张卡的数值没有用本地测量校准过。模型不能声称已校准：计划 Agent 提议的卡以“未校准”保存，你核实之后这个提示仍然保留，直到你自己证明它校准过。它们只是提示，不阻塞审批。操作员记录了核实之后，这张卡才算已核实。批准之前先读卡、核实卡：

```http
GET /wb/evidence
POST /wb/evidence/CARD_ID/verify
{"note": "对照手册第 41 页核实过", "calibrated": true}
```

只有确认这个数值已用本地测量校准过，才传 `"calibrated": true`；否则不要传，`uncalibrated` 提示就会保留。这个证明随核实记录一起保存。第一次核实为准：对已经核实过的卡再传 `"calibrated": true` 不会改变任何东西。你自己录入的卡，保留你录入的 `calibrated` 值。

列表里每张卡都有来源（`operator:<姓名>`；计划 Agent 提议的则是 `model:planner` 加任务 ID）、是否已核实、谁核实的、什么时候核实的。核实是幂等的：再核实一次，保留第一条记录；它不会修改卡片。你自己录入一张卡：

```http
POST /wb/evidence
{"source_class": "handbook", "citation": "Handbook of Lettuce Production, 3rd ed., p. 41", "claim": "200 umol m-2 s-1 适合生菜", "value": 200, "unit": "umol m-2 s-1"}
```

你录入的卡由你当场核实；响应里的 `id` 就是要告诉计划 Agent 的卡编号。这两个调用都不要求近期重新认证。

## 3. 批准运行单

```http
POST /wb/stages/STAGE_ID/approve
{"expected_digest": "第 2 步读到的 run_sheet_digest"}
```

请求体是必填的，只有这一个字段。如果运行单在你读过之后变了，答复是 `409`，代码为 `state`；重新读一遍再决定。

应该得到审批记录，其中有 `operator`、`run_sheet_version`、`run_sheet_digest` 和 `recovery_number`。`run_sheet_digest` 就是你发送的那个：服务端只批准你读过的运行单，不会批准中间提交的新版本。阶段仍然是 `pending_review`：批准不会启动阶段。

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

控制台的**实时环境**页显示每个传感器的最新读数和每个通道记录的档位，每 5 秒刷新一次。阶段运行期间，运行单控制的通道还会显示运行单此刻要求的档位；实际档位不同时，标为**与运行单不符**。下方是最近 1 小时到 7 天的趋势，阶段之内和阶段之间的数据都包括在内。读数中断时会明确提示，不会把旧读数当成当前值。

| 要做什么 | 发送 |
| --- | --- |
| 读取阶段 | `GET /wb/stages/STAGE_ID` |
| 实时查看环境：最新读数、各通道档位与运行单此刻要求的对照、趋势 | `GET /wb/environment`，或控制台的**实时环境**页 |
| 读取未解决的告警，把某条标为已读 | `GET /wb/alerts`、`POST /wb/alerts/EVENT_ID/read` |
| 读取某次写入的回执 | `GET /wb/receipts/REQUEST_ID` |
| 记录一次人工测量 | `POST /wb/measurements` |
| 查看到期的人工任务，记录完成或跳过 | `GET /wb/stages/STAGE_ID/manual-tasks`、`POST /wb/stages/STAGE_ID/manual-tasks`，或阶段页的**人工任务** |
| 执行计划内浇水（局域网入口） | `POST /wb/stages/STAGE_ID/manual-tasks/irrigate` |
| 暂停 | `POST /wb/stages/STAGE_ID/pause`，请求体可选 `{"reason": "..."}` |
| 续跑 | `POST /wb/stages/STAGE_ID/resume`（需要重新认证） |
| 人工接管 | [人工接管、灌溉与交还](Manual-Takeover-and-Irrigation.md) |

### 记录一次测量

在控制台里，测量表单把该实验已声明的人工变量列成指标下拉框（多于一个时带“选择变量”占位项），单位由变量决定；一个人工变量都没有时，表单换成一条说明。通过 HTTP，`GET /wb/experiments/EXPERIMENT_ID/variables` 列出这些变量。`POST /wb/measurements` 发现问题时以 422 `param` 拒绝，并列出找到的每一个问题：

| 问题 | 怎么办 |
| --- | --- |
| 没有已声明的变量：该实验的协议没有声明任何变量 | 协议没有声明变量的实验不能记录测量。保存一个声明了这些变量的协议版本，并用它运行新的一轮：新版本要等新一轮的某个阶段按它运行这个实验，才对该实验生效。 |
| 指标没有被声明 | 提示里列出已声明的 ID。改用其中之一，或在新的协议版本里声明这个变量，并用它运行新的一轮。 |
| 种类不对 | 该变量是 sensor 或 factor，不是人工（`manual`）变量。改选一个人工变量。 |
| 单位不对 | 提示里给出正确的单位。按这个单位填值。 |
| 数值超出 `min` 和 `max` | 边界是闭区间。检查读数；不要为了迁就错误的数值去放宽目录。 |

测量的请求体包含 `experiment_id`、`batch`、`plant_id`、`layout_version`、`measured_at`（UTC 秒）、`position`、`method`、`metric`、`value` 和 `unit`。要更正以前的一条测量，加上 `corrects` 并填那条记录的 ID；原记录会保留。

更正是一条新记录，可以同时改指标和数值。写入更正会把包含原记录的每一份数据快照和每一份报告标为失效，所以之后要重新冻结快照、重新生成报告。人工记录总是保存标准 ID。

### 人工任务

运行单里的 `manual_tasks`（浇水、测量、拍照）每天到点都需要有人在现场。阶段页按时间倒序列出每次任务，最多显示到一天后，并标出状态：未到期、待完成、已完成、延迟完成、已跳过、已错过。每次任务都要记录：

```http
POST /wb/stages/STAGE_ID/manual-tasks

{"task_id": "photo-noon", "due_at": 1800003600, "outcome": "done", "note": "tray 3"}
```

`due_at` 用列表里给出的值，指明是哪一次任务。`done_at`（UTC 秒）可选，默认是现在；它不能晚于现在，也不能早于到期时间一小时以上；到期前一小时以上的任务不能记录。记录不会被修改：再记一次，以最新的为准。到期两小时后才完成的算延迟，除非运行单允许补做（`make_up_allowed`），这时阶段结束前完成都算按时。截止时间过后一天以上才录入的记录，不论填写的 `done_at` 是什么，都算延迟；记录照常保存和显示。报告会把人工任务有超过 10% 没有按时完成的轮次算作方案偏离（见[研究方法](Research-Methodology.md)）。

带 `seconds` 的浇水任务是计划内的水泵运行。在局域网入口的阶段页上启动（`POST /wb/stages/STAGE_ID/manual-tasks/irrigate`，带 `task_id` 和 `due_at`）后，水泵在阶段写入权下运行这么多秒，阶段继续运行。完整且得到确认的运行记为已完成；被截断（阶段暂停或交接、保护写入、联锁或看门狗关泵）或没有得到确认的运行记为部分完成，带水泵实际运行的秒数和原因，算作没有按时完成。每次任务最多开一次泵（之后标为跳过也不能再开一次），过了截止时间（到期后两小时；可补做的任务为阶段结束后两小时）也不能再开。灌溉的所有检查照旧适用，见[控制与安全模型](Control-and-Safety-Model.md)。不带 `seconds` 的浇水任务是人工浇水。

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

研究 Agent 可以先用 `inspect_stage_data` 查看这个阶段的数据（只读：覆盖率、缺口、各通道取值范围、人工测量、人工任务是否按时完成），再用 `freeze_dataset` 工具冻结数据快照。冻结时会自己核验覆盖率和文件摘要。快照完整（覆盖率不低于 0.9）并且通过校验时，轮次进入 `analysis`；否则停在 `data_verification`。

人工测量必须在快照冻结之前用 `POST /wb/measurements` 记录进去。测量属于某个已存在阶段的实验：对没有任何阶段运行的实验 ID，路由以 `scope` 拒绝，这样每条测量都能追溯到一个项目。

研究 Agent 要有一个研究任务才会做这件事。端到端测试里，操作员用 `POST /wb/goals` 提出第二个目标，脚本化的编排 Agent 把它交给研究 Agent。真实模型是否也这样做，没有验证过。

快照让轮次往前走之后，`GET /wb/rounds/ROUND_ID` 会给出 `snapshot_id`。查看快照的内容或覆盖率**无路由**。

## 7 和 8. 分析与报告

研究 Agent 分析冻结的快照，然后调用 `publish_research_report`。报告保存为数据目录下 `agent_work/reports/` 里的 `research_report_<artifact id>.json`，并在项目档案里登记为 `research_report` 类型的产物。正式报告会让轮次进入 `delivered`。需要复核的报告会让轮次留在 `analysis`。`GET /wb/rounds/ROUND_ID` 给出轮次状态；报告发布后，还给出它的 `report_artifact_id`。

### 运行冻结的分析

研究 Agent 冻结了快照（第 6 步）之后，操作员对它启动冻结脚本的那唯一一次运行。这个请求要求最近 300 秒内重新认证过。

```sh
curl -s -b wb.cookies -X POST -H "Origin: $BASE" -H 'x-growbridge-ui: 1' \
  -H 'Content-Type: application/json' \
  -d '{"project_id": "PROJECT_ID", "protocol_id": "PROTOCOL_ID", "snapshot_id": "SNAPSHOT_ID"}' \
  "$BASE/wb/analysis/runs"
```

响应有 `run_id`、`status`（`succeeded` 或 `failed`）、`exit_code`、`timed_out`，以及 `stdout` 和 `stderr`，各截到 4000 个字符。运行结束时才有响应，最长 600 秒。守护进程的其余部分，包括保护规则和关泵，在这期间照常运行。

请求会在沙箱启动之前按下面的顺序被拒绝：

1. `state`：项目里没有这个协议。
2. `scope`：这份快照不是运行这个协议的某一轮的快照，或者它的实验属于不止一个协议版本的轮次。`state`：快照被后来的更正作废了。起作用的版本是快照被收集时所在的版本，不是最新保存的版本，所以更晚的版本还没有脚本也没有关系。
3. `state`：那个版本还没有冻结脚本。
4. `state`：快照背后有阶段在脚本冻结之前就启动了。冻结之前收集的数据永远不能是确认性的。
5. `snapshot_incomplete`：快照不完整，或者某个文件和清单对不上了。
6. `scope`：快照里有留出批次的结局数据。留出数据不进入任何分析。`state`：快照里有人工测量是在脚本冻结之前记录的（以档案自己的记录时间为准，不看你填的 `measured_at`），或者它没有记录时间，因为它早于档案开始保存这个时间。
7. `already_run`：这份快照以前运行过。失败或超时的运行同样用掉了这一次机会。
8. `sandbox_unavailable`：这个平台没有沙箱（只有 macOS 有）。这一次机会不会被用掉。

报告按它的数据被收集时所在的协议版本来分析，这个版本从它引用的快照所属的轮次读出；快照来自不止一个版本，就以 `param` 被拒绝。那个版本已经冻结脚本时，只要研究 Agent 的 `publish_research_report` 引用的快照里有任何一份的运行状态是 `none` 或 `running`，它就以 `state` 被拒绝。所有运行都结束后，报告才会发布：所有运行都成功、也没有别的原因压低标签时，它可以是确认性的；有一次运行失败，它就是探索性的。没有冻结脚本时一切照旧：报告是探索性的。

读取报告、读取或列出研究任务、处理 `needs_review` 或 `needs_attention` 的任务，都**无路由**。`GET /wb/alerts` 里类型为 `agent_task` 的告警，说明某个模型任务失败了或者需要处理；监察任务对应的是 `audit_task`，警告级，每个阶段一条。

## 目前没有路由或命令的步骤

- 列出项目或轮次，读取已保存的研究协议。
- 只读取调用预算而不设置它。
- 读取某个研究任务，或列出一个项目的任务。
- 读取阶段历史或暂停原因。
- 撤销审批，给执行中的阶段切换运行单。
- 给留出数据登记模型，或者给模型打分。
- 读取日报或数据快照。

其中大部分功能在服务里已经有对应的方法，不少在 [`workflow/service.py`](../../../src/growbridge/workflow/service.py) 里。路由和命令还没有。一轮研究的任何一步都没有 CLI 命令。

## 另见

- [启用 DiAGRI](Enable-DiAGRI.md)
- [人工接管、灌溉与交还](Manual-Takeover-and-Irrigation.md)
- [故障处理手册](Troubleshooting-Runbook.md)
- [工作流与状态机](Workflow-and-State-Machines.md)
- [HTTP、工作台与 MCP 接口](API-Reference.md)
- [拒绝码与事件类型](Denial-Codes-and-Events.md)
