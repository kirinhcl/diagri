# 多用户与温室锁定 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 DiAGRI 工作台加上用户角色、12 个温室的登记与原子锁定、项目所有者，以及"只看自己的"可见性，全部由服务端强制。

**Architecture:** 新逻辑放新文件：`workflow/locks.py`（锁表与释放）、`workflow/access.py`（权限与可见性规则）、`workbench/greenhouses.py` 与 `workbench/admin.py`（新路由）、`workbench/scope.py`（路由共用检查）、`workbench/visibility.py`（读路由登记表）、`runtime_access.py`（装配）。现有文件只加接入点。整层由 `Settings.multi_user` 开关控制，默认关；关闭时只保留 Task 1 的缺陷修正与 Task 5 的告警归属（二者本身就是修正）。释放与转移都是纯数据库操作，不做设备写入。

**Tech Stack:** Python 3.11+ / FastAPI / pydantic v2 / SQLite（`archive/db.py` 的 `Database.migrate`，同一命名空间只能追加步骤）；控制台为原生 ES 模块，Node 20 `node --test`。

**Spec:** `docs/superpowers/specs/2026-11-16-multi-user-locks-design.md`（第 14、15 节是两轮审查后的修订，以它们为准）

## Global Constraints

- 只在 `settings.auto_research and settings.multi_user` 时启用；`multi_user` 默认 `False`。关闭时不构造 `Access`，所有调用点以 `access is None` 跳过检查。
- 锁表、角色列、项目 `owner` 列、`wf_project_owner_events` 都在工作流库 `dbs["workflow"]`（`Operators`、`TaskBoard` 已在此库）。
- 角色只有 `"user"` / `"admin"`；锁事件 `action` 只有 `"lock"` / `"release"` / `"force_release"`。
- 释放：先 `await control.handover(care_right, "release")`，再一个事务完成复核、清养护指针、标记 `care_released`、删锁。不写设备。
- 转移：仅当原所有者为 `NULL` 或已停用、且项目没有未结束阶段；不动锁。
- 告警身份 = `(kind, key, scope_kind, scope_id)`；没有归属的告警只给管理员。
- 隐藏对象：返回该路由对**同一个 id** 在对象不存在时的完整响应；响应里不得出现任何父对象 id。`not_owner` 只给能看见对象的管理员；`not_lock_holder` 只给没锁温室的所有者。
- 新拒绝码：`lock_taken`（409）、`greenhouse_busy`（409）、`not_owner`（403）、`not_lock_holder`（403）、`admin_only`（403）。409 的两个登记进 `workbench/api.py` 的 `STATUS_BY_CODE`。
- 管理员写操作例外只有：暂停、停止任何阶段；强制释放；用户管理；项目转移；CSC 余额与结算。
- 不在 `Database.transaction()` 内 `await`。不新增 `_commit` 复核。
- 代码限制：文件 ≤ 800 行，函数 ≤ 30 行，嵌套 ≤ 3 层。`runtime.py`（797 行）净增 ≤ 3 行，装配写进 `runtime_access.py`；`workflow/service.py`（754 行）每个检查点一行，超过 800 行就把检查辅助挪进 `workflow/access.py`。
- 门禁：`ruff check -q && ruff format --check -q && pytest -q && node --test tests/web/*.test.mjs`，不接管道。

## Review Focus

