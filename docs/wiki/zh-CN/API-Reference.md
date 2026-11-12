# HTTP、工作台与 MCP 接口

[English](../en/API-Reference.md)

这一页写给用程序调用 DiAGRI 的开发者和操作员。它列出桥接 HTTP 路由、工作台路由、两种模式下的 MCP 工具，以及每个模型角色的工具。

本页说的"仅桥接模式"指 `auto_research = false`。拒绝码的含义见[拒绝码与事件类型](Denial-Codes-and-Events.md)。这些表格是对照代码和测试核对的，而测试只在模拟的 AC5 上运行，见[状态与已知限制](Status-and-Known-Limitations.md)。

操作员通过下面的工作台路由创建项目、研究协议和研究轮次，设置项目的调用预算，并创建编排 Agent 的第一个任务；[运行一轮研究](Run-a-Research-Round.md)按顺序演示了这些请求。CLI 命令和模型工具都做不了这些事。`growbridge simulate` 直接做同样的服务调用，位置在 [`runtime.py`](../../../src/growbridge/runtime.py) 的 `_design_and_start`。`WorkflowService` 还有 `switch_run_sheet` 和 `revoke_approval` 两个方法，没有任何路由、命令或工具调用它们。

## 监听

| 监听 | 地址 | 模式 | 提供什么 |
| --- | --- | --- | --- |
| 回环 | `127.0.0.1:<port>` | 两种模式 | 桥接路由；DiAGRI 模式下还有工作台路由。从这个端口进来、`Host` 在 `overlay_hosts` 里的请求属于覆盖网络入口。 |
| 局域网 | `<lan_bind>:<lan_port>` | DiAGRI 模式，且两个字段都已设置 | 同一个应用。从这个端口进来、`Host` 在 `lan_hosts` 里的请求属于局域网入口。 |

请求的 `Host` 必须是 `localhost`、`127.0.0.1`、`testserver`（供测试客户端使用），或者在 DiAGRI 模式下是 `lan_hosts`、`overlay_hosts` 里的地址；否则在进入任何路由之前就返回 400。

## 桥接 HTTP API

来源：[`api.py`](../../../src/growbridge/api.py) 的 `create_app`。共 14 个路由和一个静态挂载。

| 认证方式 | 含义 |
| --- | --- |
| 无 | 不需要凭据。 |
| 令牌 | 请求头 `Authorization: Bearer <token>`，`token` 取自配置文件。 |
| 令牌或会话 | 带上面的令牌请求头；没有 `Authorization` 请求头时，用 Cookie `growbridge_session`，这时除 `GET` 和 `HEAD` 以外的方法还需要允许的 `Origin` 和请求头 `X-GrowBridge-UI: 1`。 |

