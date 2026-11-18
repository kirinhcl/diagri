# 开发环境、测试与 CI

[English](../en/Development-Setup-Testing-and-CI.md)

这一页写给贡献者。它带你从刚克隆的仓库走到测试全部通过，然后列出 CI 跑的每一项检查、测试的目录结构，以及新写的测试必须遵守的规则。

这一页的所有步骤都跑在模拟器上。除了安装依赖和构建发行包，其余步骤都不需要联网，也都不需要 AC5、蓝牙和模型的 API 密钥。哪些已经在真机上测过、哪些没有，见[状态与已知限制](Status-and-Known-Limitations.md)。

## 准备工作

| 需要 | 用途 | 在哪里规定 |
| --- | --- | --- |
| Python 3.11 或更新版本 | 所有步骤 | [`pyproject.toml`](../../../pyproject.toml) 里的 `requires-python = ">=3.11"` |
| Node.js | 对桥接控制台和操作员控制台的脚本做语法检查，并运行操作员控制台的单元测试（`node --test`，不需要 npm 包）。CI 用的是 Node 22。 | [`.github/workflows/ci.yml`](../../../.github/workflows/ci.yml) |
| Xcode Command Line Tools（仅 macOS） | 编译原生 BLE 辅助程序，也就是 CI 的最后一步 | 同上 |

CI 一共跑四个作业：`ubuntu-latest` 和 `macos-latest`，各配 Python 3.11 和 3.13。本页记录的那次测试结果是在 macOS、Python 3.14 上跑出来的，这个版本不在 CI 的矩阵里。

## 创建环境

```sh
git clone <repository-url>
cd diagri
python3 -m venv .venv
.venv/bin/python -m pip install -c constraints-tested.txt -e '.[dev]'
```

安装命令里各部分的作用：

- `-c constraints-tested.txt` 把运行时依赖（`bleak`、`fastapi`、`httpx`、`mcp`、`pydantic`、`starlette`、`uvicorn`）固定在 [`constraints-tested.txt`](../../../constraints-tested.txt) 记录的版本上。开发工具和可选依赖不受它约束。
- `-e` 是可编辑安装，`growbridge` 命令和测试直接使用 `src/` 下的文件。
- `dev` 这组依赖包含 `pytest`、`pytest-asyncio`、`pytest-cov`、`ruff` 和 `build`。
- `bleak` 只在 Linux 上安装。macOS 上的 BLE 连接由 [`native/BLEHelper.swift`](../../../src/growbridge/native/BLEHelper.swift) 这个 Swift 辅助程序负责。

虚拟环境放在 `.venv/` 里，[`.gitignore`](../../../.gitignore) 已经把它排除。

### 可选依赖

| 名称 | 安装的包 | 用途 | 不装会怎样 |
| --- | --- | --- | --- |
| `agents` | `anthropic` | [`agents/llm.py`](../../../src/growbridge/agents/llm.py) 里的 `AnthropicClient`，模型角色通过它调用模型。 | 包照常导入和运行。开启 DiAGRI 并配置了 `roles` 时，`growbridge serve` 会产生一条告警，模型角色保持关闭。有两个测试被跳过。 |
| `csc` | `pyfirecrest` | 构造 [`compute/firecrest.py`](../../../src/growbridge/compute/firecrest.py) 里的 `FirecrestBackend`。 | 不注入客户端时，`FirecrestBackend()` 抛出 `BackendUnavailable`。没有测试依赖这个包：测试传入的是假客户端。 |
| `docs` | `zensical` | 用 [`scripts/build_wiki_site.py`](../../../scripts/build_wiki_site.py) 把本 Wiki 构建成网站。 | 无法构建网站。构建整个网站的那一个测试会被跳过。 |

`csc` 只安装客户端库。适配器依据它的文档实现，只对假客户端测试过，从未连接过 CSC。见[状态与已知限制](Status-and-Known-Limitations.md)。

要加装可选依赖，把名称写在 `dev` 后面：

```sh
.venv/bin/python -m pip install -c constraints-tested.txt -e '.[dev,agents]'
```

## 跑一遍 CI 的检查

