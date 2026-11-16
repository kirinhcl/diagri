# 多用户与温室锁定 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 DiAGRI 工作台加上用户角色、12 个温室的登记与原子锁定（含释放时的养护交接）、项目所有者，以及"只看自己的"可见性，全部由服务端强制。

**Architecture:** 新逻辑放新文件：`workflow/locks.py`（锁表）、`workflow/access.py`（权限与可见性规则）、`workflow/release.py`（释放时的空闲写入与养护交接）、`workbench/greenhouses.py` 与 `workbench/admin.py`（新路由）、`workbench/scope.py`（路由共用检查）、`workbench/visibility.py`（读路由登记表）、`runtime_access.py`（装配）。现有文件只加接入点。整层由 `Settings.multi_user` 开关控制，默认关；关闭时只保留第 1 个任务里的缺陷修正。

**Tech Stack:** Python 3.11+ / FastAPI / pydantic v2 / SQLite（`archive/db.py` 的 `Database.migrate`，同一命名空间只能追加步骤）；控制台为原生 ES 模块，Node 20 `node --test`。

**Spec:** `docs/superpowers/specs/2026-11-16-multi-user-locks-design.md`（第 14 节是第 1 轮审查后的修订，以它为准）

## Global Constraints

- 只在 `settings.auto_research and settings.multi_user` 时启用；`multi_user` 默认 `False`。关闭时不构造 `Access`，所有调用点以 `access is None` 跳过检查。
- 锁表、角色列、项目 `owner` 列、`wf_project_owner_events` 都在工作流库 `dbs["workflow"]`（`Operators` 已在此库）。
- 角色只有 `"user"` / `"admin"`；锁事件 `action` 只有 `"lock"` / `"release"` / `"force_release"` / `"transfer"`。
- 空闲状态默认 `{light: 0, exhaust: 30, fan: 3, pump: 0}`，只写该阶段运行单里 `ownership == host` 的通道；水泵恒为 0。
- 告警归属只来自显式 `scope`（`("stage", id)` / `("project", id)` / `("device", id)`），没有 `scope` 的告警只给管理员。
- 隐藏对象：返回**该路由自己**对不存在 id 的完整响应（状态码与响应体），响应里不得出现任何父对象 id。`not_owner` 只给能看见对象的管理员；`not_lock_holder` 只给没锁温室的所有者。
- 新拒绝码：`lock_taken`（409）、`greenhouse_busy`（409）、`idle_unconfirmed`（409）、`not_owner`（403）、`not_lock_holder`（403）、`admin_only`（403）。409 的三个登记进 `workbench/api.py` 的 `STATUS_BY_CODE`。
- 管理员写操作例外只有：暂停、停止任何阶段；强制释放；用户管理；项目转移；CSC 余额与结算。
- 不在 `Database.transaction()` 内 `await`（`archive/db.py` 开头的约定）。
- 代码限制：文件 ≤ 800 行，函数 ≤ 30 行，嵌套 ≤ 3 层。`runtime.py`（797 行）只加 ≤ 3 行，装配写进 `runtime_access.py`；`workflow/service.py`（754 行）每个检查点一行，超过 800 行就把检查辅助挪进 `workflow/access.py`。
- 门禁：`ruff check -q && ruff format --check -q && pytest -q && node --test tests/web/*.test.mjs`，不接管道。

## Review Focus

1. **用别人的 id 直接请求**：B 用 A 的 `stage_id` / `round_id` / `project_id` / `request_id` / 测量 id（`corrects`）/ `/goals` 的 `round_id` 发请求，回答与随机不存在的 id 完全相同。→ Task 9 `test_b_cannot_see_a` 与 Task 8 `test_b_cannot_write_a`。
2. **收件箱被别人挤满**：B 有 60 个待选择的轮次与 60 个待处理任务时，A 的 1 个仍在 A 的收件箱，`truncated` 不含 B 的数。→ Task 10 `test_inbox_filters_before_sql_limit`。
3. **释放时设备写不进去**：空闲写入有一条未确认，释放失败，锁与养护写入权恢复原状。→ Task 5 `test_release_rolls_back_when_idle_unconfirmed`。
4. **重启后养护复活**：释放后重启（调用 `restore_care`），已释放温室的旧阶段不得重新拿到养护写入权。→ Task 5 `test_released_care_not_restored`。
5. **转移与命令同时发生**：A 的接管请求已过授权、尚未提交时项目被转给 C，提交在事务里被拒、没有新写入权留在控制侧。→ Task 7 `test_transfer_during_command_rolls_back`。

