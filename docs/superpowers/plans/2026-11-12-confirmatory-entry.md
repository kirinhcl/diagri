# 确认性结论的入口：实施计划

**目标：** 让一轮研究能在 DiAGRI 模式下真正得出确认性结论：操作员在看到数据之前冻结分析脚本，数据冻结后由操作员触发那唯一一次运行，研究 Agent 发布的报告据此标为确认性。同时修复一个安全问题：沙箱运行会卡住事件循环。

**现状（2026-11-12，`main` = `5fb6c15`）：**

- `research/analysis.py` 的 `ConfirmatoryRunner` 已有 `freeze_analysis`（按协议版本登记脚本哈希）、`run`（每份快照只运行一次，失败也算用掉）和 `completed`，但 `src/` 里没有任何调用方。
- `freeze_analysis` 只存哈希，不存脚本原文，`run` 要调用方再提供脚本文件。冻结时间没有限制。
- `agents/handlers_report.py` 的 `_decide`：报告引用的快照只要有一份没有成功的确认性运行，标签就被压到探索性（`NO_RUN_NOTE`）。所以现在发布的报告永远不是确认性的。
- 工具处理函数在 `agents/tools.py:165` 同步调用。`agents/handlers_researcher.py` 的 `_local_analysis` 直接调用 `deps.sandbox.run`，内部是 `subprocess.run(timeout=…)`，最长 600 秒。`serve` 的 1 Hz 执行循环（`cli.py` 的 `_tick_forever`）与模型角色（`_agents_forever`）在同一个事件循环里，所以分析期间保护规则和关泵联锁都会停摆。

**全局约束：**

- 先写失败的测试，再实现。测试只用 `src/growbridge/sim/` 里的模拟对象，不联网，不接设备，不用真实凭据。
- 文件不超过 800 行，函数不超过 50 行。`workflow/service.py` 现为 719 行，`runtime.py` 为 744 行。
- 服务之间只通过 `ports.py` 的协议和 `archive/models.py` 的模型交互，`runtime.py` 负责装配。工作台可以使用 `WorkflowService` 和研究模块的类（现有的工作台已经这样做）。
- 授权只来自服务端（会话、入口、近期重新认证），绝不来自请求体或模型输出里的字段。
- 新的数据库表只能追加迁移步骤（`Database.migrate` 只追加），不改已有步骤。
- 原始数据不可变；冻结的脚本和运行记录只增不改。
- 不提交、不推送、不切换分支。工作分支：`feat/confirmatory-entry`。

---

## 任务 A：沙箱运行不得阻塞事件循环（安全修复）

**文件：** `src/growbridge/agents/handlers_researcher.py`，新测试放在 `tests/dispatch/` 或 `tests/e2e/`。

- `_local_analysis` 改为异步，用 `await asyncio.to_thread(deps.sandbox.run, …)` 运行沙箱。快照校验、范围检查等其余步骤仍在事件循环线程里做，并且在沙箱启动之前完成。
- 检查 `src/` 里是否还有其他在事件循环中同步调用 `sandbox.run`、`subprocess.run` 或其他长时间阻塞操作的地方，一并列出；属于本任务文件范围的就修。
- **测试：** 用一个会阻塞到 `threading.Event` 被放行的假沙箱，让研究 Agent 的 `run_local_analysis` 正在运行；在此期间执行循环（`Runtime.tick()` 或 `serve` 用的循环）必须继续推进，比如在分析未结束时完成至少 3 次 tick。修复前这个测试必须失败（会卡住或超时，测试要设置自身的超时，不得把整个测试套件挂死）。

## 任务 B：确认性分析的入口

### B1. 冻结脚本并保存原文

**文件：** `src/growbridge/research/analysis.py`，`tests/research/`。

- 追加迁移步骤：
  - `research_script_files(sha256 TEXT PRIMARY KEY, content BLOB NOT NULL)`：按哈希保存脚本原文。
  - 给 `research_scripts` 增加 `frozen_by TEXT`，给 `research_runs` 增加 `started_by TEXT`（用 `ALTER TABLE … ADD COLUMN`）。
- `freeze_analysis(protocol, script: bytes, actor_id: str) -> str`：在原有检查（与协议声明的哈希一致；同一版本只能冻结一个脚本，重复冻结同一脚本是幂等的）之外，保存原文、记录冻结人。脚本最长 `MAX_SCRIPT_CHARS`（20 000 字符，按 UTF-8 文本校验），不是合法 UTF-8 的拒绝（`param`）。
- 新增 `frozen_script(protocol) -> tuple[str, bytes] | None` 和 `status(snapshot_id, protocol) -> Literal["none", "running", "succeeded", "failed"]`（`running`：已登记开始、尚未写结束时间）。
- 新增 `async run_frozen(protocol, snapshot, snapshot_dir, actor_id) -> AnalysisRun`：脚本取自 `research_script_files`；登记（`_claim`）和写结果在事件循环线程里做，只有 `sandbox.run` 放进 `asyncio.to_thread`。沙箱拒绝运行（`Denied`）时删掉登记，与现有 `run` 一致。保留现有 `run` 以兼容测试，或改为内部复用同一逻辑，由实现者决定。