CI 按下面的顺序执行。推送之前，请按同样的顺序在本地跑一遍。CI 里调用这些工具时不带 `.venv/bin/` 前缀。

| 步骤 | 命令 | 检查什么 |
| --- | --- | --- |
| 1 | `for f in src/growbridge/web/app.js $(find src/growbridge/web/workbench -name '*.js'); do node --check "$f"; done` | 桥接控制台脚本和操作员控制台的每个脚本都没有语法错误。 |
| 2 | `node --test tests/web/*.test.mjs` | 操作员控制台的单元测试（2026-11-14 共 148 个）：路由、格式化、拒绝提示和曲线计算等纯逻辑，以及一个守卫测试，保证控制台脚本不用 `innerHTML` 写入 HTML。它们在 Node 里运行，不需要浏览器、服务器或网络。
| 3 | `.venv/bin/python -m pip install -c constraints-tested.txt -e '.[dev,docs]'` | 包能按固定的版本装上，同时装上网站测试要用的 `zensical`。 |
| 4 | `.venv/bin/ruff check src tests scripts` | 代码检查。规则集 `E`、`F`、`I`、`B`、`UP`，行宽 100，都在 `pyproject.toml` 里配置。 |
| 5 | `.venv/bin/ruff format --check src tests scripts` | 代码格式。 |
| 6 | `.venv/bin/pytest -q` | 全部测试。 |
| 7 | `.venv/bin/python -m build` | 源码包和 wheel 能构建出来，产物在 `dist/`。 |
| 8 | `xcrun swiftc src/growbridge/native/BLEHelper.swift -o /tmp/growbridge-ble -framework CoreBluetooth -framework AppKit` | 仅 macOS。原生辅助程序能编译通过。它只被编译、不会被启动，所以不会用到蓝牙。 |

几点说明：

- **第 4、5 步。** 大多数问题可以用 `.venv/bin/ruff check --fix src tests scripts` 和 `.venv/bin/ruff format src tests scripts` 自动修好。
- **第 6 步。** 整套测试由代码测试加上 `tests/docs/` 里的 Wiki 测试组成。2026-11-14 共收集到 2385 个测试，其中代码测试 2274 个、Wiki 测试 111 个；在 macOS 上用 Python 3.14（装了 `agents`）运行，结果是 `2385 passed`，用时约 65 秒。Wiki 测试每页大约两个，所以总数会随 Wiki 页面增加。
- **第 7 步。** `build` 会新建一个隔离环境并下载构建后端（`setuptools`），所以这一步需要联网。`dist/` 已被 Git 忽略。

另一个 workflow [`.github/workflows/wiki-site.yml`](../../../.github/workflows/wiki-site.yml) 负责把本 Wiki 构建成网站。只有 `docs/wiki/`、`docs/images/`、[`scripts/build_wiki_site.py`](../../../scripts/build_wiki_site.py)、`pyproject.toml` 或它自己有改动时才运行。它安装 `docs`，运行 `python scripts/build_wiki_site.py`；链接指向不存在的文件、链接指向同一语言页面上不存在的标题，或者有页面没列在 `_Sidebar.md` 里，构建就会停止。指向另一种语言的链接里的锚点不做检查。在 PR 上只构建；合并到 `main` 后还会发布到 GitHub Pages。推送 Wiki 改动之前，先在本地跑一遍同样的构建：第一次运行 `.venv/bin/python -m pip install -e '.[docs]'`，之后运行 `.venv/bin/python scripts/build_wiki_site.py`。

还有一项 CI 不跑、但很有用的检查：`.venv/bin/growbridge simulate` 会用装配好的运行时在模拟的 AC5 上跑完一个很短的阶段，并打印结果摘要。[教程：在模拟器上跑通一轮研究](Tutorial-Simulated-Round.md)里有完整的讲解。

## 测试的目录结构

测试都在 [`tests/`](../../../tests) 下，一个领域一个目录。这些目录不是 Python 包，所以测试文件不能重名，文件名都以所在领域开头，例如 `test_control_rights.py`。