---

### Task 1: 修正现有代码里的三处缺陷（不依赖开关）

**Files:**
- Modify: `src/growbridge/workflow/service.py`（`_replace_run_sheet`）、`src/growbridge/archive/store.py`（`add_measurement`）、`src/growbridge/agents/handlers_orchestrator.py`（`project_state`）
- Test: `tests/workflow/test_workflow_sheet_binding.py`、`tests/archive/test_archive_corrections.py`、`tests/agents/test_orchestrator_active_stage.py`（目录按现有测试布局放）

**Interfaces:**
- Produces: `_replace_run_sheet` 在新运行单的 `(project_id, experiment_id, device_id)` 与阶段记录不同时 `Denied("state", "a replacement run sheet keeps the stage's project, experiment and device")`；`add_measurement` 在 `corrects` 指向别的实验时 `ValueError`（工作台已把 `ValueError` 转成 `rejected`）；`project_state` 的 `active_stage` 仅当活动阶段的 `project_id == data.project_id` 时给出，否则 `None`。

- [ ] **Step 1: 写失败测试** `test_replacement_cannot_change_device`、`test_replacement_cannot_change_experiment`、`test_correction_must_stay_in_experiment`（A 实验的测量不能被 B 实验的记录更正，A 的测量数仍为 1）、`test_active_stage_of_other_project_is_hidden`。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现。**
- [ ] **Step 4: 运行通过**，并跑 `pytest tests/workflow tests/archive tests/agents -q`。
- [ ] **Step 5: 提交** `fix: a replacement run sheet keeps its stage's device, corrections stay in their experiment, and project state names only its own active stage`

### Task 2: 温室登记、空闲状态与开关（配置）

**Files:**
- Modify: `src/growbridge/config.py`
- Test: `tests/test_config_greenhouses.py`

**Interfaces:**
- Produces: `class IdleLevels(BaseModel)`：`light: int = 0`、`exhaust: int = 30`、`fan: int = 3`（各自按 `check_level` 校验）；`class Greenhouse(BaseModel)`：`id`（`^[a-z0-9][a-z0-9-]{0,31}$`）、`name`（1..64）、`device_id`、`idle: IdleLevels = IdleLevels()`；`Settings.multi_user: bool = False`、`Settings.greenhouses: list[Greenhouse] = []`；`Settings.greenhouse_registry() -> tuple[Greenhouse, ...]`（空列表时返回 `(Greenhouse(id="gh-01", name="Greenhouse 1", device_id=self.device),)`）。

- [ ] **Step 1: 写失败测试** `test_default_registry_is_the_local_device`、`test_ids_and_devices_unique`、`test_local_device_must_be_registered`、`test_idle_defaults`、`test_idle_levels_validated`（`fan=11` → `ValidationError`）、`test_multi_user_defaults_off`。
- [ ] **Step 2–4: 失败 → 实现 → 通过**（再跑 `pytest tests -q -k config`）。
- [ ] **Step 5: 提交** `feat: register greenhouses with idle levels and a multi_user switch`

### Task 3: 角色与停用（账号）

**Files:**
- Modify: `src/growbridge/workbench/auth.py`（`STEPS` 追加 `ALTER TABLE operators ADD COLUMN role TEXT NOT NULL DEFAULT 'user'` 与 `ADD COLUMN disabled_at REAL`）、`src/growbridge/ports.py`（`Actor.role: Literal["user", "admin"] | None = None`）、`src/growbridge/cli.py`（`operator add --admin`）
- Test: `tests/workbench/test_workbench_accounts.py`

