# 多用户与温室锁定 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 DiAGRI 工作台加上用户角色、12 个温室的登记与原子锁定、项目所有者，以及"只看自己的"可见性，全部由服务端强制。

**Architecture:** 新逻辑放新文件：`workflow/locks.py`（锁）、`workflow/access.py`（权限与可见性规则）、`workbench/greenhouses.py` 与 `workbench/admin.py`（新路由）、`workbench/visibility.py`（读路由登记表）、`runtime_access.py`（装配）。现有文件只加接入点。整层由 `Settings.multi_user` 开关控制，默认关，现有测试与 `growbridge simulate` 行为不变；开启时 `Access` 注入 `WorkflowService` 与工作台。

**Tech Stack:** Python 3.11+ / FastAPI / pydantic v2 / SQLite（`archive/db.py` 的 `Database.migrate`）；控制台为原生 ES 模块，Node 20 `node --test`。

**Spec:** `docs/superpowers/specs/2026-11-16-multi-user-locks-design.md`

## Global Constraints

- 只在 `settings.auto_research and settings.multi_user` 时生效；`multi_user` 默认 `False`（实现者判断：对他仓库保持向后兼容，开关写进配置参考与 PR 说明）。
- 锁表、角色列、项目 `owner` 列都在工作流库 `dbs["workflow"]`；迁移只能在各 `STEPS` 末尾追加。
- 角色只有 `"user"` / `"admin"`；锁事件 `action` 只有 `"lock"` / `"release"` / `"force_release"`。
- 未登记归属的告警 `kind` 只给管理员；看不到的对象按"不存在"回答，用现有的 `Denied("state", "unknown …")`。
- 新拒绝码：`lock_taken`（409）、`not_owner`（403）、`not_lock_holder`（403）、`admin_only`（403）、`greenhouse_busy`（409）。在 `api.py` 的 `STATUS_BY_CODE` 登记 409 的两个，并加进控制台 `i18n/codes.*.js` 与 `tests/web/fixtures/known-codes.json`。
- 管理员写操作例外只有：暂停、停止任何阶段；强制释放；用户管理；项目转移；CSC 余额与结算。管理员不能替别人审批、启动、续跑、接管。
- 只检查 `operator` 身份；`model` / `workflow` / `observer` 身份不受所有者与锁检查约束。
- 用户全局代码限制：文件 ≤ 800 行，函数 ≤ 30 行，嵌套 ≤ 3 层。`runtime.py` 已 797 行、`workflow/service.py` 754 行：装配写进 `runtime_access.py`，`service.py` 的每个检查点只加一行调用。
- 门禁：`ruff check -q && ruff format --check -q && pytest -q && node --test tests/web/*.test.mjs`，不接管道。

## Review Focus

1. **别人的 id 直接拼进 URL**：用户 B 用 A 的 `stage_id` / `round_id` / `project_id` / `request_id` 访问任何路由，应得到与不存在相同的回答，而不是 403 透露其存在。→ Task 8 的 `test_b_cannot_see_a` 逐路由断言。
2. **收件箱上限挤掉自己的条目**：别人有 60 条告警时，自己的 1 条仍应出现。→ Task 9 `test_inbox_cap_applies_after_filter`。
3. **锁定请求里重复或未知的温室编号**：`["gh-01","gh-01"]` 或 `["gh-99"]` 应整组拒绝，库里无残留。→ Task 3 `test_lock_rejects_duplicates_and_unknown`。
4. **停用用户仍持有的会话**：停用后其已登录浏览器的下一次请求应被拒。→ Task 2 `test_disabled_user_session_ends`。
5. **旧库升级**：已有项目（`owner` 为空）开启多用户后只对管理员可见，且任何人都不能动其阶段，直到被转移。→ Task 4 `test_legacy_projects_go_to_admin_only` 与 Task 10 `test_transfer_then_owner_can_act`。

---

### Task 1: 温室登记与开关（配置）

**Files:**
- Modify: `src/growbridge/config.py`
- Test: `tests/test_config_greenhouses.py`