| 方法 | 路径 | 认证方式 | 输入 | 返回 | DiAGRI 模式下 |
| --- | --- | --- | --- | --- | --- |
| `GET` | `/` | 无 | 无 | 控制台页面 `index.html`。 | 不变 |
| 挂载 | `/assets` | 无 | 文件路径 | [`web/`](../../../src/growbridge/web) 下的静态文件。 | 不变 |
| `POST` | `/ui/session` | 令牌 | 无 | `code` 和 `expires_in`（60）。code 只能用一次。 | 不变 |
| `POST` | `/ui/session/redeem` | 无；但 `Origin` 必须在允许范围内 | 请求体 `code`（20 到 100 个字符） | `{"connected": true}`，并设置 Cookie `growbridge_session`（HttpOnly、SameSite=Strict、12 小时）。 | 不变；入口地址也算允许的来源 |
| `POST` | `/ui/logout` | 令牌或会话 | 无 | `{"connected": false}`。撤销会话并删除 Cookie。 | 不变 |
| `GET` | `/ui/settings` | 令牌或会话 | 无 | `stale_seconds`、`max_pump_seconds`、`pump_cooldown_seconds`、`pump_ready_at`、`retention_days`。 | 不变 |
| `GET` | `/health` | 令牌或会话 | 无 | `connected`、`protocol_version`、`controls_enabled`、`pump_off_unconfirmed`、`last_sample_at`、`age_seconds`、`stale`、`last_error`、`outlet_mapping`。 | 不变 |
| `GET` | `/status` | 令牌或会话 | 查询参数 `refresh`（布尔，默认 `false`） | `health`、`data`、`system`。带 `refresh` 时先向设备查询一次。 | 不变 |
| `GET` | `/history` | 令牌或会话 | 查询参数 `hours`（大于 0，不超过 168，默认 24）、`limit`（1 到 2000，默认 500） | `samples`：由 `timestamp` 和 `data` 组成的列表。 | 不变 |
| `GET` | `/history/series` | 令牌或会话 | 查询参数 `hours`（同上）、`points`（2 到 2000，默认 600） | `samples`、`window`、`total_samples`、`downsampled`。 | 不变 |
| `GET` | `/activity` | 令牌或会话 | 查询参数 `limit`（1 到 100，默认 20） | `operations`：由 `request_id`、`action`、`params`、`state`、`requested_at` 组成的列表。 | 不变 |
| `GET` | `/history/export.csv` | 令牌或会话 | 查询参数 `hours`（同上） | 文件 `growbridge-history.csv`：`timestamp_utc`、六个传感器列、`outlet_1_on` 到 `outlet_5_on`、`light_level`、`exhaust_level`、`fan_level`。 | 不变 |
| `POST` | `/control/{device}` | 令牌或会话 | 路径参数 `device`：`light`、`exhaust` 或 `fan`；请求体 `request_id`、`level`（整数 0 到 100；风扇是 0 到 10） | 一张回执：`request_id`、`action`、`completed_at` 和确认后的状态。 | 拒绝：403 |
| `POST` | `/outlet` | 令牌或会话 | 请求体 `request_id`、`number`（1 到 5）、`on`（布尔） | 同上的回执。 | 拒绝：403 |
| `POST` | `/pump` | 令牌或会话 | 请求体 `request_id`、`seconds`（大于 0，不超过 60，且不超过 `max_pump_seconds`） | 同上的回执。 | 拒绝：403 |

`request_id` 长度 8 到 100 个字符，只能用字母、数字、`_` 和 `-`。请求体里有未知字段会被拒绝。DiAGRI 模式下，三个写入路由在检查请求体之前就被拒绝，detail 是 `Device writes go through the workbench`。

| 状态码 | 什么情况 |
| --- | --- |
| 401 | 没带令牌或令牌不对（`Authentication required`）；没有有效会话（`Open the dashboard with growbridge dashboard to connect`）；code 已用过或已过期。 |
| 403 | `Origin` 不在允许范围内；缺少请求头 `X-GrowBridge-UI`；在 DiAGRI 模式下调用写入路由。 |
| 404 | `device` 不是 `light`、`exhaust` 或 `fan`。 |
| 409 | 请求被桥接层拒绝或执行失败（`BridgeError`），例如控制未开启、数据过期、水泵冷却未结束，或 `request_id` 被用于不同的参数。响应体是 `{"detail": "<message>"}`。 |
| 422 | 请求体或查询参数没有通过校验。请求里的 NaN 或无穷大会以文本形式回显，例如 `"nan"`。 |
| 429 | 已有 64 个 code 在等待，或已有 64 个会话。 |

## 工作台路由

工作台是 DiAGRI 模式下操作员使用的 HTTP 接口：`/wb` 下的一组 JSON 路由，由 [`workbench/api.py`](../../../src/growbridge/workbench/api.py) 的 `create_workbench` 构建，只在 `auto_research = true` 时挂载。发起和掌控一轮研究的路由在 [`workbench/rounds.py`](../../../src/growbridge/workbench/rounds.py) 里。工作台没有自己的网页，`web/` 里的文件是桥接控制台。共 33 个路由。其中两个告警路由只在传入告警簿时才存在，预算和目标两个路由只在传入任务板和调用预算时才存在，三个分析路由（[`workbench/analysis.py`](../../../src/growbridge/workbench/analysis.py)）只在传入确认性分析运行器时才存在。运行时总是全部都传。