**Interfaces:**
- Produces: `Operators.add(name, secret, role="user")`；`Operators.role(name) -> str | None`；`Operators.disable(name)`（置 `disabled_at`、删其全部会话；未知名字 `ValueError`）；`Operators.reset_secret(name, secret)`（删其全部会话）；`Operators.active(name) -> bool`；`Operators.listing() -> list[dict]`（`name, role, created_at, disabled_at`）；`Operators.actor()` 填 `Actor.role`；停用用户登录按口令错误处理（同耗时、同拒绝码）。

- [ ] **Step 1: 写失败测试** `test_add_admin_role`、`test_default_role_is_user`、`test_disabled_cannot_log_in`、`test_disabled_user_session_ends`、`test_reset_secret_ends_sessions`、`test_listing_has_no_secrets`（键集合恰为四个）、`test_cli_add_admin`、`test_name_with_slash_is_manageable`（`lab/alice` 可停用、可重置）。
- [ ] **Step 2–4: 失败 → 实现 → 通过**（再跑 `pytest tests/workbench -q`）。
- [ ] **Step 5: 提交** `feat: operator roles, disabling and secret reset`

### Task 4: 锁表与项目所有者（存储）

**Files:**
- Create: `src/growbridge/workflow/locks.py`
- Modify: `src/growbridge/workflow/store.py`（`STEPS` 追加：`ALTER TABLE wf_projects ADD COLUMN owner TEXT`；`ALTER TABLE wf_stages ADD COLUMN care_released INTEGER NOT NULL DEFAULT 0`；`CREATE TABLE wf_project_owner_events(id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, from_owner TEXT, to_owner TEXT NOT NULL, actor TEXT NOT NULL, at REAL NOT NULL, note TEXT NOT NULL)`）、`src/growbridge/workflow/service.py`（`create_project` 在 operator 时写 `owner`）、`src/growbridge/workflow/listing.py`、`src/growbridge/workflow/tasks.py`
- Test: `tests/workflow/test_workflow_locks.py`、`tests/workflow/test_workflow_owner.py`

**Interfaces:**
- Consumes: `Settings.greenhouse_registry()`（Task 2）。
- Produces:
  - `WorkflowStore`：`add_project(project_id, name, now, owner=None)`；`project_owner(project_id) -> str | None`；`set_project_owner(project_id, owner, actor, note, now)`（同事务写 `wf_project_owner_events`）；`device_unfinished(device_id) -> bool`（存在状态不在 `ENDED`/`STOPPED` 的阶段）；`unfinished_devices_of_project(project_id) -> tuple[str, ...]`；`care_holder(device_id) -> StageRow | None`（该设备上 `care_right IS NOT NULL` 的阶段）；`mark_care_released(stage_id)`。
  - `restore_care`（`workflow/recovery.py`）跳过 `care_released = 1` 的阶段。
  - `project_summaries(store, limit, *, only_owner: str | None = None)`、`rounds_awaiting_choice(store, limit, *, only_owner=None)`、`count_rounds_awaiting_choice(store, *, only_owner=None)`；`TaskBoard.in_states(states, limit, *, only_owner=None)`、`TaskBoard.count_in_states(states, *, only_owner=None)`——`only_owner` 以 `JOIN wf_projects` 加在 SQL 的 `WHERE` 里，位于 `LIMIT` 之前（`TaskBoard` 用的就是工作流库）。
  - `class GreenhouseLocks(db, clock, registry)`（命名空间 `"greenhouse_locks"`）：`lock(holder, ids) -> tuple[str, ...]`（一个事务内全锁或全不锁；占用 → `Denied("lock_taken", <被占编号>)`；重复或未知 → `Denied("state")`）；`delete(greenhouse_id, action, actor, note="")`（只删行与记事件，不做业务检查）；`move(greenhouse_ids, to_holder, actor, note)`；`holder_of_device(device_id) -> str | None`；`locked_at(device_id) -> float | None`；`held_by(holder)`；`greenhouse(id) -> Greenhouse`；`overview() -> list[dict]`；`events(limit=100)`。

