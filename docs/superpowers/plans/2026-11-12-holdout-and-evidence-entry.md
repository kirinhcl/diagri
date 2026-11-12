# 留出集与证据卡的入口：实施计划

**目标：** 让操作员能登记留出集、录入和核实证据卡，让计划 Agent 能查询和提议证据卡，并让操作员审阅运行单时看到每个设定值的证据状态。

**现状（2026-11-12，`main` = `3fbd32c`）：**

- `research/holdout.py` 的 `HoldoutRegistry.register(project_id, holdout_id, batch_ids, outcome_fields, development_batches)` 没有调用方。`development_batches` 是调用方自报的数量，没有核对；登记时也不检查这些批次是否已经有结局数据。登记后，`development_filter` 会立即把留出批次的结局测量挡在快照和模型工具之外（这部分已经接好）。
- `register_model` 和 `evaluate` 只是一道标签关卡，没有任何流程用留出数据给模型打分。
- `archive/store.py` 的 `Archive.add_evidence` 没有调用方。`EvidenceCard`（`archive/models.py`）字段为 `id`、`source_class`（`handbook`/`paper`/`local`）、`citation`、`claim`、`value`、`unit`、`verified`、`calibrated`。证据卡是全局的，不属于某个项目。
- `planning/validate.py` 的 `check_evidence` 会给出 `no_evidence`、`unverified_source`、`uncalibrated` 提示，但只在计划 Agent 的 `validate_run_sheet` 工具里运行。操作员审阅用的 `GET /wb/stages/{stage_id}/run-sheet`（`workbench/rounds.py` 的 `review_json`）看不到这些提示。
- 只有研究 Agent 有 `query_evidence`，计划 Agent 不能查询证据卡，也不能提议。

**全局约束：**

- 先写失败的测试，再实现。测试只用 `src/growbridge/sim/` 的模拟对象，不联网，不接设备，不用真实凭据。
- 文件不超过 800 行，函数不超过 50 行。`runtime.py` 现为 749 行，`workflow/service.py` 为 719 行，新代码尽量放进新模块。
- 授权只来自服务端：会话、入口、近期重新认证，以及模型运行时绑定的任务（`handlers_common.py` 的 `require_bound`）。绝不来自请求体或模型输出里的字段。
- 数据库只追加迁移步骤。原始记录和已登记的内容只增不改：核实是一条新的记录，不修改证据卡本身。
- 所有新路由沿用 `workbench/rounds.py` 和 `workbench/analysis.py` 的写法（`Operator` 与 `fresh` 依赖、`workbench/common.py` 的请求体、拒绝码与 HTTP 状态的对应）。
- 不提交、不推送、不切换分支。工作分支：`feat/holdout-evidence-entry`。

---

## 任务 A：留出集登记

**文件：** `src/growbridge/research/holdout.py`，新建 `src/growbridge/workbench/holdouts.py`，在 `workbench/api.py` 挂载，`runtime.py` 按需传入依赖；测试放在 `tests/research/`、`tests/workbench/`。

- `register` 改为接收明确的开发批次列表 `development_batch_ids`，不再接收数量：
  - 至少 `MIN_DEVELOPMENT_BATCHES`（2）个；
  - 与留出批次不重叠；
  - 批次和指标名都不能为空串，也不能重复。
  - 追加迁移步骤，保存开发批次和登记人（`registered_by`）。旧数据库里已有的登记，这两项为空。
- **登记必须早于结局数据：** 项目内任何实验里，只要已有一条人工测量的 `batch` 属于留出批次、`metric` 属于结局指标，就拒绝登记（`Denied("state", …)`），并说明原因：那些数据可能已经被看过。项目与实验的对应用工作流存储查。不在消息里引用任何测量值。
- 路由（仅操作员）：

| 方法与路径 | 请求体或参数 | 作用 | 近期重新认证 |
| --- | --- | --- | --- |
| `POST /wb/holdouts` | `project_id`、`batch_ids`、`development_batch_ids`、`outcome_fields` | 登记一个留出集，`holdout_id` 由服务端生成；返回登记内容 | 需要 |
| `GET /wb/holdouts?project_id=…` | | 列出该项目的留出集，以及每个留出集的读取记录（`reads`） | 不需要 |