| 调用方 | 凭据 | 检查 |
| --- | --- | --- |
| 操作员 | Cookie `growbridge_operator`，由 `POST /wb/login` 设置：HttpOnly、SameSite=Strict、路径 `/wb`、8 小时，在覆盖网络入口上带 `Secure`。 | 请求必须从已登记的入口进来，并且是会话建立时的那个入口。除 `GET`、`HEAD`、`OPTIONS` 以外的方法，还需要一个在允许范围内、并且和请求的 `Host` 一致的 `Origin`，以及请求头 `X-GrowBridge-UI: 1`。恢复编号一变，会话就失效。 |
| 模型角色 | 请求头 `Authorization: Bearer <role token>`。令牌来自 `GROWBRIDGE_ROLE_TOKEN_<ROLE>`。 | 不要求入口，也不检查 `Origin`。只要带了这个请求头，就不再看 Cookie。仅桥接模式的 `token` 在这里不被接受。 |

表中的"重新认证"指近期重新认证：操作员在最近 300 秒内登录过，或调用过 `POST /wb/reauth`（[`workflow/permissions.py`](../../../src/growbridge/workflow/permissions.py) 的 `REAUTH_SECONDS`）。请求体里下文没有列出的字段会被丢弃，所以请求体无法声明身份、权限或入口。

凡是需要操作员的路由，都可能返回 `session`、`entry` 和 `model_role`。最后一列列出该路由另外可能返回的拒绝码。"授予类拒绝码"指 `host_unregistered`、`right_held` 和 `scope`，在控制服务授予写入权时产生。"写入类拒绝码"指 `controls_disabled`、`host_unregistered`、`right_invalid`、`scope`、`unsettled`、`interlock`、`not_connected`、`stale` 和 `request_id_reused`，在控制服务受理动作时产生。

