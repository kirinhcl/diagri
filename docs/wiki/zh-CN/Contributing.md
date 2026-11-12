# 贡献流程

[English](../en/Contributing.md)

这一页写给准备提交改动的人。它按步骤说明这个仓库目前是怎么做改动的，最后给出评审时用的检查清单。

下面写的是目前的做法，不是正式的制度。仓库里没有 `CONTRIBUTING.md`，没有 Pull Request 模板，也没有自带的 Git 钩子。提交历史里还看不出来的习惯，本页会直接说明。

## 开始之前

1. 搭好环境，先让测试全部通过：[开发环境、测试与 CI](Development-Setup-Testing-and-CI.md)。
2. 找到要改的代码，弄清它必须遵守的契约：[代码结构与扩展点](Code-Structure-and-Extension-Points.md)。

## 做一次改动

### 1. 在分支上工作

```sh
git switch -c feat/<short-name>
```

改动在分支上做，不直接在 `main` 上做。到目前为止唯一的功能分支是 `feat/auto-research-agents`，Agent 系统就是在它上面加进来的。除了这个例子，分支怎么命名没有别的规定。

### 2. 会让硬件动起来的地方，先写测试

凡是改 [`control/`](../../../src/growbridge/control)、[`executor/`](../../../src/growbridge/executor) 或 [`workflow/`](../../../src/growbridge/workflow)，都先写一个会失败的测试，再写代码。这三个包决定了往真实设备上写什么、什么时候写，这里出错，灯、风扇或水泵就会跟着动。

- 修 bug 时，先写一个因为这个 bug 而失败的测试。
- 使用模拟器，测试不需要 AC5。规则见[开发环境、测试与 CI](Development-Setup-Testing-and-CI.md)。
- 测试放在对应领域的目录里，例如 `tests/control/`，文件名以领域开头。

其他的包，目前的做法没有规定先后顺序。

### 3. 跑一遍 CI 的检查

```sh
.venv/bin/ruff check src tests scripts
.venv/bin/ruff format --check src tests scripts
.venv/bin/pytest -q
```

完整的清单和 CI 的执行顺序见[开发环境、测试与 CI](Development-Setup-Testing-and-CI.md)。

### 4. 提交

提交信息的标题行写成 `<type>: <description>`。

| 类型 | 用于 |
| --- | --- |
| `feat` | 新的行为 |
| `fix` | 修复 bug |
| `refactor` | 调整结构，行为不变 |
| `docs` | 只改文档 |
| `test` | 只改测试 |
| `chore` | 归不到其他类型的维护工作 |
| `perf` | 性能方面的改动 |
| `ci` | CI 工作流 |

`git log --oneline` 目前的实际情况：一共十个提交。最新的三个采用了这个格式，`feat:` 一次，`docs:` 两次。更早的七个是以动词开头的普通句子，例如“Add local dashboard with live controls, history charts and CSV export”。其余六种类型属于同一套约定，只是还没有出现过。

### 5. 推送，等 CI 通过

每次推送和每个 Pull Request 都会触发 CI。四个作业全部通过，改动才算可以送审：Linux 和 macOS，各配 Python 3.11 和 3.13。只在一个操作系统上通过是不够的，因为两边的 BLE 传输不同、沙箱不同，还有 14 个测试只在其中一边运行。

## 目前一直遵守的规则

### 仓库里不放密钥

凭据只有两个来源，都不是受版本管理的文件。

| 来源 | 内容 | 由谁读取 |
| --- | --- | --- |
| 环境变量 | 模型的 API 密钥、`GROWBRIDGE_TELEGRAM_TOKEN`、`GROWBRIDGE_ROLE_TOKEN_<ROLE>`、`FIRECREST_*` 这一组变量 | [`agents/llm.py`](../../../src/growbridge/agents/llm.py)、[`observer/channels.py`](../../../src/growbridge/observer/channels.py)、[`cli.py`](../../../src/growbridge/cli.py)、[`compute/firecrest.py`](../../../src/growbridge/compute/firecrest.py) |
| 私有配置文件 | 安装令牌 | [`config.py`](../../../src/growbridge/config.py)。`growbridge init` 默认把它建在仓库之外，只有文件所有者可读。 |

[`.gitignore`](../../../.gitignore) 已经把常见的载体排除在外：`.env`、`config.toml`、`*.sqlite*`、`*.backup`、`*.jsonl` 和 `.local/`。测试里的凭据一律是占位值。真实的设备地址、账号名和原始协议抓包同样不应进入仓库。

