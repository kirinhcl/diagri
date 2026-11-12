# 心跳与计算服务接线：实施计划

**目标：** 让 `growbridge serve` 在 DiAGRI 模式下真正发出外部心跳，并在配置齐全时启动计算服务：它能通过 CSC 的 FirecREST 接口向 Roihu 提交、跟踪、取回和清理作业，操作员也能录入项目余额和任务的计算预算。

**现状（2026-11-12，`main` = `f5a14fb`）：**

- 心跳已经实现，只是没有接上：
  - `observer/channels.py` 的 `HeartbeatChannel(env)` 在发送时按环境变量名读取地址，`ping()` 请求该地址，`fail()` 请求该地址加 `/fail`。
  - `observer/health.py` 的 `ExternalMonitor(host, run, clock)` 管"主机"和"运行"两路心跳。
  - `runtime.py` 的 `build_runtime(..., heartbeats=(host, run))` 已经预留参数；`_beat_due` 让心跳每 `HEARTBEAT_SECONDS`（60 秒）发一次，运行健康状态变化时立即发。
  - 但 `cli.py` 的 `_serve_auto_research` 调用 `build_runtime(settings)` 时没有传 `heartbeats`，所以 `Runtime.monitor` 为 `None`。
- 计算服务：
  - `compute/service.py` 的 `ComputeService(db, clock, backend, templates, members, service_cpu_cap, service_storage_cap)` 已实现。
  - `runtime.py` 的 `_compute` 只在传入后端时构造它，模板和成员都是空的；`serve` 没有传后端。
  - `ComputeService._check_caps` 每次提交前要求两样东西：这个任务的预算（`set_task_budget`，`src/` 里没有调用方），以及一条项目余额记录（`refresh_balance` → `backend.balance()`）。缺任何一样就以 `quota` 拒绝。
  - `compute/firecrest.py` 的 `FirecrestBackend` 只检查依赖和环境变量（`FIRECREST_URL`、`FIRECREST_TOKEN_URL`、`FIRECREST_CLIENT_ID`、`FIRECREST_CLIENT_SECRET`、`FIRECREST_SYSTEM`），8 个远端操作全部抛 `NotImplementedError`。
- `runtime.py` 现为 752 行，接近 800 行上限。新的接线代码一律放进新模块。

**已查实的外部事实（2026-11-12）：**