| 目录 | 覆盖的内容 |
| --- | --- |
| `tests/foundation/` | 共享的数据模型、SQLite 的 `Database` 封装，以及模拟器本身。 |
| `tests/archive/` | 项目档案：只追加的存储、数据快照、元数据导出、旧样本库的接入、存储空间不足时的降级和备份。 |
| `tests/control/` | 控制服务：写入权、写入的提交流程、关泵联锁、结果未知动作的对账。 |
| `tests/rules/` | 反馈规则和保护规则的求值，都是纯函数。 |
| `tests/executor/` | 执行 Agent 的每一拍：定时动作、养护规则、保护规则、阶段事件、重启、设备状态读不出来的情况。 |
| `tests/workflow/` | 工作流服务：研究轮次、阶段、权限、阶段事件、待核对与对账。 |
| `tests/tasks/` | 研究任务的看板和模型调用预算。 |
| `tests/planning/` | 实验设计检查、运行单校验和证据检查。 |
| `tests/research/` | 统计方法、确认性分析的关口、留出数据、报告发布和代码沙箱。 |
| `tests/agents/` | 模型客户端的适配、Agent 循环、角色定义和工具注册表。 |
| `tests/dispatch/` | 各模型角色的工具处理函数接在真实服务上的行为，包括模型给出的 ID 是否被限定在范围内。 |
| `tests/compute/` | 计算服务：作业的生命周期、额度、并发竞争，`FirecrestBackend` 对假客户端的行为、模板加载，以及工作台的余额和预算路由（`tests/workbench/test_workbench_compute.py`）。 |
| `tests/observer/` | 告警、通知渠道、发件箱、每日指标和日报、运行健康检查与心跳。 |
| `tests/workbench/` | 工作台的路由：操作员登录与会话、入口、请求关口、阶段操作和人工操作，以及发起和掌控一轮研究。 |
| `tests/transport/` | 两种 BLE 传输的 `halt`，以及原生传输对 pid 文件和目录权限的检查。 |
| `tests/e2e/` | 装配好的运行时：完整的一轮研究、人工干预、模型角色、CLI 命令，以及经 HTTP 路由走完的一轮。 |
| `tests/web/` | 操作员控制台的脚本，用 `node --test` 运行（见 CI 第 2 步）：路由、格式化、文案、拒绝提示、回执、阶段页的规则、曲线计算，以及对 `innerHTML` 的禁用。用 Node 自带的测试运行器，不需要 npm 包。 |
| `tests/docs/` | 这个 Wiki 本身：每个页面在 `en/` 和 `zh-CN/` 下都有；[Wiki 的 README](../README.md) 里的页面表和实际存在的页面完全一致；相对链接指向的文件存在；每个页面都链接到另一种语言的版本；参考页面的表格与代码一致：拒绝码、CLI、配置项、路由、MCP 工具和模型角色的工具。还有 [`test_build_wiki_site.py`](../../../tests/docs/test_build_wiki_site.py) 里的网站构建测试：链接怎样改写成网站上的链接，侧边栏列出了所有页面，以及装了 `docs` 时整个网站能构建出来、没有链接跑出站点。 |
| `tests/test_*.py` | 最初的桥接层：协议分帧、设备控制、HTTP API 与 MCP、控制台。共 32 个测试。 |

有两点对所有目录都适用：

- 异步测试不用加装饰器，因为 `pyproject.toml` 里设置了 `asyncio_mode = "auto"`。
- [`tests/conftest.py`](../../../tests/conftest.py) 提供两个夹具：`settings`（临时数据目录，设备名为 `SIMULATED`）和 `bridge`（接在 `SimulatedTransport` 上、已经启动的 `Bridge`）。多数目录还有自己的 `conftest.py`，以及一个名为 `*_helpers.py` 或 `*_support.py` 的辅助模块。

## 在模拟设备上运行控制台

[`scripts/dev_workbench.py`](../../../scripts/dev_workbench.py) 在模拟的 AC5 上启动运行时，不用蓝牙、不联网、不碰真实设备，让你可以在浏览器里使用操作员控制台。它预置一套已批准的安全配置和一个等待审核的阶段，每秒向模拟设备轮询一次以便读数持续到来，并且只绑定 `127.0.0.1`。操作员 `dev` 的密码只从环境变量读取，不接受命令行参数，至少 12 个字符。

