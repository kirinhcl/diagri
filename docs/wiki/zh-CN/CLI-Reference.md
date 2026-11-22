# CLI 参考

[English](../en/CLI-Reference.md)

这一页写给使用 `growbridge` 命令的人。它列出每个子命令和选项、各自做什么、打印什么，以及怎样退出。

解析器是 [`cli.py`](../../../src/growbridge/cli.py) 里的 `main()`。下面的表格已对照 `growbridge --help` 和每个子命令的 `--help` 核对过，版本 `0.2.0`。本页说的"仅桥接模式"指 `auto_research = false`。

## 用法

```text
growbridge [-h] [--version] [--config CONFIG]
           {init,scan,serve,mcp,status,dashboard,operator,host,recovery,export-dataset,simulate,trace} ...
```

## 全局选项

全局选项写在子命令前面，例如 `growbridge --config /absolute/path/to/config.toml status`。

| 选项 | 参数 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `-h`, `--help` | 无 | | 打印帮助并以 0 退出。每个子命令也接受它。 |
| `--version` | 无 | | 打印版本号并以 0 退出。 |
| `--config` | `CONFIG`，一个路径 | `~/.config/spiderfarmer-growbridge/config.toml` | 要读取的配置文件。对 `init` 来说是要创建的文件。 |

## 子命令

共 12 个子命令。`operator`、`host`、`recovery` 和 `trace` 各带一个必填的二级子命令。

| 命令 | 参数和选项 | 是否读取配置文件 | 是否需要守护进程在运行 | DiAGRI 模式 |
| --- | --- | --- | --- | --- |
| `init` | `--device DEVICE`（必填）、`--enable-controls` | 否，它负责创建 | 否 | 不需要 |
| `scan` | 无 | 否 | 否 | 不需要 |
| `serve` | 无 | 是 | 它就是守护进程 | 两种模式都能用 |
| `mcp` | 无 | 是 | 是，每个工具都要调用它 | 两种模式都能用，工具不同 |
| `status` | 无 | 是 | 是 | 两种模式都能用 |
| `dashboard` | `--no-open` | 是 | 是 | 两种模式都能用；DiAGRI 模式下控制台不能写入 |
| `operator add` | `name`（位置参数，必填）、`--admin`（设为管理员；多用户） | 是 | 否 | 为它准备；命令本身不检查 `auto_research` |
| `host register` | 无 | 是 | 否 | 为它准备；命令本身不检查 `auto_research` |
| `recovery bump` | `--reason REASON`（必填） | 是 | 否，而且必须先停掉 | 为它准备；命令本身不检查 `auto_research` |
| `export-dataset` | `--snapshot SNAPSHOT`、`--out OUT`、`--licence LICENCE`、`--creator CREATOR`（都必填）、`--url URL` | 是 | 否，守护进程运行时也能执行 | 读取 DiAGRI 已记录的数据；命令本身不检查 `auto_research` |
| `simulate` | 无 | 否 | 否 | 在临时目录里自建一个 DiAGRI 运行时 |
| `trace show` | `file`（位置参数，必填），`--full`（不截断长内容） | 否 | 否 | 读取模型轨迹文件；不需要 DiAGRI 模式 |
| `trace replay` | `file`（位置参数，必填），`--data-dir DIR`（在该数据目录的副本上重放），`--keep-going`（出现不一致后继续），`--keep-copy`（保留临时副本） | 是 | 否 | 需要配置文件；只写数据的临时副本 |

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
| `export-dataset` | 把一个冻结快照的训练数据集写进新建的目录 `OUT`：11 张 CSV 表和 `croissant.json`。只读取数据库和快照，除假名密钥外不向 `data_dir` 写任何东西。`--licence` 和 `--creator` 记进元数据（创作者记为组织）；`--url` 是数据集发布的地址（如果有）。`--licence`、`--creator` 和 `--url` 两端的空白会被去掉；只有空白的 `--url` 视为没有。见[训练数据集导出](Training-Dataset-Export.md)。 | 一个 JSON 对象，包含 `out`、`rows`（每个文件的数据行数）和 `counts`（元数据里的十项计数） |
| `simulate` | 在临时目录里，用模拟的 AC5 和模拟时钟跑一个很短的阶段：批准安全配置，创建项目、协议和轮次，提交并批准运行单，启动阶段，一直 tick 到阶段结束。不用无线电，也不联网。 | 一个 JSON 对象，包含 `stage`、`round`、`beats`、`samples` 和 `writes` |
| `trace show` | 逐步列出一个模型轨迹文件：先是运行头部，再是每一轮的思考、文字、工具调用和结果，最后是结束信息或 `Record incomplete: the run has no end line.` 这一行。超过 400 个字符的内容会被截断，除非加 `--full`；轨迹里的控制字符和转义序列会被去掉。 | 标准输出上的列表；文件读不了或被截断时退出码为 2，并在标准错误输出上给出原因（出错行之前的内容仍会列出） |
| `trace replay` | 用记录下来的模型回复，在数据的临时副本上（权限 0700，结束后删除，除非加 `--keep-copy`）把一个模型轨迹按当前代码重新运行一遍。数据来源依次为 `--data-dir` 选项、轨迹旁该次运行的运行前副本、`data_dir`；输出第一行写明来源，来源不是运行前副本时再加一行 `Replay from <kind>: results are for reference only (no pre-run copy).` 来源数据库的内容绝不会被修改，但 SQLite 读取一个正在使用的数据库时，可能在它旁边创建 `-wal`/`-shm` 辅助文件；运行前副本以只读且不可变方式打开，保持逐字节不变。重放不会启动设备链路，也没有通知渠道、心跳或计算服务。它为每次工具调用输出一行（`ok` 或 `DIFFERENT`），对第一个不一致处给出工具名、输入以及记录结果与重放结果的差异，最后给出两个结束代码。输出的值会去掉控制字符。 | 每一步和结束都一致时退出码为 0，有不一致时为 1，无法重放（文件读不了、被截断、没有结束行或配置文件无效）时为 2 |

