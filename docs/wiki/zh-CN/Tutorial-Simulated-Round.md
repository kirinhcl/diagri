# 教程：在模拟器上跑通一轮研究

[English](../en/Tutorial-Simulated-Round.md)

这一页写给想先看 DiAGRI 跑起来、暂时不碰硬件的新手。你会在模拟的 AC5 上跑完一个很短的阶段，读懂输出里每个字段的含义，然后运行端到端测试，看一轮研究轮次怎样从一个问题走到报告归档。

这里的所有操作都不用蓝牙、不联网、不需要模型的 API 密钥，也不读你的配置文件。程序面对的是 [`sim/device.py`](../../../src/growbridge/sim/device.py) 里的 `SimulatedTransport`，用的是假时钟，数据写在临时目录里，结束后自动删除。

> 模拟只能说明软件各部分能配合起来，说明不了真实的 AC5、真实的蓝牙链路和树莓派上的情况。见[状态与已知限制](Status-and-Known-Limitations.md)。

## 准备

克隆仓库，并把软件包装进 `.venv`，也就是[安装与快速开始](Installation-and-Quick-Start.md)的第 1 步。那一页的第 2 到 5 步这里用不到。

## 第 1 步：运行模拟阶段

在仓库根目录执行：

```sh
.venv/bin/growbridge simulate
```

大约一秒后结束，输出如下：

```json
{
  "stage": "ended",
  "round": "data_verification",
  "beats": 10,
  "samples": 21,
  "writes": 3
}
```

## 第 2 步：读懂发生了什么

这条命令调用的是 [`runtime.py`](../../../src/growbridge/runtime.py) 里的 `simulate_stage()`。它依次做了这些事：

1. 构建一个 `Runtime`：`auto_research=True`，设备是模拟的，没有任何通知渠道，假时钟设在 `Europe/Helsinki` 时区的 2027-01-15 10:00。`growbridge serve` 装配的也是这同一套服务。
2. 把本机登记为写入主机，启动运行时，连接上模拟设备。
3. 以名为 `simulator` 的操作员身份批准一份安全配置，里面只有一条保护规则：温度高于 35 °C 持续 30 秒就关灯。
4. 创建项目，保存研究协议，创建轮次。
5. 为阶段 `stage-sim` 提交一份运行单，提交者标记为计划 Agent。这里没有调用任何模型，运行单是 [`sim/fixtures.py`](../../../src/growbridge/sim/fixtures.py) 里的固定样例。阶段时长 600 秒；灯在 06:00 到 22:00 之间开到 60 %，排风全天 30 %，阶段结束时关灯。
6. 确认校验没有阻断项，以操作员身份批准并启动这个阶段。
7. 反复执行「一拍」，直到阶段结束，最多 40 拍。一拍包含三件事：把时钟拨快 60 秒，向设备请求一次状态，调用一次 `runtime.tick()`。`tick` 就是常驻服务每秒调用一次的那个函数：先把新样本归档，再运行执行 Agent，然后是观察与通知 Agent 和其余的例行步骤。

输出里的五个字段：

| 字段 | 值 | 含义 | 来源 |
| --- | --- | --- | --- |
| `stage` | `ended` | 阶段状态。`ended` 表示到达了计划时长，结束动作也已执行。 | `runtime.workflow.stage("stage-sim").state` |
| `round` | `data_verification` | 轮次状态。最后一个阶段已结束，这一轮在等待冻结数据。 | `runtime.workflow.round_state(round_id)` |
| `beats` | `10` | 一共跑了多少拍：阶段 600 秒，每拍 60 秒。 | 循环计数 |
| `samples` | `21` | 项目档案里属于实验 `experiment-sim` 的样本数。只有阶段开始之后到达的样本才算。 | `runtime.archive.samples("experiment-sim")` |
| `writes` | `3` | 模拟的 AC5 收到的 `setConfigField` 命令数，也就是对设备的全部写入。 | `device.commands` |

有三点值得多说几句。

**为什么 10 拍有 21 个样本。** 每收到一次状态应答（`getDevSta`），桥接层就存一个样本（见 [`service.py`](../../../src/growbridge/service.py)）。循环每拍请求一次状态，每次写入之后的回读又会再请求。

**三次写入分别是什么。** 都是执行 Agent 用阶段写入权、经控制服务发出的。动作账本记下了每一次写入从 `pending` 到 `maybe_sent` 再到 `confirmed` 的过程，`confirmed` 表示回读结果与预期一致。

| 写入 | 动作账本里的触发原因 | 为什么 |
| --- | --- | --- |
| 灯调到 60 | `experiment_action:light-on` | 阶段在 10:00 开始，而定时动作 `light-on` 从 06:00 起就该生效。 |
| 排风调到 30 | `experiment_action:exhaust-base` | 定时动作 `exhaust-base` 从 00:00 起生效。 |
| 灯调到 0 | `end:light` | 运行单的结束动作。 |

**为什么轮次停在 `data_verification`。** `simulate` 只跑一个阶段就结束。这个阶段启动时从 `pending_review` 变为 `running`，结束动作执行后变为 `ended`。一轮研究剩下的步骤，也就是冻结数据快照（`analysis`）和发布报告（`delivered`），在下一步要跑的测试里。

## 第 3 步：用测试跑完整的一轮