- [ ] **Step 1: 写失败测试** `test_lock_is_all_or_nothing`、`test_lock_rejects_duplicates_and_unknown`、`test_two_threads_one_winner`、`test_operator_becomes_owner`、`test_workflow_actor_leaves_owner_empty`、`test_legacy_projects_have_no_owner`（旧 STEPS 建库后迁移）、`test_summaries_rounds_tasks_filter_before_limit`（B 有 60 条、A 有 1 条，`limit=50` 时 A 的查询仍返回 1 条）、`test_care_holder_and_release_mark`、`test_restore_care_skips_released`。
- [ ] **Step 2–4: 失败 → 实现 → 通过**（再跑 `pytest tests/workflow -q`）。
- [ ] **Step 5: 提交** `feat: greenhouse locks, project owners and owner-filtered listings`

### Task 5: 释放温室：空闲写入与养护交接

**Files:**
- Create: `src/growbridge/workflow/release.py`
- Test: `tests/workflow/test_workflow_release.py`

**Interfaces:**
- Consumes: `GreenhouseLocks`、`WorkflowStore.care_holder / device_unfinished / mark_care_released`（Task 4）、`ControlPort.grant / submit / handover`、`workflow.store.right_scope`。
- Produces: `class GreenhouseRelease(workflow: WorkflowService, locks: GreenhouseLocks)`：`async release(greenhouse_id, actor, *, force=False, note="") -> None`。
  顺序：①`device_unfinished` → `Denied("greenhouse_busy")`；非强制且锁不属于 `actor.id` → `Denied("not_lock_holder")`；②`care_holder(device)` 为空 → 直接 ③；否则以该阶段运行单签一个 `MANUAL` 写入权（`right_scope(stage, sheet, RightKind.MANUAL)`，operator `f"release:{actor.id}"`），对每个 host 通道提交空闲等级（`request_id = f"release-{greenhouse_id}-{channel}-{int(now)}"`，`trigger = "release"`），任一结果不是 `ActionState.CONFIRMED` → 交还该手动写入权、`Denied("idle_unconfirmed")`，养护写入权与锁不动；全部确认 → 交还手动与养护写入权、`update_stage(care_right=None)`、`mark_care_released`；③`locks.delete(id, "force_release" if force else "release", actor.id, note)`。

- [ ] **Step 1: 写失败测试**（用 `tests/workbench/workbench_support.RecordingControl` 或同类假控制）：`test_release_writes_idle_then_hands_over_care`（提交了 light 0、exhaust 30、fan 3，养护写入权已交还，锁已删）、`test_release_only_host_channels`（运行单里 light 为 device 所有 → 不写 light）、`test_release_rolls_back_when_idle_unconfirmed`、`test_release_refused_while_stage_unfinished`、`test_force_release_records_note`、`test_released_care_not_restored`、`test_release_without_care_holder_only_deletes_lock`。
- [ ] **Step 2–4: 失败 → 实现 → 通过。**
- [ ] **Step 5: 提交** `feat: releasing a greenhouse sets idle levels and hands over care`

### Task 6: 告警的显式归属

**Files:**
- Modify: `src/growbridge/observer/alerts.py`（`STEPS` 追加 `ADD COLUMN scope_kind TEXT` 与 `ADD COLUMN scope_id TEXT`；`Alert` 加同名可选字段；`raise_alert(kind, key, severity, message, scope: tuple[str, str] | None = None)`，新建与合并时都写入 scope）、`runtime.py`（`_alert` / `alert` 透传 `scope`，净增 ≤ 2 行）、产生点：`observer/stage_checks.py`、`agents/handlers_auditor.py`、`observer/frozen_watch.py`、`observer/service.py`、`executor/watchdog.py`、`runtime.py` 的 `stage_waiting` 与 `task_deadline`、`runtime_agents.py` 的 `agent_task` 与 `audit_task`
- Test: `tests/observer/test_alert_scope.py`

