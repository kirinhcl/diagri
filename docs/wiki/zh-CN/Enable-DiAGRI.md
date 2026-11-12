# 启用 DiAGRI

[English](../en/Enable-DiAGRI.md)

这一页写给已经在跑仅桥接模式守护进程、想打开 DiAGRI 的操作员：要改哪些配置项，怎么登记写入主机和第一个操作员，凭据从哪里来，怎么启动 `serve`、怎么确认它起来了，以及怎么再关掉。

> **现在打开之后能得到什么。** 设了 `auto_research = true`，`serve` 会启动运行时，大约每秒跑一次执行 Agent，挂上 `/wb` 下的工作台路由；配置了 `roles` 时，每 30 秒处理一次未完成的模型任务。操作员通过这些路由发起一轮研究：项目、研究协议、轮次、模型调用预算和目标，见[运行一轮研究](Run-a-Research-Round.md)。这件事没有网页，也没有 CLI 命令。真实模型拿到目标后会做什么，从没有运行过：测试用的是脚本化的模型。`serve` 也不发送外部心跳，不启动计算服务。以上这些都只在模拟的 AC5 上测试过。见[状态与已知限制](Status-and-Known-Limitations.md)。

## 开始之前

- 仅桥接模式已经能用：`.venv/bin/growbridge status` 能打印设备状态。还不行的话，先看[安装与快速开始](Installation-and-Quick-Start.md)。
- 知道守护进程用的是哪个配置文件。默认是 `~/.config/spiderfarmer-growbridge/config.toml`。用别的文件时，在下面每条命令的子命令前面加 `--config /absolute/path/to/config.toml`。
- 想先不接设备看看效果，可以跑 `.venv/bin/growbridge simulate`。它不需要配置文件，会打印一段摘要，其中 `"stage": "ended"`。见[教程：在模拟器上跑通一轮研究](Tutorial-Simulated-Round.md)。

## 1. 停掉守护进程

前台运行的 `serve` 用 Ctrl-C 停掉。装成后台服务的，先把服务卸掉：

```sh
.venv/bin/python scripts/install_macos.py --uninstall   # macOS
.venv/bin/python scripts/install_linux.py --uninstall   # Linux
```

配置文件只在 `serve` 启动时读一次。

## 2. 填写配置项

顶层的配置项要写在所有 `[roles.*]` 表之前，因为 TOML 会把表头之后的键都算进那张表。

```toml
auto_research = true
controls_enabled = true

lan_bind = "YOUR_LAN_ADDRESS"
lan_port = 9443
lan_hosts = ["YOUR_LAN_HOST"]
overlay_hosts = ["YOUR_OVERLAY_HOST"]

report_time = "08:00"
report_timezone = "Europe/Helsinki"

backup_dir = "/absolute/path/to/backup"
backup_interval_seconds = 21600

[roles.planner]
model = "claude-opus-5-5"
effort = "medium"
max_tokens = 16000
```

| 配置项 | 填什么 | 不填会怎样 |
| --- | --- | --- |
| `auto_research` | `true` | 守护进程按仅桥接模式运行。 |
| `controls_enabled` | `true` | 所有写入都被拒绝，拒绝码 `controls_disabled`，执行 Agent 什么也做不了。 |
| `lan_bind`、`lan_port` | 现场监听的地址和端口。端口单独用一个，不要和 `port` 相同。 | 两项都填了才会启动这个监听。没有它就没有局域网入口，灌溉会被拒绝，拒绝码 `entry`。 |
| `lan_hosts` | 现场的客户端在 `Host` 头里写的主机名或地址。 | 任何请求都不会被认作局域网入口。 |
| `overlay_hosts` | 覆盖网络地址的主机名。 | 没有覆盖网络入口。 |
| `report_time`、`report_timezone` | `HH:MM` 和 IANA 时区名。 | `08:00` 和 `UTC`。 |
| `backup_dir`、`backup_interval_seconds` | 独立介质上的目录，以及两次备份之间的秒数（不小于 60）。 | 不做备份，并且一直挂着 `backup_unconfigured` 警告。间隔默认 21600。 |
| `[roles.<name>]` | 每个模型角色一张表：`orchestrator`、`planner`、`researcher`。 | 一张表都没有时，模型角色不启用。至少有一张时，没写表的角色用默认值。 |

[`config.py`](../../../src/growbridge/config.py) 的加载逻辑和 [`workbench/auth.py`](../../../src/growbridge/workbench/auth.py) 的入口判断，对这些配置项是这样处理的：