- CSC 为 Roihu 提供 FirecREST HPC API。
  - 地址：`https://api.roihu.csc.fi/v1`，基于 FirecREST v2。
  - 子系统（即 `system_name`）：`cpu` 和 `gpu`。
  - Python 客户端只支持 pyfirecrest 的 v2 API。
  - 来源：[docs.csc.fi/computing/firecrest/](https://docs.csc.fi/computing/firecrest/)、[connecting](https://docs.csc.fi/computing/firecrest/connecting/)、[pyfirecrest](https://docs.csc.fi/computing/firecrest/pyfirecrest/)。
- 认证：
  - 无人值守的程序用**机器人账户**：OAuth 2.0 客户端凭据模式，客户端 ID 是机器人账户名，密钥是它的密码，令牌地址是 `https://user-auth.csc.fi/idp/profile/oidc/token`，scope 为 `openid`。
  - pyfirecrest 的写法是 `firecrest.ClientCredentialsAuth(client_id=..., client_secret=..., token_uri=...)`。
  - 个人访问令牌只有 24 小时有效期，不适合常驻进程。
- pyfirecrest v2 异步客户端（[reference_async_v2](https://pyfirecrest.readthedocs.io/en/stable/reference_async_v2.html)）的签名：
  - `firecrest.v2.AsyncFirecrest(firecrest_url, authorization, verify=True)`
  - `submit(system_name, working_dir, script_str=None, script_local_path=None, script_remote_path=None, env_vars=None, account=None, partition=None, reservation=None) -> dict`
  - `job_info(system_name, jobid=None, allusers=False, account=None, name=None, time_window=None) -> list`
  - `cancel_job(system_name, jobid) -> dict`
  - `upload(system_name, local_file, directory, filename, account=None, blocking=True, transfer_method='s3')`
  - `download(system_name, source_path, target_path, account=None, blocking=True, transfer_method='s3')`
  - `checksum(system_name, path) -> dict`
  - `list_files(system_name, path, show_hidden=False, recursive=False, ...) -> list[dict]`
  - `mkdir(system_name, path, create_parents=False) -> dict`
  - `rm(system_name, path, account=None, blocking=True, timeout=None)`
  - `userinfo(system_name)`
- 返回结构，取自 Roihu 的 [OpenAPI 规范](https://api.roihu.csc.fi/v1/openapi.json)：
  - 提交返回 `{"jobId": ...}`。
  - 作业信息是 `JobModel` 的列表，字段有 `jobId`、`name`、`status`（含 `state`、`stateReason`、`exitCode`）、`time`（含 `elapsed`、`start`、`end`、`limit`）、`allocationNodes`、`workingDirectory`。规范没有列出 `state` 的取值，用的是 Slurm 的状态名。
  - 校验和是 `{"algorithm": "SHA-256", "checksum": "..."}`。HTTP 响应把它包在 `output` 里；pyfirecrest 返回哪一层，文档没写，两种都要能处理。
  - **接口没有 CPU 用量字段，也没有查询项目计费余额的接口。**

**全局约束：**

- 先写失败的测试，再实现。测试不联网、不接设备、不用真实凭据；CI 只装 `dev` 依赖，所以测试不能要求安装 pyfirecrest。
- 凭据和心跳地址只从环境变量读，绝不写进配置文件或日志，`repr` 里也不能出现。
- 文件不超过 800 行，函数不超过 50 行。
- 只追加数据库迁移步骤；授权只来自服务端。
- 不提交、不推送、不切换分支。工作分支：`feat/heartbeat-compute`。

---

## 任务 H：接上心跳

**文件：** 新模块（例如 `src/growbridge/runtime_wiring.py`，由实现者命名），`cli.py` 的 `_serve_auto_research`，`observer/` 里需要的地方；测试放在 `tests/observer/` 或 `tests/e2e/`。

- 两个环境变量：`GROWBRIDGE_HEARTBEAT_HOST_URL`（主机心跳）和 `GROWBRIDGE_HEARTBEAT_RUN_URL`（运行心跳）。先在代码里查有没有已定义的名称，有就沿用。
- `serve` 两个都配了才构造 `ExternalMonitor`。都没配时不发心跳，但发一条常驻告警说明外部监控还没接上，和 `notify_unconfigured` 的做法一致。只配了一个时，启动失败并给出清楚的错误：只监控一半会造成虚假的安心。
- 地址不出现在日志、告警文本和 `repr` 里。
- **测试：**
  - 两个都配时，心跳按间隔发出，走的是注入的假 HTTP 客户端。
  - 都没配时出现常驻告警，不发任何请求。
  - 只配一个时拒绝启动。
  - 运行健康状态变坏时发 `/fail`。

## 任务 C：接上计算服务

**文件：** `compute/firecrest.py`，新模块（例如 `src/growbridge/compute/wiring.py` 和 `src/growbridge/workbench/compute.py`），`config.py`，`cli.py`；测试放在 `tests/compute/`、`tests/workbench/`。

### C1. 实现 `FirecrestBackend`

- 构造时接受一个可注入的客户端（测试里传假的），默认才用 `firecrest.v2.AsyncFirecrest` 加 `firecrest.ClientCredentialsAuth`，并在那时才导入 pyfirecrest。
- 环境变量：
  - 保留现有 5 个；
  - 新增 `FIRECREST_ACCOUNT`（CSC 项目，如 `project_2001234`）和 `FIRECREST_WORKDIR`（远端工作目录的根，如 `/scratch/project_2001234/diagri`）。
  - `FIRECREST_SYSTEM` 只接受 `cpu` 或 `gpu`。
- 每个作业在 `FIRECREST_WORKDIR/<job_name>/` 下独立一个目录。
  - **`submit`**：建目录、上传输入、以 `script_str` 提交模板脚本，并传入 `account`。作业参数一律通过 `env_vars` 传给脚本，不拼接进脚本文本，避免注入。返回 `jobId`。
  - **`find_by_name`**：用 `job_info(name=...)` 查找。
  - **`status`**：用 `job_info(jobid=...)` 查询，把 Slurm 状态映射到 `queued`、`running`、`completed`、`failed`、`cancelled`。不认识的状态不能当成完成，要抛 `BackendError` 并带上原始状态名。
  - **`fetch`**：列出作业输出目录，逐个下载，并用远端 `checksum` 返回"文件名 → SHA-256"。
  - **`cleanup`**：删除这个作业的目录。
  - **`cancel`**：用 `cancel_job`。
- **用量：** 接口不报告 CPU 用量，所以一个作业按模板的 `max_cpu_hours` 全额计账，宁多不少。实现者查清 `ComputeService` 结算时怎样使用 `RemoteJob.cpu_hours_used`，并说明选择。
- **余额：** `balance()` 抛出 `BackendUnavailable`，说明 FirecREST 不提供计费余额。余额改由操作员录入（C2）。
- **输入：** 实现者查清 `ComputeService` 交给后端的 `inputs` 是什么（目前是快照内的相对路径），以及本地文件从哪里来。如果服务没有把本地根目录传给后端，就在服务里补上，并说明。

### C2. 操作员录入余额和任务预算

**文件：** 新建 `workbench/compute.py` 并在 `workbench/api.py` 挂载，配合 `ComputeService` 的少量新方法；没有计算服务时不挂载。

| 方法与路径 | 请求体 | 作用 | 近期重新认证 |
| --- | --- | --- | --- |
| `POST /wb/compute/balance` | `cpu_hours`（有限、非负）、可选 `note` | 记录操作员从 MyCSC 读到的项目剩余 CPU 小时，连同录入人 | 需要 |
| `POST /wb/compute/tasks/{task_id}/budget` | `cpu_hours`、`storage_gb`（有限、非负） | 设定一个研究任务的计算预算；任务必须存在 | 需要 |
| `GET /wb/compute` | | 当前余额（录入时间和录入人）、各任务预算与已用量、进行中的作业 | 不需要 |

- `ComputeService.refresh_balance` 遇到 `BackendUnavailable` 时保留最近一次操作员录入的余额，不能当作余额为零，也不能当作无限。
- 余额记录只追加；如需记录录入人，通过追加迁移步骤加列。

### C3. 模板与成员

- `config.py` 新增：
  - `compute_templates_dir`：一个目录，里面每个 JSON 文件就是一个 `JobTemplate`，按模型校验；
  - `compute_member`：研究 Agent 提交时对应的 CSC 账户名。
- 默认都不设置，即不提供任何模板。
- 启动时校验每个模板，坏的模板让启动失败并指出文件名。日志记录每个模板的 `id`、`version` 和文件的 SHA-256，便于追溯。

### C4. `serve` 接线

- 只有 FirecREST 的 7 个环境变量和 `compute_templates_dir` 都齐了，才构造 `FirecrestBackend` 并传给 `build_runtime`。否则不启动计算服务，计算相关的工具照旧返回 `unavailable`。
- 只配了一部分时，日志里说明缺了哪些（不打印取值）。

## 任务 W：Wiki（中英两版同时改）

由完成任务 H、C 的人各自更新：

- `Configuration-Reference.md`：新环境变量和配置项。
- `Notifications-Reports-and-Backup.md`：心跳怎样配置、何时发、缺配置时的告警。
- `API-Reference.md`：新路由。
- `Enable-DiAGRI.md`：配置心跳和计算服务的步骤。
- `Status-and-Known-Limitations.md`：心跳和计算服务改为"已接上，但没有对真实服务验证"；写明 CPU 用量按预留全额计，余额由人工录入。
- `Denial-Codes-and-Events.md`：新的拒绝场景。
- 用词：项目叫 DiAGRI，模式叫 DiAGRI 模式；不要写 "Auto Research"。

## 完成标准

- 新测试先失败后通过；`.venv/bin/python -m pytest -q` 全部通过（开始前 1945 个）；`ruff check` 和 `ruff format --check`（`src tests scripts`）干净；`pytest -q tests/docs` 通过。
- 交回：每项改动的文件和行号、新测试名称、全量测试数、没能验证的地方，以及计划与代码不一致之处。

## 有意不做

- 真实连接 CSC Roihu：需要机器人账户凭据，这次只对假客户端测试。
- 从 CSC 自动读取计费余额：接口不提供。
- 默认作业模板：模板是要审核的作业脚本，由使用者自己提供。
