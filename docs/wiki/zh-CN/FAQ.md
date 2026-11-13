# 常见问题

[English](../en/FAQ.md)

这一页写给新用户和新贡献者，用几句话回答最先会遇到的问题，并指出详细内容在哪一页。

## 安全与控制

### 模型能开水泵吗？能改设备的其他设置吗？

不能。阶段控制和设备控制的工具（包括 `run_pump` 和 `set_light`）都列在 `CONTROL_TOOLS` 里，会从每个模型角色的工具集中剔除（见 [`agents/tools.py`](../../../src/growbridge/agents/tools.py)）。水泵还有另外几道限制：运行单里只要有会启动水泵的动作，校验就不通过；执行 Agent 也拒绝开泵。只有操作员在人工接管期间、从局域网入口调用 `/wb/irrigation`，水泵才会启动，而且每次最长不超过 `max_pump_seconds`。

详见[控制与安全模型](Control-and-Safety-Model.md)和[人工接管、灌溉与交还](Manual-Takeover-and-Irrigation.md)。

### 模型接口不可用时会怎样？

设备控制不受影响。驱动执行 Agent、保护规则和观察与通知 Agent 的那个 tick 从不调用模型，所以已批准的阶段会照常跑到结束（见 [`runtime.py`](../../../src/growbridge/runtime.py)）。模型调用失败的那个研究任务会转为 `needs_attention`，记下原因并发出告警；它不会自己重新运行（见 [`agents/dispatch.py`](../../../src/growbridge/agents/dispatch.py)）。如果常驻服务启动时就建不起模型客户端，它会发一条告警，然后在没有模型角色的情况下继续提供服务。

详见[五个 Agent](The-Five-Agents.md)和[故障处理手册](Troubleshooting-Runbook.md)。

### 为什么打开 DiAGRI 之后，`set_light` 和控制台上的控制都不能用了？

这是有意的设计。`auto_research = true` 时，仅桥接模式的三个写入接口一律返回 403，提示 `Device writes go through the workbench`（见 [`api.py`](../../../src/growbridge/api.py)），MCP 服务也只注册三个读取工具（见 [`mcp_server.py`](../../../src/growbridge/mcp_server.py)）。这时想手动写设备，要走 `/wb/manual/{channel}`，并且必须有一个处于人工接管状态的阶段。

详见[人工接管、灌溉与交还](Manual-Takeover-and-Irrigation.md)和 [HTTP、工作台与 MCP 接口](API-Reference.md)。

## 运行

### 怎么关掉 DiAGRI？

在 `config.toml` 里把 `auto_research` 设为 `false`，或者删掉这一行，然后重启 `growbridge serve` 和所有 MCP 客户端。常驻服务会按仅桥接模式启动：不构建运行时，不挂载 `/wb` 路由；只要 `controls_enabled` 为 true，仅桥接模式的写入接口和 MCP 写入工具就恢复可用（见 [`cli.py`](../../../src/growbridge/cli.py)）。DiAGRI 的数据库原样留在数据目录里。关闭之前请先停止正在执行的阶段，因为仅桥接模式下没有任何东西去执行它的运行单、养护规则和保护规则。

详见[启用 DiAGRI](Enable-DiAGRI.md)和[配置参考](Configuration-Reference.md)。

### 需要模型的 API 密钥吗？

仅桥接模式、`growbridge simulate` 和测试都不需要。在 DiAGRI 模式下，模型角色是可选的：只有配置里设置了 `roles`，常驻服务才会去建模型客户端（见 [`cli.py`](../../../src/growbridge/cli.py)）。模型客户端需要用 `pip install '.[agents]'` 装上 `agents` 这组可选依赖；凭据从环境变量读取，不会从 `config.toml` 里读（见 [`config.py`](../../../src/growbridge/config.py)）。

详见[启用 DiAGRI](Enable-DiAGRI.md)。

### 现在就能向它提一个研究问题吗？

可以，走工作台路由：用 `/workbench` 的控制台页面，或者手工发请求。没有命令。操作员创建项目、研究协议和轮次，设置模型调用预算，再用 `POST /wb/goals` 提出问题。[运行一轮研究](Run-a-Research-Round.md)列出了这些请求。工作台是 `/wb` 下的一组 HTTP 路由，`/workbench` 的操作员控制台是它的页面。这条路径只在 [`tests/e2e/`](../../../tests/e2e/) 的测试里跑过，用的是脚本化的模型和模拟的 AC5。真实模型拿到问题后会怎么做，没有验证过。

详见[状态与已知限制](Status-and-Known-Limitations.md)。