1. **用别人的 id 直接请求**：B 用 A 的 `stage_id` / `round_id` / `project_id` / `request_id` / 测量 id（`corrects`）/ `/goals` 的 `round_id` 发请求，回答与"同一 id 不存在"时完全相同。→ Task 8 `test_b_cannot_write_a`、Task 9 `test_b_cannot_see_a`。
2. **收件箱被别人挤满**：B 有 60 个待选择轮次与 60 个待处理任务时，A 的 1 个仍在 A 的收件箱，`truncated` 不含 B 的数。→ Task 10 `test_inbox_filters_before_sql_limit`。
3. **释放与起草同时发生**：交还养护的 `await` 期间所有者提交了新阶段，释放以 `greenhouse_busy` 失败、锁仍在、新阶段可正常审批启动。→ Task 4 `test_release_loses_to_concurrent_submission`。
4. **重启后养护复活**：释放后重启（新 `WorkflowService` 调 `restore_care`），已释放温室的旧阶段不再拿到养护写入权；而在交还后、事务前崩溃时，重启会重新签发。→ Task 4 `test_released_care_not_restored`、`test_crash_between_handover_and_commit_restores_care`。
5. **告警 key 撞车**：阶段 `grow:1` 的任务 `water` 与阶段 `grow` 的任务 `1:water` 产生同一个 key，两条告警各归其主、互不合并。→ Task 5 `test_same_key_different_scope_stay_apart`。

---

### Task 1: 修正现有代码里的缺陷（不依赖开关）

**Files:**
- Modify: `src/growbridge/workflow/service.py`（`_replace_run_sheet`；`handback` 与 `_apply` 的交还前复核）、`src/growbridge/archive/store.py`（`add_measurement`）、`src/growbridge/agents/handlers_orchestrator.py`（`project_state`）、`src/growbridge/workflow/tasks.py`（`create` 的去重）
- Test: `tests/workflow/test_workflow_sheet_binding.py`、`tests/archive/test_archive_corrections.py`、`tests/agents/test_orchestrator_scoping.py`（目录按现有测试布局放）

**Interfaces:**
- `_replace_run_sheet`：新运行单的 `(project_id, experiment_id, device_id)` 与阶段记录不同 → `Denied("state", "a replacement run sheet keeps the stage's project, experiment and device")`。
- `add_measurement`：`corrects` 指向别的实验 → `ValueError`（工作台已转成 `rejected`）。
- `project_state`：`active_stage` 仅当活动阶段的 `project_id == data.project_id` 时给出，否则 `None`。
- 交还前复核：`handback()` 在 `await control.differences(...)` 之后、`control.handover(...)` 之前重新读阶段，`rev` 或状态变了 → `Denied("state", "stage changed while the request was running")`，不做任何交还；`_apply()` 在每次 `control.handover` 之前同样复核（保留最后的 CAS）。原因：`ControlService.handover()` 会无条件结束当前灌溉周期（`control/service.py:181`），迟到的交还会打断同一设备上别的阶段的灌溉（评审第 3 轮实测）。
- `TaskBoard.create`：`trigger_event_id` 已属于另一个项目的任务 → `Denied("state", "this trigger_event_id is already used")`，回答里不含那个任务的 id、状态或所属；同项目的重复行为不变。`handlers_orchestrator.py` 里拼出已有任务 id 的那条消息只在同项目时使用。

- [ ] **Step 1: 写失败测试** `test_replacement_cannot_change_device`、`test_replacement_cannot_change_experiment`、`test_correction_must_stay_in_experiment`（A 的测量数仍为 1）、`test_active_stage_of_other_project_is_hidden`、`test_trigger_of_other_project_is_refused_without_its_id`、`test_late_handback_does_not_end_other_irrigation`（handback 在读差异时挂起，期间阶段被停止、另一阶段启动并开始计划灌溉；恢复后 handback 被拒，灌溉未被结束——用真实 `ControlService` 与假设备 I/O，沿用 `tests/control` 现有夹具）。
- [ ] **Step 2–4: 失败 → 实现 → 通过**（再跑 `pytest tests/workflow tests/archive tests/agents -q`）。
- [ ] **Step 5: 提交** `fix: replacement run sheets keep their stage's binding; corrections, project state and task triggers stay inside their project`

### Task 2: 温室登记与开关（配置）

**Files:**
- Modify: `src/growbridge/config.py`
- Test: `tests/test_config_greenhouses.py`