### B2. "看到数据之前才能冻结"

**文件：** `src/growbridge/workflow/service.py`（或 `workflow/store.py`），`tests/workflow/`。

- 新增只读查询：这个协议 ID 和版本下，是否有任何轮次的任何阶段已经开始过（`started_at` 不为空）。
- 冻结路由在已经开始过时拒绝，`Denied("state", …)`，说明原因：确认性分析必须在看到结局数据之前冻结（架构文档 §6.5）。

### B3. 工作台路由（仅操作员）

**文件：** 新建 `src/growbridge/workbench/analysis.py`，在 `workbench/api.py` 中挂载（仿照 `add_round_routes`），`runtime.py` 把 `runner`、`holdout` 和 `archive` 传进来。没有 `runner` 时不挂载这些路由。测试放在 `tests/workbench/`。

| 方法与路径 | 请求体或参数 | 作用 | 近期重新认证 |
| --- | --- | --- | --- |
| `POST /wb/protocols/{protocol_id}/analysis` | `project_id`、`script`（文本）、可选 `request_id` | 冻结该项目下这个协议的最新版本的分析脚本；返回 `protocol_id`、`version`、`script_sha256`、`frozen_at` | 需要 |
| `GET /wb/protocols/{protocol_id}/analysis?project_id=…` | | 冻结状态（哈希、时间、冻结人，不返回脚本原文以外的秘密）以及每份快照的运行状态 | 不需要 |
| `POST /wb/analysis/runs` | `project_id`、`protocol_id`、`snapshot_id` | 用冻结的脚本对这份快照运行一次；返回 `run_id`、`status`、`exit_code`、`timed_out`，以及截断到 4 000 字符的 `stdout`、`stderr` | 需要 |

运行路由的检查顺序，任何一条不满足都在启动沙箱之前拒绝：

1. 协议属于该项目（`latest_protocol(protocol_id, project_id)`），且已冻结脚本（否则 `state`）。
2. 快照存在，并且它的实验属于一个按这个协议 ID 和版本运行的轮次中的阶段（否则 `scope`）。
3. 快照完整并通过逐文件哈希校验（`snapshot_incomplete`，由 `_check_snapshot` 做）。
4. 配置了留出集登记时，快照里的测量全部通过 `development_filter(project_id)`，否则拒绝（`scope`）：留出数据不进入任何分析。把这项检查放在 `research/holdout.py` 里作为可复用函数；`agents/handlers_common.py` 现有的同类检查改为调用它，保持一处实现。
5. 已经运行过的快照拒绝（`already_run`）。

### B4. 发布报告时的保护

**文件：** `src/growbridge/agents/handlers_report.py`，`tests/dispatch/`。

- 协议版本已冻结脚本、而报告引用的某份快照运行状态为 `none` 或 `running` 时，`publish_research_report` 拒绝：`Denied("state", "快照 … 的预注册确认性运行还没有完成；由操作员通过 POST /wb/analysis/runs 启动")`。目的是不让轮次在预注册分析运行之前，被不知不觉地以探索性结论交付。
- 状态为 `failed` 时照常发布，标签按现有规则压到探索性。
- 协议没有冻结脚本时行为不变。
- **端到端测试**（`tests/e2e/` 新文件）：在模拟 AC5 和脚本化模型上，从冻结脚本、阶段执行、冻结数据、操作员触发运行，到研究 Agent 发布，最后得到一份标签为 `confirmatory` 的报告。需要 `sandbox-exec` 的部分在非 macOS 上跳过；如果能用一个确定性的假沙箱完成整个流程，就不要依赖真实沙箱。

### B5. Wiki（中英两版同时改）

- `Run-a-Research-Round.md`：在分析一步加上冻结脚本和触发运行的操作步骤，包括请求示例。
- `API-Reference.md`：路由表加上三条新路由。
- `Research-Methodology.md`：确认性关卡一节写明现在可以从工作台走通，以及"冻结必须早于任何阶段开始"。
- `Denial-Codes-and-Events.md`：新的拒绝场景。
- `Status-and-Known-Limitations.md`：删掉"确认性分析没有入口"这一条；保留"每份快照各运行一次，而不是架构文档所说的整个系列一次"这一差异。
- 用词：项目叫 DiAGRI，模式叫 DiAGRI 模式；不要写 "Auto Research"。

## 完成标准

- 新测试先失败后通过；`.venv/bin/python -m pytest -q` 全部通过（开始前 1641 个）；`ruff check` 和 `ruff format --check`（`src tests scripts`）干净；`pytest -q tests/docs` 通过。
- 交回：每项改动的文件和行号、新测试名称、全量测试数、没能验证的地方。

## 有意不做

- 留出集登记（`HoldoutRegistry.register`）和证据卡录入的工作台入口：属于模型评估和计划依据，下一步单独做。
- 架构文档说确认性运行应覆盖整个系列一次，代码是每份快照一次；这次不改。
- 研究 Agent 起草确认性脚本的工具：这次由操作员提交脚本文本。
