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
| 测试套件 | 在 macOS 上用 Python 3.14 运行，2274 个代码测试全部通过（最近一次运行是 2026-11-14）。CI 用 Python 3.11 和 3.13 运行同一套测试。这个数字不含 `tests/docs/`，那里检查的是本 Wiki 的链接，页面越多测试越多。 | [`tests/`](../../../tests/)，用 `.venv/bin/pytest -q` 运行 |
| 持续集成 | 在 `ubuntu-latest` 和 `macos-latest` 上用 Python 3.11 和 3.13 通过。CI 执行 `ruff check`、`ruff format --check`、`pytest -q`、`python -m build`，以及对桥接控制台和操作员控制台脚本的语法检查，外加操作员控制台的 142 个 Node 单元测试。macOS 上还会编译 Swift 辅助程序，但不运行它。 | [`ci.yml`](../../../.github/workflows/ci.yml) |
| 覆盖率 | `growbridge` 的语句覆盖率为 96 %（9192 条中有 396 条没有执行），2026-11-13 在 macOS 上用 Python 3.14 跑整套测试测得。CI 不测覆盖率。 | `.venv/bin/pytest -q --cov=growbridge`；仓库里没有记录 |
| 完整的一轮研究 | 在模拟的 AC5 上，从创建项目一直到 `delivered`，中间有一次人工接管和交还。 | [`test_e2e_round.py`](../../../tests/e2e/test_e2e_round.py) |
| 模型角色的端到端流程 | 用脚本化的模型客户端驱动编排、计划和研究三个 Agent，不联网，不需要密钥，从派发任务一直到轮次交付。 | [`test_e2e_agents.py`](../../../tests/e2e/test_e2e_agents.py) |
| 经工作台得出确认性结论 | 在模拟的 AC5 上走四轮，操作员的每一步都是发给 `/wb` 的 HTTP 请求。分析脚本在第一个阶段之前冻结；阶段一旦启动，冻结就被拒绝；冻结的分析没有在每份快照上运行之前，报告被拒绝；之后报告是确认性的，轮次交付。这个测试里的代码沙箱是假的。 | [`test_e2e_confirmatory.py`](../../../tests/e2e/test_e2e_confirmatory.py)、[`test_workbench_analysis.py`](../../../tests/workbench/test_workbench_analysis.py) |
| 操作员控制台 | 2026-11-13 在模拟的 AC5 上（`scripts/dev_workbench.py`）用浏览器手工检查，宽度 1440、1024、768 像素，中英文各走一遍，两个入口都试过：登录、待我处理、项目、新建项目、保存协议、设置调用预算、发起轮次、提交目标、一个阶段从审批到启动、曲线里出现读数、接管、手动写灯光并看到回执、局域网入口上的灌溉（覆盖网络入口上不可用）、交还和停止、轮次选择、告警、录入证据卡、没有计算服务时的计算页，以及修改安全限值并通过重新认证对话框。没有页面出现横向滚动，焦点环和文字对比度都查过。没有试过：登记留出批次、核实模型提出的证据卡、配置了计算服务时的计算页，以及手机大小的屏幕。 | [`web/workbench/`](../../../src/growbridge/web/workbench)、[`tests/web/`](../../../tests/web)、[开发环境、测试与 CI](Development-Setup-Testing-and-CI.md) |
| 经工作台路由走完一轮 | 在模拟的 AC5 上，从登录一直到 `delivered`。操作员的每一步都是发给 `/wb` 的 HTTP 请求，由进程内的客户端发给 `serve` 所构建的那个应用；模型角色用脚本化的客户端。另一个测试停止一个阶段、选择 `redo`、再中止轮次。没有 `serve` 进程参与，也没有真实模型参与。 | [`test_e2e_http_round.py`](../../../tests/e2e/test_e2e_http_round.py)、[`test_workbench_rounds.py`](../../../tests/workbench/test_workbench_rounds.py) |
| 没有模型时阶段照常执行 | 没有模型客户端时，已批准的阶段能跑到结束；每次模型调用都失败时也一样。`tick` 从不调用模型。 | [`test_e2e_runtime.py`](../../../tests/e2e/test_e2e_runtime.py)、[`test_e2e_agents.py`](../../../tests/e2e/test_e2e_agents.py) |
| 重启与恢复 | 重启后，进行中的阶段先进入 `recovery_check`，再到 `paused`，由操作员确认续跑。重启时还在等待审查的阶段会自己回到 `pending_review`。写入应答丢失会让阶段暂停。恢复编号加一后，审批和会话全部失效。 | [`test_e2e_runtime.py`](../../../tests/e2e/test_e2e_runtime.py)、[`test_e2e_reviewed.py`](../../../tests/e2e/test_e2e_reviewed.py) |
| 阶段为什么在等待 | 阶段被系统暂停或被送进恢复待核对时，产生告警 `stage_waiting`，写明事件和事件携带的内容；同样的内容也保存在阶段历史里。阶段离开这个状态时告警解除。墙上时钟跳变只让运行中的阶段暂停一次，操作员续跑被它暂停的阶段后不再计较；启动另一个阶段不会解除。 | [`test_e2e_stage_alerts.py`](../../../tests/e2e/test_e2e_stage_alerts.py)、[`test_executor_clock.py`](../../../tests/executor/test_executor_clock.py)、[`test_workflow_events.py`](../../../tests/workflow/test_workflow_events.py) |
| 没有通知渠道时的运行 | 不会有通知入队，`notify_unconfigured` 警告一直挂着，运行健康不受影响。配置了渠道之后，未解除的告警会发出。 | [`test_e2e_notifications.py`](../../../tests/e2e/test_e2e_notifications.py) |
| `growbridge simulate` | 一个已批准的阶段在模拟的 AC5 上跑到 `ended`，三次写入都得到回读确认。 | [教程](Tutorial-Simulated-Round.md)、[`test_e2e_cli.py`](../../../tests/e2e/test_e2e_cli.py) |
| GrowBridge 单独运行（仅桥接模式）连接真实 AC5 | 人工验证，在 macOS 上，对象是一台 AC5（广播名称 SF-GGS-PS5、固件 3.2、明文协议 v1）：扫描、连接、实时遥测、一次经回读确认的调光写入、MCP 客户端、控制台。记录日期是 2026-10-29，早于 DiAGRI 其余部分的加入。此后没有新的真机验证记录。 | [VALIDATION.md](../../../VALIDATION.md) |