- 配置项名字写错，`serve` 启动时直接失败。顶层和角色表里都一样。
- 同时出现在 `lan_hosts` 和 `overlay_hosts` 里的主机，不算任何入口。
- 覆盖网络入口就是回环监听 `127.0.0.1:<port>`。请求到达这个监听、并且 `Host` 头在 `overlay_hosts` 里，才算覆盖网络入口。仓库不带反向代理，也不带覆盖网络的配置：需要自己准备一个 HTTPS 反向代理，转发到这个监听并保留 `Host` 头。未验证。
- 角色表里，代码实际读取的是 `model`、`effort`、`max_tokens` 和 `tools`。`provider`、`max_calls` 和 `data` 在加载时会校验，但目前没有任何地方读取。

全部配置项见[配置参考](Configuration-Reference.md)。日报和备份的行为见[通知、日报与备份](Notifications-Reports-and-Backup.md)。

## 3. 登记写入主机

```sh
.venv/bin/growbridge host register
```

应该看到 `Write host registered: <host id>`。这个 ID 保存在数据目录的 `host_id` 文件里。重复执行没有副作用。

如果被拒绝，提示 `another host is registered for this device`，说明控制数据库里登记的是另一台机器。见[故障处理手册](Troubleshooting-Runbook.md)里的“从备份恢复或更换写入主机”。

这一步要在启动 `serve` 之前做。没登记就启动的守护进程不会打开 BLE 连接，会产生告警 `runtime` / `write_host`，并拒绝写入；登记之后还要重启才生效。

## 4. 添加操作员

```sh
.venv/bin/growbridge operator add YOUR_OPERATOR
```

命令会让你输入两遍密钥，密钥不能作为参数传入。长度 12 到 256 个字符。应该看到 `Operator added: YOUR_OPERATOR`。数据库里只保存加盐哈希。

| 提示 | 怎么办 |
| --- | --- |
| `the secret needs at least 12 characters` | 换一个更长的密钥。 |
| `the two entries differ` | 重新执行命令。 |
| `operator 'YOUR_OPERATOR' already exists` | 换一个名字。目前没有删除操作员或修改密钥的命令。 |

## 5. 把凭据放进环境变量

配置文件里不放任何凭据。`serve` 从自己的进程环境里读取。

| 用途 | 来源 |
| --- | --- |
| 模型调用 | Anthropic SDK 自己读取环境变量；测试里设的是 `ANTHROPIC_API_KEY`（[`tests/agents/test_agents_llm.py`](../../../tests/agents/test_agents_llm.py)）。SDK 是 [`pyproject.toml`](../../../pyproject.toml) 里的可选依赖 `agents`：`.venv/bin/python -m pip install '.[agents]'`。`constraints-tested.txt` 没有固定它的版本。 |
| 模型角色经 HTTP 调用 `/wb` | `GROWBRIDGE_ROLE_TOKEN_<ROLE>`，例如 `GROWBRIDGE_ROLE_TOKEN_PLANNER`，请求时放在 `Authorization: Bearer ...` 里。至少 32 个字符，太短会让 `serve` 启动时退出。`serve` 自己运行的模型任务不用这些令牌。 |
| 通知 | `GROWBRIDGE_TELEGRAM_*`、`GROWBRIDGE_EMAIL_TO`、`GROWBRIDGE_SMTP_*`。见[通知、日报与备份](Notifications-Reports-and-Backup.md)。 |

`scripts/` 里的安装脚本不会往 launchd 或 systemd 服务里写环境变量。要在后台服务里用这些变量，得自己改服务定义。未验证。真实的模型调用也没有在任何测试里发生过：测试里都是打桩的。

## 6. 启动守护进程

```sh
.venv/bin/growbridge serve
```

`serve` 监听 `127.0.0.1:<port>`；填了 `lan_bind` 和 `lan_port` 时，还会监听那个地址。日志里留意这几行：

| 日志 | 含义 |
| --- | --- |
| `not the registered write host: the BLE connection stays closed` | 第 3 步没做。停掉，登记，再启动。 |
| `the device did not identify itself within 20.0 s` | AC5 没有应答。守护进程继续运行，并持续重连。 |
| `model roles are off: ...` | 配了 `roles`，但缺 SDK 或凭据。其余功能照常运行。 |
| `growbridge: the token of role '...' is shorter than 32 characters` | `serve` 已退出。修正角色令牌。 |

这两个真实的监听没有测试覆盖；测试是在进程内直接访问同一个应用。

## 7. 确认已经起来

1. `.venv/bin/growbridge status` 仍然能打印设备状态。
2. 工作台已经挂上。不带会话的请求会得到 `401`，拒绝码 `session`；得到 `404` 说明守护进程还在仅桥接模式。

   ```sh
   curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8766/wb/me
   ```

