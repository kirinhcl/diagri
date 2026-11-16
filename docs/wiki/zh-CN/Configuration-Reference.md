# 配置参考

[English](../en/Configuration-Reference.md)

这一页写给安装和运维 DiAGRI 的人。它列出配置文件的每个字段、加载时做的检查，以及哪些值只从环境变量读取、从不写进文件。

字段定义在 [`config.py`](../../../src/growbridge/config.py) 的 `Settings` 和 `RoleModel` 里。本页说的"仅桥接模式"指 `auto_research = false`，也就是默认值。

## 配置文件

| 项目 | 值 |
| --- | --- |
| 格式 | TOML |
| 默认路径 | `~/.config/spiderfarmer-growbridge/config.toml`，由 `default_config()` 给出 |
| 指定其他路径 | `growbridge --config /absolute/path/to/config.toml <command>` |
| 谁会读它 | 除 `init`、`scan`、`simulate` 以外的所有命令（见 [CLI 参考](CLI-Reference.md)） |
| 未知的键 | 拒绝加载：`Settings` 和 `RoleModel` 都设置了 `extra="forbid"` |

## `Settings` 字段

共 25 个字段。"必填"表示没有默认值。最后一列说明该字段是否只在 DiAGRI 模式下起作用。

| 字段 | 类型 | 默认值 | 允许的取值 | 作用 | 仅 DiAGRI |
| --- | --- | --- | --- | --- | --- |
| `device` | 字符串 | 必填 | 任意字符串 | AC5 的地址或 UUID，取 `growbridge scan` 在本机打印的值。 | 否 |
| `token` | 字符串 | 必填 | 至少 24 个字符 | 桥接 HTTP API 的 Bearer 令牌。CLI 和 MCP 服务从这个文件读取它。在 DiAGRI 模式下它只能读、不能写。 | 否 |
| `data_dir` | 路径 | 必填 | 任意路径；`~` 会展开 | 存放数据库、`daemon.lock` 和 `host_id` 的目录。 | 否 |
| `port` | 整数 | `8766` | 1024 到 65535 | `127.0.0.1` 上监听的端口。在 DiAGRI 模式下，只有从这个端口进来的请求才可能属于覆盖网络入口。 | 否 |
| `controls_enabled` | 布尔 | `false` | `true`、`false` | 是否允许写设备。为 `false` 时，桥接 API 返回 409，控制服务以 `controls_disabled` 拒绝。 | 否 |
| `stale_seconds` | 数值 | `20` | 5 到 120 | 最新样本超过多少秒算过期（`health.stale`）。普通写入要求数据新鲜。 | 否 |
| `max_pump_seconds` | 数值 | `5` | 大于 0，不超过 60 | 水泵单次运行的最长秒数。仅桥接模式下约束 `POST /pump`，DiAGRI 模式下约束 `POST /wb/irrigation`。 | 否 |
| `pump_cooldown_seconds` | 数值 | `60` | 不小于 0 | 两次开泵之间的最短间隔，单位秒。 | 否 |
| `pump_outlet` | 整数 | `4` | 1 到 5 | 水泵接在哪个插座。 | 否 |
| `light_outlet` | 整数 | `1` | 1 到 5 | 灯接在哪个插座。 | 否 |
| `exhaust_outlet` | 整数 | `2` | 1 到 5 | 排风扇接在哪个插座。 | 否 |
| `fan_outlet` | 整数 | `3` | 1 到 5 | 循环风扇接在哪个插座。 | 否 |
| `retention_days` | 整数 | `30` | 1 到 365 | 守护进程的样本库保留多少天的样本。在 DiAGRI 模式下，只删除已经复制到项目档案的样本。 | 否 |
| `auto_research` | 布尔 | `false` | `true`、`false` | 把守护进程切换到 DiAGRI 模式：启动运行时和工作台路由，三个桥接写入路由返回 403，MCP 服务只提供读取工具。 | 它就是开关 |
| `lan_hosts` | 字符串列表 | `[]` | 主机名或地址；端口部分会被忽略 | 局域网入口的地址。它们会加入受信任主机和允许的浏览器来源。 | 是 |
| `overlay_hosts` | 字符串列表 | `[]` | 主机名或地址；端口部分会被忽略 | 覆盖网络入口的地址。它们会加入受信任主机和允许的浏览器来源（按 `https://`）。 | 是 |
| `lan_bind` | 字符串 | `""` | 本机的一个地址 | 局域网监听绑定的地址。只有 `lan_bind` 和 `lan_port` 都设置了，这个监听才会启动。 | 是 |
| `lan_port` | 整数或不设置 | 不设置 | 1024 到 65535 | 局域网监听的端口。请求必须从这个端口进来，并且 `Host` 在 `lan_hosts` 里，才属于局域网入口。不设置就没有局域网入口。 | 是 |
| `report_time` | 字符串 | `"08:00"` | 24 小时制 `HH:MM`，`00:00` 到 `23:59` | 每天从这个本地时间起生成前一天的日报。只有存在活动阶段时才生成日报。 | 是 |
| `report_timezone` | 字符串 | `"UTC"` | 主机认识的 IANA 时区名 | `report_time` 和日报日期所用的时区。操作员控制台显示和录入时间也用这个时区（由 `GET /wb/me` 的 `timezone` 给出）。未知的时区名在加载时被拒绝。 | 是 |
| `roles` | `RoleModel` 表 | `{}` | 键是角色名 | 每个模型角色的模型配置。为空时，`serve` 不创建模型客户端，模型角色都不运行。 | 是 |
| `backup_dir` | 路径或不设置 | 不设置 | 任意路径；`~` 会展开 | SQLite 在线备份的目录。不设置就没有备份，运行时启动时会发出一条 `backup_unconfigured` 警告级告警。 | 是 |
| `backup_interval_seconds` | 数值 | `21600` | 不小于 60 | 两次备份之间的秒数。 | 是 |
| `compute_templates_dir` | 路径或未设置 | 未设置 | 一个存放 `*.json` 文件的目录；`~` 会被展开 | 每个 JSON 文件是一个审核过的作业模板（`JobTemplate`）。与 `compute_member` 和七个 `FIRECREST_*` 变量一起启用计算服务。启动时逐个校验；有坏文件时 `serve` 启动失败，错误信息指出文件名。 | 是 |
| `compute_member` | 字符串或未设置 | 未设置 | 至少 1 个字符 | 研究 Agent 的作业以哪个 CSC 账户名提交。 | 是 |