**Interfaces:**
- `class Greenhouse(BaseModel)`：`id`（`^[a-z0-9][a-z0-9-]{0,31}$`）、`name`（1..64）、`device_id`；`Settings.multi_user: bool = False`、`Settings.greenhouses: list[Greenhouse] = []`；`Settings.greenhouse_registry() -> tuple[Greenhouse, ...]`（空列表时返回 `(Greenhouse(id="gh-01", name="Greenhouse 1", device_id=self.device),)`）。

- [ ] **Step 1: 写失败测试** `test_default_registry_is_the_local_device`、`test_ids_and_devices_unique`、`test_local_device_must_be_registered`、`test_multi_user_defaults_off`。
- [ ] **Step 2–4: 失败 → 实现 → 通过**（再跑 `pytest tests -q -k config`）。
- [ ] **Step 5: 提交** `feat: register greenhouses and a multi_user switch in the settings`

### Task 3: 角色与停用（账号）

**Files:**
- Modify: `src/growbridge/workbench/auth.py`（`STEPS` 追加 `ALTER TABLE operators ADD COLUMN role TEXT NOT NULL DEFAULT 'user'` 与 `ADD COLUMN disabled_at REAL`）、`src/growbridge/ports.py`（`Actor.role: Literal["user", "admin"] | None = None`）、`src/growbridge/cli.py`（`operator add --admin`）
- Test: `tests/workbench/test_workbench_accounts.py`

**Interfaces:**
- `Operators.add(name, secret, role="user")`；`role(name) -> str | None`；`disable(name)`（置 `disabled_at`、删其全部会话；未知名字 `ValueError`）；`reset_secret(name, secret)`（删其全部会话）；`active(name) -> bool`；`listing() -> list[dict]`（`name, role, created_at, disabled_at`）；`actor()` 填 `Actor.role`；停用用户登录按口令错误处理（同耗时、同拒绝码）。

- [ ] **Step 1: 写失败测试** `test_add_admin_role`、`test_default_role_is_user`、`test_disabled_cannot_log_in`、`test_disabled_user_session_ends`、`test_reset_secret_ends_sessions`、`test_listing_has_no_secrets`、`test_cli_add_admin`、`test_name_with_slash_is_manageable`（`lab/alice`）。
- [ ] **Step 2–4: 失败 → 实现 → 通过**（再跑 `pytest tests/workbench -q`）。
- [ ] **Step 5: 提交** `feat: operator roles, disabling and secret reset`

### Task 4: 锁表、释放与项目所有者（存储）

**Files:**
- Create: `src/growbridge/workflow/locks.py`
- Modify: `src/growbridge/workflow/store.py`（`STEPS` 追加：`ALTER TABLE wf_projects ADD COLUMN owner TEXT`；`ALTER TABLE wf_stages ADD COLUMN care_released INTEGER NOT NULL DEFAULT 0`；`CREATE TABLE wf_project_owner_events(id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, from_owner TEXT, to_owner TEXT NOT NULL, actor TEXT NOT NULL, at REAL NOT NULL, note TEXT NOT NULL)`）、`src/growbridge/workflow/recovery.py`（`restore_care` 跳过 `care_released = 1`）、`src/growbridge/workflow/service.py`（`create_project` 在 operator 时写 `owner`）、`src/growbridge/workflow/listing.py`、`src/growbridge/workflow/tasks.py`
- Test: `tests/workflow/test_workflow_locks.py`、`tests/workflow/test_workflow_owner.py`