3. 从局域网入口登录。工作台没有网页，用任何能保存 Cookie 的 HTTP 客户端发请求即可。每个请求都要带的请求头见[运行一轮研究](Run-a-Research-Round.md)。

   ```http
   POST /wb/login
   Host: YOUR_LAN_HOST:9443
   Origin: http://YOUR_LAN_HOST:9443
   x-growbridge-ui: 1
   Content-Type: application/json

   {"name": "YOUR_OPERATOR", "secret": "YOUR_OPERATOR_SECRET"}
   ```

   应该得到 `{"operator": "YOUR_OPERATOR", "entry": "lan", "reauth_seconds": 300}`，以及 Cookie `growbridge_operator`。它有效 8 小时，只对 `/wb` 下的路径生效。
4. 带上这个 Cookie 请求 `GET /wb/alerts`，返回 `{"alerts": [...]}`。新装的环境里，没填 `backup_dir` 会有 `backup_unconfigured`，模型角色没起来会有 `model_client`。出现 `runtime`、键为 `write_host` 的告警，说明主机没有登记。没有配置任何通知渠道时，会有一条一直挂着的 `notify_unconfigured` 警告：告警会记录，但不会发出；见[通知、日报与备份](Notifications-Reports-and-Backup.md)。
5. 仅桥接模式的写入接口 `POST /control/{device}`、`POST /outlet` 和 `POST /pump` 现在返回 `403`，提示 `Device writes go through the workbench`。控制台上的控制按钮和 MCP 的写入工具调用的就是这几个接口，所以它们不再可用；读取不受影响。

## 8. 批准安全配置

保护规则要等操作员批准了安全配置才存在。在登录或重新认证后的 300 秒内发送：

```http
POST /wb/safety/approve

{"config": {"version": 1, "rules": [{"id": "overheat-light-off", "sensor": "temp", "unit": "C",
  "validity_seconds": 20, "trigger": {"op": ">", "value": 35}, "duration_seconds": 30,
  "action": {"channel": "light", "level": 0}}]}}
```

应该得到 `{"protection_right": <编号>}`。上面这条规则取自模拟器的测试数据（[`sim/fixtures.py`](../../../src/growbridge/sim/fixtures.py)），只用来说明格式，不是推荐的设定值。保护规则能做什么，见[控制与安全模型](Control-and-Safety-Model.md)。

## 某一步被拒绝时

| 现象 | 怎么办 |
| --- | --- |
| `400 Invalid host header` | 用的 `Host` 不在 `lan_hosts` 或 `overlay_hosts` 里。加进去，重启。 |
| 登录时 `403`，拒绝码 `entry` | 主机和监听对不上：局域网主机必须从 `lan_port` 进来，覆盖网络主机必须从 `port` 进来。`127.0.0.1` 不是入口。缺少 `Origin` 或 `x-growbridge-ui` 请求头时也是这个拒绝码。 |
| `401`，拒绝码 `session` | 名字或密钥不对，或者会话过期。重新登录。 |
| `429`，拒绝码 `locked` | 同一个名字从同一个地址在 15 分钟内失败了 5 次。等一会儿。 |
| `403`，拒绝码 `reauth_required` | 发送 `POST /wb/reauth`，请求体 `{"secret": "..."}`，然后重发原请求。 |
| `A daemon already owns this data directory` | 同一个 `data_dir` 上已经有一个 `serve` 在跑。 |

全部拒绝码见[拒绝码与事件类型](Denial-Codes-and-Events.md)。

## 再关掉

1. 先停掉所有还没结束的阶段：`POST /wb/stages/STAGE_ID/stop`。模式关掉之后，没有任何东西再按运行单执行，养护规则和保护规则也不再运行。
2. 停掉守护进程，把 `auto_research` 改成 `false`，再启动 `serve`。其他配置项可以留着，仅桥接模式不看它们。
3. 确认：第 7 步的 `curl` 命令现在打印 `404`；`controls_enabled` 为 `true` 时，仅桥接模式的写入接口重新可用。

数据库、操作员和写入主机登记都留在数据目录里。以后再打开这个模式，启动过程和普通重启一样处理：所有不是 `ended` 或 `stopped` 的阶段都进入 `recovery_check`。见[故障处理手册](Troubleshooting-Runbook.md)。

## 另见

- [运行一轮研究](Run-a-Research-Round.md)
- [配置参考](Configuration-Reference.md)
- [CLI 参考](CLI-Reference.md)
- [控制与安全模型](Control-and-Safety-Model.md)
- [状态与已知限制](Status-and-Known-Limitations.md)