- 项目必须存在，否则拒绝（`scope`）。
- **有意不做：** 登记模型（`register_model`）和用留出数据给模型打分。现在没有任何流程能在不把留出结局暴露给模型的前提下计算预测得分，这需要单独设计。Wiki 里写明这一点。

## 任务 B：证据卡

**文件：** `src/growbridge/archive/store.py`，新建 `src/growbridge/workbench/evidence.py`，`workbench/api.py` 挂载，`workbench/rounds.py`（审阅），`src/growbridge/agents/handlers_planner.py` 与 `agents/tools.py`（计划 Agent 的工具）；测试放在 `tests/archive/`、`tests/workbench/`、`tests/dispatch/`。

- **来源与核实只追加：**
  - 证据卡的来源（谁录入或提议：操作员 ID，或 `model:planner` 加任务 ID）存在单独的列或表里，通过追加迁移步骤加入。
  - 核实是一张新表里的一条记录（卡 ID、核实人、时间、备注）。
  - `Archive.evidence()` 返回的卡，只要有核实记录，`verified` 就为真，以便 `check_evidence` 直接使用。卡片原文永不改动。
- **操作员录入：** `POST /wb/evidence`（仅操作员，不要求重新认证）。
  - 请求体为 `source_class`、`citation`（必填，非空，长度有上限）、`claim`、`value`（如有，必须是有限数）、`unit`、`calibrated`。
  - 卡 ID 由服务端生成。
  - 操作员录入即视为由本人核实，同时写入一条核实记录。
- **操作员核实：** `POST /wb/evidence/{card_id}/verify`（仅操作员），可带备注。对同一张卡重复核实是幂等的，不重复写记录。
- **列表：** `GET /wb/evidence`（仅操作员）。列出全部卡片，附带来源、是否已核实、核实人和核实时间。
- **计划 Agent 的工具：**
  - 加入 `query_evidence`，复用研究 Agent 的实现。
  - 新增 `propose_evidence_card`：需要绑定的任务；字段同上。无论输入如何，卡片都以"未核实"保存，来源记为计划 Agent 和任务 ID。返回卡 ID，供运行单的 `evidence` 字段引用。
  - 研究 Agent 和编排 Agent 不获得提议工具。
  - 两个工具都要进入 `ROLE_TOOLS`，并检查 `build_toolset` 的角色划分测试。
- **审阅时可见：**
  - `GET /wb/stages/{stage_id}/run-sheet` 返回的 `findings` 里包含 `check_evidence` 的提示，所用证据卡要计入核实记录。
  - 这些提示都不阻塞审批，保持现状。
  - 研究或计划 Agent 引用了不存在的卡，同样显示为 `no_evidence`。

## 任务 C：Wiki（中英两版同时改）

由完成任务 A、B 的人各自更新与自己改动相关的页面：

- `API-Reference.md`：新路由，以及计划 Agent 的两个工具。
- `Run-a-Research-Round.md`：登记留出集（在开发开始之前），以及审阅时查看证据提示、核实证据卡。
- `Research-Methodology.md`：留出集一节，写明"登记必须早于结局数据"和"目前没有用留出数据给模型打分的流程"。
- `Data-Archive-and-Traceability.md`：证据卡的来源与核实记录。
- `Status-and-Known-Limitations.md`：删去"留出集登记、证据卡录入没有入口"；加上"留出集还不能用于模型评估"。
- `Denial-Codes-and-Events.md`：新的拒绝场景。
- 用词：项目叫 DiAGRI，模式叫 DiAGRI 模式；不要写 "Auto Research"。

## 完成标准

- 新测试先失败后通过；`.venv/bin/python -m pytest -q` 全部通过（开始前 1773 个）；`ruff check` 和 `ruff format --check`（`src tests scripts`）干净；`pytest -q tests/docs` 通过。
- 交回：每项改动的文件和行号、新测试名称、全量测试数、没能验证的地方。