**Interfaces:**
- Produces: `class Greenhouse(BaseModel)`: `id: str`（`^[a-z0-9][a-z0-9-]{0,31}$`）、`name: str`（1..64）、`device_id: str`；`Settings.multi_user: bool = False`、`Settings.greenhouses: list[Greenhouse] = []`；`Settings.greenhouse_registry() -> tuple[Greenhouse, ...]`（列表为空时返回 `(Greenhouse(id="gh-01", name="Greenhouse 1", device_id=self.device),)`）。

- [ ] **Step 1: 写失败测试** `test_default_registry_is_the_local_device`（空列表 → 单个 `gh-01`，`device_id == settings.device`）、`test_ids_and_devices_unique`（重复 `id` 或重复 `device_id` → `ValidationError`）、`test_local_device_must_be_registered`（非空列表不含 `settings.device` → `ValidationError`）、`test_multi_user_defaults_off`。
- [ ] **Step 2: 运行确认失败** `pytest tests/test_config_greenhouses.py -q` → 4 failed。
- [ ] **Step 3: 实现**，校验放在 `Settings` 已有 `model_validator(mode="after")` 风格的新校验器里。
- [ ] **Step 4: 运行确认通过**，再跑 `pytest tests -q -k config` 确认旧配置测试不受影响。
- [ ] **Step 5: 提交** `feat: register greenhouses and a multi_user switch in the settings`

### Task 2: 角色与停用（账号）

**Files:**
- Modify: `src/growbridge/workbench/auth.py`（`STEPS` 追加两条 `ALTER TABLE operators ADD COLUMN role TEXT NOT NULL DEFAULT 'user'`、`... disabled_at REAL`）、`src/growbridge/ports.py`（`Actor.role: Literal["user", "admin"] | None = None`）、`src/growbridge/cli.py`（`operator add --admin`）
- Test: `tests/workbench/test_workbench_accounts.py`

**Interfaces:**
- Produces: `Operators.add(name, secret, role: Literal["user","admin"] = "user")`；`Operators.role(name) -> str | None`；`Operators.disable(name) -> None`（置 `disabled_at`，删其全部会话；未知名字 `ValueError`）；`Operators.reset_secret(name, secret) -> None`（删其全部会话）；`Operators.listing() -> list[dict]`（`name, role, created_at, disabled_at`，不含哈希）；`Operators.actor()` 返回的 `Actor.role` 为该用户角色；`_verify` 对停用用户按"口令错误"处理（同样耗时、同一拒绝码）。

- [ ] **Step 1: 写失败测试** `test_add_admin_role`、`test_default_role_is_user`、`test_disabled_cannot_log_in`（`Denied("session")`）、`test_disabled_user_session_ends`（已有会话 `actor()` → `Denied("session")`）、`test_reset_secret_ends_sessions`、`test_listing_has_no_secrets`（返回键集合恰为上述四个）、`test_cli_add_admin`（调用 `_add_operator` 带 `--admin` 后 `role == "admin"`；口令读取按现有 CLI 测试的方式打桩）。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现。**
- [ ] **Step 4: 运行通过**，并跑 `pytest tests/workbench -q` 确认现有登录测试不变。
- [ ] **Step 5: 提交** `feat: operator roles, disabling and secret reset`

### Task 3: 温室锁

**Files:**
- Create: `src/growbridge/workflow/locks.py`
- Modify: `src/growbridge/workflow/store.py`（新增 `device_unfinished`）
- Test: `tests/workflow/test_workflow_locks.py`

