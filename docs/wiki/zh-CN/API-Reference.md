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
| 409 | 请求被桥接层拒绝或执行失败（`BridgeError`），例如控制未开启、数据过期、水泵冷却未结束，或 `request_id` 被用于不同的参数。响应体是 `{"detail": "<message>", "code": <代码或 null>, "reason": <原因或 null>, "params": {}}`；`detail` 仍是字符串，`code`、`reason` 和 `params` 见工作台错误表后面对错误体字段的说明（`PumpOffUnconfirmed` 错误是 `interlock` / `pump_unconfirmed`，`params` 为 `{"device_id": null}`，因为桥接层在这里不知道设备；其余的 `code`、`reason` 为 `null`，`params` 为 `{}`）。 |
| 422 | 请求体或查询参数没有通过校验。请求里的 NaN 或无穷大会以文本形式回显，例如 `"nan"`。 |
| 429 | 已有 64 个 code 在等待，或已有 64 个会话。 |

## 工作台路由

工作台是 DiAGRI 模式下操作员使用的 HTTP 接口：`/wb` 下的一组 JSON 路由，由 [`workbench/api.py`](../../../src/growbridge/workbench/api.py) 的 `create_workbench` 构建，只在 `auto_research = true` 时挂载。发起和掌控一轮研究的路由在 [`workbench/rounds.py`](../../../src/growbridge/workbench/rounds.py) 里。操作员控制台是 `/workbench` 下的一个网页，只调用这些路由（见[启用 DiAGRI](Enable-DiAGRI.md)）；`web/workbench/` 之外的 `web/` 文件是桥接控制台。共 55 个路由。第一张表末尾的七个读取路由总是挂载：没有传入的服务，[`workbench/reads.py`](../../../src/growbridge/workbench/reads.py) 在待办里直接略过。其中两个告警路由只在传入告警簿时才存在，预算和目标两个路由只在传入任务板和调用预算时才存在，三个分析路由（[`workbench/analysis.py`](../../../src/growbridge/workbench/analysis.py)）只在传入确认性分析运行器时才存在，两个留出集路由（[`workbench/holdouts.py`](../../../src/growbridge/workbench/holdouts.py)）只在传入留出数据登记时才存在。运行时总是全部都传。

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
| `POST` | `/wb/drafts/run-sheet` | 操作员、planner 的角色令牌 | 局域网、覆盖网络 | 否 | 只有 `session`、`entry`、`state`，其他角色的令牌得到 `model_role` |
| `POST` | `/wb/manual/{channel}` | 操作员 | 局域网、覆盖网络 | 否 | `pump_on_forbidden`、`state`、写入类拒绝码 |
| `POST` | `/wb/irrigation` | 操作员 | 仅局域网 | 否 | `entry`（不在局域网入口上）、`state`、`cooldown`、写入类拒绝码 |
| `POST` | `/wb/stages/{stage_id}/manual-tasks` | 操作员 | 局域网、覆盖网络 | 否 | `scope`（没有这次任务）、`state`（阶段未开始，或离到期还有一小时以上）、`param`（`done_at`） |
| `POST` | `/wb/stages/{stage_id}/manual-tasks/irrigate` | 操作员 | 仅局域网 | 否 | `entry`（不在局域网入口上）、`scope`（不是计划内浇水）、`state`（阶段不在 `running`、未到期、已过截止时间、已完成，或这次任务已经开过泵）、`cooldown`、写入类拒绝码 |
| `POST` | `/wb/measurements` | 操作员 | 局域网、覆盖网络 | 否 | `scope` |
| `POST` | `/wb/safety/approve` | 操作员 | 局域网、覆盖网络 | 是 | `reauth_required`、`host_unregistered` |
| `GET` | `/wb/stages/{stage_id}` | 操作员、角色令牌 | 局域网、覆盖网络 | 否 | 只有 `session`、`entry`、`state` |
| `GET` | `/wb/receipts/{request_id}` | 操作员、角色令牌 | 局域网、覆盖网络 | 否 | 只有 `session`、`entry` |
| `GET` | `/wb/alerts` | 操作员、角色令牌 | 局域网、覆盖网络 | 否 | 只有 `session`、`entry` |
| `POST` | `/wb/alerts/{event_id}/read` | 操作员 | 局域网、覆盖网络 | 否 | `state` |
| `POST` | `/wb/projects` | 操作员 | 局域网、覆盖网络 | 否 | `state` |
| `POST` | `/wb/protocols` | 操作员 | 局域网、覆盖网络 | 否 | `state` |
| `POST` | `/wb/rounds` | 操作员 | 局域网、覆盖网络 | 否 | `state` |
| `GET` | `/wb/rounds/{round_id}` | 操作员 | 局域网、覆盖网络 | 否 | `state` |
| `GET` | `/wb/rounds/{round_id}/report` | 操作员 | 局域网、覆盖网络 | 否 | `state` |
| `POST` | `/wb/rounds/{round_id}/choice` | 操作员 | 局域网、覆盖网络 | 否 | `state` |
| `POST` | `/wb/rounds/{round_id}/abort` | 操作员 | 局域网、覆盖网络 | 否 | `state` |
| `GET` | `/wb/stages/{stage_id}/run-sheet` | 操作员 | 局域网、覆盖网络 | 否 | `state` |
| `POST` | `/wb/projects/{project_id}/budget` | 操作员 | 局域网、覆盖网络 | 是 | `reauth_required`、`state` |
| `POST` | `/wb/goals` | 操作员 | 局域网、覆盖网络 | 否 | `budget`、`state` |
| `GET` | `/wb/projects/{project_id}/conversation` | 操作员 | 局域网、覆盖网络 | 否 | `state` |
| `POST` | `/wb/protocols/{protocol_id}/analysis` | 操作员 | 局域网、覆盖网络 | 是 | `reauth_required`、`state`、`script_hash`、`param` |
| `GET` | `/wb/protocols/{protocol_id}/analysis` | 操作员 | 局域网、覆盖网络 | 否 | `state` |
| `POST` | `/wb/analysis/runs` | 操作员 | 局域网、覆盖网络 | 是 | `reauth_required`、`state`、`scope`、`snapshot_incomplete`、`already_run`、`sandbox_unavailable` |
| `POST` | `/wb/holdouts` | 操作员 | 局域网、覆盖网络 | 是 | `reauth_required`、`scope`、`state`、`batches`、`param` |
| `GET` | `/wb/holdouts` | 操作员 | 局域网、覆盖网络 | 否 | `scope` |
| `POST` | `/wb/evidence` | 操作员 | 局域网、覆盖网络 | 否 | 无 |
| `POST` | `/wb/evidence/{card_id}/verify` | 操作员 | 局域网、覆盖网络 | 否 | `state` |
| `GET` | `/wb/evidence` | 操作员 | 局域网、覆盖网络 | 否 | 无 |
| `POST` | `/wb/compute/balance` | 操作员 | 局域网、覆盖网络 | 是 | `reauth_required` |
| `POST` | `/wb/compute/tasks/{task_id}/budget` | 操作员 | 局域网、覆盖网络 | 是 | `reauth_required`、`scope` |
| `POST` | `/wb/compute/attempts/{attempt_id}/settle` | 操作员 | 局域网、覆盖网络 | 是 | `reauth_required`、`state` |
| `GET` | `/wb/compute` | 操作员 | 局域网、覆盖网络 | 否 | 无 |
| `GET` | `/wb/inbox` | 操作员 | 局域网、覆盖网络 | 否 | 无 |
| `GET` | `/wb/projects` | 操作员 | 局域网、覆盖网络 | 否 | 无 |
| `GET` | `/wb/projects/{project_id}` | 操作员 | 局域网、覆盖网络 | 否 | `state` |
| `GET` | `/wb/stages/{stage_id}/readings` | 操作员 | 局域网、覆盖网络 | 否 | `state` |
| `GET` | `/wb/environment` | 操作员 | 局域网、覆盖网络 | 否 | — |
| `GET` | `/wb/stages/{stage_id}/measurements` | 操作员 | 局域网、覆盖网络 | 否 | `state` |
| `GET` | `/wb/stages/{stage_id}/history` | 操作员 | 局域网、覆盖网络 | 否 | `state` |
| `GET` | `/wb/stages/{stage_id}/manual-tasks` | 操作员 | 局域网、覆盖网络 | 否 | `state` |
| `GET` | `/wb/safety` | 操作员 | 局域网、覆盖网络 | 否 | 无 |