`report_time` 的准确模式是：

```text
^([01]\d|2[0-3]):[0-5]\d$
```

同时出现在 `lan_hosts` 和 `overlay_hosts` 里的主机，不属于任何入口（见 [`workbench/auth.py`](../../../src/growbridge/workbench/auth.py) 的 `entry_for`）。

## `RoleModel` 字段

共 9 个字段。`roles` 的每个键对应一个 `RoleModel`，写成 `[roles.<role>]` 表。这些字段都只在 DiAGRI 模式下起作用。

| 字段 | 类型 | 默认值 | 允许的取值 | 作用 |
| --- | --- | --- | --- | --- |
| `provider` | 字符串 | `"anthropic"` | `"anthropic"` | 模型提供方。代码里只有 `AnthropicClient` 这一个客户端。 |
| `model` | 字符串 | `"claude-opus-5-5"` | 任意字符串 | 该角色每次请求使用的模型名。只有默认模型有内置单价（[`agents/llm.py`](../../../src/growbridge/agents/llm.py) 的 `DEFAULT_PRICE`）；换成其他模型时必须同时设置 `input_per_mtok` 和 `output_per_mtok`，否则加载时被拒绝。 |
| `effort` | 字符串 | `"medium"` | `low`、`medium`、`high`、`xhigh`、`max` | 每次请求以 `output_config.effort` 发送。 |
| `max_tokens` | 整数 | `16000` | 256 到 64000 | 每次请求的 `max_tokens`。 |
| `max_calls` | 整数 | `20` | 不小于 1 | 该角色一次运行最多调用模型的次数（[`agents/loop.py`](../../../src/growbridge/agents/loop.py) 里 `run_agent` 的 `max_turns`）。达到上限时运行以 `max_turns` 结束，任务转为 `needs_attention`。项目调用预算（[`agents/budget.py`](../../../src/growbridge/agents/budget.py)）同时生效。 |
| `tools` | 字符串列表 | `[]` | 该角色的工具名（见[接口参考](API-Reference.md#模型角色的工具)） | 收窄该角色可用的工具。为空表示角色允许的全部工具。写入控制类工具或其他角色的工具，角色运行时会以 `model_role` 被拒绝，任务转为 `needs_attention`。 |
| `data` | 字符串列表 | `[]` | 任意字符串 | 加载时会校验，但没有代码读取它：它不限制角色能读到什么。 |
| `input_per_mtok` | 数字或不设置 | 不设置 | 不小于 0 | `model` 每百万输入 token 的价格（美元），用于费用预算。要和 `output_per_mtok` 一起设置。`model` 不是默认模型时必填。 |
| `output_per_mtok` | 数字或不设置 | 不设置 | 不小于 0 | `model` 每百万输出 token 的价格（美元）。要和 `input_per_mtok` 一起设置。 |

会被读取的角色名是 `orchestrator`、`planner`、`researcher` 和 `auditor`（[`agents/tools.py`](../../../src/growbridge/agents/tools.py) 的 `ROLE_TOOLS`）。其他键能通过校验，但会被忽略。只要 `roles` 里有一个键，没有列出的角色就按上表的默认值运行，监察 Agent 除外：它的默认值是默认模型，每次监察最多 6 次模型调用（`AUDIT_MAX_CALLS`）；配置了 `[roles.auditor]` 就会替换这个默认值，所以不想要 6 次时要在那里设置 `max_calls`（[`runtime_agents.py`](../../../src/growbridge/runtime_agents.py) 的 `make_dispatcher`）。

## 作业模板文件

`compute_templates_dir` 里的每个 `*.json` 文件是一个 `JobTemplate`（[`compute/backend.py`](../../../src/growbridge/compute/backend.py)）。`serve` 启动时逐个校验，第一个有错的文件会让它停下，并指出文件名。规则如下：

| 字段 | 规则 |
| --- | --- |
| `id`、`version` | 这一对在所有文件里必须唯一。同一个 `id` 的最新版本是实际运行的版本；被重试的尝试所用的版本已被取代时，重试会被拒绝。 |
| `script` | Slurm 批处理脚本。必须以 `#!` 开头，必须设置运行时限（`#SBATCH --time=...` 或 `-t`），让作业有界，且不能自己设置作业名（服务会加上 `gb-<尝试编号>`）。参数只以 `DIAGRI_PARAM_<NAME>` 传入，输入以 `DIAGRI_INPUT_<NAME>` 传入；结果写进 `DIAGRI_OUTPUT_DIR`。 |
| `parameters` | 名字必须能用作环境变量名。`kind` 是 `int`、`float`、`str` 或 `bool`。数值可以有 `minimum` 和 `maximum`，浮点数必须是有限的。`str` 必须列出 `choices`，或者声明 `pattern`：整个取值都要匹配的正则表达式。`max_length` 可以进一步限制长度；任何文本都不超过 1000 个字符，含控制字符的值一律被拒绝。`default` 本身也要通过这些规则。没有 `default` 的参数是必填的。 |
| `max_cpu_hours`、`max_storage_gb` | 有限的数，0 或更大。这是一次尝试预留的量；接口不报告用量时，也按它计账。`max_storage_gb`（十进制 GB）同时是一次取回产物的上限：一个作业的产物合计最多这么多字节、最多 1000 个文件，否则在下载任何东西之前就拒绝取回；每次下载都被看着，文件一超过剩余额度就取消传输，已下载的文件会被删除（磁盘上可能短暂地多出一点，最多是链路在 0.25 秒内传送的量）。每个产物在 FirecREST 的列表里都必须带有大小，否则拒绝取回。 |
| `result_changing` | 参数名的列表，每个都必须存在。重试时改了其中之一，就开始新的分析版本。 |
| `max_retries` | 默认 2。 |

## `load` 做哪些检查

每个需要读配置的命令都会调用 `load`。CLI 不捕获这些错误，命令会带着回溯信息退出。

| 顺序 | 检查 | 不通过时的错误 |
| --- | --- | --- |
| 1 | 指定路径或默认路径上有这个文件（`~` 会展开）。 | `FileNotFoundError` |
| 2 | 文件是合法的 TOML。 | `tomllib.TOMLDecodeError` |
| 3 | 有 `data_dir`。 | `KeyError` |
| 4 | 每个字段符合上面两张表的类型、范围和模式，并且没有未知的键。`report_timezone` 是已知时区。使用非默认模型的角色写明了两个单价。 | `pydantic.ValidationError` |
| 5 | `pump_outlet`、`light_outlet`、`exhaust_outlet`、`fan_outlet` 是四个不同的编号。 | `ValueError: Each device must have a separate outlet` |

`load` 不读取模板文件，`serve` 在启动时检查它们。`load` 不检查这些：`data_dir`、`backup_dir` 和 `compute_templates_dir` 是否存在，`lan_bind` 和 `lan_port` 是否成对设置，`roles` 里的角色名，以及 `tools` 里的工具名。

## `initialize` 写入什么

`growbridge init --device DEVICE` 调用 `initialize`。它以 `0700` 权限创建上级目录，以 `0600` 权限创建文件。它从不覆盖：文件已存在就失败。它写入下面 11 个键，不写任何 DiAGRI 字段。

| 键 | 写入的值 |
| --- | --- |
| `device` | `--device` 参数 |
| `token` | 由 `secrets.token_urlsafe(32)` 新生成的随机值 |
| `data_dir` | `~/.local/share/spiderfarmer-growbridge`，写成绝对路径 |
| `controls_enabled` | `false`；带 `--enable-controls` 时为 `true` |
| `port` | `8766` |
| `max_pump_seconds` | `5` |
| `pump_cooldown_seconds` | `60` |
| `light_outlet` | `1` |
| `exhaust_outlet` | `2` |
| `fan_outlet` | `3` |
| `pump_outlet` | `4` |

## 从不写进文件的值

凭据从 `growbridge serve` 进程的环境变量读取，全部只在 DiAGRI 模式下起作用。向真实的 Telegram 和 SMTP 服务投递尚未验证，见[状态与已知限制](Status-and-Known-Limitations.md)。

| 变量 | 在哪里读取 | 是什么 | 规则 |
| --- | --- | --- | --- |
| 代码里没有写出变量名 | [`agents/llm.py`](../../../src/growbridge/agents/llm.py) 的 `AnthropicClient` | 模型凭据 | 客户端用不带参数的 `anthropic.AsyncAnthropic()` 创建，凭据由 SDK 从它自己的环境变量解析。测试里设置的是 `ANTHROPIC_API_KEY`。SDK 属于可选依赖 `agents`。客户端创建不了时，`serve` 记一条警告日志，发出 `model_client` 告警，然后在没有模型角色的情况下继续运行。 |
| `GROWBRIDGE_ROLE_TOKEN_<ROLE>` | [`cli.py`](../../../src/growbridge/cli.py) 的 `role_tokens_from_env` | 模型角色调用工作台路由时用的 Bearer 令牌。角色 ID 是后缀的小写形式。 | 至少 32 个字符，否则 `serve` 在启动任何东西之前就退出。空值会被忽略。 |
| `GROWBRIDGE_TELEGRAM_TOKEN` | [`runtime.py`](../../../src/growbridge/runtime.py) 的 `default_channels`，[`observer/channels.py`](../../../src/growbridge/observer/channels.py) 的 `TelegramChannel` | Telegram 机器人令牌 | 只有它和 `GROWBRIDGE_TELEGRAM_CHAT_IDS` 都设置了，才有 `telegram` 渠道。 |
| `GROWBRIDGE_TELEGRAM_CHAT_IDS` | `default_channels` | 接收通知的 chat ID | 用逗号分隔。 |
| `GROWBRIDGE_EMAIL_TO` | `default_channels` | 邮件通知的收件人 | 用逗号分隔。只有它和 `GROWBRIDGE_SMTP_HOST` 都设置了，才有 `email` 渠道。 |
| `GROWBRIDGE_SMTP_HOST` | `default_channels`，`observer/channels.py` 的 `_smtp_send` | SMTP 服务器 | 连接总是使用 STARTTLS。 |
| `GROWBRIDGE_SMTP_PORT` | `_smtp_send` | SMTP 端口 | 默认 `587`。 |
| `GROWBRIDGE_SMTP_USER` | `_smtp_send` | SMTP 登录名 | 不设置就不登录。 |
| `GROWBRIDGE_SMTP_PASSWORD` | `_smtp_send` | SMTP 密码 | 默认为空。 |
| `GROWBRIDGE_SMTP_FROM` | `_smtp_send` | 发件人地址（`From`） | 默认是 SMTP 登录名；没有登录名时是 `growbridge@localhost`。 |
| `FIRECREST_URL` | [`compute/firecrest.py`](../../../src/growbridge/compute/firecrest.py) 里的 `FirecrestBackend` | FirecREST API 的基础地址，例如 `https://api.roihu.csc.fi/v1`（FirecREST v2）。 | 属于"要么全配、要么都不配"的计算服务设置：这九项（这七个变量加 `compute_templates_dir`、`compute_member`）缺任何一项，计算服务都不会启动，日志只写缺了哪些名字，不写取值。 |
| `FIRECREST_TOKEN_URL` | [`compute/firecrest.py`](../../../src/growbridge/compute/firecrest.py) 里的 `FirecrestBackend` | 机器人账户的 OAuth 令牌地址，例如 `https://user-auth.csc.fi/idp/profile/oidc/token`。 | 属于"要么全配、要么都不配"的计算服务设置：这九项（这七个变量加 `compute_templates_dir`、`compute_member`）缺任何一项，计算服务都不会启动，日志只写缺了哪些名字，不写取值。 |
| `FIRECREST_CLIENT_ID` | [`compute/firecrest.py`](../../../src/growbridge/compute/firecrest.py) 里的 `FirecrestBackend` | CSC 机器人账户的客户端 ID（即账户名）。 | 属于"要么全配、要么都不配"的计算服务设置：这九项（这七个变量加 `compute_templates_dir`、`compute_member`）缺任何一项，计算服务都不会启动，日志只写缺了哪些名字，不写取值。 |
| `FIRECREST_CLIENT_SECRET` | [`compute/firecrest.py`](../../../src/growbridge/compute/firecrest.py) 里的 `FirecrestBackend` | 机器人账户的客户端密钥（即它的密码）。不写日志，不进错误信息，不出现在 `repr` 里。 | 属于"要么全配、要么都不配"的计算服务设置：这九项（这七个变量加 `compute_templates_dir`、`compute_member`）缺任何一项，计算服务都不会启动，日志只写缺了哪些名字，不写取值。 |
| `FIRECREST_SYSTEM` | [`compute/firecrest.py`](../../../src/growbridge/compute/firecrest.py) 里的 `FirecrestBackend` | Roihu 的子系统：只接受 `cpu` 或 `gpu`。 | 属于"要么全配、要么都不配"的计算服务设置：这九项（这七个变量加 `compute_templates_dir`、`compute_member`）缺任何一项，计算服务都不会启动，日志只写缺了哪些名字，不写取值。 |
| `FIRECREST_ACCOUNT` | [`compute/firecrest.py`](../../../src/growbridge/compute/firecrest.py) 里的 `FirecrestBackend` | 作业计费的 CSC 项目，例如 `project_2001234`。只允许字母、数字和 `_`。 | 属于"要么全配、要么都不配"的计算服务设置：这九项（这七个变量加 `compute_templates_dir`、`compute_member`）缺任何一项，计算服务都不会启动，日志只写缺了哪些名字，不写取值。 |
| `FIRECREST_WORKDIR` | [`compute/firecrest.py`](../../../src/growbridge/compute/firecrest.py) 里的 `FirecrestBackend` | 远端工作目录的绝对路径，每个作业在其下有自己的 `gb-<尝试编号>` 目录，例如 `/scratch/project_2001234/diagri`。不能含 `..`。 | 属于"要么全配、要么都不配"的计算服务设置：这九项（这七个变量加 `compute_templates_dir`、`compute_member`）缺任何一项，计算服务都不会启动，日志只写缺了哪些名字，不写取值。 |

两个渠道都没有配置时，不会有任何通知入队。告警照常记录，`GET /wb/alerts` 可以看到，运行时启动时还会发出一条 `notify_unconfigured` 警告级告警（[`runtime.py`](../../../src/growbridge/runtime.py) 的 `build_runtime` 和 `Runtime.start`）。

## 冻结读数门槛（`SafetyConfig.frozen`）

它不在配置文件里：门槛是已批准安全配置的一个字段 `SafetyConfig.frozen`，类型是 [`archive/models.py`](../../../src/growbridge/archive/models.py) 里的 `FrozenCheck`。它和其余安全限值一起由人批准（`POST /wb/safety/approve`），工作台的安全页会显示。观察者会标出读数持续完全不变、超过门槛的传感器。

| 字段 | 类型 | 默认值 | 校验 | 作用 |
| --- | --- | --- | --- | --- |
| `minutes` | 传感器名到数字的字典 | `{"temp": 120, "humi": 60, "co2": 60, "tempSoil": 240}`（`DEFAULT_FROZEN_MINUTES`，每份配置各拿一份副本） | 每个值必须大于 0 且不超过 1440（`0`、负数、NaN、无穷大和超过 1440 的值都会被拒绝）。允许空字典，意思是不检查任何传感器。批准时，设备没有的传感器名会被拒绝（`approval_invalid`）；AC5 有 `temp`、`humi`、`vpd`、`co2`、`ppfd` 和 `tempSoil`。拼错的名字因此不会悄悄关掉某项检查。 | 传感器读数保持不变多少分钟后算冻结。没有写在里面的传感器不检查。 |
| `max_gap_seconds` | 数字 | `600` | 大于 0 且不超过 3600（NaN、无穷大和更大的值会被拒绝）。 | 两次读数之间最长多少秒的空档，仍算同一段不间断的相同读数。 |

没有批准过安全配置时，门槛用上面的默认值。这个字段出现之前存下来的安全配置没有 `frozen`，读出来时用默认值。

## 没有对应配置项的功能

| 功能 | 代码里的现状 |
| --- | --- |
| 外部心跳（`ExternalMonitor`、`HeartbeatChannel`） | `Settings` 里没有字段，由环境变量 `GROWBRIDGE_HEARTBEAT_HOST_URL` 和 `GROWBRIDGE_HEARTBEAT_RUN_URL` 设置。两个都设或者都不设：只设一个，`serve` 拒绝启动；都不设，发出警告 `monitor_unconfigured`。URL 是机密，不会写进日志。见[通知、日报与备份](Notifications-Reports-and-Backup.md)。 |
| 计算服务（`ComputeService`） | 由 `compute_templates_dir`、`compute_member` 和七个 `FIRECREST_*` 环境变量设置，要么全配、要么都不配。全配：`serve` 在 `FirecrestBackend` 上创建计算服务。都不配：没有计算服务。配了一部分：没有计算服务，日志里警告缺了哪些名字。模板有错、没装 `pyfirecrest`，或 `FIRECREST_SYSTEM`、`FIRECREST_ACCOUNT`、`FIRECREST_WORKDIR` 无效，都会让 `serve` 启动失败。没有对真实的 CSC 服务验证过；见[状态与已知限制](Status-and-Known-Limitations.md)。 |
| 告警规则 | `Settings` 里没有字段。`runtime.py` 的 `DEFAULT_ALERT_RULES` 是空的。 |
| 操作员账号 | 由 `growbridge operator add` 存进 `data_dir`，不在配置文件里。 |

## 示例

最小的仅桥接模式配置。控制保持关闭。

```toml
device = "YOUR_SCANNED_ADDRESS"
token = "REPLACE_WITH_AT_LEAST_24_CHARACTERS"
data_dir = "/absolute/path/to/data"
```

最小的 DiAGRI 配置：两个入口、备份，以及四个都用默认值的模型角色。

```toml
device = "YOUR_SCANNED_ADDRESS"
token = "REPLACE_WITH_AT_LEAST_24_CHARACTERS"
data_dir = "/absolute/path/to/data"
controls_enabled = true
auto_research = true
lan_hosts = ["YOUR_PI_LAN_ADDRESS"]
lan_bind = "YOUR_PI_LAN_ADDRESS"
lan_port = 8767
overlay_hosts = ["YOUR_PI_OVERLAY_NAME"]
backup_dir = "/absolute/path/to/backup"

[roles.orchestrator]

[roles.planner]

[roles.researcher]
```

## 另见

- [CLI 参考](CLI-Reference.md)
- [HTTP、工作台与 MCP 接口](API-Reference.md)
- [启用 DiAGRI](Enable-DiAGRI.md)
- [通知、日报与备份](Notifications-Reports-and-Backup.md)
- [术语表](Glossary.md)