**Interfaces:**
- Produces: 每个产生点的归属：阶段类 `("stage", stage_id)`；`agent_task` / `task_deadline` → `("project", task.project_id)`；`audit_task` → `("stage", stage_id)`，无阶段时 `("project", task.project_id)`；设备类 → `("device", settings.device)`。

- [ ] **Step 1: 写失败测试** `test_scope_saved_and_kept_on_merge`、`test_old_rows_have_no_scope`、每个产生点一条断言其 `scope`（参数化：触发方式沿用各模块现有测试的夹具）。
- [ ] **Step 2–4: 失败 → 实现 → 通过**（再跑 `pytest tests/observer tests/executor tests/e2e -q`）。
- [ ] **Step 5: 提交** `feat: alerts carry the stage, project or device they belong to`

### Task 7: 权限规则与工作流检查点

**Files:**
- Create: `src/growbridge/workflow/access.py`
- Modify: `src/growbridge/workflow/service.py`、`src/growbridge/workflow/recovery.py`（`record_onsite_check`）
- Test: `tests/workflow/test_workflow_access.py`、`tests/workflow/test_workflow_access_points.py`

**Interfaces:**
- Consumes: Task 3、4、6。
- Produces: `class Access(store, locks, local_device)`：`is_admin(actor)`；`require_project(actor, project_id, hidden: Callable[[], Exception])`（非 operator 通过；所有者通过；管理员 → `Denied("not_owner")`；其他人 → `raise hidden()`）；`require_stage(actor, stage, hidden, emergency=False)`（`emergency` 且管理员通过；所有者但非锁定人 → `Denied("not_lock_holder")`）；`require_sheet_device(project_id, device_id)`（项目所有者须锁着该设备，所有 actor 种类都查；不满足 → `Denied("not_lock_holder")`）；`require_admin(actor)`；`sees_project / sees_stage / sees_device / sees_alert(actor, alert)`；`owner_filter(actor) -> str | None`；`still_allowed(actor, stage_id, emergency) -> bool`（只读库，供提交时复核）。
  `WorkflowService.__init__(..., access: Access | None = None)`；检查点：`save_protocol`、`create_round`、`choose_after_stop`、`abort_round` → `require_project`；`submit_run_sheet` → operator 时 `require_project`，所有种类 `require_sheet_device`；`approve`、`revoke_approval`、`resume_stage`、`takeover`、`handback`、`record_onsite_check`、`switch_run_sheet`、`start_stage`（operator 时）→ `require_stage`；`pause_stage`（operator 时）、`stop_stage` → `require_stage(emergency=True)`。`_commit` 的事务开头调用 `access.still_allowed`，为假则 `Denied("state", "authorization changed")` 并交还本次签出的写入权。检查点里 `hidden` 用该方法现有的不存在回答（`store.stage` 的 `Denied`）。

- [ ] **Step 1: 写失败测试**：设计第 6 节表格每行一允一拒；`test_admin_can_stop_but_not_approve`；`test_model_draft_needs_owner_lock`；`test_onsite_check_by_other_has_no_control_effects`（B 请求后 `control` 上无 reconcile/handover 调用）；`test_transfer_during_command_rolls_back`（在 `takeover` 的 `await reconcile_unsettled` 处插入转移，提交被拒、控制侧新签写入权已交还）；`test_access_none_unchanged`（`tests/workflow` 现有启动用例原样再跑）。
- [ ] **Step 2–4: 失败 → 实现 → 通过**（`wc -l` 两个文件 ≤ 800；再跑 `pytest tests/workflow tests/e2e -q`）。
- [ ] **Step 5: 提交** `feat: owner and lock-holder checks in the workflow, rechecked at commit`

### Task 8: 工作台装配与写路由