最后二十八个路由只给操作员用，其中的十三个读取路由也一样：角色令牌会以 `model_role` 被拒绝。

下表里的"阶段运行信息"指去掉运行单的 `StageRuntime`：`stage_id`、`experiment_id`、`project_id`、`state`、`prior_state`、`right_number`、`care_right`、`manual_right`、`started_at`、`paused_at`、`end_pending`。`RunSheet`、`ResearchProtocol`、`SafetyConfig`、`Approval` 和 `ActionRecord` 定义在 [`archive/models.py`](../../../src/growbridge/archive/models.py)。`RunSheet` 和 `SafetyConfig` 里的任何数都不能是 NaN 或无穷大（写成文本也不行），不管它们从哪里来：路由回答 `422`，模型工具返回错误结果，什么都不保存，也不批准。

| 方法 | 路径 | 请求体 | 返回 |
| --- | --- | --- | --- |
| `POST` | `/wb/login` | `name`（1 到 64 个字符）、`secret`（1 到 256） | `operator`、`entry`、`reauth_seconds`，以及会话 Cookie |
| `POST` | `/wb/logout` | 无 | `{"operator": null}`；Cookie 被删除 |
| `POST` | `/wb/reauth` | `secret`（1 到 256） | `reauth_seconds` |
| `GET` | `/wb/me` | 无 | `kind`、`id`、`operator`、`entry`、`reauth_at`、`timezone`（即设置 `report_timezone`，控制台显示时间用的时区） |
| `POST` | `/wb/stages/{stage_id}/approve` | `expected_digest`（必填，1 到 128 个字符，不接受其他字段）：审阅过的运行单的摘要。当前运行单与它不同时，路由以 `state` 拒绝；缺少请求体或该字段、或带了其他字段时，以 `422` 拒绝 | 这次的 `Approval` |
| `POST` | `/wb/stages/{stage_id}/start` | 无 | 阶段运行信息 |
| `POST` | `/wb/stages/{stage_id}/pause` | 可选 `reason`（最长 200，默认 `operator request`） | 阶段运行信息 |
| `POST` | `/wb/stages/{stage_id}/resume` | 无 | 阶段运行信息 |
| `POST` | `/wb/stages/{stage_id}/stop` | 无 | 阶段运行信息 |
| `POST` | `/wb/stages/{stage_id}/takeover` | 无 | 阶段运行信息 |
| `POST` | `/wb/stages/{stage_id}/handback` | 可选 `accept_as_intervention`（布尔，默认 `false`） | `stage`（阶段运行信息）和 `differences`（由 `channel`、`field`、`expected`、`actual` 组成的列表） |
| `POST` | `/wb/stages/{stage_id}/onsite-check` | `note`（1 到 500） | 阶段运行信息 |
| `POST` | `/wb/drafts/run-sheet` | `round_id`（1 到 100）、`run_sheet`（一个 `RunSheet`） | `stage_id` 和 `findings`（由 `code`、`variant`、`params`、`message`、`blocking` 组成的列表） |
| `POST` | `/wb/manual/{channel}` | 路径参数 `channel`：`light`、`exhaust`、`fan` 或 `pump`；请求体 `stage_id`、`request_id`、`level`（整数：灯和排风 0 到 100，风扇 0 到 10，水泵只能是 0）、可选 `note`（最长 200） | 对应的 `ActionRecord` |
| `POST` | `/wb/stages/{stage_id}/manual-tasks` | `task_id`、`due_at`（指明哪一次任务，用列表给出的值）、`outcome`（`done` 或 `skipped`）、可选 `done_at`（UTC 秒，默认现在；只用于 `done`，不能晚于现在，也不能早于 `due_at` 一小时以上）、可选 `note`（最长 200）。追加一条记录，以最新的为准。 | 这次任务，格式同列表 |
| `POST` | `/wb/stages/{stage_id}/manual-tasks/irrigate` | `task_id`、`due_at`、可选 `note`；请求号由这次任务推导（请求体里的 `request_id` 会被忽略），所以重试只返回第一次运行，不会再开一次泵。在阶段写入权下让水泵运行该任务的 `seconds`，阶段继续运行（见[控制与安全模型](Control-and-Safety-Model.md)）；完整且得到确认的运行记为已完成，被截断或没有得到确认的运行记为 `partial`，带 `ran_seconds` 和 `ended_early`。 | `action`（`ActionRecord`，带 `ran_seconds` 和 `ended_early`）和 `task`（这次任务；运行没有到达设备时为 `null`） |
| `POST` | `/wb/irrigation` | `stage_id`、`request_id`、`seconds`（大于 0，不超过 60，且不超过 `max_pump_seconds`）、可选 `note`（最长 200） | 对应的 `ActionRecord` |
| `POST` | `/wb/measurements` | `experiment_id`、`batch`、`plant_id`、`layout_version`、`measured_at`、`position`、`method`、`metric`、`value`、`unit`；可选 `id`、`corrects`；`experiment_id` 必须属于某个已存在的阶段，否则路由以 `scope` 拒绝 | `id` |
| `POST` | `/wb/safety/approve` | `config`（一个 `SafetyConfig`，含 `frozen` 门槛；不写则用默认值） | `protection_right` |
| `GET` | `/wb/stages/{stage_id}` | 无 | 阶段运行信息；操作员另外得到已存阶段的 `round_id`、`project_id` 和 `state_at`（角色令牌得到的运行信息和以前一样，没有 `round_id`）。操作员还得到 `project_name`、`round_number`、`stage_index` 和 `phase`，含义同轮次；找不到时各为 `null` |
| `GET` | `/wb/receipts/{request_id}` | 无 | 对应的 `ActionRecord`。失败、作废或结果不明的写入在英文 `error` 之外还有 `error_code` 和 `error_params`（`receipt` 族的代码）；提前结束的浇水在 `ended_early` 之外还有 `ended_early_code` 和 `ended_early_params`（`task_end` 族）。有代码之前写下的记录两者都没有。 |
| `GET` | `/wb/alerts` | 无 | `alerts`：未解决的告警。每条在英文 `message` 之外还有 `code`（`alert` 族的消息码；有代码之前存下的告警为 `null`）和 `params`（对象，代码没有参数时为空）。 |
| `POST` | `/wb/alerts/{event_id}/read` | 无 | `event_id` |
| `POST` | `/wb/projects` | `name`（1 到 200） | `project_id` |
| `POST` | `/wb/protocols` | `protocol`（一个 `ResearchProtocol`；`id` 和 `project_id` 为 1 到 100，`version` 为 1 到 1000000，不能有 NaN 或无穷大） | `protocol_id`、`version`、`digest` |
| `POST` | `/wb/rounds` | `project_id`、`protocol_id`（各 1 到 100） | `round_id`、`state` |
| `GET` | `/wb/rounds/{round_id}` | 无 | `round_id`、`project_id`、`protocol_id`、`protocol_version`、`state`、`stages_done`、`stage_total`、`awaiting_choice`、`snapshot_id`、`report_artifact_id`，`project_name` 和 `round_number`（轮次在项目里同一协议的轮次中的序号，从 1 起），以及 `stages`（由 `stage_id`、`state`、`stage_index`（按创建顺序的序号，从 1 起）和 `phase`（协议版本给这个序号的生长期）组成的列表）。服务器找不到的名字（项目或协议已不存在、协议的生长期比阶段少）为 `null` |
| `GET` | `/wb/rounds/{round_id}/report` | 无 | 轮次已发布的报告：`round_id`、`artifact_id`、`label`、`sha256`，以及 `report`（报告文件内容：`label`、`reasons`、`conclusion`、`estimate`、`limitations`、`unresolved`、`next_round`、`evidence_chain`、`snapshot_id`；其中 `estimate` 在 `note` 之外还有 `note_code` 和 `note_params`，精确估计的 `note_code` 为空）和 `primary_endpoint`（轮次的协议所定的主要终点指标，协议已不存在时为 `null`）。只有文件和档案记录的摘要一致时才读出；不一致或轮次没有报告时返回 `state`。 |
| `POST` | `/wb/rounds/{round_id}/choice` | `choice`：`redo`、`next`、`verify` 或 `abort` | `round_id`、`state` |
| `POST` | `/wb/rounds/{round_id}/abort` | 无 | `round_id`、`state` |
| `GET` | `/wb/stages/{stage_id}/run-sheet` | 无 | `stage_id`、`state`、`run_sheet_version`、`run_sheet_digest`、`run_sheet`（即 `RunSheet`）、`findings`（由 `code`、`variant`、`params`、`message`、`blocking` 组成的列表：`variant` 为空，或把 `code` 细分到某一句话，`params` 是那句话要写出的值；先是校验器的发现，再是每个设定值的证据提示 `no_evidence`、`unverified_source`、`uncalibrated`，这些提示不阻塞）、`blocking` |
| `POST` | `/wb/projects/{project_id}/budget` | `max_calls`（整数，0 到 1000000）、`max_cost`（美元，0 到 1000000） | `project_id`、`max_calls`、`max_cost`、`remaining_calls`、`remaining_cost` |
| `POST` | `/wb/goals` | `project_id`、`goal`（去掉首尾空白后 1 到 2000）；可选 `round_id`、`constraints`（最多 20 条，每条 1 到 500）、`request_id` | `task_id`、`state`、`reused`。新目标同时写进项目对话 |
| `GET` | `/wb/projects/{project_id}/conversation` | 查询参数 `after`（一个 `seq`，默认 0） | `entries`，从旧到新，最多 500 条：`seq`、`task_id`、`role`（`user` 或某个模型角色）、`kind`（`message`、`reply`、`tool`、`status`）、`text`、`detail`（工具调用时有 `input`、`is_error`、`result`，都会截短；`status` 条目有 `reason`，以及说明任务为何结束的 `code` 和 `params`，有代码之前写下的条目没有这两项）、`at` |
| `POST` | `/wb/protocols/{protocol_id}/analysis` | `project_id`（1 到 100）、`script`（文本，1 到 20000 个字符，只编译、从不运行） | `protocol_id`、`version`、`script_sha256`、`frozen_at`、`note`（冻结的脚本不能更正） |
| `GET` | `/wb/protocols/{protocol_id}/analysis` | 查询参数 `project_id`（1 到 100） | `protocol_id`、`version`、`started`、`frozen`（`null`，或 `script_sha256`、`frozen_at`、`frozen_by`、`script`）、`snapshots`（一组 `snapshot_id`、`experiment_id`、`complete`、`run_status`、`created_at`） |
| `POST` | `/wb/analysis/runs` | `project_id`、`protocol_id`、`snapshot_id`（各 1 到 100） | `run_id`、`status`、`exit_code`、`timed_out`、`stdout`、`stderr`（后两个截到 4000 个字符） |
| `POST` | `/wb/holdouts` | `project_id`、`batch_ids`、`development_batch_ids`、`outcome_fields`（各 1 到 50 个名字，每个 1 到 100 个字符，不重复；两个批次列表不重叠，开发批次至少 2 个） | `holdout_id`（由服务端生成）、`project_id`、`batch_ids`、`outcome_fields`、`development_batch_ids`、`registered_at`、`registered_by`（会话中的操作员） |
| `POST` | `/wb/evidence` | `source_class`（`handbook`、`paper` 或 `local`）、`citation`（去掉首尾空白后 1 到 500 个字符）、`claim`（1 到 1000）；可选 `value`（有限数）、`unit`（最多 40）、`calibrated`（默认为真） | `id`（由服务器生成）、`verified`（恒为真：录入的操作员当场核实）、`source`（`operator:<姓名>`） |
| `POST` | `/wb/evidence/{card_id}/verify` | 可选 `note`（最多 500 个字符），可选 `calibrated`（默认为假：操作员证明这个数值已用本地测量校准过） | `card_id`、`verified`、`verified_by`、`verified_at`、`note`、`calibrated`。重复核实返回第一条记录（含证明），不再写入；对已核实的卡再传 `calibrated: true` 不会改变任何东西。卡不存在以 `state` 拒绝 |
| `GET` | `/wb/evidence` | 无 | `cards`：每张卡，另有 `source`（`operator:<姓名>` 或 `model:planner`）、`task_id`、`added_at`、`verified`、`verified_by`、`verified_at`、`note` |
| `GET` | `/wb/holdouts` | 查询参数 `project_id` | `holdouts`：每个登记如上，另有 `reads`，一组 `reader`、`at`、`label`、`model_sha` |
| `POST` | `/wb/compute/balance` | `cpu_hours`（有限的数，0 或更大；字符串和布尔值会被拒绝），可选 `note`（最多 500 个字符） | 这条录入：`cpu_hours`、`entered_by`（会话里的操作员；请求体里的姓名会被丢弃）、`note`、`recorded_at` |
| `POST` | `/wb/compute/tasks/{task_id}/budget` | `cpu_hours`、`storage_gb`（有限的数，0 或更大） | 该任务的一行：`task_id`、`cpu_hours_budget`、`storage_gb_budget`、`cpu_hours_used`、`storage_gb_used`、`cpu_hours_reserved`、`storage_gb_reserved`。任务不存在时以 `scope` 拒绝。 |
| `POST` | `/wb/compute/attempts/{attempt_id}/settle` | `reason`（去掉首尾空白后 1 到 500 个字符） | `attempt_id`、`phase`（`failed`）、`task_state`、`used_cpu`、`used_storage`、`settled_by`（会话里的操作员）、`settle_reason`、`error`、`error_code`、`error_params`。仍在进行的尝试按全额预留计账；用量已经计过账的，保持原来的账。已经是终态的或不存在的尝试以 `state` 拒绝。 |
| `GET` | `/wb/compute` | 无 | `balance`（最近一条录入，或 `null`）、`tasks`（如上的行）、`service`（`cpu_hours_cap`、`storage_gb_cap`、`cpu_hours_committed`、`storage_gb_committed`）、`jobs`（进行中的尝试：`attempt_id`、`task_id`、`template_id`、`phase`、`task_state`、`remote_job_id`、`created_at`）、`stuck`（需要人处理的尝试：`attempt_id`、`task_id`、`phase`、`reason`、`reason_code`、`reason_params`、`since`；原因是尝试自己的错误时还有 `error_code` 和 `error_params`；有代码之前存下的行没有代码） |
| `GET` | `/wb/inbox` | 无 | `items` 和 `truncated`。每个条目有 `kind`（`stage_review`、`stage_manual`、`stage_recovery`、`stage_paused`、`alert`、`compute_stuck`、`round_choice` 或 `task`）、`id`、`project_id`、`round_id`、`since` 和 `detail`，以及名字 `project_name`、`round_number`、`stage_index` 和 `phase`（找不到或该类型没有时为 `null`：`stage_*` 条目四个都有，`round_choice` 条目有 `project_name` 和 `round_number`，`task` 条目有 `project_name`）。每一类最多保留 50 条：告警先按严重程度，同一严重程度内从未被读过的排在再次询问的之前，再按最近一次触发的时间取舍，其他类型取最早的。`alert` 条目的 `detail` 有 `alert_kind`、`severity`、`message`、`count`、`last_at` 和 `never_read`（没有操作员读过它、或读的时候没有记录严重程度时为 `true`）。`alert` 条目的 `detail` 还有告警的 `code` 和 `params`；`compute_stuck` 条目的 `detail` 就是 `/wb/compute` 给出的那一行。`round_choice` 条目的 `detail` 有 `awaiting_choice` 和 `since_from`：`stage_stopped` 表示 `since` 是 `awaiting_choice` 所指阶段停止的时间，`round_created` 表示那个阶段已不存在或没有停止，`since` 是轮次的创建时间。保留下来的条目按最早的在前排列，`truncated` 给出每一类被截掉的条数。 |
| `GET` | `/wb/projects` | 无 | `projects`：每个项目的摘要，最多 200 个；其中的 `latest_round` 还有 `round_number` |
| `GET` | `/wb/projects/{project_id}` | 无 | 项目的 `project_id`、`name`、`created_at`、`rounds`（新的在前，每个带 `round_number`）和 `protocols`（每个协议的最新版本）、`budget`（`calls_left`、`cost_left`、`used_calls`、`used_cost`、`max_calls` 和 `max_cost`，没有设置预算时为 `null`；`used_cost` 可以超过 `max_cost`，照实显示）和 `tasks`（最多 100 条）。项目不存在时以 `state` 拒绝。 |
| `GET` | `/wb/stages/{stage_id}/readings` | 查询参数 `points`（2 到 2000，默认 600） | `samples`（由 `timestamp`、`data`、`quality`、`clock_synced`、`flagged` 组成的列表）、`window`（`start`、`end`、`bucket_seconds`，阶段尚未开始时为 `null`）、`total_samples`、`flagged_total` 和 `downsampled`。每个时间桶保留最新的一条样本；`flagged` 是该桶里质量不是 `ok` 或时钟未同步的样本数。`points` 超出范围时返回 422。 |
| `GET` | `/wb/environment` | 查询参数 `window`（秒，300 到 604800，默认 21600）、`points`（2 到 1000，默认 360） | 实时环境页的数据，取自档案，不向设备发请求：`now`、`clock_synced`；`latest` 是最新一条样本（`timestamp`、`age_seconds`、`quality`、`clock_synced`、`experiment_id`、`sensors`，以及 `channels` 里每个通道记录的 `level` 和 `on`），没有样本时为 `null`；`stage` 是当前阶段，包括它的 `project_name`、`round_number`、`stage_index` 和 `phase`（找不到时各为 `null`）、它的 `state`、每个通道的 `ownership`，以及仅在阶段处于 `running` 时运行单此刻要求的档位 `expected`（其他状态为 `null`）和 `planned`（时间窗内的计划：`light`、`exhaust`、`fan` 各一个 `[时间, 档位]` 点的列表，窗口起点一个、每次计划变化一个；阶段不在运行时为 `{}`；温度和湿度没有计划值）；没有当前阶段时 `stage` 为 `null`；`sensors` 和 `level_ranges` 取自设备能力；`alerts` 是按严重程度计数的未处理告警；`readings` 是时间窗内的全部样本（不论是否属于阶段），格式和阶段读数相同。 |
| `GET` | `/wb/stages/{stage_id}/measurements` | 无 | `measurements`：该阶段所属实验的测量，包含已被更正的 |
| `GET` | `/wb/stages/{stage_id}/manual-tasks` | 无 | `stage_id`、`stage_state`、`timezone`、`on_time_seconds`、`early_seconds`、`now`，以及 `occurrences`：运行单的人工任务在阶段时间窗内的每一次（`task_id`、`kind`、`due_at`、`make_up_allowed`、`seconds`），带 `status`（`upcoming`、`open`、`done`、`late`、`skipped`、`missed`）和起作用的那条 `record`（没有时为 `null`）；阶段开始前为空 |
| `GET` | `/wb/stages/{stage_id}/history` | 无 | `history`（阶段的状态变化）和 `interventions`（该实验中属于本阶段的干预） |
| `GET` | `/wb/safety` | 无 | `safety`：已批准的 `SafetyConfig`（含 `frozen`：每个传感器的 `minutes` 和 `max_gap_seconds`），没有批准过时为 `null` |