```sh
GROWBRIDGE_DEV_SECRET='YOUR_DEV_SECRET' .venv/bin/python scripts/dev_workbench.py
```

| 入口 | 地址 | 说明 |
| --- | --- | --- |
| 现场 | `http://localhost:8770/workbench` | 局域网入口：全部功能，包括灌溉。 |
| 覆盖网络 | `http://127.0.0.1:8765/workbench` | 覆盖网络入口：除灌溉外的全部功能，控制台把灌溉显示为不可用。 |

数据放在新建的临时目录里，除非用 `--data-dir` 指定。按 Ctrl+C 停止脚本。

### 带上模型角色

`--roles FILE.toml` 会同时运行模型角色，和配置了 `roles` 的 `serve` 一样。文件里每个角色一张表（`[orchestrator]`、`[planner]` 或 `[researcher]`），字段同 `RoleModel`。Anthropic SDK 从环境变量读取地址和密钥，所以用 `ANTHROPIC_BASE_URL` 可以接到本地兼容 Anthropic 接口的模型服务。

`--claude-code` 改用本机的 Claude Code 命令行（`claude -p`，见 [`scripts/claude_code_client.py`](../../../scripts/claude_code_client.py)）运行这些角色：不需要 API 密钥，用的是 Claude Code 已登录的账号。每一轮模型回复是一次无界面调用，Claude Code 自带的工具全部关闭；所有工具仍由 diagri 自己的循环校验和执行。不给 `--roles` 时，三个角色都用默认模型。

`--transcript FILE.jsonl` 每次模型调用追加一行记录。里面是明文的提示词和工具结果，只在开发时使用。

`--fast-forward` 让运行中的阶段快进：每一步把时钟拨快运行单的一个采样间隔，读一次模拟设备再执行一次 tick，所以一周长的阶段一两分钟就跑完，数据也是完整的。阶段不在运行时按真实时间走。拨快的时间记在数据目录的 `dev_clock_offset` 里，重启后时钟不会倒退。登录会话也按这个时钟计时，阶段跑完后要重新登录。

开发工作台会像一个小帐篷那样改变模拟读数：温度和湿度随昼夜变化，灯光让空气升温，排风让空气降温变干，开灯时冠层会消耗 CO₂，另外加一点噪声。读数如果一直不变，会触发冻结读数检查，长阶段会被暂停。[示例：模型角色跑完整一轮](Example-Full-Round-With-Claude.md)记录了这样完整跑一轮的过程。

```sh
GROWBRIDGE_DEV_SECRET='YOUR_DEV_SECRET' .venv/bin/python scripts/dev_workbench.py --claude-code
```

项目页面上会显示项目对话：在那里提问，编排 Agent 大约 30 秒内回复。每个角色调用过的工具都列在它的回复下面。

## 只跑一部分

```sh
.venv/bin/pytest -q tests/control                               # 一个领域
.venv/bin/pytest -q tests/executor/test_executor_protection.py  # 一个文件
.venv/bin/pytest -q tests/workflow -k recovery                  # 名称匹配的测试
.venv/bin/pytest -q -rs                                         # 全部测试，并列出每个跳过的原因
```

别人还在写 Wiki 页面的时候，`tests/docs/` 可能因为不属于你的页面而失败。这时用 `.venv/bin/pytest -q --ignore=tests/docs` 跑其余的测试。

`dev` 里还带了 `pytest-cov`，但 CI 不统计覆盖率。如果你运行 `.venv/bin/pytest -q --cov=growbridge`，注意不要提交它生成的 `.coverage` 文件，`.gitignore` 里没有这一项。

## 哪些测试会被跳过