**Files:**
- Create: `src/growbridge/workbench/scope.py`（`project_write(access, actor, project_id, hidden)`、`stage_write(access, actor, stage_id, hidden, emergency=False)`、`admin_only(access, actor)`，`access is None` 时直接返回）
- Modify: `workbench/api.py`（`create_workbench(..., access=None, release: GreenhouseRelease | None = None)`；`manual_stage` → `stage_write`；`/measurements` → 实验所属项目 `project_write`；`/safety/approve` → 锁定人或管理员；`/drafts/run-sheet` 在 `access` 非空时拒绝模型令牌（`model_role`）；`/alerts/{id}/read` 不可见 → 与不存在同答；`/me` 加 `multi_user`、`role`、`greenhouses`；`STATUS_BY_CODE` 加三个 409）、`workbench/rounds.py`、`workbench/manual_tasks.py`、`workbench/analysis.py`、`workbench/holdouts.py`、`workbench/compute.py`（任务预算按任务项目；余额与结算 `admin_only`）、`tests/workbench/workbench_support.py`（`Bench(..., multi_user=False, with_compute=False)`；为真时建 `GreenhouseLocks`、`Access`、`GreenhouseRelease` 并传入；`bench.user(name, role="user") -> TestClient`（已登录）、`bench.lock(client, *ids)`、`bench.full()` 返回挂满可选服务的夹具）
- Test: `tests/workbench/test_workbench_multi_user_writes.py`

**Interfaces:**
- Consumes: Task 5、7。
- Produces: 上述 `create_workbench` 参数与 `Bench` 辅助。

- [ ] **Step 1: 写失败测试**：顶部一张写路由表（路径、方法、样例体），参数化 `test_b_cannot_write_a`（B 的回答与对不存在 id 的回答完全相同）与 `test_a_can_write_own`；`test_compute_balance_admin_only`；`test_manual_write_and_irrigation_need_lock`；`test_model_token_draft_refused_when_multi_user`；`test_corrects_other_experiment_refused`；`test_goal_with_foreign_round_hidden`。
- [ ] **Step 2–4: 失败 → 实现 → 通过**（`multi_user` 默认关，现有 `tests/workbench` 应全过）。
- [ ] **Step 5: 提交** `feat: workbench writes need the project owner and the greenhouse lock`

### Task 9: 项目、轮次、阶段、回执的读取

**Files:**
- Create: `src/growbridge/workbench/visibility.py`（`READ_RULES: dict[str, str]`：`/wb` 下每个 GET 路径 → `"project" | "stage" | "round" | "receipt" | "device" | "alerts" | "inbox" | "compute" | "public" | "admin" | "self"`）
- Modify: `workbench/reads.py`（`/projects` 用 `only_owner`；`/projects/{id}`、`/stages/{id}/readings|measurements|history`）、`workbench/rounds.py`（`/rounds/{id}`、`/rounds/{id}/report`、`/stages/{id}/run-sheet`、对话）、`workbench/api.py`（`/stages/{id}`；`/receipts/{id}` 按回执的 `stage_id` 判，空则仅管理员，不可见时 404 同不存在）、`workbench/manual_tasks.py`、`workbench/analysis.py`、`workbench/holdouts.py`（读）
- Test: `tests/workbench/test_workbench_multi_user_reads.py`

**Interfaces:**
- Consumes: `Bench(multi_user=True).full()`（Task 8）。

- [ ] **Step 1: 写失败测试** `test_every_get_route_is_registered`（对 `bench.full()` 的路由集合）；`test_b_cannot_see_a`（按 `READ_RULES` 类别参数化，A 的对象 id 与随机 id 的响应体逐字相同，且响应文本不含 A 的任何 id）；`test_admin_sees_everything`；`test_projects_list_only_own`。
- [ ] **Step 2–4: 失败 → 实现 → 通过。**
- [ ] **Step 5: 提交** `feat: operators read only their own projects, rounds, stages and receipts`

### Task 10: 收件箱、告警、环境、安全、计算

**Files:**
- Modify: `workbench/reads.py`（`_inbox_routes`：阶段、轮次、任务、告警、计算都先按可见性取数，轮次与任务用 Task 4 的 `only_owner`，再 `_cap`）、`workbench/api.py`（`/alerts` 用 `sees_alert`）、`workbench/environment.py`（锁定人或管理员；样本只取 `locks.locked_at(device)` 之后；`active_stage` 与告警计数只给可见的；否则 `Denied("not_lock_holder")`）、`reads.py` 的 `/safety`（同上规则）、`workbench/compute.py` 与 `compute/overview.py`（普通用户：任务、作业、卡住的尝试只列自己项目的，用量只算这些，`balance` 与全局用量为 `null`）
- Test: `tests/workbench/test_workbench_multi_user_inbox.py`