[`tests/e2e/`](../../../tests/e2e/) 里的端到端测试就是可以直接运行的示例。每个测试都在一台模拟设备和一个假时钟上搭起真实的服务（见 [`e2e_support.py`](../../../tests/e2e/e2e_support.py)），然后分别扮演操作员、设备和流逝的时间。

运行测试需要先装开发依赖：

```sh
.venv/bin/python -m pip install -c constraints-tested.txt -e '.[dev]'
```

运行把一个问题走完整轮的那个测试：

```sh
.venv/bin/pytest tests/e2e/test_e2e_round.py -v
```

输出的结尾是这样的（耗时每次不同）：

```text
tests/e2e/test_e2e_round.py::test_open_question_goes_through_a_whole_round PASSED [100%]

============================== 1 passed in 1.07s ===============================
```

打开 [`test_e2e_round.py`](../../../tests/e2e/test_e2e_round.py)，对照下面的步骤读。这个测试：

1. 批准安全配置，创建项目，保存研究协议，创建轮次，此时轮次是 `designing`；
2. 提交运行单（`stage_review`），批准并启动阶段（`stage_running`）；
3. 等执行 Agent 把灯调到 60，然后以操作员身份接管（阶段变为 `manual`），手动把排风调到 55，再交还，并把这处差异登记为一次人工干预；
4. 让阶段跑到结束（`data_verification`）；
5. 冻结一份数据快照并校验（`analysis`）；
6. 用四条人工测量数据算出配对区组估计，把这次分析判定为 `confirmatory`，得到的结论是 `uncertain`，因为两个区组太少，达不到显著性水平；
7. 发布报告，轮次变为 `delivered`。

## 第 4 步：看一次接管和一次重启

`tests/e2e/` 里的每个文件各演示系统的一部分。

| 文件 | 演示什么 |
| --- | --- |
| [`test_e2e_round.py`](../../../tests/e2e/test_e2e_round.py) | 一个问题走完整轮，中间有一次人工接管 |
| [`test_e2e_agents.py`](../../../tests/e2e/test_e2e_agents.py) | 用脚本化的客户端驱动三个模型角色，不联网，不需要密钥：编排 Agent 派发任务，计划 Agent 的草稿停在待审，研究 Agent 冻结数据并发布报告。还包括：每次模型调用都失败时阶段照样跑完；计划 Agent 无法批准或启动任何东西。 |
| [`test_e2e_interventions.py`](../../../tests/e2e/test_e2e_interventions.py) | 一次接管会记入项目档案和冻结的快照，而且只记一次 |
| [`test_e2e_runtime.py`](../../../tests/e2e/test_e2e_runtime.py) | 没有模型客户端时阶段照常执行；重启；本机不是已登记的写入主机；tick 的某一步出错后转成告警 |
| [`test_e2e_reviewed.py`](../../../tests/e2e/test_e2e_reviewed.py) | 各种故障路径：采集过期、备份、心跳失败、写入应答丢失导致阶段暂停、恢复编号加一后审批和会话全部失效 |
| [`test_e2e_assembly.py`](../../../tests/e2e/test_e2e_assembly.py) | `build_runtime` 装配出了什么：每个服务一个数据库文件、主机 ID、沙箱、tick 各步骤的顺序、每天一份日报 |
| [`test_e2e_cli.py`](../../../tests/e2e/test_e2e_cli.py) | DiAGRI 的几个子命令：`operator add`、`host register`、`recovery bump`、`simulate` |

接下来建议运行并阅读这两个测试：

```sh
.venv/bin/pytest "tests/e2e/test_e2e_interventions.py::test_takeover_is_in_the_archive_and_in_the_frozen_snapshot" -v
.venv/bin/pytest "tests/e2e/test_e2e_runtime.py::test_restart_enters_recovery_check_then_the_operator_resumes" -v
```

第一个测试接管一个正在执行的阶段，再交还，然后在项目档案和快照文件 `interventions.jsonl` 里都找到了这次接管。第二个测试在阶段执行到一半时停掉运行时，再用同一份数据新建一个。阶段恢复后处于 `recovery_check`，没有任何写入权；过一拍后变为 `paused`；只有操作员确认续跑，它才重新执行。

运行整个目录只需要几秒：

```sh
.venv/bin/pytest tests/e2e -q
```

## 这里没有展示的东西

- 真实设备。时序、蓝牙中断和断电在这里都没有模拟。
- 真实模型。测试里的模型角色是照脚本作答的（见 [`sim/llm.py`](../../../src/growbridge/sim/llm.py)）。
- 通知。`simulate` 运行时没有任何渠道，测试用的是假渠道。
- 常驻服务本身。本页的任何操作都没有启动 `growbridge serve` 和它的后台循环。

## 接下来读什么

- [工作流与状态机](Workflow-and-State-Machines.md)：你刚才看到的状态 `designing`、`stage_review`、`stage_running`、`data_verification`、`analysis`、`delivered`。
- [人工接管、灌溉与交还](Manual-Takeover-and-Irrigation.md)：接管测试里做的那些事。
- [启用 DiAGRI](Enable-DiAGRI.md)：在真实帐篷上打开这个模式。

## 另见

- [项目概览](Overview.md)
- [科研方法](Research-Methodology.md)：测试里的结论为什么是 `uncertain`。
- [开发环境、测试与 CI](Development-Setup-Testing-and-CI.md)
- [术语表](Glossary.md)