**Interfaces:**
- `WorkflowStore`：`add_project(project_id, name, now, owner=None)`；`project_owner(project_id) -> str | None`；`set_project_owner(project_id, owner, actor, note, now, eligible: Callable[[], None])`（同一事务里先调 `eligible()` 复核转移条件，再改所有者并写事件表）；`device_unfinished(device_id) -> bool`（有状态不在 `ENDED`/`STOPPED` 的阶段）；`project_unfinished(project_id) -> bool`；`care_holder(device_id) -> StageRow | None`；`mark_care_released(stage_id)`。
- `project_summaries(store, limit, *, only_owner=None)`、`rounds_awaiting_choice(store, limit, *, only_owner=None)`、`count_rounds_awaiting_choice(store, *, only_owner=None)`；`TaskBoard.in_states(states, limit, *, only_owner=None)`、`TaskBoard.count_in_states(states, *, only_owner=None)`——`only_owner` 以 `JOIN wf_projects` 加进 `WHERE`，位于 `LIMIT` 之前。
- `class GreenhouseLocks(db, clock, registry, store: WorkflowStore, control: ControlPort)`（命名空间 `"greenhouse_locks"`）：
  - `lock(holder, ids) -> tuple[str, ...]`：一个事务内全锁或全不锁；占用 → `Denied("lock_taken", <被占编号>)`；重复或未知 → `Denied("state")`。
  - `async release(greenhouse_id, actor: str, *, force=False, note="")`：事务前检查（未结束阶段 → `greenhouse_busy`；非强制且不是持有者 → `not_lock_holder`）；`care_holder` 有养护写入权则 `await control.handover(number, "release")`；然后一个事务：复核同样两条（失败抛同样的码）、`update_stage(care_right=None)`、`mark_care_released`、删锁、记事件（`release` / `force_release`）。
  - `holder_of_device(device_id)`、`locked_at(device_id)`、`held_by(holder)`、`greenhouse(id)`、`overview()`、`events(limit=100)`。

- [ ] **Step 1: 写失败测试** `test_lock_is_all_or_nothing`、`test_lock_rejects_duplicates_and_unknown`、`test_two_threads_one_winner`、`test_release_hands_over_care_and_frees`（控制侧该写入权已交还；阶段 `care_right` 为空且 `care_released`）、`test_release_refused_while_stage_unfinished`、`test_release_only_own_unless_forced`、`test_release_loses_to_concurrent_submission`（在 `handover` 的 await 里插入一次提交）、`test_released_care_not_restored`、`test_crash_between_handover_and_commit_restores_care`（交还后让事务抛错，再按生产启动顺序 `control.startup()` → `workflow.on_restart()`：未完成的释放 → 锁仍在、得到新的有效养护写入权；已完成的释放 → 标记仍在、不签发）、`test_operator_becomes_owner`、`test_legacy_projects_have_no_owner`、`test_listings_filter_before_limit`。
- [ ] **Step 2–4: 失败 → 实现 → 通过**（再跑 `pytest tests/workflow -q`）。
- [ ] **Step 5: 提交** `feat: greenhouse locks with care hand-over on release, and project owners`

### Task 5: 告警的显式归属（不依赖开关）

**Files:**
- Modify: `src/growbridge/observer/alerts.py`（`STEPS` 追加 `scope_kind TEXT`、`scope_id TEXT` 两列与一个 `(kind, key, scope_kind, scope_id, resolved_at)` 索引；`Alert` 加同名可选字段；`raise_alert(kind, key, severity, message, scope: tuple[str, str] | None = None)` 与 `resolve(kind, key, scope=None)` 都按四元组查找；新增 `open_for_scope(kind_set, scope) -> list[Alert]`）
- 产生点与读者：`observer/stage_checks.py`（`_set` 增加 `stage_id` 参数；解除改用 `open_for_scope`）、`agents/handlers_auditor.py`（读与产生都按 `("stage", stage_id)`）、`observer/frozen_watch.py` 与 `observer/service.py`（构造参数 `device_id`）、`executor/watchdog.py`（告警回调增加 `scope` 关键字参数）、`runtime.py`（`_alert`/`alert`/`resolve_alert` 透传 `scope`；`stage_waiting`、`task_deadline`；构造观察者与冻结检查时传 `settings.device`；净增 ≤ 3 行，超出部分放 `runtime_access.py`）、`runtime_agents.py`（`agent_task` → `("project", task.project_id)`；`audit_task` → `("stage", id)`，无阶段时 `("project", task.project_id)`）
- Test: `tests/observer/test_alert_scope.py`