**Interfaces:**
- Consumes: Task 4、6、7、9。

- [ ] **Step 1: 写失败测试** `test_inbox_filters_before_sql_limit`；`test_system_alerts_admin_only`；`test_device_alerts_follow_lock`；`test_environment_starts_at_lock_time`（锁定前的样本不出现）；`test_environment_hides_previous_stage`；`test_safety_needs_lock`；`test_compute_overview_scoped`。
- [ ] **Step 2–4: 失败 → 实现 → 通过。**
- [ ] **Step 5: 提交** `feat: inbox, alerts, environment and compute show each operator their own`

### Task 11: 温室与管理路由

**Files:**
- Create: `src/growbridge/workbench/greenhouses.py`（`add_greenhouse_routes(router, operator, fresh, locks, release, access)`）、`src/growbridge/workbench/admin.py`（`add_admin_routes(router, fresh, operators, locks, release, store, access)`）
- Modify: `workbench/api.py`（`access` 非空时挂载）、`workbench/visibility.py`（登记 `/wb/greenhouses` → `"self"`，`/wb/admin/*` → `"admin"`）
- Test: `tests/workbench/test_workbench_greenhouses.py`

**Interfaces（全部在 `/wb` 下）:**
- `GET /greenhouses` → `{"greenhouses": [{"id","name","state": "free"|"mine"|"taken","locked_at"}]}`，管理员每项多 `"holder"`。
- `POST /greenhouses/lock`（fresh）`{"greenhouse_ids": [...]}` → `{"locked": [...]}`。
- `POST /greenhouses/{id}/release` → `GreenhouseRelease.release(id, actor)` → `{"released": id}`。
- `GET /admin/operators`；`POST /admin/operators`（fresh，`{name, secret, role}`）；`POST /admin/operators/disable`（fresh，`{name}`）；`POST /admin/operators/secret`（fresh，`{name, secret}`）。列表每项加 `unfinished_stages`（停用用户名下项目的未结束阶段数）。
- `GET /admin/locks` → `{"locks": overview, "events": events}`。
- `POST /admin/greenhouses/{id}/release`（fresh，`{note}` 1..500）→ `release(id, actor, force=True, note=note)`。
- `POST /admin/projects/{project_id}/owner`（fresh，`{owner, note}`）：新所有者须存在且未停用；同一事务里 `set_project_owner` 与 `locks.move(unfinished_devices_of_project 对应的温室, owner, actor, note)`；目标温室被第三人锁着 → `Denied("lock_taken")`，整体不变。

- [ ] **Step 1: 写失败测试** `test_lock_flow_over_http`（B 看到 `taken` 且无 `holder`；B 再锁 → 409 `lock_taken`）；`test_lock_needs_reauth`；`test_release_over_http_sets_idle`；`test_admin_force_release_needs_note`；`test_force_release_refused_while_stage_live`；`test_user_cannot_call_admin_routes`；`test_transfer_moves_locks_with_project`（停用 A 后把 A 的运行中项目转给 C，C 可直接暂停、续跑）；`test_transfer_then_owner_can_act`（旧项目）；`test_admin_list_marks_unfinished_stages`。
- [ ] **Step 2–4: 失败 → 实现 → 通过。**
- [ ] **Step 5: 提交** `feat: greenhouse lock and administrator routes`

### Task 12: 运行时装配与端到端

**Files:**
- Create: `src/growbridge/runtime_access.py`：`build_access(settings, db, clock, workflow) -> AccessParts | None`（`AccessParts` 为 `locks, access, release` 的 NamedTuple；`multi_user` 关闭时 `None`）。`WorkflowService` 在构造后用 `workflow.access = parts.access` 注入（避免构造顺序循环）。
- Modify: `src/growbridge/runtime.py`（≤ 3 行）
- Test: `tests/e2e/test_e2e_multi_user.py`