| 测试 | 什么时候跳过 | 原因 |
| --- | --- | --- |
| [`tests/research/test_research_sandbox.py`](../../../tests/research/test_research_sandbox.py) 里的 14 个，[`tests/e2e/test_e2e_assembly.py`](../../../tests/e2e/test_e2e_assembly.py) 里的 1 个，[`tests/e2e/test_e2e_sandbox_roots.py`](../../../tests/e2e/test_e2e_sandbox_roots.py) 里的 1 个 | 不是 macOS，或者没有 `/usr/bin/sandbox-exec`。 | 它们在 macOS 的沙箱（`SeatbeltSandbox`）里真正运行脚本，或者检查沙箱禁止读取哪些目录。其他平台上代码使用 `RefusingSandbox`，第一个文件里的其他测试覆盖了它。 |
| [`tests/agents/test_agents_llm.py`](../../../tests/agents/test_agents_llm.py) 里的 2 个 | 没有安装 `anthropic`。 | 它们构造 `AnthropicClient`，并把 `messages.create` 换成桩。不会发出任何请求。 |
| [`tests/docs/test_build_wiki_site.py`](../../../tests/docs/test_build_wiki_site.py) 里的 1 个 | 没有安装 `zensical`（即 `docs`）。 | 它构建整个网站，并检查没有链接跑出站点。CI 装了 `docs`，所以在 CI 里会运行。 |

CI 安装 `dev` 和 `docs`，不装 `agents`，所以这两个 `anthropic` 测试在所有 CI 作业里都会被跳过，16 个沙箱测试在 Linux 作业里也会被跳过。2026-11-13 的 CI 日志与此一致：macOS 作业跳过 2 个，Linux 作业跳过 18 个。

## 规则：不联网、不碰蓝牙、不用真实凭据

测试不访问网络，不使用蓝牙，也不使用任何真实账号。请使用 [`src/growbridge/sim/`](../../../src/growbridge/sim) 里的模拟器：

| 模拟器 | 代替什么 | 文件 |
| --- | --- | --- |
| `SimulatedTransport` | `WriteTransport` 协议背后的 AC5。测试可以改传感器读数、像在设备面板上那样改设备配置、断开连接、丢掉回复，还可以设定 `halt` 的返回值。 | [`sim/device.py`](../../../src/growbridge/sim/device.py) |
| `FakeClock` | `Clock` 协议。`advance` 让墙上时钟和单调时钟一起前进，`jump` 只拨动墙上时钟。 | [`sim/clock.py`](../../../src/growbridge/sim/clock.py) |
| `FakeControl` | 内存里的 `ControlPort`。设备状态可以直接设定，并记录写入权的授予和交接。 | [`sim/control.py`](../../../src/growbridge/sim/control.py) |
| `FakeBackend` | 内存里的 `ComputeBackend`。 | [`sim/compute.py`](../../../src/growbridge/sim/compute.py) |
| `ScriptedClient` | `ModelClient` 协议。按顺序回放用 `text_reply` 和 `tool_reply` 构造的回复。 | [`sim/llm.py`](../../../src/growbridge/sim/llm.py) |
| `make_run_sheet`、`make_protocol`、`make_safety`、`humidity_rule` | 一组合法的模型对象，测试按需覆盖其中的字段。 | [`sim/fixtures.py`](../../../src/growbridge/sim/fixtures.py) |

其他几类资源的做法：

- **HTTP** 不出进程。对外的请求换成 `httpx.MockTransport`，写法见 [`tests/observer/test_observer_channels.py`](../../../tests/observer/test_observer_channels.py)。调用应用本身时用 `httpx.ASGITransport` 或 FastAPI 的 `TestClient`。
- **凭据** 一律是用 `monkeypatch.setenv` 设置的占位值。测试不读取你环境里的真实密钥。
- **文件** 写在 pytest 的 `tmp_path` 或其他临时目录里，不碰真实的数据目录。
- **时间** 凡是服务接受 `Clock` 的地方，都用 `FakeClock.advance` 推进，测试时长和期限时不用真的等待。

这条规则没有自动化手段来保证，靠评审把关，见[贡献流程](Contributing.md)。

## 另见

- [代码结构与扩展点](Code-Structure-and-Extension-Points.md)
- [贡献流程](Contributing.md)
- [教程：在模拟器上跑通一轮研究](Tutorial-Simulated-Round.md)
- [状态与已知限制](Status-and-Known-Limitations.md)
- [README](../../../README.md) 的“Development and validation”一节，以及 [`VALIDATION.md`](../../../VALIDATION.md)