**Interfaces:**
- 归属：阶段类 `("stage", stage_id)`；`agent_task` / `task_deadline` → `("project", project_id)`；设备类 `("device", device_id)`；其余不给。

- [ ] **Step 1: 写失败测试** `test_scope_is_part_of_identity`、`test_same_key_different_scope_stay_apart`、`test_unscoped_legacy_row_not_merged_into_scoped`、`test_auditor_reads_by_scope_not_prefix`（B 的阶段 `grow` 读不到 A 的 `grow:1` 告警）、每个产生点一条断言其 `scope`（参数化，沿用各模块现有测试的夹具）。
- [ ] **Step 2–4: 失败 → 实现 → 通过**（再跑 `pytest tests/observer tests/executor tests/agents tests/e2e -q`）。
- [ ] **Step 5: 提交** `feat: alerts carry the stage, project or device they belong to`

### Task 6: 权限规则与工作流检查点

**Files:**
- Create: `src/growbridge/workflow/access.py`
- Modify: `src/growbridge/workflow/service.py`、`src/growbridge/workflow/recovery.py`（`record_onsite_check`）
- Test: `tests/workflow/test_workflow_access.py`、`tests/workflow/test_workflow_access_points.py`

**Interfaces:**
- `class Access(store, locks, local_device)`：`is_admin(actor)`；`require_project(actor, project_id, hidden: Callable[[], Exception])`（非 operator 通过；所有者通过；管理员 → `Denied("not_owner")`；其他 → `raise hidden()`）；`require_stage(actor, stage, hidden, emergency=False)`（`emergency` 且管理员通过；所有者但非锁定人 → `Denied("not_lock_holder")`）；`require_sheet_device(project_id, device_id)`（所有 actor 种类；所有者未锁该设备 → `Denied("not_lock_holder")`）；`require_admin(actor)`；`sees_project / sees_stage / sees_device / sees_alert`；`owner_filter(actor) -> str | None`。
- `WorkflowService.access: Access | None = None`（属性，Task 11 装配时赋值）。检查点：`save_protocol`、`create_round`、`choose_after_stop`、`abort_round` → `require_project`；`abort_round` 还要在它自己的事务开头（`service.py` 约 616 行）对 operator 再查一次当前所有者，不符则回滚（它在交还养护后才提交，期间项目可能被转移；评审第 3 轮实测）；`submit_run_sheet` → operator 时 `require_project`，并在**写入阶段的同一事务里** `require_sheet_device`；`approve`、`revoke_approval`、`resume_stage`、`takeover`、`handback`、`record_onsite_check`（在任何控制侧调用之前）、`switch_run_sheet`、`start_stage`（operator 时）→ `require_stage`；`pause_stage`（operator 时）、`stop_stage` → `require_stage(emergency=True)`。`hidden` 用该方法对不存在 id 的现有回答。检查抛出的码不得被 `_apply_once` 当作"已在目标状态"吞掉（它只吞 `state`；新码不是 `state`，加一条测试锁住）。

- [ ] **Step 1: 写失败测试**：设计第 6 节表格每行一允一拒；`test_admin_can_stop_but_not_approve`；`test_model_draft_needs_owner_lock`；`test_onsite_check_by_other_has_no_control_effects`；`test_refusal_not_swallowed_by_apply_once`；`test_abort_after_disable_and_transfer_is_refused`（A 的中止在交还养护时挂起，期间 A 被停用、项目转给 C，恢复后中止被拒、C 的轮次不变）；`test_access_none_unchanged`（`tests/workflow` 现有启动用例原样再跑）。
- [ ] **Step 2–4: 失败 → 实现 → 通过**（`wc -l` ≤ 800；再跑 `pytest tests/workflow tests/e2e -q`）。
- [ ] **Step 5: 提交** `feat: owner and lock-holder checks in the workflow`

### Task 7: 测试夹具

**Files:**
- Modify: `tests/workbench/workbench_support.py`
- Test: `tests/workbench/test_workbench_support_multi_user.py`