**Interfaces:**
- Consumes: `Settings.greenhouse_registry()`（Task 1）。
- Produces:
  - `WorkflowStore.device_unfinished(device_id: str) -> bool`：该设备上存在状态不在 `(ENDED, STOPPED)` 的阶段。
  - `class GreenhouseLocks(db: Database, clock: Clock, registry: Sequence[Greenhouse], unfinished: Callable[[str], bool])`，命名空间 `"greenhouse_locks"`，表见设计 §5.3。
  - `lock(holder: str, ids: Sequence[str]) -> tuple[str, ...]`：一个事务内全锁或全不锁；有被占用 → `Denied("lock_taken", "…")`，消息列出被占用的编号；重复或未知编号 → `Denied("state", …)`。
  - `release(holder: str, greenhouse_id: str) -> None`：不是自己的锁 → `Denied("not_lock_holder")`；`unfinished(device_id)` → `Denied("greenhouse_busy")`。
  - `force_release(greenhouse_id: str, actor: str, note: str) -> None`：同样受 `greenhouse_busy` 约束；记 `force_release` 事件。
  - `holder_of_device(device_id: str) -> str | None`；`held_by(holder: str) -> tuple[str, ...]`；`overview() -> list[dict]`（`id, name, device_id, holder, locked_at`）；`events(limit: int = 100) -> list[dict]`。

- [ ] **Step 1: 写失败测试** `test_lock_is_all_or_nothing`（B 先锁 gh-02，A 锁 [gh-01, gh-02] → `lock_taken`，gh-01 仍空闲）、`test_lock_rejects_duplicates_and_unknown`、`test_two_threads_one_winner`（两个线程同时锁 gh-01，恰一个成功）、`test_release_refused_while_stage_unfinished`（`unfinished` 返回 True → `greenhouse_busy`，`force_release` 同样）、`test_release_only_own`、`test_events_record_each_action`、`test_holder_of_device`。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现**（`lock` 用 `db.transaction()` 先 SELECT 再批量 INSERT；主键冲突也转成 `lock_taken`）。
- [ ] **Step 4: 运行通过。**
- [ ] **Step 5: 提交** `feat: atomic greenhouse locks in the workflow database`

### Task 4: 项目所有者

**Files:**
- Modify: `src/growbridge/workflow/store.py`（`STEPS` 追加 `ALTER TABLE wf_projects ADD COLUMN owner TEXT`；`add_project(project_id, name, now, owner: str | None = None)`；新增 `project_owner(project_id) -> str | None`、`set_project_owner(project_id, owner) -> None`、`project_of_stage(stage_id) -> str | None`）、`src/growbridge/workflow/service.py`（`create_project` 在 `actor.kind == "operator"` 时写入 `owner=actor.id`）、`src/growbridge/workflow/listing.py`（`project_summaries` 加关键字参数 `only_owner`）
- Test: `tests/workflow/test_workflow_owner.py`

**Interfaces:**
- Produces: 上述 store 方法；`project_summaries(..., only_owner: str | None = None)`，`None` = 不过滤（管理员与关闭多用户时）。

- [ ] **Step 1: 写失败测试** `test_operator_becomes_owner`、`test_workflow_actor_leaves_owner_empty`、`test_legacy_projects_go_to_admin_only`（先用旧 STEPS 建库插一条项目，再迁移，`project_owner` 为 None）、`test_summaries_filter_by_owner`。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现。**
- [ ] **Step 4: 运行通过**，并跑 `pytest tests/workflow -q`。
- [ ] **Step 5: 提交** `feat: projects record the operator who created them`

### Task 5: 权限与可见性规则

**Files:**
- Create: `src/growbridge/workflow/access.py`
- Test: `tests/workflow/test_workflow_access.py`