| 方法 | 路径 | 谁可以调用 | 入口 | 重新认证 | 其他拒绝码 |
| --- | --- | --- | --- | --- | --- |
| `POST` | `/wb/login` | 持有操作员名字和密码的任何人 | 局域网、覆盖网络 | 否 | 只有 `entry`、`session`、`locked` |
| `POST` | `/wb/logout` | 操作员 | 局域网、覆盖网络 | 否 | 无 |
| `POST` | `/wb/reauth` | 操作员 | 局域网、覆盖网络 | 否 | `locked` |
| `GET` | `/wb/me` | 操作员、角色令牌 | 局域网、覆盖网络 | 否 | 只有 `session`、`entry` |
| `POST` | `/wb/stages/{stage_id}/approve` | 操作员 | 局域网、覆盖网络 | 是 | `reauth_required`、`state`、`approval_invalid` |
| `POST` | `/wb/stages/{stage_id}/start` | 操作员 | 局域网、覆盖网络 | 否 | `state`、`approval_invalid`、`safety_conflict`、`interlock`、授予类拒绝码 |
| `POST` | `/wb/stages/{stage_id}/pause` | 操作员 | 局域网、覆盖网络 | 否 | `state` |
| `POST` | `/wb/stages/{stage_id}/resume` | 操作员 | 局域网、覆盖网络 | 是 | `reauth_required`、`state`、`approval_invalid`、`interlock`、`not_connected`、授予类拒绝码 |
| `POST` | `/wb/stages/{stage_id}/stop` | 操作员 | 局域网、覆盖网络 | 否 | `state`、授予类拒绝码 |
| `POST` | `/wb/stages/{stage_id}/takeover` | 操作员 | 局域网、覆盖网络 | 是 | `reauth_required`、`state`、授予类拒绝码 |
| `POST` | `/wb/stages/{stage_id}/handback` | 操作员 | 局域网、覆盖网络 | 否 | `state`、`not_connected`、授予类拒绝码 |
| `POST` | `/wb/stages/{stage_id}/onsite-check` | 操作员 | 局域网、覆盖网络 | 否 | `state`、授予类拒绝码 |
| `POST` | `/wb/drafts/run-sheet` | 操作员、角色令牌 | 局域网、覆盖网络 | 否 | 只有 `session`、`entry`、`state` |
| `POST` | `/wb/manual/{channel}` | 操作员 | 局域网、覆盖网络 | 否 | `pump_on_forbidden`、`state`、写入类拒绝码 |
| `POST` | `/wb/irrigation` | 操作员 | 仅局域网 | 否 | `entry`（不在局域网入口上）、`state`、`cooldown`、写入类拒绝码 |
| `POST` | `/wb/measurements` | 操作员 | 局域网、覆盖网络 | 否 | 无 |
| `POST` | `/wb/safety/approve` | 操作员 | 局域网、覆盖网络 | 是 | `reauth_required`、`host_unregistered` |
| `GET` | `/wb/stages/{stage_id}` | 操作员、角色令牌 | 局域网、覆盖网络 | 否 | 只有 `session`、`entry`、`state` |
| `GET` | `/wb/receipts/{request_id}` | 操作员、角色令牌 | 局域网、覆盖网络 | 否 | 只有 `session`、`entry` |
| `GET` | `/wb/alerts` | 操作员、角色令牌 | 局域网、覆盖网络 | 否 | 只有 `session`、`entry` |
| `POST` | `/wb/alerts/{event_id}/read` | 操作员 | 局域网、覆盖网络 | 否 | `state` |
| `POST` | `/wb/projects` | 操作员 | 局域网、覆盖网络 | 否 | `state` |
| `POST` | `/wb/protocols` | 操作员 | 局域网、覆盖网络 | 否 | `state` |
| `POST` | `/wb/rounds` | 操作员 | 局域网、覆盖网络 | 否 | `state` |
| `GET` | `/wb/rounds/{round_id}` | 操作员 | 局域网、覆盖网络 | 否 | `state` |
| `POST` | `/wb/rounds/{round_id}/choice` | 操作员 | 局域网、覆盖网络 | 否 | `state` |
| `POST` | `/wb/rounds/{round_id}/abort` | 操作员 | 局域网、覆盖网络 | 否 | `state` |
| `GET` | `/wb/stages/{stage_id}/run-sheet` | 操作员 | 局域网、覆盖网络 | 否 | `state` |
| `POST` | `/wb/projects/{project_id}/budget` | 操作员 | 局域网、覆盖网络 | 是 | `reauth_required`、`state` |
| `POST` | `/wb/goals` | 操作员 | 局域网、覆盖网络 | 否 | `budget`、`state` |
| `POST` | `/wb/protocols/{protocol_id}/analysis` | 操作员 | 局域网、覆盖网络 | 是 | `reauth_required`、`state`、`script_hash`、`param` |
| `GET` | `/wb/protocols/{protocol_id}/analysis` | 操作员 | 局域网、覆盖网络 | 否 | `state` |
| `POST` | `/wb/analysis/runs` | 操作员 | 局域网、覆盖网络 | 是 | `reauth_required`、`state`、`scope`、`snapshot_incomplete`、`already_run`、`sandbox_unavailable` |

最后十二个路由只给操作员用，其中的三个读取路由也一样：角色令牌会以 `model_role` 被拒绝。

下表里的"阶段运行信息"指去掉运行单的 `StageRuntime`：`stage_id`、`experiment_id`、`project_id`、`state`、`prior_state`、`right_number`、`care_right`、`manual_right`、`started_at`、`paused_at`、`end_pending`。`RunSheet`、`ResearchProtocol`、`SafetyConfig`、`Approval` 和 `ActionRecord` 定义在 [`archive/models.py`](../../../src/growbridge/archive/models.py)。`RunSheet` 和 `SafetyConfig` 里的任何数都不能是 NaN 或无穷大（写成文本也不行），不管它们从哪里来：路由回答 `422`，模型工具返回错误结果，什么都不保存，也不批准。