**Interfaces:**
- `Bench(..., multi_user=False, with_compute=False)`；为真时建 `GreenhouseLocks`（用 `RecordingControl`）与 `Access`，赋给 `workflow.access` 并传给 `create_workbench(access=...)`；`bench.user(name, role="user") -> TestClient`（已登录、已重新认证）；`bench.lock(client, *ids)`；`Bench.full(tmp_path)` 返回 `multi_user=True, with_compute=True` 且挂满可选服务的夹具；`bench.absent_twin()` 返回同配置、但不含 A 数据的第二个夹具，用于"同一 id 不存在"的对照。

- [ ] **Step 1: 写失败测试** `test_full_bench_mounts_every_optional_service`、`test_user_helper_logs_in`。
- [ ] **Step 2–4: 失败 → 实现 → 通过**（现有 `tests/workbench` 全过）。
- [ ] **Step 5: 提交** `test: a multi-user workbench fixture`

### Task 8: 工作台装配与写路由

**Files:**
- Create: `src/growbridge/workbench/scope.py`（`project_write(access, actor, project_id, hidden)`、`stage_write(access, actor, stage_id, hidden, emergency=False)`、`admin_only(access, actor)`，`access is None` 时直接返回）
- Modify: `workbench/api.py`（`create_workbench(..., access=None, locks=None)`；`manual_stage` → `stage_write`；`/measurements` → 实验所属项目；`/safety/approve` → 锁定人或管理员；`/drafts/run-sheet` 在 `access` 非空时拒绝模型令牌（`model_role`）；`/alerts/{id}/read` 不可见 → 与不存在同答；`/me` 加 `multi_user`、`role`、`greenhouses`；`STATUS_BY_CODE`）、`workbench/rounds.py`、`workbench/manual_tasks.py`、`workbench/analysis.py`、`workbench/holdouts.py`、`workbench/compute.py`（任务预算按任务项目；余额与结算 `admin_only`）
- Test: `tests/workbench/test_workbench_multi_user_writes.py`

- [ ] **Step 1: 写失败测试**：顶部一张写路由表（路径、方法、样例体），参数化 `test_b_cannot_write_a`（与 `absent_twin` 对同一 id 的回答完全相同）与 `test_a_can_write_own`；`test_compute_balance_admin_only`；`test_manual_write_and_irrigation_need_lock`；`test_model_token_draft_refused_when_multi_user`；`test_corrects_other_experiment_refused`；`test_goal_with_foreign_round_hidden`。
- [ ] **Step 2–4: 失败 → 实现 → 通过。**
- [ ] **Step 5: 提交** `feat: workbench writes need the project owner and the greenhouse lock`

### Task 9: 项目、轮次、阶段、回执的读取

**Files:**
- Create: `src/growbridge/workbench/visibility.py`（`READ_RULES: dict[str, str]`：`/wb` 下每个 GET 路径 → `"project" | "stage" | "round" | "receipt" | "device" | "alerts" | "inbox" | "compute" | "public" | "admin" | "self"`）
- Modify: `workbench/reads.py`（`/projects` 用 `only_owner`；`/projects/{id}`、`/stages/{id}/readings|measurements|history`）、`workbench/rounds.py`（`/rounds/{id}`、`/rounds/{id}/report`、`/stages/{id}/run-sheet`、对话）、`workbench/api.py`（`/stages/{id}`；`/receipts/{id}` 按回执的 `stage_id`，空则仅管理员，不可见时 404）、`workbench/manual_tasks.py`、`workbench/analysis.py`、`workbench/holdouts.py`（读）
- Test: `tests/workbench/test_workbench_multi_user_reads.py`