**Interfaces:**
- Consumes: `GreenhouseLocks`（Task 3）、`WorkflowStore.project_owner / project_of_stage / find_stage`（Task 4）、`Actor.role`（Task 2）。
- Produces: `class Access(store: WorkflowStore, locks: GreenhouseLocks, local_device: str)`：
  - `is_admin(actor) -> bool`
  - `require_project(actor, project_id) -> None`：非 operator 直接通过；所有者通过；否则 `Denied("not_owner")`。项目不存在或对其不可见时 `Denied("state", f"unknown project {id}")`。
  - `require_stage(actor, stage: StageRow, emergency: bool = False) -> None`：`emergency` 且管理员 → 通过；否则 `require_project` + `locks.holder_of_device(stage.device_id) == actor.id`，不满足 → `Denied("not_lock_holder")`。
  - `require_device(actor, device_id) -> None`：管理员或锁定人。
  - `require_admin(actor) -> None` → `Denied("admin_only")`。
  - `sees_project(actor, project_id) -> bool`；`sees_stage(actor, stage_id) -> bool`；`sees_device(actor, device_id) -> bool`；`owner_filter(actor) -> str | None`（管理员 `None`，否则 `actor.id`）。
  - `sees_alert(actor, alert: Alert) -> bool`：管理员全看；`ALERT_SCOPES: dict[str, Literal["stage","device","task"]]` 登记：`stage` = `stage_waiting, task_missed, measurement_missing, measurement_outside_window, audit_finding`（`key == stage_id` 或以 `f"{stage_id}:"` 开头，对调用者可见的阶段逐个比对，沿用 `observer/stage_checks._of_stage` 的匹配）；`device` = `frozen_reading, data_gap, threshold, pump_unreadable, pump_unexpected, pump_watchdog`（看 `local_device` 的锁定人）；`task` = `task_deadline`（`key` 是任务 id → 任务所属项目）。表里没有的 kind → 仅管理员。
  - 关闭多用户时不构造 `Access`；调用方以 `access is None` 表示不检查。

- [ ] **Step 1: 写失败测试**：用 `test_workflow_access.py` 内的小夹具（一个库、两个用户 A/B、一个管理员、A 锁 gh-01 并拥有一个阶段）覆盖设计 §6 表的每一行至少一允一拒；`test_admin_can_pause_but_not_approve`（`require_stage(admin, stage)` 拒、`emergency=True` 过）；`test_model_actor_is_not_checked`；`test_unregistered_alert_kind_is_admin_only`；`test_stage_alert_with_colon_in_stage_id`；`test_device_alert_follows_lock_holder`。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现。**
- [ ] **Step 4: 运行通过。**
- [ ] **Step 5: 提交** `feat: owner, lock-holder and visibility rules`

### Task 6: 工作流服务的检查点

**Files:**
- Modify: `src/growbridge/workflow/service.py`
- Test: `tests/workflow/test_workflow_access_points.py`

**Interfaces:**
- Consumes: `Access`（Task 5）。
- Produces: `WorkflowService.__init__(..., access: Access | None = None)`；私有 `_guard(actor, stage_or_project, emergency=False)`，`access is None` 时什么也不做。检查点（每处一行）：`save_protocol`/`create_round`（protocol/project 的 `require_project`）、`submit_run_sheet`（仅 operator：`require_project`）、`approve`、`revoke_approval`、`start_stage`（operator 时）、`resume_stage`、`takeover`、`handback`、`record_onsite_check`、`switch_run_sheet`（operator 时）→ `require_stage`；`pause_stage`（operator 时）、`stop_stage` → `require_stage(emergency=True)`；`choose_after_stop`、`abort_round` → 轮次所属项目 `require_project`。

- [ ] **Step 1: 写失败测试**：A 拥有并锁定 → 审批/启动/暂停/续跑/接管/交还/停止全通过；B（不是所有者）→ `not_owner`；A 释放锁后（阶段已结束、新建下一阶段待审）→ 审批 `not_lock_holder`；管理员停止 A 的阶段通过、审批被拒；`access=None` 时旧行为不变（取 `tests/workflow` 现有一条启动用例原样再跑）。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现**；改完 `wc -l src/growbridge/workflow/service.py` ≤ 800。
- [ ] **Step 4: 运行通过**，并跑 `pytest tests/workflow tests/e2e -q`。
- [ ] **Step 5: 提交** `feat: the workflow checks owner and lock holder before stage actions`

### Task 7: 工作台装配与写路由检查