## 未验证或未实现

「未验证」指代码已经有了，但从没有在真实条件下运行过。「部署事项」指设计上需要、代码也留了位置，但仓库里没有任何东西把它搭起来。「未实现」指代码还没有写。

| 方面 | 状态 | 说明 | 去哪里核对 |
| --- | --- | --- | --- |
| 多用户（`multi_user`） | 只在测试中验证 | 账号、温室锁定、项目所有者和按人可见，在模拟的 AC5 上和工作台路由上测过，没有真实用户或设备验证。一个进程仍只驱动一台 AC5：其余登记的温室可以锁定，但在多设备接入完成前不能运行阶段。释放温室时设备保持当前设置。共享令牌的桥接路由（`/status`、`/history*`、`/activity`）、命令行 `status`/`dashboard` 和 MCP 读取工具，仍向持有令牌的人显示全部设备数据。协议、运行单、阶段、实验和测量的编号是全局的：猜中别人的编号能知道它存在（仅此而已）。下一个阶段启动前，新样本仍记在已释放阶段的实验名下。通知发给配置的接收方，不按人区分。 | [`workflow/access.py`](../../../src/growbridge/workflow/access.py)、[适配说明](../../multi-user-adaptation.md) |
| DiAGRI 模式连接实体 AC5 | 未验证 | 从未运行过。包括阶段执行中途蓝牙中断、主机或 AC5 断电，以及长时间无人值守运行。 | [VALIDATION.md](../../../VALIDATION.md) |
| 水泵插座读回 | 未验证 | 看门狗依赖设备状态里水泵插座的 `on` 读回。这在模拟的 AC5 上测过，没有在真机上核对过：插座读回的格式、更新的时机，以及面板开泵后多久能读到，都没有实测。读不出来时只发警告，看门狗不会动手。 | [`executor/watchdog.py`](../../../src/growbridge/executor/watchdog.py)、[`control/device.py`](../../../src/growbridge/control/device.py) |
| 树莓派与 Linux 蓝牙 | 未验证 | `BleakTransport`（BlueZ 上的 Bleak）只在测试里对着假客户端跑过。没有在实体树莓派上运行的记录。 | [`transport.py`](../../../src/growbridge/transport.py)、[`tests/transport/`](../../../tests/transport/) |
| 事件通道关闭后 Swift 辅助程序退出 | 未验证 | 在 macOS 上，Python 一侧断开时，辅助程序应当丢弃排队中的写入并退出（`watchChannel`）。CI 只编译这个辅助程序。 | [`BLEHelper.swift`](../../../src/growbridge/native/BLEHelper.swift) |
| 其他控制器、其他固件、加密协议 v2 | 未验证 | 只用过一台明文协议 v1 的 AC5。控制要求协议版本为 1，否则拒绝。 | [`service.py`](../../../src/growbridge/service.py)、[VALIDATION.md](../../../VALIDATION.md) |
| `serve` 的后台任务 | 没有自动化测试 | 每秒一次的 tick 循环（`_tick_forever`）、每 30 秒一次的模型角色轮询（`_agents_forever`），以及为局域网入口开的第二个监听（`_serve_listeners`），都没有测试覆盖。测试是直接调用 `Runtime.tick()` 和 `Runtime.run_agents()` 的。 | [`cli.py`](../../../src/growbridge/cli.py) |
| Telegram 和邮件的真实投递 | 未验证 | `TelegramChannel` 和 `EmailChannel` 只用假的传输层测试过。 | [`observer/channels.py`](../../../src/growbridge/observer/channels.py)、[`test_observer_channels.py`](../../../tests/observer/test_observer_channels.py) |
| 外部心跳 | 已接进 `serve`，未对真实服务验证 | `GROWBRIDGE_HEARTBEAT_HOST_URL` 和 `GROWBRIDGE_HEARTBEAT_RUN_URL` 都设了时，`serve` 每 60 秒发一次信号，运行健康变化时立即再发；只设一个则拒绝启动；都不设则留下常驻警告 `monitor_unconfigured`。只用假 HTTP 客户端测试过：没有任何信号发到过真实的监控服务。 | [`runtime_heartbeat.py`](../../../src/growbridge/runtime_heartbeat.py)、[`test_e2e_heartbeat.py`](../../../tests/e2e/test_e2e_heartbeat.py) |
| 主机时间同步 | 未实现 | 没有任何代码检查主机时钟是否已同步：`SystemClock.synced` 一直是 true。唯一的时钟检查是墙上时钟相对单调时钟跳变超过 5 秒，它会让运行中的阶段暂停，直到操作员续跑。主机休眠后被唤醒，看起来就是这样一次跳变。 | [`archive/clock.py`](../../../src/growbridge/archive/clock.py)、[`executor/outage.py`](../../../src/growbridge/executor/outage.py) |
| 模型角色的 `data` 和 `provider` | 未生效 | 这两个字段加载时会校验，但没有代码读取。`data` 不限制角色能读到什么；角色能接触到什么由它的工具决定。 | [`config.py`](../../../src/growbridge/config.py)、[`agents/tools.py`](../../../src/growbridge/agents/tools.py) |
| 模型单价 | 未验证 | 默认模型的内置单价（`DEFAULT_PRICE`）是代码里的常量，没有和提供方当前的价目表核对过。其他模型的单价都来自配置。 | [`agents/llm.py`](../../../src/growbridge/agents/llm.py)、[配置参考](Configuration-Reference.md) |
| 系统账户隔离 | 部署事项 | 代码是单进程的。它为每个服务各保留一个 SQLite 文件（`control`、`workflow`、`archive`、`observer`、`compute`、`agents`），将来分账户就建立在这个基础上。 | [`runtime.py`](../../../src/growbridge/runtime.py)（`DATABASES`） |
| 覆盖网络 | 部署事项 | 常驻服务监听 `127.0.0.1`，覆盖网络入口要靠架在它前面的代理。仓库里没有代理或网络的配置。 | [`workbench/auth.py`](../../../src/growbridge/workbench/auth.py)（`entry_for`） |
| 通行密钥（passkey） | 未实现 | 操作员用一个至少 12 个字符的密码登录，密码以加盐的 scrypt 哈希保存。 | [`workbench/auth.py`](../../../src/growbridge/workbench/auth.py) |
| 提交研究目标 | 在模拟器上验证到报告交付 | 操作员通过 `/wb` 路由创建项目、研究协议和轮次，设置调用预算，再提出目标，也可以在项目页面的对话里提出。2026-11-14 在模拟的 AC5 上（`scripts/dev_workbench.py --claude-code`，各角色经 Claude Code 命令行使用 `claude-opus-5-5`），目标从编排 Agent 交给计划 Agent，计划 Agent 保存了通过校验的运行单；编排 Agent 被后续任务唤醒，告诉用户去审阅。同一天又用 `--fast-forward` 这样跑完了完整一轮：审批、14 天的阶段、录入测量、研究 Agent 检查数据、冻结并出报告，最后交付。2026-11-15 在 PR 4 最后几处修复之后，又这样跑了一轮，阶段 21 天，带人工任务记录（[示例：模型角色跑完整一轮](Example-Full-Round-With-Claude.md)）；它发现的待解决问题列在那一页。还没有在 `serve`、真实设备或模型 API 密钥下跑过。没有 CLI 命令。 | [`workbench/rounds.py`](../../../src/growbridge/workbench/rounds.py)、[运行一轮研究](Run-a-Research-Round.md) |
| 还缺的工作台路由 | 未实现 | 没有路由能读取已保存研究协议的内容，处理研究任务，读取数据快照或报告，撤销审批，或给执行中的阶段切换运行单。项目、轮次、任务、阶段历史和待办由读取路由列出。是哪个操作员创建了项目、协议或轮次，是谁设了预算，都没有记录。 | [`workbench/api.py`](../../../src/growbridge/workbench/api.py)、[`workbench/rounds.py`](../../../src/growbridge/workbench/rounds.py)、[`workflow/service.py`](../../../src/growbridge/workflow/service.py) |
| 操作员控制台 | 只在模拟的 AC5 上检查过 | `/workbench` 的页面已经有了（见上面的「已验证」表）。没有对真实设备、真实通知渠道或 CSC 用过，没有在 Safari 或 Firefox 里试过（只用了开发工具自带的浏览器窗格），也没有在手机上试过。时间按 `report_timezone` 的时区显示。登记留出批次时仍要自己填批次编号。操作员批准时，控制台会带上它展示的运行单摘要，运行单在此之后变过，服务端就拒绝（`expected_digest`）；控制台的安全页在操作员审阅期间已批准的限值变了时会拒绝批准（确认前后各重新读取一次），但服务端对安全配置的批准还没有这样的前置条件，留作后续。 |
| 工作台路由上的角色令牌 | 已知限制 | 持有角色令牌的模型角色可以读取任何阶段的运行信息，并向它指名的任何轮次提交运行单草稿。这在控制台出现之前就存在。没有操作员的批准什么都不会运行，而批准现在要求带上所审阅运行单的摘要。给角色令牌限定这些路由的范围，或者关闭它们，留作后续。 | [`workbench/api.py`](../../../src/growbridge/workbench/api.py) | [`web/workbench/`](../../../src/growbridge/web/workbench)、[启用 DiAGRI](Enable-DiAGRI.md) |
| 在 CSC 上跑作业 | 已接入 `serve`，没有对 CSC 验证过 | `compute_templates_dir`、`compute_member` 和七个 `FIRECREST_*` 变量都设了时，`serve` 在 `FirecrestBackend` 上构建计算服务。它依据 CSC 和 pyfirecrest 的文档实现，只对假客户端测试过。接口既不报告 CPU 用量，也不提供计费余额：每个作业按模板的 `max_cpu_hours`（以及 `max_storage_gb`）全额计账，项目余额和各任务的预算由操作员通过工作台录入（`POST /wb/compute/balance`、`POST /wb/compute/tasks/{task_id}/budget`）。Slurm 的状态名文档里没有列全：代码不认识的状态（例如 `SUSPENDED`）一律报错，绝不当作"已完成"。文档也没说作业查询能不能找到已经结束的作业，所以 FirecREST 不再列出的已结束作业无法取回或清理。tick 每分钟会对没有回应的提交对账、对进行中的作业轮询；结果未知时（查不到作业，或取消后读不到结果）这次尝试按全额预留计账，没有人能恢复的尝试可由操作员结算（`POST /wb/compute/attempts/{attempt_id}/settle`；`GET /wb/compute` 列出卡住的）。`DEADLINE`、`PREEMPTED`、`BOOT_FAIL`、`REVOKED` 让尝试以失败结束，`REQUEUED` 和 `REQUEUE_HOLD` 让它保持排队，`SUSPENDED` 和 `STOPPED` 让它保持运行；这个对应关系是对 Slurm 手册的理解，不是 CSC 的文档。配置不全时，计算相关的工具回答 `unavailable`。 | [`compute/firecrest.py`](../../../src/growbridge/compute/firecrest.py)、[`runtime_compute.py`](../../../src/growbridge/runtime_compute.py)、[`workbench/compute.py`](../../../src/growbridge/workbench/compute.py) |
| 文献检索 | 未实现 | 没有检索后端。计划 Agent 的 `lookup_crop_conditions` 和 `search_and_verify_sources` 两个工具回答 `unavailable`。 | [`agents/handlers_planner.py`](../../../src/growbridge/agents/handlers_planner.py)、[`runtime_agents.py`](../../../src/growbridge/runtime_agents.py) |
| 运行模型所写代码的沙箱 | 只支持 macOS | 沙箱依赖 `sandbox-exec`。在其他系统上，包括 Linux 和树莓派，它拒绝运行任何代码，拒绝码是 `sandbox_unavailable`。因此在这些系统上，本地分析和确认性分析都跑不了。 | [`research/sandbox.py`](../../../src/growbridge/research/sandbox.py) |
| 确认性分析 | 只在测试里验证过 | 操作员通过工作台冻结脚本、启动每一次运行；端到端测试用的是假沙箱。每份快照各运行一次，而不是架构文档 6.5 节所说的对系列各轮做一次总的运行。进程在运行途中死掉，这次运行会保持未结束，直到下一次启动把它按失败处理并标为 `interrupted`：这一次机会仍然算用掉，引用这份快照的报告随后以探索性发布。留出数据通过工作台登记，必须早于它的结局数据；它们还不能用来评估模型（见下）。 | [`workbench/analysis.py`](../../../src/growbridge/workbench/analysis.py)、[`research/analysis.py`](../../../src/growbridge/research/analysis.py)、[研究方法](Research-Methodology.md) |
| 用留出数据评估模型 | 未实现 | 留出集可以登记，登记之后留出批次的结局不会进入开发数据。但没有任何流程用它们给模型打分：登记模型和 `evaluate` 只核对哈希、统计读取次数，也没有路由能登记模型。打分需要一个不把留出结局暴露给模型的设计。 | [`research/holdout.py`](../../../src/growbridge/research/holdout.py)、[`workbench/holdouts.py`](../../../src/growbridge/workbench/holdouts.py)、[研究方法](Research-Methodology.md) |
| 告警规则 | 默认为空 | `DEFAULT_ALERT_RULES` 是空的，配置里也没有设置告警规则的字段，所以观察与通知 Agent 不会发出任何阈值告警。 | [`runtime.py`](../../../src/growbridge/runtime.py) |
| 相机采集 | 未实现 | 没有任何相机相关的代码。长势观察靠录入人工测量。 | [`observer/report.py`](../../../src/growbridge/observer/report.py) |
| 备份 | 只备份 SQLite 数据库 | 一次备份复制的是 DiAGRI 的六个数据库，不包括仅桥接模式的历史文件 `growbridge.sqlite3`，也不包括数据目录下 `archive/` 里的文件（例如数据快照）。目前还没有图像采集，所以也没有图像可备份。没有设置 `backup_dir` 时什么都不备份，并且会有一条常驻的警告。 | [`runtime_backup.py`](../../../src/growbridge/runtime_backup.py)、[`archive/backup.py`](../../../src/growbridge/archive/backup.py) |
| 在事件循环里冻结快照 | 已知限制 | 冻结数据快照（`freeze_dataset`）以及本地分析前重新核验快照，都要读文件、算哈希，同时持有数据库事务，而且是在承担每秒一次执行循环的同一个事件循环里进行。阶段较长时，执行循环可能因此停顿几秒。沙箱运行本身和确认性运行前的检查已经移出事件循环。 | [`archive/snapshot.py`](../../../src/growbridge/archive/snapshot.py)、[`agents/handlers_researcher.py`](../../../src/growbridge/agents/handlers_researcher.py) |
| 监察 Agent | 未验证 | 监察 Agent 只在测试里用预先写好的模型回复跑过，从未用真实模型跑过。它写的说明、提出的发现，以及它如何使用那 8 次调用，都没有在真实模型下看到过。 | [`agents/handlers_auditor.py`](../../../src/growbridge/agents/handlers_auditor.py)、[`runtime_agents.py`](../../../src/growbridge/runtime_agents.py) |
| 冻结读数的门槛 | 未验证 | 默认门槛（temp 120、humi 60、co2 60、tempSoil 240 分钟）来自 64 分钟的闲置数据。在依赖冻结读数触发暂停之前，需要用真实实验数据重新调整。 | [`observer/frozen_watch.py`](../../../src/growbridge/observer/frozen_watch.py) |
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