- [ ] **Step 1: 写失败测试** `test_every_get_route_is_registered`（对 `Bench.full` 的路由集合）；`test_b_cannot_see_a`（按 `READ_RULES` 类别参数化：B 对 A 的 id 的响应 == `absent_twin` 对同一 id 的响应，且响应文本不含 A 的其他 id）；`test_admin_sees_everything`；`test_projects_list_only_own`。
- [ ] **Step 2–4: 失败 → 实现 → 通过。**
- [ ] **Step 5: 提交** `feat: operators read only their own projects, rounds, stages and receipts`

### Task 10: 收件箱、告警、环境、安全、计算

**Files:**
- Modify: `workbench/reads.py`（`_inbox_routes`：阶段、轮次、任务、告警、计算都先按可见性取数，轮次与任务用 `only_owner`，再 `_cap`）、`workbench/api.py`（`/alerts` 用 `sees_alert`）、`workbench/environment.py`（锁定人或管理员，否则 `Denied("not_lock_holder")`；样本只取 `locks.locked_at(device)` 之后；`active_stage` 与告警计数只给可见的；不可见的 `experiment_id` 置 `null`）、`reads.py` 的 `/safety`（同上）、`workbench/compute.py` 与 `compute/overview.py`（普通用户：任务、作业、卡住的尝试只列自己项目的，用量只算这些，`balance` 与全局用量为 `null`）
- Test: `tests/workbench/test_workbench_multi_user_inbox.py`

- [ ] **Step 1: 写失败测试** `test_inbox_filters_before_sql_limit`；`test_system_alerts_admin_only`；`test_device_alerts_follow_lock`；`test_environment_starts_at_lock_time`；`test_environment_hides_previous_stage_and_experiment`；`test_safety_needs_lock`；`test_compute_overview_scoped`。
- [ ] **Step 2–4: 失败 → 实现 → 通过。**
- [ ] **Step 5: 提交** `feat: inbox, alerts, environment and compute show each operator their own`

### Task 11: 温室与管理路由，运行时装配

**Files:**
- Create: `src/growbridge/workbench/greenhouses.py`（`add_greenhouse_routes(router, operator, fresh, locks, access)`）、`src/growbridge/workbench/admin.py`（`add_admin_routes(router, fresh, operators, locks, store, access)`）、`src/growbridge/runtime_access.py`（`build_access(settings, db, clock, workflow, control) -> AccessParts | None`，`AccessParts = NamedTuple(locks, access)`；装配后 `workflow.access = parts.access`）
- Modify: `workbench/api.py`（`access` 非空时挂载）、`workbench/visibility.py`（`/wb/greenhouses` → `"self"`，`/wb/admin/*` → `"admin"`）、`runtime.py`（≤ 3 行）
- Test: `tests/workbench/test_workbench_greenhouses.py`、`tests/e2e/test_e2e_multi_user.py`

**Interfaces（全部在 `/wb` 下）:**
- `GET /greenhouses` → `{"greenhouses": [{"id","name","state": "free"|"mine"|"taken","locked_at"}]}`，管理员每项多 `"holder"`。
- `POST /greenhouses/lock`（fresh）`{"greenhouse_ids": [...]}` → `{"locked": [...]}`。
- `POST /greenhouses/{id}/release` → `{"released": id}`。
- `GET /admin/operators`（每项加 `unfinished_stages`：其名下项目的未结束阶段数）；`POST /admin/operators`（fresh，`{name, secret, role}`）；`POST /admin/operators/disable`（fresh，`{name}`）；`POST /admin/operators/secret`（fresh，`{name, secret}`）。
- `GET /admin/locks` → `{"locks": overview, "events": events}`。
- `POST /admin/greenhouses/{id}/release`（fresh，`{note}` 1..500）。
- `POST /admin/projects/{project_id}/owner`（fresh，`{owner, note}`）：原所有者须为空或已停用、项目无未结束阶段、新所有者存在且未停用，否则 `Denied("state", …)`。

