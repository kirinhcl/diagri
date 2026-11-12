# CLI 参考

[English](../en/CLI-Reference.md)

这一页写给使用 `growbridge` 命令的人。它列出每个子命令和选项、各自做什么、打印什么，以及怎样退出。

解析器是 [`cli.py`](../../../src/growbridge/cli.py) 里的 `main()`。下面的表格已对照 `growbridge --help` 和每个子命令的 `--help` 核对过，版本 `0.2.0`。本页说的"仅桥接模式"指 `auto_research = false`。

## 用法

```text
growbridge [-h] [--version] [--config CONFIG]
           {init,scan,serve,mcp,status,dashboard,operator,host,recovery,simulate} ...
```

## 全局选项

全局选项写在子命令前面，例如 `growbridge --config /absolute/path/to/config.toml status`。

| 选项 | 参数 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `-h`, `--help` | 无 | | 打印帮助并以 0 退出。每个子命令也接受它。 |
| `--version` | 无 | | 打印版本号并以 0 退出。 |
| `--config` | `CONFIG`，一个路径 | `~/.config/spiderfarmer-growbridge/config.toml` | 要读取的配置文件。对 `init` 来说是要创建的文件。 |

## 子命令

共 10 个子命令。`operator`、`host` 和 `recovery` 各带一个必填的二级子命令。

| 命令 | 参数和选项 | 是否读取配置文件 | 是否需要守护进程在运行 | DiAGRI 模式 |
| --- | --- | --- | --- | --- |
| `init` | `--device DEVICE`（必填）、`--enable-controls` | 否，它负责创建 | 否 | 不需要 |
| `scan` | 无 | 否 | 否 | 不需要 |
| `serve` | 无 | 是 | 它就是守护进程 | 两种模式都能用 |
| `mcp` | 无 | 是 | 是，每个工具都要调用它 | 两种模式都能用，工具不同 |
| `status` | 无 | 是 | 是 | 两种模式都能用 |
| `dashboard` | `--no-open` | 是 | 是 | 两种模式都能用；DiAGRI 模式下控制台不能写入 |
| `operator add` | `name`（位置参数，必填） | 是 | 否 | 为它准备；命令本身不检查 `auto_research` |
| `host register` | 无 | 是 | 否 | 为它准备；命令本身不检查 `auto_research` |
| `recovery bump` | `--reason REASON`（必填） | 是 | 否，而且必须先停掉 | 为它准备；命令本身不检查 `auto_research` |
| `simulate` | 无 | 否 | 否 | 在临时目录里自建一个 DiAGRI 运行时 |

没有任何命令可以创建项目、研究协议或研究轮次，也没有命令可以设置项目的调用预算或创建编排 Agent 的第一个任务。这些事由操作员通过工作台路由来做，见[运行一轮研究](Run-a-Research-Round.md)。命令里只有 `simulate` 会做这些调用，位置在 [`runtime.py`](../../../src/growbridge/runtime.py) 的 `_design_and_start`。

## 每个命令做什么