### 文件不超过 800 行

`src/`、`tests/` 和 `scripts/` 下的每个 Python 文件目前都在 800 行以内。文件快到上限时，按职责拆分：工具处理函数拆成了 `agents/handlers_*.py`；工作流服务超过 800 行时，它的恢复核对逻辑移到了 [`workflow/recovery.py`](../../../src/growbridge/workflow/recovery.py)。控制台的 `web/app.js` 和 `web/style.css` 比这长，它们属于桥接部分，比 DiAGRI 的其余部分更早。

### Wiki 页面两种语言一起改，放在同一次提交里

每个页面在 `en/` 和 `zh-CN/` 下各有一份，文件名相同。两份要在同一次提交里修改，并遵守 [Wiki 的 README](../README.md) 里的十条编写约定。[`tests/docs/test_docs_wiki.py`](../../../tests/docs/test_docs_wiki.py) 这个测试负责检查程序能检查的部分：

- 每个页面两种语言都有；
- Wiki 的 README 里的页面表，和实际存在的页面完全一致；
- 每个相对链接指向的文件都存在；
- 每个页面都链接到另一种语言的版本。

它不检查两个版本说的是不是同一件事，这要靠评审的人来看。

### 不要绕过 Git 钩子

提交和推送时不要加 `--no-verify`。仓库本身不带钩子，所以这里指的是你本机或你所在组织安装的钩子。钩子拦下提交时，把它指出的问题修好。

## 评审检查清单

清单里的每一项，都是这份代码在评审中真实出现过的一类缺陷。送审之前，先对照它检查自己的改动。

| 要找的问题 | 该问什么 | 代码里正确的做法在哪里 |
| --- | --- | --- |
| 读取失败时，检查反而放行 | 读取抛出异常或什么都没返回时，这个分支会怎么做？“读不出来”绝不能当成“一致”“安全”或“没有差异”。 | 执行 Agent 把读不出来的设备状态当作有差异处理：[`tests/executor/test_executor_unreadable.py`](../../../tests/executor/test_executor_unreadable.py)。 |
| 模型给出的 ID 没有限定在它的任务范围内 | 在读取或创建任何东西之前，每个快照、轮次或阶段的 ID 是否都对照过调用方任务所属的项目？ | [`agents/handlers_common.py`](../../../src/growbridge/agents/handlers_common.py) 里的 `scoped_snapshot` 和 `require_round`，以及 [`tests/dispatch/test_dispatch_snapshot_scope.py`](../../../tests/dispatch/test_dispatch_snapshot_scope.py)。 |
| 写入没有经过控制服务 | 每一次写设备，是否都走 `ControlPort` 的 `submit`、`irrigate` 或 `pump_off`？ | 在 DiAGRI 的各个包里，只有 `control/` 导入 `Bridge`。契约在 [`ports.py`](../../../src/growbridge/ports.py)。 |
| 该用单调时钟的地方比较了墙上时钟 | 这是一段时长、一个超时还是一个最小间隔？是的话就用 `Clock.monotonic()`。`Clock.now()` 用于按日历触发的动作和记录上的时间戳。 | [`executor/rules.py`](../../../src/growbridge/executor/rules.py) 和 [`archive/clock.py`](../../../src/growbridge/archive/clock.py)。测试里可以用 `FakeClock.jump` 拨动墙上时钟，而不让时间流逝。 |
| 测试访问了网络 | 测试有没有建立真实连接、解析真实主机名，或读取真实密钥？ | [`tests/observer/test_observer_channels.py`](../../../tests/observer/test_observer_channels.py) 里的 `httpx.MockTransport`，以及 [`sim/`](../../../src/growbridge/sim) 里的模拟器。 |

还有两个问题，每次改动都要问：

- 新增的工具、路由或命令，会不会让模型角色得到控制阶段或设备的能力？不允许这样。见[控制与安全模型](Control-and-Safety-Model.md)。
- 改动是否描述了真机、树莓派、真实通知服务或 CSC 上的行为？如果是，要写明哪些测过、哪些没有，并链接到[状态与已知限制](Status-and-Known-Limitations.md)。这是 Wiki 的 README 里第 6 条约定的要求。

## 另见

- [开发环境、测试与 CI](Development-Setup-Testing-and-CI.md)
- [代码结构与扩展点](Code-Structure-and-Extension-Points.md)
- [控制与安全模型](Control-and-Safety-Model.md)
- [状态与已知限制](Status-and-Known-Limitations.md)
- [Wiki 的编写约定](../README.md)