| 方法 | 路径 | 请求体 | 返回 |
| --- | --- | --- | --- |
| `POST` | `/wb/login` | `name`（1 到 64 个字符）、`secret`（1 到 256） | `operator`、`entry`、`reauth_seconds`，以及会话 Cookie |
| `POST` | `/wb/logout` | 无 | `{"operator": null}`；Cookie 被删除 |
| `POST` | `/wb/reauth` | `secret`（1 到 256） | `reauth_seconds` |
| `GET` | `/wb/me` | 无 | `kind`、`id`、`operator`、`entry`、`reauth_at` |
| `POST` | `/wb/stages/{stage_id}/approve` | 无 | 这次的 `Approval` |
| `POST` | `/wb/stages/{stage_id}/start` | 无 | 阶段运行信息 |
| `POST` | `/wb/stages/{stage_id}/pause` | 可选 `reason`（最长 200，默认 `operator request`） | 阶段运行信息 |
| `POST` | `/wb/stages/{stage_id}/resume` | 无 | 阶段运行信息 |
| `POST` | `/wb/stages/{stage_id}/stop` | 无 | 阶段运行信息 |
| `POST` | `/wb/stages/{stage_id}/takeover` | 无 | 阶段运行信息 |
| `POST` | `/wb/stages/{stage_id}/handback` | 可选 `accept_as_intervention`（布尔，默认 `false`） | `stage`（阶段运行信息）和 `differences`（由 `channel`、`field`、`expected`、`actual` 组成的列表） |
| `POST` | `/wb/stages/{stage_id}/onsite-check` | `note`（1 到 500） | 阶段运行信息 |
| `POST` | `/wb/drafts/run-sheet` | `round_id`（1 到 100）、`run_sheet`（一个 `RunSheet`） | `stage_id` 和 `findings`（由 `code`、`message`、`blocking` 组成的列表） |
| `POST` | `/wb/manual/{channel}` | 路径参数 `channel`：`light`、`exhaust`、`fan` 或 `pump`；请求体 `stage_id`、`request_id`、`level`（整数：灯和排风 0 到 100，风扇 0 到 10，水泵只能是 0）、可选 `note`（最长 200） | 对应的 `ActionRecord` |
| `POST` | `/wb/irrigation` | `stage_id`、`request_id`、`seconds`（大于 0，不超过 60，且不超过 `max_pump_seconds`）、可选 `note`（最长 200） | 对应的 `ActionRecord` |
| `POST` | `/wb/measurements` | `experiment_id`、`batch`、`plant_id`、`layout_version`、`measured_at`、`position`、`method`、`metric`、`value`、`unit`；可选 `id`、`corrects` | `id` |
| `POST` | `/wb/safety/approve` | `config`（一个 `SafetyConfig`） | `protection_right` |
| `GET` | `/wb/stages/{stage_id}` | 无 | 阶段运行信息 |
| `GET` | `/wb/receipts/{request_id}` | 无 | 对应的 `ActionRecord` |
| `GET` | `/wb/alerts` | 无 | `alerts`：未解决的告警 |
| `POST` | `/wb/alerts/{event_id}/read` | 无 | `event_id` |
| `POST` | `/wb/projects` | `name`（1 到 200） | `project_id` |
| `POST` | `/wb/protocols` | `protocol`（一个 `ResearchProtocol`；`id` 和 `project_id` 为 1 到 100，`version` 为 1 到 1000000，不能有 NaN 或无穷大） | `protocol_id`、`version`、`digest` |
| `POST` | `/wb/rounds` | `project_id`、`protocol_id`（各 1 到 100） | `round_id`、`state` |
| `GET` | `/wb/rounds/{round_id}` | 无 | `round_id`、`project_id`、`protocol_id`、`protocol_version`、`state`、`stages_done`、`stage_total`、`awaiting_choice`、`snapshot_id`、`report_artifact_id`，以及 `stages`（由 `stage_id`、`state` 组成的列表） |
| `POST` | `/wb/rounds/{round_id}/choice` | `choice`：`redo`、`next`、`verify` 或 `abort` | `round_id`、`state` |
| `POST` | `/wb/rounds/{round_id}/abort` | 无 | `round_id`、`state` |
| `GET` | `/wb/stages/{stage_id}/run-sheet` | 无 | `stage_id`、`state`、`run_sheet_version`、`run_sheet_digest`、`run_sheet`（即 `RunSheet`）、`findings`（由 `code`、`message`、`blocking` 组成的列表）、`blocking` |
| `POST` | `/wb/projects/{project_id}/budget` | `max_calls`（整数，0 到 1000000）、`max_cost`（美元，0 到 1000000） | `project_id`、`max_calls`、`max_cost`、`remaining_calls`、`remaining_cost` |
| `POST` | `/wb/goals` | `project_id`、`goal`（去掉首尾空白后 1 到 2000）；可选 `round_id`、`constraints`（最多 20 条，每条 1 到 500）、`request_id` | `task_id`、`state`、`reused` |
| `POST` | `/wb/protocols/{protocol_id}/analysis` | `project_id`（1 到 100）、`script`（文本，1 到 20000 个字符，只编译、从不运行） | `protocol_id`、`version`、`script_sha256`、`frozen_at`、`note`（冻结的脚本不能更正） |
| `GET` | `/wb/protocols/{protocol_id}/analysis` | 查询参数 `project_id`（1 到 100） | `protocol_id`、`version`、`started`、`frozen`（`null`，或 `script_sha256`、`frozen_at`、`frozen_by`、`script`）、`snapshots`（一组 `snapshot_id`、`experiment_id`、`complete`、`run_status`） |
| `POST` | `/wb/analysis/runs` | `project_id`、`protocol_id`、`snapshot_id`（各 1 到 100） | `run_id`、`status`、`exit_code`、`timed_out`、`stdout`、`stderr`（后两个截到 4000 个字符） |

