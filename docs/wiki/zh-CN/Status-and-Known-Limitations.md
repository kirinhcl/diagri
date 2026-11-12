# 状态与已知限制

[English](../en/Status-and-Known-Limitations.md)

这一页写给需要判断这套系统可以信到什么程度的人：用户、操作员和贡献者。它列出哪些东西已经验证过、是怎么验证的，以及哪些没有验证或尚未实现。每一行都写明了去哪里核对。

本页最近一次对照工作区代码核对是在 2026-11-10。

## 三句话概括

- DiAGRI 模式至今只在模拟的 AC5 上运行过（见 [`sim/device.py`](../../../src/growbridge/sim/device.py)）。这个模式下从未向真实设备写入过。
- 单独运行的 GrowBridge（仅桥接模式）在一台 Mac 上读取并控制过一台真实的 AC5。这份记录早于 DiAGRI 其余部分的代码。
- 树莓派、真实的通知服务和 CSC 都没有验证过。

## 已验证

| 内容 | 怎么验证的 | 去哪里核对 |
| --- | --- | --- |
| 测试套件 | 在 macOS 上用 Python 3.14 运行，1452 个代码测试全部通过（最近一次运行是 2026-11-11）。Python 3.11 上最近一次运行时是 1292 个测试。这个数字不含 `tests/docs/`，那里检查的是本 Wiki 的链接，页面越多测试越多。 | [`tests/`](../../../tests/)，用 `.venv/bin/pytest -q` 运行 |
| 持续集成 | 在 `ubuntu-latest` 和 `macos-latest` 上用 Python 3.11 和 3.13 通过。CI 执行 `ruff check`、`ruff format --check`、`pytest -q`、`python -m build`，以及对控制台脚本的语法检查。macOS 上还会编译 Swift 辅助程序，但不运行它。 | [`ci.yml`](../../../.github/workflows/ci.yml) |
| 覆盖率 | 测量时是 95 %，当时有 1292 个测试。CI 不测覆盖率，之后也没有重新测过。 | 仓库里没有记录 |
| 完整的一轮研究 | 在模拟的 AC5 上，从创建项目一直到 `delivered`，中间有一次人工接管和交还。 | [`test_e2e_round.py`](../../../tests/e2e/test_e2e_round.py) |
| 模型角色的端到端流程 | 用脚本化的模型客户端驱动编排、计划和研究三个 Agent，不联网，不需要密钥，从派发任务一直到轮次交付。 | [`test_e2e_agents.py`](../../../tests/e2e/test_e2e_agents.py) |
| 经工作台路由走完一轮 | 在模拟的 AC5 上，从登录一直到 `delivered`。操作员的每一步都是发给 `/wb` 的 HTTP 请求，由进程内的客户端发给 `serve` 所构建的那个应用；模型角色用脚本化的客户端。另一个测试停止一个阶段、选择 `redo`、再中止轮次。没有 `serve` 进程参与，也没有真实模型参与。 | [`test_e2e_http_round.py`](../../../tests/e2e/test_e2e_http_round.py)、[`test_workbench_rounds.py`](../../../tests/workbench/test_workbench_rounds.py) |
| 没有模型时阶段照常执行 | 没有模型客户端时，已批准的阶段能跑到结束；每次模型调用都失败时也一样。`tick` 从不调用模型。 | [`test_e2e_runtime.py`](../../../tests/e2e/test_e2e_runtime.py)、[`test_e2e_agents.py`](../../../tests/e2e/test_e2e_agents.py) |
| 重启与恢复 | 重启后，进行中的阶段先进入 `recovery_check`，再到 `paused`，由操作员确认续跑。重启时还在等待审查的阶段会自己回到 `pending_review`。写入应答丢失会让阶段暂停。恢复编号加一后，审批和会话全部失效。 | [`test_e2e_runtime.py`](../../../tests/e2e/test_e2e_runtime.py)、[`test_e2e_reviewed.py`](../../../tests/e2e/test_e2e_reviewed.py) |
| 阶段为什么在等待 | 阶段被系统暂停或被送进恢复待核对时，产生告警 `stage_waiting`，写明事件和事件携带的内容；同样的内容也保存在阶段历史里。阶段离开这个状态时告警解除。墙上时钟跳变只让运行中的阶段暂停一次，操作员续跑后不再计较。 | [`test_e2e_stage_alerts.py`](../../../tests/e2e/test_e2e_stage_alerts.py)、[`test_executor_clock.py`](../../../tests/executor/test_executor_clock.py)、[`test_workflow_events.py`](../../../tests/workflow/test_workflow_events.py) |
| 没有通知渠道时的运行 | 不会有通知入队，`notify_unconfigured` 警告一直挂着，运行健康不受影响。配置了渠道之后，未解除的告警会发出。 | [`test_e2e_notifications.py`](../../../tests/e2e/test_e2e_notifications.py) |
| `growbridge simulate` | 一个已批准的阶段在模拟的 AC5 上跑到 `ended`，三次写入都得到回读确认。 | [教程](Tutorial-Simulated-Round.md)、[`test_e2e_cli.py`](../../../tests/e2e/test_e2e_cli.py) |
| GrowBridge 单独运行（仅桥接模式）连接真实 AC5 | 人工验证，在 macOS 上，对象是一台 AC5（广播名称 SF-GGS-PS5、固件 3.2、明文协议 v1）：扫描、连接、实时遥测、一次经回读确认的调光写入、MCP 客户端、控制台。记录日期是 2026-10-29，早于 DiAGRI 其余部分的加入。此后没有新的真机验证记录。 | [VALIDATION.md](../../../VALIDATION.md) |