- [ ] **Step 1: 写失败测试** `test_two_users_in_parallel`（12 个温室、本机为 gh-01；A 锁 gh-01 经 HTTP 跑完一个模拟阶段到 `ended`；B 同时锁 gh-02..gh-04，B 的项目列表为空、读不到 A；A 释放 gh-01 时空闲等级被写入、养护交还，B 随后可锁）；`test_multi_user_off_is_unchanged`（`growbridge simulate` 现有断言照常通过）。
- [ ] **Step 2–4: 失败 → 实现 → 全量门禁。**
- [ ] **Step 5: 提交** `feat: wire accounts, locks and access into serve`

### Task 13: 控制台

**Files:**
- Create: `src/growbridge/web/workbench/pages/greenhouses.js`、`pages/admin.js`；`tests/web/fixtures/greenhouses.json`、`admin-locks.json`、`admin-operators.json`
- Modify: `router.js`（`FLAT`、`PAGES` 加 `greenhouses`、`admin`）、`ui/layout.js`（`me.multi_user` 时加「温室」；再 `me.role === "admin"` 时加「管理」）、`main.js`（`multi_user` 且无锁、无项目时首页跳 `greenhouses`）、`pages/environment.js` 与 `pages/safety.js`（收到 `not_lock_holder` 时显示说明与「去锁定温室」链接，不渲染空表单）、`pages/compute.js`（`balance` 为 `null` 时不显示余额录入与结算控件）、`denials.js`（六个新码的说明）、`i18n/zh.js`、`i18n/en.js`、`i18n/codes.zh.js`、`i18n/codes.en.js`、`tests/web/fixtures/known-codes.json`、`tests/web/fixtures/me.json`（加 `multi_user`、`role`、`greenhouses`）、`tests/web/support/render-page.mjs`（新夹具的路径映射）、`tests/web/leaks.test.mjs`（页面清单加两页）、`tests/web/denials.test.mjs`（期望数量随新码更新）
- Test: `tests/web/greenhouses-page.test.mjs`、`tests/web/admin-page.test.mjs`、`tests/web/router.test.mjs`（增补）

- [ ] **Step 1: 写失败测试**：温室页三种状态（`taken` 的复选框 `disabled`）；锁定返回 `lock_taken` 时提示被占编号并保留勾选；释放返回 `idle_unconfirmed` 时提示且仍显示为"我的"；`multi_user=false` 的 `me` 下导航没有「温室」「管理」；普通用户导航没有「管理」；环境页对 `not_lock_holder` 显示说明；`parseHash/hrefFor` 往返两条。
- [ ] **Step 2–4: 失败 → 实现 → 通过**（`node --test tests/web/*.test.mjs`）。
- [ ] **Step 5: 提交** `feat: greenhouse and administration pages in the console`

### Task 14: 文档与适配说明

**Files:**
- Modify: 两种语言的 `docs/wiki/*/Configuration-Reference.md`（`multi_user`、`greenhouses`、`idle`）、`API-Reference.md`（新路由、`/me` 字段、模型令牌起草在多用户下被拒）、`Denial-Codes-and-Events.md`（六个新码；与 `denials.js` 一致）、`Status-and-Known-Limitations.md`（多用户只在模拟设备与测试中验证；共享令牌入口暴露全部设备数据，不是工作台管理员身份）、`CLI-Reference.md`（`--admin`）
- Create: `docs/multi-user-adaptation.md`（设计第 11 节，中英各一节，PR 引用）
- Test: `pytest tests/docs -q`、`node --test tests/web/denials.test.mjs`

- [ ] **Step 1: 写文档。**
- [ ] **Step 2: 运行** 上述两条测试 → 通过。
- [ ] **Step 3: 全量门禁。**
- [ ] **Step 4: 提交** `docs: multi-user accounts, greenhouse locks and the adaptation notes`