已保存的协议版本不会被覆盖：`id` 和 `version` 相同而内容不同，会以 `state` 被拒绝。`POST /wb/rounds` 使用最新保存的版本。读取路由给出的 `run_sheet_digest` 就是审批记录里的那个摘要。再设一次预算只改上限，已记录的用量保留。`POST /wb/goals` 创建一个归编排 Agent 所有的研究任务；项目还没有预算，或者预算已经用完时，它以 `budget` 被拒绝。带 `request_id` 时，同一个操作员对同一个项目把同样的请求再发一次，得到的是第一次建的任务，并带 `"reused": true`；同一个 ID 下换了目标文本、轮次或约束条件，会以 `state` 被拒绝。不带 `request_id` 时，每次请求都新建一个任务。这些路由路径里的 ID 为 1 到 100 个字符。分析路由冻结协议最新版本的分析脚本（这个版本下一旦有阶段启动，冻结就以 `state` 被拒绝），并在一份数据快照上把它运行一次；它们的检查顺序见[开展一轮研究](Run-a-Research-Round.md#运行冻结的分析)。

`request_id` 的规则和桥接 API 相同。`POST /wb/manual/{channel}` 和 `POST /wb/irrigation` 要求阶段处于 `manual` 状态。对 `POST /wb/manual/pump`，`level` 为 1 会以 `pump_on_forbidden` 被拒绝。

| 状态码 | 什么情况 | 响应体 |
| --- | --- | --- |
| 401 | 拒绝码 `session` | `{"detail": {"code": "<code>", "message": "<text>"}}` |
| 403 | 本表没有单独列出的其他所有拒绝码 | 同样的结构 |
| 409 | 拒绝码 `state` | 同样的结构 |
| 429 | 拒绝码 `locked` | 同样的结构 |
| 404 | `GET /wb/receipts/{request_id}` 的 ID 不存在 | `{"detail": "Unknown request id"}` |
| 422 | `level` 超出该通道的范围，测量记录没有被接受，或者协议的 ID 或版本超出范围、含有非有限的数 | `{"detail": {"code": "param", "message": "<text>"}}` |
| 422 | 请求体没有通过校验，包括运行单里有非有限的数 | 校验错误列表；请求里的 NaN 或无穷大以文本形式回显 |

## MCP 工具

来源：[`mcp_server.py`](../../../src/growbridge/mcp_server.py)。`growbridge mcp` 通过标准输入输出运行名为 `spiderfarmer-growbridge` 的服务。每个工具都带着令牌调用桥接 HTTP API。仅桥接模式有 8 个工具，DiAGRI 模式只有 3 个读取工具。

| 工具 | 仅桥接模式 | DiAGRI 模式 | 输入 | 调用 |
| --- | --- | --- | --- | --- |
| `get_health` | 有 | 有 | 无 | `GET /health` |
| `get_status` | 有 | 有 | 无 | `GET /status` |
| `get_history` | 有 | 有 | 可选 `hours`（默认 24）、`limit`（默认 500） | `GET /history` |
| `set_light` | 有 | 无 | `brightness_percent`、`request_id` | `POST /control/light` |
| `set_exhaust` | 有 | 无 | `speed_percent`、`request_id` | `POST /control/exhaust` |
| `set_fan` | 有 | 无 | `level`、`request_id` | `POST /control/fan` |
| `set_outlet` | 有 | 无 | `number`、`on`、`request_id` | `POST /outlet` |
| `run_pump` | 有 | 无 | `seconds`、`request_id` | `POST /pump` |

## 模型角色的工具

来源：[`agents/tools.py`](../../../src/growbridge/agents/tools.py) 的 `ROLE_TOOLS`，以及 [`handlers_orchestrator.py`](../../../src/growbridge/agents/handlers_orchestrator.py)、[`handlers_planner.py`](../../../src/growbridge/agents/handlers_planner.py)、[`handlers_researcher.py`](../../../src/growbridge/agents/handlers_researcher.py)、[`handlers_report.py`](../../../src/growbridge/agents/handlers_report.py) 和 [`handlers_common.py`](../../../src/growbridge/agents/handlers_common.py) 里的处理函数。编排 Agent 有 7 个工具，计划 Agent 有 8 个，研究 Agent 有 7 个。这些工具由守护进程内部的模型调用，既不是 HTTP 路由，也不是 MCP 工具。

"类别"取值为 `read`、`write`、`web`（结果是不可信的网页内容）或 `sandbox`。一个角色在一次运行里调用过 `web` 工具之后，它的 `write` 和 `sandbox` 工具在这次运行的剩余部分都会被拒绝。输入里有未知字段时校验失败。被拒绝时，模型收到的是一条错误结果，格式为 `Error: denied (<code>): <message>`。

| 角色 | 工具 | 类别 | 必填输入 | 作用 |
| --- | --- | --- | --- | --- |
| orchestrator | `get_project_state` | read | `project_id` | 读取项目的任务和当前活动阶段；带 `round_id` 时还读取轮次状态和它的各个阶段。 |
| orchestrator | `get_run_status` | read | `stage_id` | 读取一个阶段的状态和近期历史。 |
| orchestrator | `create_research_task` | write | `project_id`、`owner_role`、`question`、`trigger_event_id`、`correlation_id` | 给计划 Agent 或研究 Agent 创建一个研究任务。 |
| orchestrator | `delegate_task` | write | `project_id`、`to_role`、`goal`、`budget`、`trigger_event_id`、`correlation_id` | 带完整交接信息，给计划 Agent 或研究 Agent 创建一个研究任务。 |
| orchestrator | `submit_run_for_review` | write | `round_id`、`run_sheet` | 提交运行单草稿，等操作员审阅。它不做审批。 |
| orchestrator | `get_task_status` | read | `task_id` | 读取正在运行的任务或它下面委派出去的任务的状态，以及它的产物 ID。 |
| orchestrator | `read_artifact` | read | `artifact_id` | 核对摘要后读取一个已登记的文本产物。 |
| planner | `get_device_capabilities` | read | 无 | 读取设备的传感器、通道和档位范围。 |
| planner | `find_prior_runs` | read | `experiment_id` | 列出一个实验的数据快照和测量条数。 |
| planner | `lookup_crop_conditions` | web | `crop` | 搜索某种作物的生长条件。 |
| planner | `search_and_verify_sources` | web | `query` | 搜索资料来源。 |
| planner | `check_experimental_design` | read | `project_id`、`protocol_id` | 检查一份已保存的研究协议的设计。 |
| planner | `estimate_sample_size` | read | `effect`、`sd` | 估算需要多少个区组或实验单位。 |
| planner | `validate_run_sheet` | read | `run_sheet` | 校验运行单，但不保存。 |
| planner | `save_plan_draft` | write | `round_id`、`run_sheet` | 提交运行单草稿，等操作员审阅。它不做审批。 |
| researcher | `freeze_dataset` | write | `task_id`、`stage_id` | 把一个阶段的数据冻结成经过校验的数据快照；带 `round_id` 且快照完整时，还会推进轮次。 |
| researcher | `query_evidence` | read | 无 | 在项目档案里搜索证据卡。 |
| researcher | `run_local_analysis` | sandbox | `task_id`、`snapshot_id`、`script` | 在沙箱里对一个数据快照运行探索性脚本。 |
| researcher | `submit_compute_job` | write | `task_id`、`template_id` | 按已登记的模板提交一个计算作业。 |
| researcher | `get_compute_job` | read | `attempt_id` | 读取计算作业的状态。 |
| researcher | `fetch_compute_artifacts` | write | `attempt_id` | 取回并校验计算作业的输出。 |
| researcher | `publish_research_report` | write | `task_id`、`protocol_id`、`treatment_id`、`snapshots` | 发布本轮的报告；带 `round_id` 且报告为最终版时，还会交付轮次。 |

研究 Agent 的工具只要涉及快照、阶段、轮次或计算提交，就必须带 `task_id`。这个编号要和调度器正在运行的任务比对，而不是照单全收：任何其他编号、别的角色的任务、以及在调度运行之外发起的调用，都会以 `scope` 被拒绝；其他项目的阶段、轮次或快照同样以 `scope` 被拒绝。

另外两个角色以同样的方式绑定。编排和计划 Agent 调用里的每个 `project_id`、`round_id`、`stage_id` 和 `experiment_id`，都必须属于正在运行的任务所在的项目，而且该实验必须只有一个所属项目。`get_task_status` 只回答正在运行的任务和它下面委派出去的任务；`read_artifact` 只回答本项目任务的产物；`delegate_task` 只接受正在运行的任务作为 `parent_task_id`。以上情况都以 `scope` 拒绝。

`growbridge serve` 构建的守护进程没有传入搜索后端和计算服务。因此 `lookup_crop_conditions`、`search_and_verify_sources`、`submit_compute_job`、`get_compute_job` 和 `fetch_compute_artifacts` 都返回 `denied (unavailable)`。沙箱只在 macOS 上存在；在其他系统上，`run_local_analysis` 返回 `denied (sandbox_unavailable)`。

`agents/tools.py` 的 `CONTROL_TOOLS` 列出了 14 个阶段和设备控制类的工具名，任何模型角色都拿不到它们。这些名字都没有对应的处理函数。

## 另见

- [拒绝码与事件类型](Denial-Codes-and-Events.md)
- [配置参考](Configuration-Reference.md)
- [CLI 参考](CLI-Reference.md)
- [控制与安全模型](Control-and-Safety-Model.md)
- [五个 Agent](The-Five-Agents.md)
- [术语表](Glossary.md)