已保存的协议版本不会被覆盖：`id` 和 `version` 相同而内容不同，会以 `state` 被拒绝。`POST /wb/rounds` 使用最新保存的版本。读取路由给出的 `run_sheet_digest` 就是审批记录里的那个摘要。再设一次预算只改上限，已记录的用量保留。`POST /wb/goals` 创建一个归编排 Agent 所有的研究任务；项目还没有预算，或者预算已经用完时，它以 `budget` 被拒绝。带 `request_id` 时，同一个操作员对同一个项目把同样的请求再发一次，得到的是第一次建的任务，并带 `"reused": true`；同一个 ID 下换了目标文本、轮次或约束条件，会以 `state` 被拒绝。不带 `request_id` 时，每次请求都新建一个任务。这些路由路径里的 ID 为 1 到 100 个字符。分析路由冻结协议最新版本的分析脚本（这个版本下一旦有阶段启动，冻结就以 `state` 被拒绝），并在一份数据快照上把它运行一次；它们的检查顺序见[开展一轮研究](Run-a-Research-Round.md#运行冻结的分析)。

`request_id` 的规则和桥接 API 相同。`POST /wb/manual/{channel}` 和 `POST /wb/irrigation` 要求阶段处于 `manual` 状态。对 `POST /wb/manual/pump`，`level` 为 1 会以 `pump_on_forbidden` 被拒绝。

控制台显示的文字由代码拼出，不取英文句子。一个代码属于某一族（`alert`、`finding`、`receipt`、`task_end`、`compute_error`、`compute_stuck`、`chat_end`、`estimate`），`params` 放句子要写出的值，控制台按页面语言写出文字。各族代码的完整清单在 `tests/web/fixtures/message-codes.json`，由 `scripts/export_message_codes.py` 从 `src/growbridge/codes.py` 导出。`message`、`error`、`reason` 和 `note` 保持英文、内容不变，供日志、旧客户端和通知使用。有代码之前存下的记录没有代码，控制台显示一句通用的话。

人起的名字显示出来，id 只进技术详情。处理相关的发现 `treatment_not_applied`、`no_replication` 和 `missing_control.unallocated` 在 `treatment`、`treatments` 或 `control` 里写处理的名字，在 `treatment_id`、`treatment_ids` 或 `control_id` 里写 id。`unknown_treatment` 和 `missing_control.undefined` 没有名字可写，仍写 id。计划浇水时没能确认水泵已关，任务记录以 `task_end` 族的 `pump_off_unconfirmed` 结束（无参数），它优先于这次运行自己的提前结束代码。因输出文件太多而被拒绝的取回带 `compute_error` 族的 `too_many_files`，参数是 `file_count` 和 `limit_count`；其余输出上限仍是 `output_limit`。

| 状态码 | 什么情况 | 响应体 |
| --- | --- | --- |
| 401 | 拒绝码 `session` | `{"detail": {"code": "<code>", "message": "<text>"}}` |
| 403 | 本表没有单独列出的其他所有拒绝码 | 同样的结构 |
| 409 | 拒绝码 `state` | 同样的结构 |
| 429 | 拒绝码 `locked` | 同样的结构 |
| 404 | `GET /wb/receipts/{request_id}` 的 ID 不存在 | `{"detail": {"code": "state", "message": "Unknown request id", "reason": "unknown_request", "params": {"request_id": "<id>"}}}` |
| 422 | `level` 超出该通道的范围，测量记录没有被接受，或者协议的 ID 或版本超出范围、含有非有限的数 | `{"detail": {"code": "param", "message": "<text>"}}` |
| 422 | 请求体没有通过校验，包括运行单里有非有限的数 | 校验错误列表；请求里的 NaN 或无穷大以文本形式回显 |

每个拒绝都会说明原因。工作台路由的 `detail` 对象多出 `reason`（`denial` 族的一个代码，没有原因的拒绝为 `null`）和 `params`（对象，原因不带参数时为空）：`{"detail": {"code": "<code>", "message": "<text>", "reason": "<reason>", "params": {}}}`。桥接路由的 `detail` 仍是字符串，响应体多出顶层的 `code`、`reason` 和 `params`。粗码和状态码不变，`message` 仍是英文文本。一个原因属于一个粗码（它的 `of`）；控制台按页面语言写出该原因的句子，旧客户端或没有原因时退回到粗码。`tests/web/fixtures/message-codes.json` 的 `denial` 族列出每个原因及其 `params`、`action`（控制台给出的下一步）和 `of`。表单字段在发出请求之前显示的文字由控制台自己给出（`msg.validation.*`），不属于这个 API。模型看到的仍是 `Error: denied (<code>): <message>`，看不到原因。

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
| orchestrator | `get_task_status` | read | `task_id` | 读取正在运行的任务或它下面委派出去的任务的状态，以及它的产物 ID。 |
| orchestrator | `read_artifact` | read | `artifact_id` | 核对摘要后读取一个已登记的文本产物。 |
| planner | `get_device_capabilities` | read | 无 | 读取设备的传感器、通道和档位范围。 |
| planner | `find_prior_runs` | read | `experiment_id` | 列出一个实验的数据快照和测量条数。 |
| planner | `lookup_crop_conditions` | web | `crop` | 搜索某种作物的生长条件。 |
| planner | `search_and_verify_sources` | web | `query` | 搜索资料来源。 |
| planner | `check_experimental_design` | read | `project_id`、`protocol_id` | 检查一份已保存的研究协议的设计。 |
| planner | `estimate_sample_size` | read | `effect`、`sd` | 估算需要多少个区组或实验单位。 |
| planner | `validate_run_sheet` | read | `run_sheet` | 校验运行单，但不保存。带 `round_id` 时，还会像 `save_plan_draft` 一样检查运行单是否执行了本轮分配的处理。 |
| planner | `query_evidence` | read | 无 | 在档案里搜索证据卡；每张卡都标明操作员是否已核实。 |
| planner | `propose_evidence_card` | write | `task_id`、`source_class`、`citation`、`claim` | 把计划 Agent 读到的一条来源存成“未核实”的证据卡，返回 `card_id`，供运行单引用。它不能核实证据卡。 |
| planner | `save_plan_draft` | write | `round_id`、`run_sheet` | 提交运行单草稿，等操作员审阅。它不做审批。没有执行本轮分配处理的运行单（`treatment_not_applied`）不会保存。 |
| researcher | `inspect_stage_data` | read | `task_id`、`stage_id` | 按冻结会用的时间窗汇总一个已启动阶段的数据（覆盖率、缺口、样本数、各通道取值范围、各指标的人工测量、人工任务是否按时完成、已有快照），不写入任何东西。留出批次的测量只给条数。 |
| researcher | `freeze_dataset` | write | `task_id`、`stage_id` | 把一个阶段的数据冻结成经过校验的数据快照；带 `round_id` 且快照完整时，还会推进轮次。 |
| researcher | `query_evidence` | read | 无 | 在项目档案里搜索证据卡。 |
| researcher | `run_local_analysis` | sandbox | `task_id`、`snapshot_id`、`script` | 在沙箱里对一个数据快照运行探索性脚本。 |
| researcher | `submit_compute_job` | write | `task_id`、`template_id` | 按已登记的模板提交一个计算作业。 |
| researcher | `get_compute_job` | read | `attempt_id` | 读取计算作业的状态。 |
| researcher | `fetch_compute_artifacts` | write | `attempt_id` | 取回并校验计算作业的输出。 |
| researcher | `publish_research_report` | write | `task_id`、`protocol_id`、`treatment_id`、`snapshots` | 发布本轮的报告；带 `round_id` 且报告为最终版时，还会交付轮次。返回 `treatment_check`：设备记录的档位和分配处理不符的轮次（按方案偏离计算），以及样本里没有档位、无法核对的轮次；`manual_task_check`：每轮计划的人工任务数和没有按时完成的次数；`server_notes`：服务器加进报告的每条说明，含中英文。 |

证据卡。`propose_evidence_card` 需要调度器正在运行的任务，而且这个任务必须是计划任务。不管输入怎么写，卡片都以“未核实”保存，来源记为 `model:planner` 和任务 ID：输入里没有核实字段，多余的字段会被拒绝。输入里也没有 `calibrated` 字段：模型不能声称已校准，所以提议的卡以“未校准”保存，即使操作员核实之后，`uncalibrated` 提示仍然保留，直到操作员核实时用 `calibrated: true` 证明校准过（这个证明随核实记录一起保存；第一次核实为准）。操作员自己录入的卡，保留操作员录入的 `calibrated` 值。模型不能提议 `local` 卡：`source_class` 为 `local` 会以 `param` 拒绝，因为只有操作员才能把本地测量记成证据。任何类别的未核实卡，包括 `local`，在运行单的审阅里一律带 `unverified_source` 提示，直到操作员核实。卡 ID 由服务器生成，一个任务最多提议 20 张卡（`quota`）；读过网页内容的计划 Agent 在这次运行的剩余时间里就没有这个写入工具了，所以要先提议、再搜索。只有操作员能核实一张卡，经 `POST /wb/evidence/{card_id}/verify`；那会追加一条记录，卡片原文永不改动。

研究 Agent 的工具只要涉及快照、阶段、轮次或计算提交，就必须带 `task_id`。这个编号要和调度器正在运行的任务比对，而不是照单全收：任何其他编号、别的角色的任务、以及在调度运行之外发起的调用，都会以 `scope` 被拒绝；其他项目的阶段、轮次或快照同样以 `scope` 被拒绝。

另外两个角色以同样的方式绑定。编排和计划 Agent 调用里的每个 `project_id`、`round_id`、`stage_id` 和 `experiment_id`，都必须属于正在运行的任务所在的项目，而且该实验必须只有一个所属项目。`get_task_status` 只回答正在运行的任务和它下面委派出去的任务；`read_artifact` 只回答本项目任务的产物；`delegate_task` 只接受正在运行的任务作为 `parent_task_id`。以上情况都以 `scope` 拒绝。

`growbridge serve` 构建的守护进程没有传入搜索后端，所以 `lookup_crop_conditions` 和 `search_and_verify_sources` 返回 `denied (unavailable)`。`submit_compute_job`、`get_compute_job` 和 `fetch_compute_artifacts` 只在配置了计算服务时才可用（见[启用 DiAGRI](Enable-DiAGRI.md)第 5 步），否则同样返回 `denied (unavailable)`。计算输入的 `ref` 是 `<快照 id>` 或 `<快照 id>/<文件>`，服务只接受任务所属项目的、已通过校验且不含留出结果的快照；其他一律在任何字节离开本机之前被拒绝。工作台的三个计算路由只在有计算服务时存在。沙箱只在 macOS 上存在；在其他系统上，`run_local_analysis` 返回 `denied (sandbox_unavailable)`。

`agents/tools.py` 的 `CONTROL_TOOLS` 列出了 14 个阶段和设备控制类的工具名，任何模型角色都拿不到它们。这些名字都没有对应的处理函数。

## 另见

- [拒绝码与事件类型](Denial-Codes-and-Events.md)
- [配置参考](Configuration-Reference.md)
- [CLI 参考](CLI-Reference.md)
- [控制与安全模型](Control-and-Safety-Model.md)
- [Agent 一览](The-Five-Agents.md)
- [术语表](Glossary.md)