### DiAGRI 控制过真实的帐篷吗？没有帐篷能不能试用？

没有控制过。DiAGRI 只在模拟的 AC5 上运行过；读取并控制过真实 AC5 的是仅桥接模式（见 [VALIDATION.md](../../../VALIDATION.md)）。想不接硬件看 DiAGRI 跑起来，运行 `growbridge simulate` 即可，它不需要配置文件，不用蓝牙，也不联网。

详见[教程：在模拟器上跑通一轮研究](Tutorial-Simulated-Round.md)和[状态与已知限制](Status-and-Known-Limitations.md)。

### 能在 Linux 或树莓派上运行吗？

代码是按两者都支持来写的，但没有在实体树莓派上验证过。在 Linux 上，蓝牙后端是 BlueZ 上的 Bleak（见 [`transport.py`](../../../src/growbridge/transport.py)），[`scripts/install_linux.py`](../../../scripts/install_linux.py) 会安装一个 systemd 用户服务，CI 也在 `ubuntu-latest` 上对着模拟设备运行测试套件。在 macOS 之外，DiAGRI 还多一条限制：没有沙箱，所以本地分析和确认性分析都会被拒绝，拒绝码是 `sandbox_unavailable`。

详见[状态与已知限制](Status-and-Known-Limitations.md)，以及 [README](../../../README.zh-CN.md) 的「树莓派部署」一节。

## 数据与结论

### 我的数据存在哪里？

都在运行常驻服务的那台机器上，分两处私有位置。配置文件（含访问令牌）是 `~/.config/spiderfarmer-growbridge/config.toml`。其余的都在配置里 `data_dir` 指向的目录下，`init` 把它设为 `~/.local/share/spiderfarmer-growbridge`：仅桥接模式的历史在 `growbridge.sqlite3` 里；在 DiAGRI 模式下，每个服务各有一个 SQLite 文件（`control`、`workflow`、`archive`、`observer`、`compute`、`agents`），另外还有存放数据快照的 `archive/` 目录（见 [`runtime.py`](../../../src/growbridge/runtime.py)）。设置了 `backup_dir` 的话，这六个数据库会定期复制到那里。

有两项由你配置的功能会把数据发到别处：模型角色会把它读到的内容发给模型服务商；通知渠道会把告警和日报的文字发到 Telegram 或你的邮件服务器。

详见[数据、档案与可追溯性](Data-Archive-and-Traceability.md)和[通知、日报与备份](Notifications-Reports-and-Backup.md)。

### 结论是 `uncertain`，是什么意思？

意思是这次实验没能回答这个问题，而不是「处理没有效应」。[`research/analysis.py`](../../../src/growbridge/research/analysis.py) 里的 `conclusion()` 在以下情况返回 `uncertain`：这一轮提前终止，或实际样本量没达到计划；效应无法估计；或者区组太少，检验根本达不到显著性水平。按默认的 0.05 水平，最后一种情况就是区组少于六个。除此之外，结论才会是 `supported` 或 `not_supported`。

详见[科研方法](Research-Methodology.md)。

## 关于项目

### 项目叫 DiAGRI，为什么软件包和命令叫 `growbridge`？

DiAGRI 是整个项目，仓库以它命名。GrowBridge 是其中的一部分：负责和 Spider Farmer AC5 通信的设备桥接。桥接部分最先写成，所以软件包名（[`pyproject.toml`](../../../pyproject.toml) 里的 `spiderfarmer-growbridge`）、导入名和命令（`growbridge`），以及配置目录（`~/.config/spiderfarmer-growbridge`）都沿用它的名字，DiAGRI 的其余部分是 `growbridge` 下的子包。所以克隆的是 `diagri`，进的目录是 `diagri`，之后敲的每条命令都是 `growbridge`。

详见[安装与快速开始](Installation-and-Quick-Start.md)。

### 提交修改之前要跑什么？

和 CI 一样的检查（见 [`ci.yml`](../../../.github/workflows/ci.yml)）：

```sh
.venv/bin/ruff check src tests scripts
.venv/bin/ruff format --check src tests scripts
.venv/bin/pytest -q
```

运行它们需要先装 `dev` 这组可选依赖。所有测试用的都是模拟设备，测试套件不会碰蓝牙，也不会碰真实的 AC5。

详见[开发环境、测试与 CI](Development-Setup-Testing-and-CI.md)和[贡献流程](Contributing.md)。

## 另见

- [项目概览](Overview.md)
- [术语表](Glossary.md)
- [状态与已知限制](Status-and-Known-Limitations.md)
- [故障处理手册](Troubleshooting-Runbook.md)