- [ ] **Step 1: 写失败测试** `test_lock_flow_over_http`；`test_lock_needs_reauth`；`test_release_over_http`；`test_admin_force_release_needs_note`；`test_force_release_refused_while_stage_live`；`test_user_cannot_call_admin_routes`；`test_transfer_rules`（活跃所有者 → 拒；有未结束阶段 → 拒；停用所有者且阶段已停 → 通过，新所有者锁温室后可建新阶段）；`test_admin_list_marks_unfinished_stages`；端到端 `test_two_users_in_parallel`（12 个温室、本机 gh-01；A 锁 gh-01 经 HTTP 跑完模拟阶段到 `ended`；B 同时锁 gh-02..gh-04，B 的项目列表为空、读不到 A；A 释放后 B 可锁 gh-01）与 `test_multi_user_off_is_unchanged`（`growbridge simulate` 照常）。
- [ ] **Step 2–4: 失败 → 实现 → 全量门禁。**
- [ ] **Step 5: 提交** `feat: greenhouse and administrator routes, wired into serve`

### Task 12: 控制台与拒绝码

**Files:**
- Create: `src/growbridge/web/workbench/pages/greenhouses.js`、`pages/admin.js`；`tests/web/fixtures/greenhouses.json`、`admin-locks.json`、`admin-operators.json`
- Modify: `router.js`（`FLAT`、`PAGES`）、`ui/layout.js`（`me.multi_user` 时加「温室」，再 `me.role === "admin"` 时加「管理」）、`main.js`（`multi_user` 且无锁无项目时首页跳 `greenhouses`）、`pages/environment.js` 与 `pages/safety.js`（`not_lock_holder` 时显示说明与「去锁定温室」链接）、`pages/compute.js`（`balance` 为 `null` 时不显示余额录入与结算控件）、`denials.js`、`i18n/zh.js`、`i18n/en.js`、`i18n/codes.zh.js`、`i18n/codes.en.js`、`tests/web/fixtures/known-codes.json`、`tests/web/fixtures/me.json`、`tests/web/support/render-page.mjs`（新夹具路径）、`tests/web/leaks.test.mjs`（页面清单）、`tests/web/denials.test.mjs`（期望数量）、**两种语言的 `docs/wiki/*/Denial-Codes-and-Events.md`**（与 `denials.js` 同一提交，否则 `denials.test.mjs` 失败）
- Test: `tests/web/greenhouses-page.test.mjs`、`tests/web/admin-page.test.mjs`、`tests/web/router.test.mjs`（增补）

- [ ] **Step 1: 写失败测试**：温室页三种状态（`taken` 的复选框 `disabled`）；`lock_taken` 时提示被占编号并保留勾选；`greenhouse_busy` 时提示先结束阶段；`multi_user=false` 时导航无「温室」「管理」；普通用户导航无「管理」；环境页对 `not_lock_holder` 显示说明；`parseHash/hrefFor` 往返两条。
- [ ] **Step 2–4: 失败 → 实现 → 通过**（`node --test tests/web/*.test.mjs` 与 `pytest tests/docs -q`）。
- [ ] **Step 5: 提交** `feat: greenhouse and administration pages, and the new denial codes`

### Task 13: 其余文档与适配说明

**Files:**
- Modify: 两种语言的 `docs/wiki/*/Configuration-Reference.md`（`multi_user`、`greenhouses`）、`API-Reference.md`（新路由、`/me` 字段、模型令牌起草在多用户下被拒）、`Status-and-Known-Limitations.md`（多用户只在模拟设备与测试中验证；共享令牌入口暴露全部设备数据；协议与运行单 id 全局唯一，猜中 id 可知其存在；释放后、下一阶段前的新样本仍记在上一实验名下）、`CLI-Reference.md`（`--admin`）
- Create: `docs/multi-user-adaptation.md`（设计第 11 节，中英各一节，PR 引用）
- Test: `pytest tests/docs -q`

- [ ] **Step 1: 写文档。**
- [ ] **Step 2: 运行** `pytest tests/docs -q` → 通过；全量门禁。
- [ ] **Step 3: 提交** `docs: multi-user accounts, greenhouse locks and the adaptation notes`