**Files:**
- Modify: `src/growbridge/workbench/api.py`（`create_workbench(..., access: Access | None = None)`；`Workbench.access`；`manual_stage` 加 `require_stage`；`/measurements` 按实验所属项目 `require_project`；`/safety/approve` → `require_device(local_device)`；`/alerts/{id}/read` → 不可见时按不存在回答；`/me` 加 `role` 与 `greenhouses`）、`workbench/rounds.py`（`/projects/{id}/budget`、`/goals`、`/rounds` 读写、`/projects/{id}/conversation`）、`workbench/manual_tasks.py`、`workbench/analysis.py`、`workbench/holdouts.py`、`workbench/compute.py`（任务预算按任务项目；余额与结算 `require_admin`）
- Create: `src/growbridge/workbench/scope.py`：路由模块共用的薄函数 `project_write(access, actor, project_id)`、`stage_write(access, actor, stage_id, emergency=False)`、`admin_only(access, actor)`，`access is None` 时直接返回。
- Modify: `tests/workbench/workbench_support.py`：`Bench(..., multi_user: bool = False)`；为真时建 `GreenhouseLocks` 与 `Access`，传给 `WorkflowService` 与 `create_workbench`，并提供 `bench.user(name, role="user")`（建账号并返回已登录的 `TestClient`）与 `bench.lock(client, *ids)`。
- Test: `tests/workbench/test_workbench_multi_user_writes.py`

**Interfaces:**
- Consumes: `Access`（Task 5）、`WorkflowService(access=...)`（Task 6）。
- Produces: `create_workbench(..., access=None)`；`workbench/scope.py` 的三个函数；`Bench(multi_user=True)` 与 `bench.user / bench.lock`。

- [ ] **Step 1: 写失败测试**：对每个写路由一条"B 被拒"与一条"A 通过"（参数化，路由清单写在测试文件顶部的表里）；`test_compute_balance_admin_only`；`test_manual_write_needs_lock`；`test_irrigation_needs_lock`（局域网入口）。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现。**
- [ ] **Step 4: 运行通过**，并跑 `pytest tests/workbench -q`（`multi_user` 默认关，现有用例应全过）。
- [ ] **Step 5: 提交** `feat: workbench writes need the project owner and the greenhouse lock`

### Task 8: 项目、轮次、阶段读路由过滤

**Files:**
- Modify: `src/growbridge/workbench/reads.py`（`/projects` 用 `owner_filter`；`/projects/{id}`、`/stages/{id}/readings|measurements|history` 先判可见）、`workbench/rounds.py`（`/rounds/{id}`、`/rounds/{id}/report`、`/stages/{id}/run-sheet`）、`workbench/api.py`（`/stages/{id}` 对 operator 判可见；`/receipts/{request_id}` 用回执的 `stage_id` 判可见，`stage_id` 为空时仅管理员）、`workbench/manual_tasks.py`（列表）、`workbench/analysis.py`、`workbench/holdouts.py`（读）
- Create: `src/growbridge/workbench/visibility.py`：`READ_RULES: dict[str, str]`，键为 `/wb` 下每个 GET 路径（如 `"/wb/stages/{stage_id}/readings"`），值为 `"project" | "stage" | "round" | "device" | "alerts" | "public" | "admin" | "self" | "compute"`。
- Test: `tests/workbench/test_workbench_multi_user_reads.py`

**Interfaces:**
- Consumes: `Bench(multi_user=True)`（Task 7）。
- Produces: `READ_RULES`（Task 9、10 新增的 GET 路由也要登记）。

- [ ] **Step 1: 写失败测试** `test_every_get_route_is_registered`（遍历 `bench.app.routes` 中前缀 `/wb`、方法含 GET 的路径，集合必须等于 `READ_RULES` 的键）；`test_b_cannot_see_a`（A 建项目、跑一个阶段、产生回执；B 逐个访问 `READ_RULES` 中 `project/stage/round` 类路径，每个回答都与访问随机不存在 id 的回答状态码和 `code` 相同）；`test_admin_sees_everything`；`test_projects_list_only_own`。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现。**
- [ ] **Step 4: 运行通过。**
- [ ] **Step 5: 提交** `feat: operators read only their own projects, rounds and stages`

### Task 9: 收件箱、告警、环境、安全、计算的过滤