| 命令 | 做什么 | 打印什么 |
| --- | --- | --- |
| `init` | 通过 `initialize` 创建配置文件：上级目录权限 `0700`，文件权限 `0600`，共 11 个键。见[配置参考](Configuration-Reference.md#initialize-写入什么)。 | `Configuration created: <path>` |
| `scan` | 扫描 8 秒，找出名字以 `SF-` 开头的蓝牙设备。它会先以 `0700` 权限创建 `~/.local/share/spiderfarmer-growbridge`。在 macOS 上会编译并运行一个原生辅助程序，其他系统使用 `BleakScanner`。 | 一个 JSON 列表，每项包含 `name`、`address` 和 `rssi` |
| `serve` | 以 `0700` 权限创建 `data_dir`，对其中的 `daemon.lock` 加独占锁，把日志级别设为 `INFO`，然后一直提供服务直到被停止。仅桥接模式：在 `127.0.0.1:<port>` 上提供桥接 HTTP API。DiAGRI 模式：见下一张表。 | 日志 |
| `mcp` | 通过标准输入输出运行 MCP 服务，直到客户端关闭。每个工具都用配置文件里的令牌调用 `127.0.0.1:<port>` 上的守护进程。仅桥接模式有 8 个工具，DiAGRI 模式有 3 个。见[接口参考](API-Reference.md#mcp-工具)。 | 标准输出上的 MCP 协议消息 |
| `status` | 向守护进程发送 `GET /status`。 | 返回的 JSON，包含 `health`、`data` 和 `system` 三个键 |
| `dashboard` | 向守护进程发送 `POST /ui/session`，拼出链接 `http://127.0.0.1:<port>/#session=<code>`。这个 code 只能用一次，60 秒后过期。不带 `--no-open` 时会用浏览器打开链接。 | 不带 `--no-open`：`Dashboard opened. Connection link expires in 60 seconds.` 带 `--no-open`：链接本身 |
| `operator add` | 两次提示输入密码且不回显（`Operator secret: `、`Repeat secret: `），然后把操作员存进 `data_dir` 下的 `workflow.sqlite3`。密码以加盐的 scrypt 哈希保存。名字长度 1 到 64 个字符，密码 12 到 256 个字符。 | `Operator added: <name>` |
| `host register` | 读取或创建 `data_dir` 下的 `host_id`（权限 `0600`），并在 `control.sqlite3` 里把本机登记为 `device` 的写入主机。它不打开蓝牙连接。在已登记的主机上再次运行也会成功。 | `Write host registered: <host id>` |
| `recovery bump` | 拿到守护进程锁，构建运行时但不启动，把恢复编号加一，撤销所有写入权，作废排队中的动作，把每个未结束的阶段转入 `recovery_check` 并作废它的审批。`REASON` 会随事件一起记录。 | `Recovery number is now <n>; confirm the safety config and review live stages` |
| `simulate` | 在临时目录里，用模拟的 AC5 和模拟时钟跑一个很短的阶段：批准安全配置，创建项目、协议和轮次，提交并批准运行单，启动阶段，一直 tick 到阶段结束。不用无线电，也不联网。 | 一个 JSON 对象，包含 `stage`、`round`、`beats`、`samples` 和 `writes` |

### DiAGRI 模式下的 `serve`

步骤见 `_serve_auto_research` 和 `_serve_listeners`。

| 顺序 | 步骤 |
| --- | --- |
| 1 | 读取 `GROWBRIDGE_HEARTBEAT_HOST_URL` 和 `GROWBRIDGE_HEARTBEAT_RUN_URL`：只设一个，命令在这里停下；都不设，就不发心跳并留下常驻警告。然后用 `build_runtime(settings, heartbeats=...)` 构建运行时。同时读取计算服务的设置（`compute_templates_dir`、`compute_member` 和七个 `FIRECREST_*` 变量），全部齐了才传入计算服务；只配了一部分时，日志里写出缺了哪些，模板有错则命令在这里停下。 |
| 2 | 从 `GROWBRIDGE_ROLE_TOKEN_<ROLE>` 读取模型角色令牌，并构建工作台路由。有令牌短于 32 个字符时，命令在这一步退出。 |
| 3 | 启动运行时。如果本机不是已登记的写入主机，蓝牙连接保持关闭，并发出一条告警。 |
| 4 | 启动 tick 循环：每秒调用一次 `Runtime.tick()`（`TICK_SECONDS`）。 |
| 5 | 如果 `roles` 不为空并且模型客户端能创建，就启动模型角色：每 30 秒调用一次 `Runtime.run_agents()`（`AGENT_SECONDS`）。否则模型角色都不运行。 |
| 6 | 在 `127.0.0.1:<port>` 上提供桥接路由和工作台路由；`lan_bind` 和 `lan_port` 都设置时，同时在 `<lan_bind>:<lan_port>` 上提供。 |

## 退出行为

| 情况 | 涉及的命令 | 提示信息 | 退出码 |
| --- | --- | --- | --- |
| 成功 | 全部 | 见上表 | 0 |
| 缺少子命令、未知选项、缺少必填参数 | 全部 | 用法说明和 `growbridge: error: ...` | 2 |
| 配置文件不存在，或没有通过 `load` 的检查 | 所有读取配置的命令 | Python 回溯（`FileNotFoundError`、`ValidationError`、`ValueError` 等） | 1 |
| 配置文件已经存在 | `init` | 以 `FileExistsError` 结尾的回溯 | 1 |
| 另一个守护进程持有 `data_dir` 上的锁 | `serve` | `A daemon already owns this data directory` | 2 |
| 有模型角色令牌短于 32 个字符 | DiAGRI 模式下的 `serve` | `growbridge: the token of role '<role>' is shorter than 32 characters` | 1 |
| 守护进程没有应答，或返回了错误 | `status`、`dashboard` | 回溯；返回错误时是带有守护进程 `detail` 的 `RuntimeError` | 1 |
| 密码短于 12 个字符 | `operator add` | `the secret needs at least 12 characters` | 2 |
| 两次输入的密码不一致 | `operator add` | `the two entries differ` | 2 |
| 名字为空或过长、密码过长，或操作员已存在 | `operator add` | `Operators.add` 抛出的 `ValueError` 文本 | 2 |
| 设备已经登记了另一台主机 | `host register` | `another host is registered for this device` | 2 |
| `data_dir` 上有守护进程在运行 | `recovery bump` | `a daemon is running on this data directory; stop it first` | 2 |

每个命令在解析完参数后都把进程的 umask 设为 `0o077`，所以它创建的文件只有当前用户能访问。

编写本页时没有运行 `scan`，也没有对真实的 AC5 运行 `serve`。真机上的行为尚未验证，见[状态与已知限制](Status-and-Known-Limitations.md)。

## 另见

- [配置参考](Configuration-Reference.md)
- [HTTP、工作台与 MCP 接口](API-Reference.md)
- [安装与快速开始](Installation-and-Quick-Start.md)
- [启用 DiAGRI](Enable-DiAGRI.md)
- [故障处理手册](Troubleshooting-Runbook.md)