### `trace show` 和 `trace replay`

模型轨迹在配置了 `model_trace`（见[配置参考](Configuration-Reference.md)），或开发工作台带 `--trace` 运行时（见[环境搭建、测试与 CI](Development-Setup-Testing-and-CI.md)）才会写。两条命令怎么用，见手册：[模型运行出了问题：看它的轨迹](Troubleshooting-Runbook.md#模型运行出了问题看它的轨迹)。

- `trace show` 还会把 Unicode 格式字符（零宽字符、方向标记）显示成 `<U+XXXX>`，它们就藏不进文字里。不需要配置文件。
- `trace replay` 把记录下来的模型回复原样交还，所以不调用模型，也不花钱。会访问本机以外的工具（`lookup_crop_conditions`、`search_and_verify_sources`、`submit_compute_job`、`get_compute_job`、`fetch_compute_artifacts`）直接返回当时记录的结果，它们的处理函数不会运行；但工具闸门（受限模式下看得到哪些工具、输入校验）仍然检查。其余工具在副本上真的运行，结果比较前会先屏蔽生成的 id、副本的路径和很小的时钟差。
- 恢复出来的备份不是受支持的来源：它没有 `archive/` 和 `agent_work/` 下的文件。请用运行前副本，或运行之前自己复制的数据目录。

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

### `export-dataset`

步骤在 [`dataset/command.py`](../../../src/growbridge/dataset/command.py) 的 `export_dataset` 里。命令遇到第一个问题就停下，此时除假名密钥外什么都没有写（密钥已经创建后才出现的拒绝，不会把它删掉）。拒绝时在标准错误打印 `export refused: <message>`，退出码 1。每条消息都说明发现了什么：

| 拒绝 | 什么时候 |
| --- | --- |
| `<OUT> already exists; name a directory that does not.` | `--out` 已经存在。 |
| `The parent of <OUT> does not exist.` | `--out` 的上级目录不存在。 |
| `<OUT> lies inside the data directory ...; write it elsewhere.` | `--out` 就是 `data_dir`，或在它里面。 |
| `<name>.sqlite3 is missing from <data_dir>; this is not a daemon data directory ...` | `archive`、`workflow` 或 `agents` 缺少数据库文件。导出不会替你建一个空的。 |
| `The schema of <name>.sqlite3 is older than this growbridge (...). Start the daemon once with this version, then export.` | 某个数据库还没有被已安装的版本升级；导出不会去升级它。 |
| `The data directory is busy (...); try again.` | 某个数据库被写入方锁住。 |
| `SQLite could not read the data directory: <error>.` | 读取数据库时出现其他 SQLite 错误，例如文件不是数据库、文件损坏，或这个 growbridge 读不了的数据库结构。`<error>` 是 SQLite 的报错。 |
| `Snapshot <ID> does not exist.` | 快照不存在。 |
| `Snapshot <ID> failed verification: ...` | 某个快照文件和记录的摘要不再一致。 |
| `Snapshot <ID> has no catalog.json; ...` | 快照冻结时还没有记录目录。 |
| `Snapshot file <name> cannot be read`、`... holds an invalid record` 或 `... is not an object` | 快照文件损坏。 |
| `Experiment <ID> must run under exactly one project`、`protocol version` 或 `round`; found ... | 实验的各阶段跑在两个协议版本下或两个轮次里，或者没有项目。导出会说出它发现了什么，不替你挑一个。 |
| `Protocol <ID> version <n> is not saved.` | 协议记录不存在。 |
| `Protocol <ID> version <n> cannot describe the dataset: ...` | `crop_taxon` 为空或不是 `NCBITaxon:<数字>`，或 `cultivar` 超过 200 个字符。 |
| `Name the licence ...` 或 `Name the creator ...` | `--licence` 或 `--creator` 为空。 |
| `Measurement <ID> records '<name>', which the variable catalog does not define ...` | 人工测量的名称不是目录里的变量。 |
| `Measurement <ID> is in '<unit>', but <variable> is measured in '<unit>'.` | 测量的单位和目录不一致。 |
| `Variable <ID> is in neither the snapshot's catalog nor the current one.` | 数据行用到的变量不在任何一个目录里。 |

成功时退出码 0，并打印 JSON 摘要。不属于上面这些拒绝的失败都以 Python 回溯结束（退出码 1），例如假名密钥不是 32 字节，或写文件时磁盘满了。配置缺失或无效、用法错误的表现和下表一致。

## 退出行为

| 情况 | 涉及的命令 | 提示信息 | 退出码 |
| --- | --- | --- | --- |
| 成功 | 全部 | 见上表 | 0 |
| 缺少子命令、未知选项、缺少必填参数 | 全部 | 用法说明和 `growbridge: error: ...` | 2 |
| 配置文件不存在，或没有通过 `load` 的检查 | 所有读取配置的命令 | Python 回溯（`FileNotFoundError`、`ValidationError`、`ValueError` 等） | 1 |
| 配置文件已经存在 | `init` | 以 `FileExistsError` 结尾的回溯 | 1 |
| 导出无法进行 | `export-dataset` | `export refused: <message>`，见 [`export-dataset`](#export-dataset) | 1 |
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

- [训练数据集导出](Training-Dataset-Export.md)
- [配置参考](Configuration-Reference.md)
- [HTTP、工作台与 MCP 接口](API-Reference.md)
- [安装与快速开始](Installation-and-Quick-Start.md)
- [启用 DiAGRI](Enable-DiAGRI.md)
- [故障处理手册](Troubleshooting-Runbook.md)