**Files:**
- Modify: `src/growbridge/workbench/reads.py`（`_inbox_routes`：先按 `sees_*` 过滤，再 `_cap`；`round_choice` 与 `task` 的计数改为过滤后计数）、`workbench/api.py`（`/alerts`）、`workbench/environment.py`、`reads.py` 的 `/safety`（`sees_device(local_device)`，否则回答 `{"safety": null}` 与环境页同样的"不可见"形状——用现有"未挂载"的形状，见 `pages/not-mounted.js`）、`workbench/compute.py`（`/compute`：非管理员只列自己项目任务的尝试，余额字段为 `null`）
- Test: `tests/workbench/test_workbench_multi_user_inbox.py`

**Interfaces:**
- Consumes: `Access.sees_alert / sees_device / owner_filter`（Task 5）、`READ_RULES`（Task 8）。

- [ ] **Step 1: 写失败测试** `test_inbox_cap_applies_after_filter`（B 的项目有 60 条阶段告警，A 有 1 条；A 的收件箱含这 1 条且 `truncated` 不含 B 的数）；`test_system_alerts_admin_only`（`backup_unconfigured`）；`test_device_alerts_follow_lock`（`frozen_reading` 只给锁定人）；`test_environment_needs_lock`；`test_compute_overview_hides_balance_from_users`。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现。**
- [ ] **Step 4: 运行通过。**
- [ ] **Step 5: 提交** `feat: inbox, alerts, environment and compute show each operator their own`

### Task 10: 温室与管理路由

**Files:**
- Create: `src/growbridge/workbench/greenhouses.py`（`add_greenhouse_routes(router, operator, fresh, locks, access)`）、`src/growbridge/workbench/admin.py`（`add_admin_routes(router, operator, fresh, operators, locks, store, access)`）
- Modify: `src/growbridge/workbench/api.py`（`access` 不为空时挂载两组路由）、`src/growbridge/workbench/visibility.py`（登记新 GET 路由：`/wb/greenhouses` → `"self"`，`/wb/admin/*` → `"admin"`）
- Test: `tests/workbench/test_workbench_greenhouses.py`

**Interfaces:**
- Produces（全部在 `/wb` 下）：
  - `GET /greenhouses` → `{"greenhouses": [{"id","name","state": "free"|"mine"|"taken","locked_at"}]}`；管理员每项多 `"holder"`。
  - `POST /greenhouses/lock`（fresh）`{"greenhouse_ids": [..]}` → `{"locked": [...]}`。
  - `POST /greenhouses/{id}/release` → `{"released": id}`。
  - `GET /admin/operators`、`POST /admin/operators`（fresh，`{name, secret, role}`）、`POST /admin/operators/{name}/disable`（fresh）、`POST /admin/operators/{name}/secret`（fresh，`{secret}`）。
  - `POST /admin/greenhouses/{id}/release`（fresh，`{note}` 1..500）。
  - `GET /admin/locks` → `{"locks": overview, "events": events}`。
  - `POST /admin/projects/{project_id}/owner`（fresh，`{owner, note}`）：新所有者必须是未停用的用户；每次转移记一行 `wf_project_owner_events(project_id, from_owner, to_owner, actor, at, note)`（`workflow/store.py` 的 `STEPS` 追加此表）。

- [ ] **Step 1: 写失败测试** `test_lock_flow_over_http`（A 锁 gh-01、gh-02；B 看到二者 `taken` 且无 `holder`；B 锁 gh-02 → 409 `lock_taken`）；`test_lock_needs_reauth`；`test_admin_force_release_needs_note`；`test_force_release_refused_while_stage_live`；`test_user_cannot_call_admin_routes`（每个 `/admin` 路由 → 403 `admin_only`）；`test_transfer_then_owner_can_act`（旧项目转给 A，A 锁温室后可审批）；`test_disable_from_admin_page`。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现。**
- [ ] **Step 4: 运行通过。**
- [ ] **Step 5: 提交** `feat: greenhouse lock and administrator routes`

### Task 11: 运行时装配与端到端

**Files:**
- Create: `src/growbridge/runtime_access.py`：`build_access(settings, db, clock, store) -> tuple[GreenhouseLocks, Access] | None`（`multi_user` 关闭时 `None`）。
- Modify: `src/growbridge/runtime.py`（构造 `WorkflowService` 与工作台时传入，净增 ≤ 3 行；保持 ≤ 800 行）
- Test: `tests/e2e/test_e2e_multi_user.py`

