# 通知、日报与备份

[English](../en/Notifications-Reports-and-Backup.md)

这一页写给负责配置“守护进程往外发什么、往下存什么”的操作员：日报时间，通知渠道和它们的凭据，发给外部监控的心跳，以及数据库备份和恢复。

> **未验证。** 经 Telegram 和邮件投递，以及发给外部服务的心跳，都只用假的传输层测试过，没有任何消息真正发到过外部服务。见[状态与已知限制](Status-and-Known-Limitations.md)。

## 现在有什么

| 功能 | 用什么配置 | 状态 |
| --- | --- | --- |
| 日报 | 配置文件里的 `report_time`、`report_timezone` | 有阶段管着设备时，由 `serve` 生成。 |
| Telegram 渠道 | 环境变量 | 设了对应变量，`serve` 就会建立。 |
| 邮件渠道 | 环境变量 | 设了对应变量，`serve` 就会建立。 |
| 发给外部监控的心跳 | 环境变量 | 两个 URL 都设了时由 `serve` 构建；只设一个则拒绝启动。 |
| 数据库备份 | `backup_dir`、`backup_interval_seconds` | 配了 `backup_dir`，`serve` 就会执行。 |

这一页的所有改动都在 `serve` 启动时生效。配置项的说明见[配置参考](Configuration-Reference.md)。

## 设置日报时间

1. 停掉守护进程。
2. 在配置文件里填这两项：

   ```toml
   report_time = "08:00"
   report_timezone = "Europe/Helsinki"
   ```

   `report_time` 是 24 小时制的 `HH:MM`。`report_timezone` 是 IANA 时区名。默认值是 `08:00` 和 `UTC`。
3. 启动 `serve`。

之后的行为（[`runtime.py`](../../../src/growbridge/runtime.py) 的 `_daily_report` 和 [`observer/report.py`](../../../src/growbridge/observer/report.py)）：

- 本地时间过了 `report_time`，就生成昨天（按本地日期）的日报。只有在有阶段管着设备时才生成：从一轮里第一个阶段启动开始，到这一轮交付或中止为止。
- 停机之后会补报漏掉的每一天，从最早的开始，最多补最近七天。
- 日报包含各项读数的时间加权均值、数据覆盖率和缺口、当天的保护动作和人工干预，还有一节“Frozen readings”（读数冻结），列出当天传感器一直报同一个值的各个时段（例如 `temp stuck at 24 from 08:00 to 10:05`，还没结束的会标 `(still frozen)`），方便看出哪些数据段不可信。时间按日报时区显示；不在当天的时间会连日期一起显示。任何部分都不是模型写的。运行时没有传入范围、作物观察和待办，所以这几部分是空的。
- 每个项目每个日期只保存一份，存在 `observer.sqlite3` 的 `observer_reports` 表里，并排进每个通知渠道的队列。

时区名写错，加载配置时不会报错。之后它会表现为一条类型为 `tick_step`、键为 `report` 的告警。

读取已保存的日报**无路由**。只能通过通知渠道看到它。

## 配置通知渠道

渠道的实现在 [`observer/channels.py`](../../../src/growbridge/observer/channels.py)。它们的设置只来自 `serve` 的进程环境，不来自配置文件。[`runtime.py`](../../../src/growbridge/runtime.py) 的 `default_channels` 只有在启动时某个渠道的两个必需变量都已设置，才会建立这个渠道。

| 渠道 | 必需 | 可选 |
| --- | --- | --- |
| Telegram | `GROWBRIDGE_TELEGRAM_TOKEN`（机器人令牌）、`GROWBRIDGE_TELEGRAM_CHAT_IDS`（会话 ID，逗号分隔） | 无 |
| 邮件 | `GROWBRIDGE_SMTP_HOST`、`GROWBRIDGE_EMAIL_TO`（收件地址，逗号分隔） | `GROWBRIDGE_SMTP_PORT`（默认 587）、`GROWBRIDGE_SMTP_USER`、`GROWBRIDGE_SMTP_PASSWORD`、`GROWBRIDGE_SMTP_FROM` |

1. 停掉守护进程。
2. 在启动 `serve` 的环境里设置变量：

   ```sh
   export GROWBRIDGE_TELEGRAM_TOKEN='YOUR_BOT_TOKEN'
   export GROWBRIDGE_TELEGRAM_CHAT_IDS='YOUR_CHAT_ID'
   ```

   `scripts/` 里的安装脚本不会往后台服务里写环境变量，所以装成服务时，要自己把变量加进服务定义。未验证。
3. 启动 `serve`。

渠道的行为：