## 未验证或未实现

「未验证」指代码已经有了，但从没有在真实条件下运行过。「部署事项」指设计上需要、代码也留了位置，但仓库里没有任何东西把它搭起来。「未实现」指代码还没有写。

| 方面 | 状态 | 说明 | 去哪里核对 |
| --- | --- | --- | --- |
| DiAGRI 模式连接实体 AC5 | 未验证 | 从未运行过。包括阶段执行中途蓝牙中断、主机或 AC5 断电，以及长时间无人值守运行。 | [VALIDATION.md](../../../VALIDATION.md) |
| 树莓派与 Linux 蓝牙 | 未验证 | `BleakTransport`（BlueZ 上的 Bleak）只在测试里对着假客户端跑过。没有在实体树莓派上运行的记录。 | [`transport.py`](../../../src/growbridge/transport.py)、[`tests/transport/`](../../../tests/transport/) |
| 事件通道关闭后 Swift 辅助程序退出 | 未验证 | 在 macOS 上，Python 一侧断开时，辅助程序应当丢弃排队中的写入并退出（`watchChannel`）。CI 只编译这个辅助程序。 | [`BLEHelper.swift`](../../../src/growbridge/native/BLEHelper.swift) |
| 其他控制器、其他固件、加密协议 v2 | 未验证 | 只用过一台明文协议 v1 的 AC5。控制要求协议版本为 1，否则拒绝。 | [`service.py`](../../../src/growbridge/service.py)、[VALIDATION.md](../../../VALIDATION.md) |
| `serve` 的后台任务 | 没有自动化测试 | 每秒一次的 tick 循环（`_tick_forever`）、每 30 秒一次的模型角色轮询（`_agents_forever`），以及为局域网入口开的第二个监听（`_serve_listeners`），都没有测试覆盖。测试是直接调用 `Runtime.tick()` 和 `Runtime.run_agents()` 的。 | [`cli.py`](../../../src/growbridge/cli.py) |
| Telegram 和邮件的真实投递 | 未验证 | `TelegramChannel` 和 `EmailChannel` 只用假的传输层测试过。 | [`observer/channels.py`](../../../src/growbridge/observer/channels.py)、[`test_observer_channels.py`](../../../tests/observer/test_observer_channels.py) |
| 外部心跳 | `serve` 里未实现 | `HeartbeatChannel` 和 `ExternalMonitor` 已经写好，也用假对象测试过，但 `serve` 构建运行时的时候没有传入心跳端点，所以不会发出任何心跳。传入端点后，运行时每 60 秒发一次信号，运行健康变化时立即再发一次。 | [`runtime.py`](../../../src/growbridge/runtime.py)（`build_runtime` 的 `heartbeats` 参数） |
| 主机时间同步 | 未实现 | 没有任何代码检查主机时钟是否已同步：`SystemClock.synced` 一直是 true。唯一的时钟检查是墙上时钟相对单调时钟跳变超过 5 秒，它会让运行中的阶段暂停，直到操作员续跑。主机休眠后被唤醒，看起来就是这样一次跳变。 | [`archive/clock.py`](../../../src/growbridge/archive/clock.py)、[`executor/outage.py`](../../../src/growbridge/executor/outage.py) |
| 模型角色的 `data` 和 `provider` | 未生效 | 这两个字段加载时会校验，但没有代码读取。`data` 不限制角色能读到什么；角色能接触到什么由它的工具决定。 | [`config.py`](../../../src/growbridge/config.py)、[`agents/tools.py`](../../../src/growbridge/agents/tools.py) |
| 模型单价 | 未验证 | 默认模型的内置单价（`DEFAULT_PRICE`）是代码里的常量，没有和提供方当前的价目表核对过。其他模型的单价都来自配置。 | [`agents/llm.py`](../../../src/growbridge/agents/llm.py)、[配置参考](Configuration-Reference.md) |
| 系统账户隔离 | 部署事项 | 代码是单进程的。它为每个服务各保留一个 SQLite 文件（`control`、`workflow`、`archive`、`observer`、`compute`、`agents`），将来分账户就建立在这个基础上。 | [`runtime.py`](../../../src/growbridge/runtime.py)（`DATABASES`） |
| 覆盖网络 | 部署事项 | 常驻服务监听 `127.0.0.1`，覆盖网络入口要靠架在它前面的代理。仓库里没有代理或网络的配置。 | [`workbench/auth.py`](../../../src/growbridge/workbench/auth.py)（`entry_for`） |
| 通行密钥（passkey） | 未实现 | 操作员用一个至少 12 个字符的密码登录，密码以加盐的 scrypt 哈希保存。 | [`workbench/auth.py`](../../../src/growbridge/workbench/auth.py) |
| 提交研究目标 | 未用真实模型验证 | 操作员通过 `/wb` 路由创建项目、研究协议和轮次，设置调用预算，提出目标。这些路由只在测试里跑过，用的是脚本化的模型和进程内的 HTTP 客户端。真实模型拿到目标后会做什么，从没有运行过。这些步骤没有 CLI 命令，也没有网页。 | [`workbench/rounds.py`](../../../src/growbridge/workbench/rounds.py)、[运行一轮研究](Run-a-Research-Round.md) |
| 还缺的工作台路由 | 未实现 | 没有路由能添加证据卡，列出项目或轮次，读取已保存的研究协议，读取或处理研究任务，读取阶段历史、数据快照或报告，撤销审批，或给执行中的阶段切换运行单。是哪个操作员创建了项目、协议或轮次，是谁设了预算，都没有记录。 | [`workbench/api.py`](../../../src/growbridge/workbench/api.py)、[`workbench/rounds.py`](../../../src/growbridge/workbench/rounds.py)、[`workflow/service.py`](../../../src/growbridge/workflow/service.py) |
| 工作台的网页 | 未实现 | 工作台目前是 `/wb` 下的一组 HTTP 路由。唯一的网页是仅桥接模式的控制台，它在 DiAGRI 模式下只读。 | [`workbench/api.py`](../../../src/growbridge/workbench/api.py)、[`web/`](../../../src/growbridge/web/) |
| 在 CSC 上跑作业 | 未实现 | `FirecrestBackend` 的每个远端操作都抛出 `NotImplementedError`。`serve` 不构建计算服务，所以计算相关的工具一律回答 `unavailable`。计算模板和成员名单都是空的。 | [`compute/firecrest.py`](../../../src/growbridge/compute/firecrest.py)、[`runtime.py`](../../../src/growbridge/runtime.py) |
| 文献检索 | 未实现 | 没有检索后端。计划 Agent 的 `lookup_crop_conditions` 和 `search_and_verify_sources` 两个工具回答 `unavailable`。 | [`agents/handlers_planner.py`](../../../src/growbridge/agents/handlers_planner.py)、[`runtime_agents.py`](../../../src/growbridge/runtime_agents.py) |
| 运行模型所写代码的沙箱 | 只支持 macOS | 沙箱依赖 `sandbox-exec`。在其他系统上，包括 Linux 和树莓派，它拒绝运行任何代码，拒绝码是 `sandbox_unavailable`。因此在这些系统上，本地分析和确认性分析都跑不了。 | [`research/sandbox.py`](../../../src/growbridge/research/sandbox.py) |
| 告警规则 | 默认为空 | `DEFAULT_ALERT_RULES` 是空的，配置里也没有设置告警规则的字段，所以观察与通知 Agent 不会发出任何阈值告警。 | [`runtime.py`](../../../src/growbridge/runtime.py) |
| 相机采集 | 未实现 | 没有任何相机相关的代码。长势观察靠录入人工测量。 | [`observer/report.py`](../../../src/growbridge/observer/report.py) |
| 备份 | 只备份 SQLite 数据库 | 一次备份复制的是 DiAGRI 的六个数据库，不包括仅桥接模式的历史文件 `growbridge.sqlite3`，也不包括数据目录下 `archive/` 里的文件（例如数据快照）。目前还没有图像采集，所以也没有图像可备份。没有设置 `backup_dir` 时什么都不备份，并且会有一条常驻的警告。 | [`runtime_backup.py`](../../../src/growbridge/runtime_backup.py)、[`archive/backup.py`](../../../src/growbridge/archive/backup.py) |
| 被跳过的测试 | 是「跳过」，不是「通过」 | 需要 `sandbox-exec` 的测试在没有它的系统上会被跳过，Linux 上的 CI 就是这种情况。需要构建 Anthropic 客户端的测试在没装 `anthropic` 包时会被跳过；CI 只安装 `dev` 这一组可选依赖，所以这些测试在两个 CI 系统上都被跳过。 | [`test_research_sandbox.py`](../../../tests/research/test_research_sandbox.py)、[`test_e2e_assembly.py`](../../../tests/e2e/test_e2e_assembly.py)、[`test_agents_llm.py`](../../../tests/agents/test_agents_llm.py) |

## 怎样重新核对

```sh
.venv/bin/python -m pip install -c constraints-tested.txt -e '.[dev]'
.venv/bin/pytest -q
.venv/bin/growbridge simulate
```

第一条命令安装测试工具。第二条在模拟的 AC5 上运行整个测试套件；加上 `-rs` 可以列出被跳过的测试和各自的原因。第三条运行一个模拟阶段，详见[教程](Tutorial-Simulated-Round.md)。

真机上的验证结果记在 [VALIDATION.md](../../../VALIDATION.md) 里。某一行的验证在那里有了记录，才移到第一张表。

## 另见

- [项目概览](Overview.md)
- [开发环境、测试与 CI](Development-Setup-Testing-and-CI.md)
- [故障处理手册](Troubleshooting-Runbook.md)
- [常见问题](FAQ.md)