**Interfaces:**
- Consumes: Task 3、5、6、7、10 的全部产物。

- [ ] **Step 1: 写失败测试** `test_two_users_in_parallel`：`multi_user=True`、登记 12 个温室（本机设备为 gh-01），CLI 路径建管理员与两个用户；A 锁 gh-01 并经 HTTP 跑完一个模拟阶段到 `ended`；B 同时锁 gh-02..gh-04，B 的项目列表为空、读不到 A 的阶段；A 阶段结束后释放 gh-01，B 才能锁上。`test_multi_user_off_is_unchanged`：`multi_user=False` 时 `growbridge simulate` 的现有断言照常通过。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现。**
- [ ] **Step 4: 运行全量门禁**（见 Global Constraints）。
- [ ] **Step 5: 提交** `feat: wire accounts, locks and access into serve`

### Task 12: 控制台：温室页与管理页

**Files:**
- Create: `src/growbridge/web/workbench/pages/greenhouses.js`、`pages/admin.js`
- Modify: `router.js`（`FLAT` 与 `PAGES` 加 `greenhouses`、`admin`）、`ui/layout.js`（导航加「温室」；`me.role === "admin"` 时加「管理」）、`main.js`（登录后 `me.greenhouses` 为空且项目列表为空时跳到 `greenhouses`）、`i18n/zh.js`、`i18n/en.js`、`i18n/codes.zh.js`、`i18n/codes.en.js`（五个新拒绝码）、`tests/web/fixtures/known-codes.json`、新增 `tests/web/fixtures/greenhouses.json`、`admin-locks.json`、`admin-operators.json`
- Test: `tests/web/greenhouses-page.test.mjs`、`tests/web/admin-page.test.mjs`（用 `tests/web/support/render-page.mjs` 与 `fake-dom.mjs`）

**Interfaces:**
- Consumes: Task 10 的路由与 JSON 形状；`/me` 的 `role`、`greenhouses`。
- Produces: `pages/greenhouses.js` 与 `pages/admin.js` 各导出 `render(ctx)`（与现有页面同约定）。

- [ ] **Step 1: 写失败测试**：温室页三种状态各渲染正确（`taken` 的复选框 `disabled`）；锁定返回 `lock_taken` 时显示被占用编号并保留勾选；管理页对普通用户的 `me` 不出现在导航；`router.test.mjs` 增补两条 `parseHash/hrefFor` 往返；`leaks.test.mjs` 自动覆盖新页面（如需在 `support/leaks.mjs` 的页面清单登记，一并登记）。
- [ ] **Step 2: 运行确认失败** `node --test tests/web/*.test.mjs`。
- [ ] **Step 3: 实现**（复用 `ui/table.js`、`ui/forms.js`、`ui/dialog.js`；锁定按钮走现有重新认证对话框）。
- [ ] **Step 4: 运行通过。**
- [ ] **Step 5: 提交** `feat: greenhouse and administration pages in the console`

### Task 13: 文档与适配说明

**Files:**
- Modify: `docs/wiki/zh-CN/Configuration-Reference.md`、`docs/wiki/en/Configuration-Reference.md`（`multi_user`、`greenhouses`）、两种语言的 `API-Reference.md`（新路由与拒绝码）、`Denial-Codes-and-Events.md`、`Status-and-Known-Limitations.md`（"多用户：只在模拟设备与测试中验证；旧桥接入口与 MCP 用共享令牌，持有者视为管理员级别"）、`CLI-Reference.md`（`--admin`）
- Create: `docs/multi-user-adaptation.md`（设计 §11 的适配约定，中英各一节，供 PR 引用）
- Test: `pytest tests/docs -q`（Wiki 链接检查）

- [ ] **Step 1: 写文档。**
- [ ] **Step 2: 运行** `pytest tests/docs -q` → 通过。
- [ ] **Step 3: 全量门禁。**
- [ ] **Step 4: 提交** `docs: multi-user accounts, greenhouse locks and the adaptation notes`