- Telegram 只向登记的会话 ID 发消息，没有任何读取来信的代码。邮件使用 STARTTLS，只有设了 `GROWBRIDGE_SMTP_USER` 才登录。发件地址依次取 `GROWBRIDGE_SMTP_FROM`、用户名、`growbridge@localhost`。
- 发出的消息有两类：每条告警发一次，格式是 `[severity] message`；每份日报发全文。告警解除时不发消息。
- 渠道返回 `accepted`、`unknown` 或 `failed`。没有被接收的消息 30 秒后重试，之后间隔逐次加倍，最长 30 分钟，总共最多尝试 20 次（[`observer/outbox.py`](../../../src/growbridge/observer/outbox.py)）。这些数字是代码里的常量，不是配置项。所以结果为 `unknown` 时，同一条消息可能收到两次。

目前没有发送测试消息的命令。要确认投递是否正常，看 `GET /wb/alerts`：已配置渠道上的某条通知 900 秒还没投递出去时，`run_health` 告警里会点名 `oldest_undelivered_alert`。告警本身随时可以在这个路由读到，和有没有渠道无关。

### 一个渠道都没配时

两个渠道都没配置时，`serve` 的行为如下，已在模拟设备上核对过：

1. 告警和日报都不会入队等待发送。告警照常记录，日报照常保存。
2. 启动时产生警告级告警 `notify_unconfigured`。下次 `serve` 带着渠道启动时，它会被解除。
3. 运行健康不受影响：`oldest_undelivered_alert` 只统计记在有发送器的渠道名下的通知。
4. 以后配置了渠道并重启，所有仍未解除的告警会入队并从这个渠道发出。这期间已经解除的告警和已经生成的日报不会补发。

去掉一个渠道时也一样：已经记在它名下的通知保持 `pending`，不再计入运行健康；仍未解除的告警会在剩下的渠道上入队。

目前没有清空队列的命令。在已配置的渠道上用完 20 次尝试仍未被接收的通知，会让 `oldest_undelivered_alert` 一直不通过。

## 发给外部监控的心跳

已经实现的部分，在 [`observer/health.py`](../../../src/growbridge/observer/health.py) 和 [`observer/channels.py`](../../../src/growbridge/observer/channels.py) 里：

- 两个信号：主机心跳每次发信号时都发；运行心跳只在运行健康正常时发。运行健康不正常时，改发失败信号，并停发运行心跳。
- 运行时每 60 秒发一次信号（[`runtime.py`](../../../src/growbridge/runtime.py) 的 `HEARTBEAT_SECONDS`），运行健康由好变坏或由坏变好时立即再发一次。外部监控的宽限期要设得比 60 秒长。
- `HeartbeatChannel` 从某个环境变量里读 URL：发心跳时请求这个 URL，报失败时请求这个 URL 加上 `/fail`。
- 信号发不出去时，产生告警 `external_monitor`，键是 `host` 或 `run`。

### 怎样配置

`serve` 读取两个环境变量（[`runtime_heartbeat.py`](../../../src/growbridge/runtime_heartbeat.py)，由 [`cli.py`](../../../src/growbridge/cli.py) 的 `_serve_auto_research` 调用）。两个都填监控服务给你的 URL，例如 Healthchecks.io 的 ping 地址：

| 变量 | 信号 |
| --- | --- |
| `GROWBRIDGE_HEARTBEAT_HOST_URL` | 主机心跳。 |
| `GROWBRIDGE_HEARTBEAT_RUN_URL` | 运行心跳。失败信号发到同一个 URL 加上 `/fail`。 |

- **两个都设或者都不设。** 两个都设时，`serve` 发送心跳。只设一个时，`serve` 拒绝启动，并说明缺哪个变量：只监控一半的故障，看起来像有监控，其实没有。空白值按未设置处理。
- **都不设。** 不发任何请求。运行时发出常驻警告告警 `monitor_unconfigured`（键 `heartbeats`），下次 `serve` 带着两个变量启动时自动解除。
- **URL 是机密。** 只从环境变量读取，在发送信号时才读。它不会出现在任何日志行、告警文本、错误信息或 `repr` 里。请求 URL 从不写进日志：`serve` 以 INFO 级别运行，HTTP 库在这个级别会记录每个请求的 URL，所以 [`logging_setup.py`](../../../src/growbridge/logging_setup.py) 把 `httpx` 和 `httpcore` 的日志级别固定在 WARNING。这同时保护了 Telegram 机器人令牌，它是 Bot API 请求路径的一部分。
- 监控服务的宽限期要设得比 60 秒长；心跳停了，由监控服务自己向手机发告警。

未验证：心跳只用假的 HTTP 客户端测试过，没有任何信号发到过真实的监控服务。

运行健康本身每次评估都会计算，结果体现为 `run_health` 告警。探测项和阈值如下：

| 探测项 | 什么情况下不通过 |
| --- | --- |
| `growbridge_response` | 60 秒没有收到设备的数据包。 |
| `executor_evaluation` | 30 秒没有执行 Agent 的评估。 |
| `capture` | `stale_seconds` 秒内没有样本；有阶段管着设备时，改用运行单的 `sampling.max_gap_seconds`。 |
| `archive_write` | 600 秒没有写入项目档案。 |
| `oldest_undelivered_alert` | 已配置渠道上有通知 900 秒还没投递出去。 |
| `offsite_backup` | 最近一次备份早于两个备份间隔。只有配了 `backup_dir` 才检查。 |

## 配置备份

1. 停掉守护进程。
2. 填写配置项：

   ```toml
   backup_dir = "/absolute/path/to/backup"
   backup_interval_seconds = 21600
   ```

   目录要放在和数据目录不同的介质上。代码不检查这一点。间隔最小 60 秒，默认 21600（6 小时）。
3. 启动 `serve`。第一次备份在第一次评估时开始。完成后目录里有十二个文件：`control`、`workflow`、`archive`、`observer`、`compute` 和 `agents`，各有一个 `<name>.sqlite3` 和一个 `<name>.sqlite3.manifest.json`。

工作方式（[`runtime_backup.py`](../../../src/growbridge/runtime_backup.py)、[`archive/backup.py`](../../../src/growbridge/archive/backup.py)）：

- **多久一次。** 六个数据库各自记着上次成功备份的时间，其中最早的那个超过间隔，就开始一次备份。备份在后台进行，不会拖住执行 Agent。
- **一致性。** 每个数据库通过一个单独的只读连接、在同一个读事务里复制，所以副本是一个一致的状态，写入方也不会被阻塞。
- **完整性。** 副本先用 `PRAGMA integrity_check` 检查，通过后才替换上一份备份。复制或检查失败时，上一份备份原样保留。清单文件记录该文件的 `sha256`、`size` 和 `created_at`（UTC 秒）。
- **只留一代。** 每次备份都会覆盖上一份。要保留更早的副本，需要自己安排。
- **失败时。** 产生带有错误信息的 `backup` 告警，300 秒后才会再试。没配 `backup_dir` 时，`backup_unconfigured` 警告一直挂着。

**不在备份里的东西：** 仅桥接模式的样本历史 `growbridge.sqlite3`，数据目录下 `archive/` 里的文件（数据快照文件），`agent_work/` 里的文件（研究报告文件），`host_id` 文件，以及配置文件。数据库里保存的是这些文件的记录和摘要，不是文件本身。

想手动检查一份备份，把文件和清单对一下即可，例如 `shasum -a 256 /absolute/path/to/backup/control.sqlite3`。这用的是产品之外的工具。

## 恢复备份

目前没有恢复命令。下面的步骤没有测试覆盖；只有一个测试打开备份文件，确认里面的记录和原库相同（[`tests/archive/test_archive_storage_backup.py`](../../../tests/archive/test_archive_storage_backup.py)）。

1. 停掉守护进程。
2. 逐个把备份文件和清单核对一遍。
3. 把数据目录里这六个数据库原有的 `*.sqlite3` 文件，以及旁边的 `-wal` 和 `-shm` 文件移走，再把六个备份文件复制进来。
4. 提高恢复编号：

   ```sh
   .venv/bin/growbridge recovery bump --reason "restored from backup"
   ```

5. 启动 `serve`，接着按[故障处理手册](Troubleshooting-Runbook.md)里的“从备份恢复或更换写入主机”做。

**恢复对恢复编号有什么影响。** 把文件复制回去本身什么都不改变：恢复回来的控制数据库带着做备份那一刻的恢复编号，也没有任何机制能发现“发生过一次恢复”。让恢复变得安全的是第 4 步。它把编号加一，撤销所有写入权，作废排队的写入和所有审批，把没结束的阶段都移到 `recovery_check`，并让此前的会话和安全配置审批全部失效。为什么必须这样做，见[控制与安全模型](Control-and-Safety-Model.md)。

## 另见

- [启用 DiAGRI](Enable-DiAGRI.md)
- [故障处理手册](Troubleshooting-Runbook.md)
- [配置参考](Configuration-Reference.md)
- [数据、档案与可追溯性](Data-Archive-and-Traceability.md)
- [状态与已知限制](Status-and-Known-Limitations.md)
