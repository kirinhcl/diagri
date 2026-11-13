# 工作台控制台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 DiAGRI 工作台做一个浏览器控制台：覆盖全部 42 条 `/wb` 接口，并新增它需要的 7 条只读接口。

**Architecture:**
- 后端：新的只读路由放在 `workbench/reads.py`，查询分别放在 `workflow/listing.py` 和 `archive/readings.py`。
- 前端：`web/workbench/` 下的原生 ES 模块，不需要构建。纯逻辑模块用 `node:test` 测；页面模块用开发脚本连上模拟 AC5，在内置浏览器里检查。
- 页面由 `GET /workbench` 提供，和现有控制台共用 `web/tokens.css`。

**Tech Stack:** Python 3.11+、FastAPI、SQLite（含 JSON1 扩展）、pytest；浏览器原生 ES 模块、SVG；Node 22 的 `node:test`。

**Spec:** `docs/superpowers/specs/2026-11-13-workbench-console-design.md`

## Global Constraints

- **CSP 不改：** `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`。
  - 不写内联脚本、`<style>` 和 `style=""`；`element.style` 可以用。
  - 不加载任何外部资源。
- **插入文本只用 `textContent` 或 `setAttribute`：** 控制台的 JS 里不能出现 `innerHTML`、`outerHTML`、`insertAdjacentHTML`、`document.write`（任务 7 有测试守住）。
- **会话：** Cookie 是 `growbridge_operator`（HttpOnly，`path=/wb`）。所有非 GET 请求带 `x-growbridge-ui: 1`。`fetch` 用默认的 same-origin 凭据。
- **重新认证：** 收到 `reauth_required` 最多弹一次窗、重试一次。`REAUTH_SECONDS` 为 300。
- **拒绝的格式：**
  - 业务拒绝返回 `{"detail": {"code", "message"}}`。
  - 状态码：`state` 409，`session` 401，`locked` 429，其余 403。
  - 请求体校验失败是 422，格式为 `{"detail": [{"loc", "msg", ...}]}`。
- **新的只读接口只限操作员：** 没登录返回 401 `session`，模型令牌返回 403 `model_role`。
- **接口改动范围：** 不新增写接口。唯一改动的现有接口是 `GET /wb/me`，新增字段 `timezone`。
- **数量上限：**
  - `/inbox` 每类最多 50 条；
  - `/projects` 最多 200 个；
  - 项目详情里的任务最多 100 条；
  - `readings` 的 `points` 默认 600，取值范围 2 到 2000。
- **时间：** 显示和录入都用 `me.timezone`，旁边标出时区名。
- **刷新：** 待我处理和阶段页每 15 秒刷新一次，`document.hidden` 时暂停。
- **本地存储：** `localStorage` 只存语言偏好，键名 `growbridge-workbench-language`。不存密码和任何业务数据。
- **双语：** `zh` 和 `en` 的文案键完全一致。
- **规模与依赖：**
  - 文件不超过 800 行，函数不超过 50 行；
  - 不引入 npm 依赖；
  - Node 22 直接导入 `.js` 形式的 ES 模块（Node 22.12 及以上默认识别 ES 模块语法）。
- **Python 检查：** `ruff check src tests scripts`、`ruff format --check src tests scripts`、`pytest -q` 全部通过。测试不联网，不碰设备，不用真实凭据。
- **控制类操作不做乐观更新：** 成功后重新读取受影响的对象。
- **提交：**
  - 格式 `<type>: <description>`，不加署名行；
  - 在 `feat/workbench-console` 分支上工作；
  - 不推送，不切换分支。

## Review Focus

1. **重新认证之后服务器仍然返回 `reauth_required`：** 只重试一次，第二次的拒绝原样显示，不能再弹窗而陷入循环。→ 任务 5 的 `a second reauth_required is not retried again`。
2. **网络慢时连点按钮：** 上一次请求结束前，同一个操作不会再次发出。→ 任务 5 的 `singleFlight` 测试。
3. **夏令时切换附近录入时间：**
   - Europe/Helsinki 的 2027-03-28 03:30 不存在，必须报错，不能悄悄挪到别的时刻；
   - 2027-10-31 03:30 出现两次，取较早的一次，并显示换算出的 UTC 偏移。

   → 任务 6 的 `format.test.mjs`。
4. **阶段还没开始或没有样本：** `readings` 返回空，曲线显示"还没有数据"。→ 任务 2 和任务 3 的空数据测试，以及任务 6 的空序列测试。
5. **填表途中会话过期：** 重新登录后表单内容还在（密码字段除外），而且不会自动提交。→ 任务 5 的 `drafts.test.mjs`。

---

### Task 1: 列表查询

**Files:**
- Create: `src/growbridge/workflow/listing.py`
- Modify: `src/growbridge/workflow/tasks.py`（新增 `TaskBoard.in_states`）
- Test: `tests/workflow/test_workflow_listing.py`（用 `tests/workflow/conftest.py` 的 `world` 夹具：`await world.design()` 会建好项目、协议和轮次；存储层是 `world.svc.store`）

**Interfaces:**
- Produces:
  - `project_summaries(store: WorkflowStore, limit: int = 200) -> list[dict]`
    - 每项是 `{"project_id", "name", "created_at", "round_count", "latest_round": {"round_id", "state"} | None}`；
    - 按 `created_at` 排序，新的在前。
  - `project_detail(store: WorkflowStore, project_id: str) -> dict | None`
    - 返回 `{"project_id", "name", "created_at", "rounds", "protocols"}`；
    - `rounds` 每项是 `{"round_id", "state", "protocol_id", "protocol_version", "awaiting_choice", "created_at"}`，新的在前；
    - `protocols` 每个 id 只列最新版本 `{"protocol_id", "version", "created_at"}`；
    - 项目不存在时返回 `None`。
  - `rounds_awaiting_choice(store: WorkflowStore, limit: int = 50) -> list[dict]`
    - 列出 `awaiting_choice` 不为空的轮次：`{"round_id", "project_id", "awaiting_choice", "created_at"}`；
    - 旧的在前。
  - `TaskBoard.in_states(self, states: Collection[TaskState], limit: int = 100) -> tuple[ResearchTask, ...]`
    - 按 `seq` 排序，旧的在前。

- [ ] **Step 1: 写失败的测试**

```python
async def test_project_summaries_count_rounds_and_show_the_latest(world):
    await world.design()
    (summary,) = project_summaries(world.svc.store)
    assert summary["project_id"] == world.project_id and summary["round_count"] == 1
    assert summary["latest_round"] == {"round_id": world.round_id, "state": "designing"}

def test_project_summaries_without_projects_are_empty(world):
    assert project_summaries(world.svc.store) == []

async def test_project_detail_lists_only_the_latest_protocol_version(world):
    # save version 2 of the round's protocol with world.svc.save_protocol(..., world.op)
    assert [p["version"] for p in project_detail(world.svc.store, world.project_id)["protocols"]] == [2]

def test_project_detail_of_an_unknown_project_is_none(world):
    assert project_detail(world.svc.store, "nope") is None

async def test_rounds_awaiting_choice_lists_only_waiting_rounds(world):
    await world.design()
    assert rounds_awaiting_choice(world.svc.store) == []
    world.svc.store.update_round(world.round_id, awaiting_choice="stage-1")
    assert [r["round_id"] for r in rounds_awaiting_choice(world.svc.store)] == [world.round_id]

def test_task_board_in_states_filters_across_projects(world):
    # board = TaskBoard(world.db, world.clock); board.create(...) one task in each of two
    # projects, then move one of them to needs_review
    assert [t.state for t in board.in_states({TaskState.NEEDS_REVIEW})] == [TaskState.NEEDS_REVIEW]
```

- [ ] **Step 2: 运行，确认失败**：`.venv/bin/pytest -q tests/workflow/test_workflow_listing.py`，预期是 ImportError。
- [ ] **Step 3: 实现上面四个函数。** 用 `store.db.query`，SQL 是固定文本，参数用 `?` 传入。
- [ ] **Step 4: 运行，确认通过**：同上命令，预期全部通过。
- [ ] **Step 5: 提交**：`feat: list projects, rounds and tasks for the workbench`

### Task 2: 按时间桶读取样本

**Files:**
- Create: `src/growbridge/archive/readings.py`
- Test: `tests/archive/test_archive_readings.py`（用 `tests/archive/conftest.py` 的 `db` 和 `archive` 夹具，样本用 `archive.append_sample(SampleRecord(...))` 写入）

**Interfaces:**
- Produces:
  - `DEFAULT_POINTS = 600`，`MAX_POINTS = 2000`。
  - `bucketed_samples(db: Database, experiment_id: str, start: float, end: float, points: int) -> dict`，返回：
    - `"samples"`：每项 `{"timestamp", "data", "quality", "clock_synced", "flagged"}`；
    - `"window"`：`{"start", "end", "bucket_seconds"}`；
    - `"total_samples"`、`"flagged_total"`、`"downsampled"`。

- [ ] **Step 1: 写失败的测试**

```python
def test_readings_keep_one_sample_per_bucket_and_say_so(archive, db):
    # 10 samples of experiment "e1" at t=0,10,...,90; points=5
    result = bucketed_samples(db, "e1", 0, 100, 5)
    assert len(result["samples"]) == 5 and result["total_samples"] == 10 and result["downsampled"]

def test_readings_count_flagged_samples_that_downsampling_drops(archive, db):
    # one bucket: first sample quality="suspect", last sample quality="ok"
    result = bucketed_samples(db, "e1", 0, 100, 1)
    (sample,) = result["samples"]
    assert sample["quality"] == "ok" and sample["flagged"] == 1 and result["flagged_total"] == 1

def test_readings_count_unsynced_clocks_as_flagged(archive, db):
    # a sample with clock_synced=False
    assert bucketed_samples(db, "e1", 0, 100, 600)["flagged_total"] == 1

def test_readings_leave_out_other_experiments_and_times(archive, db):
    # e1 at t=50 and t=500, e2 at t=50; window 0..100
    assert [s["timestamp"] for s in bucketed_samples(db, "e1", 0, 100, 600)["samples"]] == [50]

def test_readings_of_an_empty_window_are_empty(archive, db):
    result = bucketed_samples(db, "e1", 0, 100, 600)
    assert result["samples"] == [] and result["total_samples"] == 0 and not result["downsampled"]
```

- [ ] **Step 2: 运行，确认失败**：`.venv/bin/pytest -q tests/archive/test_archive_readings.py`
- [ ] **Step 3: 实现。** 时间桶宽度取 `max(1.0, (end - start) / points)`。每个桶取最后一个样本，与 `growbridge/store.py` 的 `series` 做法一致，同时数出桶内有问题的样本：

```sql
SELECT MAX(rowid) AS pick, COUNT(*) AS n,
       SUM(json_extract(body, '$.quality') != 'ok'
           OR json_extract(body, '$.clock_synced') = 0) AS flagged
FROM samples WHERE experiment_id = ? AND at BETWEEN ? AND ?
GROUP BY CAST((at - ?) / ? AS INTEGER)
```

  再按 `pick` 取出 `at` 和 `body`，按 `at` 排序。`data` 取自 body 里的 `data` 字段。
- [ ] **Step 4: 运行，确认通过**
- [ ] **Step 5: 提交**：`feat: read archived samples in time buckets with flagged counts`

### Task 3: 只读路由，以及 `/me` 返回时区

**Files:**
- Create: `src/growbridge/workbench/reads.py`
- Modify:
  - `src/growbridge/workbench/api.py`：在 `Workbench.__init__` 的 `_read_routes()` 之后调用 `add_read_routes`；`me()` 返回值加上 `"timezone": self.settings.report_timezone`。
- Test: `tests/workbench/test_workbench_reads.py`（用 `bench` 和 `operator` 夹具，以及 `bench.pending()`、`bench.seed_round()`、`bench.model()`）

**Interfaces:**
- Consumes: 任务 1 和任务 2 的全部函数。
- Produces:
  - 函数签名：`add_read_routes(router: APIRouter, operator: Any, workflow: WorkflowService, archive: Archive, control: ControlPort, clock: Clock, *, tasks: TaskBoard | None = None, budget: CallBudget | None = None, alerts: AlertBook | None = None, compute: ComputeService | None = None) -> None`。
  - 路径参数用 `workbench/rounds.py` 的 `PathId`。
  - 找不到对象时抛 `Denied("state", ...)`。
  - 新增路由：
    - **`GET /wb/inbox`** → `{"items": [...]}`。
      - 每项是 `{"kind", "id", "project_id", "round_id", "since", "detail"}`。
      - `kind` 取以下之一：`stage_review`、`stage_manual`、`stage_recovery`、`stage_paused`、`round_choice`、`alert`、`compute_stuck`、`task`。
      - 阶段的 `since` 取 `store.entered(stage_id, state)` 的时间，没有就用 `state_at`。
      - 按 `since` 排序，旧的在前。
      - 每类最多 50 条；对应服务没有时，那一类就为空。
    - **`GET /wb/projects`** → `{"projects": project_summaries(...)}`。
    - **`GET /wb/projects/{project_id}`** → `project_detail(...)`，再加两项：
      - `"budget"`：`{"calls_left", "cost_left"}`；没有设预算（`Denied` 码为 `budget`）时为 `None`；
      - `"tasks"`：最多 100 条，每条用 `model_dump(mode="json")`。
    - **`GET /wb/stages/{stage_id}/readings?points=`**
      - 时间窗从 `started_at` 开始；阶段处于 `ended` 或 `stopped` 时到 `state_at` 结束，否则到 `clock.now()`。
      - 还没开始的阶段返回 `{"samples": [], "window": None, "total_samples": 0, "flagged_total": 0, "downsampled": False}`。
    - **`GET /wb/stages/{stage_id}/measurements`** → `{"measurements": [...]}`，数据来自 `archive.measurements(experiment_id, include_corrected=True)`。
    - **`GET /wb/stages/{stage_id}/history`** → `{"history": store.history(stage_id), "interventions": [...]}`。`interventions` 取自 `store.interventions(experiment_id)`，只保留属于这个阶段的条目。
    - **`GET /wb/safety`** → `{"safety": <SafetyConfig 的 JSON> | None}`。

- [ ] **Step 1: 写失败的测试**

```python
READS = ["/wb/inbox", "/wb/projects", "/wb/projects/p", "/wb/stages/s/readings",
         "/wb/stages/s/measurements", "/wb/stages/s/history", "/wb/safety"]

@pytest.mark.parametrize("path", READS)
def test_reads_need_a_logged_in_operator(bench, path):
    response = bench.lan.get(path)
    assert response.status_code == 401 and response.json()["detail"]["code"] == "session"

@pytest.mark.parametrize("path", READS)
def test_reads_refuse_model_tokens(bench, path):
    response = bench.lan.get(path, headers=bench.model())
    assert response.status_code == 403 and response.json()["detail"]["code"] == "model_role"

def test_inbox_shows_a_stage_waiting_for_review(bench, operator):
    bench.pending()
    kinds = {(i["kind"], i["id"]) for i in operator.get("/wb/inbox").json()["items"]}
    assert ("stage_review", "stage-1") in kinds

def test_inbox_caps_each_kind_at_fifty(bench, operator):
    # 51 rounds of one project with awaiting_choice set
    items = operator.get("/wb/inbox").json()["items"]
    assert sum(i["kind"] == "round_choice" for i in items) == 50

def test_projects_and_project_detail(bench, operator):
    bench.seed_round()
    assert operator.get("/wb/projects").json()["projects"][0]["project_id"] == bench.project_id
    detail = operator.get(f"/wb/projects/{bench.project_id}").json()
    assert detail["rounds"][0]["round_id"] == bench.round_id and detail["budget"] is None

def test_an_unknown_project_is_a_state_refusal(operator):
    response = operator.get("/wb/projects/nope")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "state"

def test_readings_of_a_stage_not_started_are_empty(bench, operator):
    bench.pending()
    body = operator.get("/wb/stages/stage-1/readings").json()
    assert body["samples"] == [] and body["window"] is None

@pytest.mark.parametrize("points", [1, 2001])
def test_readings_points_out_of_range_are_rejected(bench, operator, points):
    bench.pending()
    assert operator.get(f"/wb/stages/stage-1/readings?points={points}").status_code == 422

def test_readings_cover_only_the_stage_window(bench, operator):
    # set started_at=100 on stage-1 via workflow.store.update_stage; samples of
    # "experiment-stage-1" at 50 and 150; clock at 200
    stamps = [s["timestamp"] for s in operator.get("/wb/stages/stage-1/readings").json()["samples"]]
    assert stamps == [150]

def test_history_of_a_stage_lists_its_transitions(bench, operator):
    bench.pending()
    assert operator.get("/wb/stages/stage-1/history").json()["history"]

def test_safety_is_null_until_approved(bench, operator):
    assert operator.get("/wb/safety").json() == {"safety": None}
    bench.control.approve_safety(make_safety(), "alice")
    assert operator.get("/wb/safety").json()["safety"] is not None

def test_me_reports_the_timezone(operator):
    assert operator.get("/wb/me").json()["timezone"] == "UTC"

def test_reads_work_on_the_overlay_entry(bench):
    assert bench.login(bench.overlay).status_code == 200
    assert bench.overlay.get("/wb/inbox").status_code == 200
```

- [ ] **Step 2: 运行，确认失败**：`.venv/bin/pytest -q tests/workbench/test_workbench_reads.py`
- [ ] **Step 3: 实现 `add_read_routes` 并接入 `Workbench`**
- [ ] **Step 4: 运行这个文件，再跑全部工作台测试**：`.venv/bin/pytest -q tests/workbench`
- [ ] **Step 5: 提交**：`feat: workbench reads for the console`

### Task 4: 页面外壳、共用设计变量、打包、CI 和开发脚本

**Files:**
- Create:
  - `src/growbridge/web/tokens.css`：把 `style.css` 第 1–21 行的 `:root { ... }` 整块原样移过来；
  - `src/growbridge/web/workbench.html`；
  - `src/growbridge/web/workbench/main.js`：暂时只渲染一行 "DiAGRI"，任务 7 再替换；
  - `src/growbridge/web/workbench/workbench.css`；
  - `scripts/dev_workbench.py`。
- Modify:
  - `src/growbridge/web/style.css`：删掉移走的那一块；
  - `src/growbridge/web/index.html`：在 `style.css` 之前加 `<link rel="stylesheet" href="/assets/tokens.css" />`；
  - `src/growbridge/api.py`：在 `create_app` 里，仅当 `workbench is not None` 时注册 `GET /workbench`，用 `FileResponse(web / "workbench.html")` 返回；
  - `pyproject.toml`：`package-data` 增加 `"web/workbench/*.js"`、`"web/workbench/*.css"`、`"web/workbench/i18n/*.js"`、`"web/workbench/ui/*.js"`、`"web/workbench/pages/*.js"`；
  - `.github/workflows/ci.yml`：把 `node --check src/growbridge/web/app.js` 换成 `for f in src/growbridge/web/app.js $(find src/growbridge/web/workbench -name '*.js'); do node --check "$f"; done`。
- Test:
  - `tests/workbench/test_workbench_page.py`
  - `tests/test_web_packaging.py`
  - `tests/test_dev_workbench_script.py`

**Interfaces:**
- Produces:
  - **`workbench.html`：**
    - `<html lang="zh-CN">`，带 `meta charset`、`viewport`、`color-scheme: light`，`<title>DiAGRI 工作台</title>`；
    - 依次引用 `/assets/tokens.css` 和 `/assets/workbench/workbench.css`；
    - 用 `<script type="module" src="/assets/workbench/main.js">` 加载脚本；
    - 页面主体是 `<div id="app">`，外加一段 `<noscript>`。
  - **`dev_workbench.py`：**
    - 端口：`DEV_PORT = 8765`，`DEV_LAN_PORT = 8770`；
    - 需要环境变量 `GROWBRIDGE_DEV_SECRET`，至少 12 个字符；缺少时退出码非零，并提示变量名；
    - 设置：`Settings(device="SIMULATED", token=secrets.token_urlsafe(32), data_dir=<--data-dir 或临时目录>, controls_enabled=True, pump_cooldown_seconds=0, auto_research=True, port=DEV_PORT, lan_bind="127.0.0.1", lan_port=DEV_LAN_PORT, lan_hosts=["localhost"])`；
    - 运行时：`build_runtime(settings, lambda _: SimulatedTransport(), channels={})`，用真实时钟；
    - 按 `cli._add_operator` 的做法添加操作员 `dev`；
    - 数据准备：
      - 以 `dev` 身份审批 `make_safety()`；
      - 建一个项目、一份 `make_protocol(...)`、一个轮次；
      - 以 `Actor(kind="model", id="planner")` 身份提交 `make_run_sheet(...)`，得到一个 `pending_review` 阶段（参照 `runtime._design_and_start`，但不审批、不启动）；
    - 启动：调用 `runtime.start()`，后台跑 `cli._tick_forever(runtime)`，再用 `cli._serve_listeners(app, settings)` 提供服务，并打印 `http://localhost:8770/workbench`。

- [ ] **Step 1: 写失败的测试**

```python
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")

def test_workbench_page_is_served_with_the_security_headers(bench):
    response = bench.lan.get("/workbench")
    assert response.status_code == 200 and response.headers["content-security-policy"] == CSP

def test_workbench_page_has_no_inline_script_or_style(bench):
    html = bench.lan.get("/workbench").text
    assert "<style" not in html and " style=" not in html
    assert re.findall(r"<script(?![^>]*\bsrc=)", html) == []

def test_workbench_page_loads_only_same_origin_assets(bench):
    links = re.findall(r'(?:src|href)="([^"]+)"', bench.lan.get("/workbench").text)
    assert links and all(link.startswith("/assets/") for link in links)

def test_workbench_page_is_absent_without_the_workbench(tmp_path):
    # create_app(settings, bridge=object(), workbench=None)
    assert client.get("/workbench").status_code == 404

def test_every_web_asset_is_in_the_package_data():
    # a file matches a glob when both have the same number of "/" parts and each part
    # matches with fnmatch.fnmatchcase (setuptools package-data semantics, no "**")
    assert unmatched == []

def test_both_pages_share_the_design_tokens():
    assert "--ink: #172e28" in tokens_css and "--ink:" not in style_css
    assert index_html.index("/assets/tokens.css") < index_html.index("/assets/style.css")

def test_dev_workbench_refuses_to_start_without_a_secret():
    # subprocess: python scripts/dev_workbench.py with GROWBRIDGE_DEV_SECRET removed from env
    assert result.returncode != 0 and "GROWBRIDGE_DEV_SECRET" in result.stderr
```

- [ ] **Step 2: 运行，确认失败**：`.venv/bin/pytest -q tests/workbench/test_workbench_page.py tests/test_web_packaging.py tests/test_dev_workbench_script.py`
- [ ] **Step 3: 实现。** 抽取设计变量前，先在内置浏览器里截一张现有控制台 `/` 的图。
- [ ] **Step 4: 检查是否通过**
  - 运行上面三个测试文件，再跑 `.venv/bin/pytest -q`；
  - 设置 `GROWBRIDGE_DEV_SECRET` 后启动 `.venv/bin/python scripts/dev_workbench.py`，打开 `http://localhost:8770/workbench`，应该看到 "DiAGRI"；
  - 打开 `/`，截图和抽取前对比，看不出差别。
- [ ] **Step 5: 提交**：`feat: serve the workbench page with shared design tokens and a dev server`

### Task 5: 请求封装、路由、文案、拒绝码和草稿

**Files:**
- Create：`src/growbridge/web/workbench/` 下的
  - `api.js`、`router.js`、`i18n.js`、`i18n/en.js`、`i18n/zh.js`、`denials.js`、`drafts.js`。
- Test：`tests/web/` 下的
  - `api.test.mjs`、`router.test.mjs`、`i18n.test.mjs`、`denials.test.mjs`、`drafts.test.mjs`。
- Modify：`.github/workflows/ci.yml`，加一步 `node --test tests/web/*.test.mjs`。

**Interfaces:**
- Produces:
  - **`api.js`**
    - `class ApiError extends Error`，字段有：
      - `status: number`；
      - `code: string | null`，是拒绝码；422 时为 `"validation"`，网络失败时为 `"network"`；
      - `fields: Array<{loc: string[], msg: string}>`，只在 422 时有值。
    - `createApi({ fetchImpl = fetch, askReauth, onSessionLost })` 返回 `{ get(path), post(path, body = {}, { action } = {}) }`。
      - `path` 不含 `/wb` 前缀，例如 `"/inbox"`。
      - `post` 发送 JSON，带 `content-type: application/json` 和 `x-growbridge-ui: 1`。
      - 遇到 `reauth_required`：调用 `await askReauth(action)`。
        - 返回 `null`：抛出原来的错误；
        - 否则：`POST /reauth {secret}`，然后把原请求重试一次。
      - 遇到 `session`：先调用 `onSessionLost()`，再抛出错误。
    - `singleFlight(fn)`：上一次调用的 promise 还没结束时，再调用就直接返回同一个 promise，不再调用 `fn`。
  - **`router.js`**
    - `parseHash(hash: string) -> { page, params }`，支持的地址和对应页面：

      | 地址 | 页面 |
      | --- | --- |
      | `#/` 或空字符串 | `inbox` |
      | `#/login` | `login` |
      | `#/projects` | `projects` |
      | `#/projects/:projectId` | `project` |
      | `#/rounds/:roundId` | `round` |
      | `#/stages/:stageId` | `stage` |
      | `#/alerts`、`#/evidence`、`#/compute`、`#/safety` | 同名页面 |
      | 其他 | `not_found` |

    - 参数用 `decodeURIComponent` 解码。
    - `hrefFor(page, params = {}) -> string`，参数用 `encodeURIComponent` 编码。
  - **`i18n.js`**
    - `LANGS = ["zh", "en"]`。
    - `makeT(lang)` 返回 `(key, vars = {}) => string`：支持 `{name}` 占位符；键不存在时原样返回键名。
    - `initialLang(stored, navigatorLanguage) -> "zh" | "en"`：优先用已存的偏好；否则浏览器语言以 `zh` 开头时取 `zh`，其余取 `en`。
  - **`i18n/en.js`、`i18n/zh.js`**：`export default { key: string }`。文案键用点号分组，例如 `inbox.empty`、`stage.irrigation.lanOnly`。
  - **`denials.js`**
    - `DENIALS[code] = { zh: {text, advice}, en: {text, advice} }`，涵盖：
      - Wiki 中 `## Denial codes` 一节表格第一列的 33 个码；
      - 前端自己用的 `validation` 和 `network`。
    - `describeDenial(code, lang) -> {text, advice} | null`。
  - **`drafts.js`**：草稿只存在内存里的 Map 中。
    - `saveDraft(key, values)`；
    - `takeDraft(key) -> object | null`，取出后即删除；
    - `stripSecrets(values, secretNames) -> object`。

- [ ] **Step 1: 写失败的测试**（`import test from "node:test"`，`import assert from "node:assert/strict"`）

```js
test("post sends JSON and the UI header", ...)        // headers["x-growbridge-ui"] === "1"
test("a denial becomes an ApiError with its code", ...) // 409 {"detail":{"code":"state"}} -> status 409, code "state"
test("422 keeps the field errors", ...)               // code "validation", fields[0].loc
test("retries once after reauth", ...)                // responses: 403 reauth_required, 200 (/reauth), 200 -> resolves; askReauth called once; 3 fetches
test("a second reauth_required is not retried again", ...) // 403, 200, 403 -> rejects code "reauth_required"; askReauth called once
test("a cancelled reauth sends nothing more", ...)    // askReauth -> null; 1 fetch; rejects
test("a lost session calls onSessionLost", ...)       // 401 {"code":"session"} -> called once; rejects
test("singleFlight ignores calls while one is pending", ...) // two calls -> fn once; after settle, a third call -> fn twice
test("parseHash reads pages and decodes ids", ...)    // "#/stages/s%201" -> {page:"stage", params:{stageId:"s 1"}}
test("unknown hashes are not_found", ...)
test("hrefFor and parseHash round-trip", ...)
test("zh and en have the same keys and no empty text", ...)
test("makeT fills placeholders and falls back to the key", ...)
test("every wiki denial code is described in both languages", ...)
// read docs/wiki/en/Denial-Codes-and-Events.md; take the `code` cells of the table under
// "## Denial codes" (33 rows); plus "validation" and "network"
test("takeDraft returns a draft once", ...)
test("stripSecrets removes password fields", ...)
```

- [ ] **Step 2: 运行，确认失败**：`node --test tests/web/*.test.mjs`
- [ ] **Step 3: 实现上面这些模块**
- [ ] **Step 4: 运行，确认通过**。另外对 `src/growbridge/web/workbench` 下每个文件跑一遍 `node --check`。
- [ ] **Step 5: 提交**：`feat: workbench console API client, routes, texts and denial messages`

### Task 6: 时间、曲线计算和配置差异

**Files:**
- Create：`src/growbridge/web/workbench/` 下的 `format.js`、`chart-math.js`、`diff.js`。
- Test：`tests/web/` 下的 `format.test.mjs`、`chart-math.test.mjs`、`diff.test.mjs`。

**Interfaces:**
- Produces:
  - **`format.js`**
    - `formatTime(epochSeconds, timeZone, lang) -> string`：格式为 `YYYY-MM-DD HH:mm`，24 小时制。
    - `offsetMinutes(epochSeconds, timeZone) -> number`。
    - `zonedToEpoch(local, timeZone) -> {epoch, offsetMinutes}`：`local` 形如 `"YYYY-MM-DDTHH:mm"`。
      - 先分别取该时刻前后 12 小时的两个偏移量作为候选；
      - 对每个候选算出 epoch，只保留换算回去后本地时间完全相同的那些；
      - 一个都没有时抛 `RangeError`；有两个时取较早的。
    - `formatNumber(value, precision, lang) -> string`：值为 null 或不是有限数时返回 `"—"`。
  - **`chart-math.js`**
    - `METRICS`：和 `web/app.js` 的 `metrics` 一致，包括：
      - `temp`（°C，1 位小数）、`humi`（% RH，1 位）、`vpd`（kPa，2 位）；
      - `co2`（ppm，0 位）、`ppfd`（µmol/m²/s，0 位）、`tempSoil`（°C，1 位）。
    - `metricValue(sample, key) -> number | null`：读取 `sample.data.sensor[key]`。
    - `seriesPoints(samples, key, { width, height, start, end })` 返回 `{ points: [{x, y, t, v, flagged}], min, max }`。
      - `flagged` 的条件：`sample.flagged > 0`，或 `quality !== "ok"`，或 `clock_synced` 为假。
      - 跳过空值。
      - 序列是常数时画成居中的水平线。
      - 没有数据时返回 `{points: [], min: null, max: null}`。
  - **`diff.js`**
    - `configDiff(before, after) -> [{path, before, after}]`。
    - 深度比较普通对象和数组；路径形如 `a.b[0].c`；新增的字段 `before` 为 `undefined`。

- [ ] **Step 1: 写失败的测试**

```js
const H = "Europe/Helsinki";
test("winter time converts at UTC+2", () =>
  assert.deepEqual(zonedToEpoch("2027-01-15T10:00", H), { epoch: Date.UTC(2027, 0, 15, 8, 0) / 1000, offsetMinutes: 120 }));
test("a time skipped by the spring change is refused", () =>
  assert.throws(() => zonedToEpoch("2027-03-28T03:30", H), RangeError));
test("a time repeated by the autumn change takes the earlier one", () =>
  assert.deepEqual(zonedToEpoch("2027-10-31T03:30", H), { epoch: Date.UTC(2027, 9, 31, 0, 30) / 1000, offsetMinutes: 180 }));
test("formatTime shows the zone's wall time", () =>
  assert.equal(formatTime(Date.UTC(2027, 0, 15, 8, 0) / 1000, H, "en"), "2027-01-15 10:00"));
test("formatNumber shows a dash for missing values", ...)
test("metricValue reads data.sensor and ignores non-numbers", ...)
test("seriesPoints marks flagged samples", ...)      // quality "suspect" -> flagged true
test("seriesPoints of no samples is empty", ...)     // {points: [], min: null, max: null}
test("a constant series is a centred line", ...)     // all y === height / 2
test("configDiff lists changed, added and removed paths", ...)
// configDiff({a:1,b:{c:[1,2]}}, {a:1,b:{c:[1,3]},d:4}) ->
// [{path:"b.c[1]",before:2,after:3},{path:"d",before:undefined,after:4}]
```

- [ ] **Step 2: 运行，确认失败**：`node --test tests/web/*.test.mjs`
- [ ] **Step 3: 实现**
- [ ] **Step 4: 运行，确认通过**
- [ ] **Step 5: 提交**：`feat: time zone, chart and config diff helpers for the console`

### Task 7: 应用外壳、登录和"待我处理"

**Files:**
- Create：`src/growbridge/web/workbench/` 下的
  - `ui/dom.js`、`ui/dialog.js`、`ui/forms.js`、`ui/layout.js`、`ui/status.js`；
  - `pages/login.js`、`pages/inbox.js`。
- Modify：`src/growbridge/web/workbench/` 下的 `main.js`（替换占位）、`workbench.css`。
- Test：`tests/web/no-html-injection.test.mjs`。

**Interfaces:**
- Consumes: 任务 5 和任务 6 的全部模块。
- Produces（后续页面都依赖这些约定）：
  - **`ui/dom.js`**
    - `h(tag, props = {}, ...children) -> Element`：
      - `props` 支持 `class`、`attrs`（用 `setAttribute` 设置）、`on`（`{事件名: 处理函数}`）、`text`；
      - 字符串子节点作为文本节点插入。
    - `svg(tag, attrs, ...children)`：在 SVG 命名空间里创建元素。
    - `clear(el)`。
  - **`ui/dialog.js`**
    - `askSecret(t, actionLabel) -> Promise<string | null>`：用 `<dialog>` 加密码框，关闭时清空输入。
    - `confirmAction(t, { title, lines, confirmLabel }) -> Promise<boolean>`。
  - **`ui/forms.js`**
    - `simpleForm({ fields, submitLabel, onSubmit, draftKey, timeZone })`：
      - 字段格式为 `{name, label, type, required?, options?, step?, value?}`，`type` 取 `text`、`number`、`datetime`、`select`、`textarea` 或 `password`；
      - `datetime` 字段旁边显示时区名，提交时用 `zonedToEpoch` 换算，换算出错就显示在该字段旁；
      - 提交按钮在 `onSubmit` 进行期间禁用（经过 `singleFlight`）；
      - 遇到 `ApiError` 时：有字段错误就显示在对应字段旁，否则显示 `describeDenial` 的说明和建议；`describeDenial` 返回 `null` 时显示服务器原文 `message`；
      - 码为 `state`（409）时，显示说明后调用 `ctx.reload()` 重新读取当前页面，因为对象可能刚被别人改过；
      - 会话丢失时，把除密码外的内容存成草稿（`draftKey`），回来后填回，不自动提交。
    - `jsonEditor({ label, value, submitLabel, onSubmit, draftKey })`：发送前先解析 JSON，解析失败当场提示；422 的错误按 `loc` 逐条列出。
  - **`ui/status.js`**
    - `statePill(t, state) -> Element`，样式分组如下：

      | 分组 | 状态 |
      | --- | --- |
      | `waiting` | `pending_review`、`manual`、`paused`、`needs_attention`、`needs_review`、`awaiting_choice` |
      | `onsite` | `recovery_check` |
      | `active` | `running`、`stage_running`、`designing`、`stage_review`、`data_verification`、`analysis`、`in_progress`、`computing`、`fetching`、`remote_queued`、`reconcile` |
      | `done` | `ended`、`stopped`、`delivered`、`aborted`、`done` |

  - **`ui/layout.js`**
    - `shell(ctx) -> { root, main, setBreadcrumbs(items), setCounts({inbox, alerts}) }`。
    - 内容包括：侧栏导航（待我处理、项目、告警、证据卡、计算、安全配置）、当前入口、语言切换、退出登录。
  - **页面约定：** `pages/*.js` 导出 `async function render(ctx, params)`，返回 `{ element, refresh?, pollSeconds? }`。
    - `ctx = { api, t, lang, me, navigate(href), notify(message, kind), reload() }`，其中 `me` 是 `/wb/me` 的返回值，`reload()` 重新渲染当前地址对应的页面。
  - **`main.js`**
    - 启动时：
      - 创建 `api`：`askReauth` 交给 `askSecret`；`onSessionLost` 记下当前地址，然后跳到 `#/login`；
      - `GET /me`，返回 401 就进入登录页。
    - 地址变化（`hashchange`）时重新渲染。
    - 页面带 `pollSeconds` 时定时调用 `refresh`，`visibilitychange` 时暂停或恢复。
  - **`pages/login.js`**
    - 提交姓名和密码，`POST /login`；
    - 成功后重新读取 `/me`，回到之前记下的地址，或者首页；
    - 遇到 `locked` 时显示 `login.locked`；
    - 每次提交后都清空密码框。
  - **`pages/inbox.js`**
    - 读取 `GET /inbox`，按 `kind` 分组显示，`pollSeconds` 为 15；没有条目时显示 `inbox.empty`。
    - 每条链接到对应页面：

      | `kind` | 跳转到 |
      | --- | --- |
      | 阶段类 | `#/stages/:id` |
      | `round_choice` | `#/rounds/:id` |
      | `alert` | `#/alerts` |
      | `compute_stuck` | `#/compute` |
      | `task` | `#/projects/:projectId` |

- [ ] **Step 1: 写失败的测试**

```js
test("console scripts never inject HTML", () => {
  // every .js file under src/growbridge/web/workbench
  for (const file of files) assert.doesNotMatch(source(file), /innerHTML|outerHTML|insertAdjacentHTML|document\.write/);
});
```

- [ ] **Step 2: 运行，确认失败**：先在任意页面文件里临时放一行 `el.innerHTML = ""`，确认测试会抓到，再删掉。
- [ ] **Step 3: 实现**
- [ ] **Step 4: 在浏览器里检查**（启动开发脚本，用内置浏览器打开 `http://localhost:8770/workbench`）：
  - 密码错误时显示翻译后的拒绝说明；
  - 登录后"待我处理"里有处于"待审批"的 `stage-1`；
  - 中英切换后整页文案都跟着变；
  - 能正常退出登录；
  - 在 1440、1024、768 三种宽度下都没有横向滚动；
  - 用 Tab 能走遍导航，焦点始终可见。
  - 然后运行 `node --test tests/web/*.test.mjs`。
- [ ] **Step 5: 提交**：`feat: workbench console shell, sign-in and inbox`

### Task 8: 项目与轮次页面

**Files:**
- Create：`src/growbridge/web/workbench/` 下的 `pages/projects.js`、`pages/project.js`、`pages/round.js`、`ui/table.js`。
- Modify：`i18n/en.js`、`i18n/zh.js`、`workbench.css`。

**Interfaces:**
- Consumes: 任务 7 的页面约定和 UI 模块。
- Produces:
  - `ui/table.js`：`table(columns, rows) -> Element`，其中 `columns` 形如 `[{label, cell: (row) => Node | string}]`。
  - 各页面与接口的对应（请求体字段以 `workbench/rounds.py`、`analysis.py`、`holdouts.py` 里的 Pydantic 模型为准）：

    | 页面 | 读取 | 写入 |
    | --- | --- | --- |
    | `projects` | `GET /projects` | 普通表单 `POST /projects`（`ProjectIn`） |
    | `project` | `GET /projects/{id}`；`GET /holdouts?project_id=` | `POST /rounds`：普通表单，协议从详情里的 `protocols` 中选；`POST /projects/{id}/budget`：普通表单（`BudgetIn`，需要重新认证）；`POST /protocols`：JSON 编辑框，预填一份最小协议示例；`POST /goals`：JSON 编辑框（`GoalIn`）；`POST /holdouts`：JSON 编辑框（`HoldoutIn`，需要重新认证） |
    | `round` | `GET /rounds/{id}`：阶段链接到 `#/stages/:id`；`GET /protocols/{protocol_id}/analysis` | `POST /rounds/{id}/choice`：只在 `awaiting_choice` 不为空时显示，选项按 `ChoiceIn`；`POST /rounds/{id}/abort`：先 `confirmAction`；`POST /protocols/{protocol_id}/analysis`：JSON 编辑框（`FreezeIn`，需要重新认证）；`POST /analysis/runs`：普通表单（`RunIn`，需要重新认证） |

  - 面包屑：项目 › 轮次。

- [ ] **Step 1: 在浏览器里逐条检查**（DOM 部分不写单元测试，在开发脚本上验证；新加的文案键由任务 5 的 `i18n.test.mjs` 守住两种语言一致）：
  - 新建项目后列表里能看到；
  - 设预算时会弹出重新认证；
  - 用不存在的协议发起轮次，会显示翻译后的拒绝说明；
  - 保存协议，一次故意写错 JSON，一次让服务器 422，两种错误都显示在对应位置；
  - 中止轮次前有确认框。
- [ ] **Step 2: 实现**
- [ ] **Step 3: 重做 Step 1 的检查**，然后运行 `node --test tests/web/*.test.mjs` 和 `node --check`，确认都通过。
- [ ] **Step 4: 提交**：`feat: projects and rounds pages of the workbench console`

### Task 9: 阶段页面

**Files:**
- Create：`src/growbridge/web/workbench/` 下的
  - `pages/stage.js`：状态、运行单、测量、历史、曲线；
  - `pages/stage-actions.js`：各种控制操作；
  - `ui/chart.js`。
- Modify：`i18n/en.js`、`i18n/zh.js`、`workbench.css`。

**Interfaces:**
- Consumes: 任务 6 的 `seriesPoints`、`METRICS`、`formatTime`、`formatNumber`；任务 7 的页面约定。
- Produces:
  - **`ui/chart.js`**：`readingsChart(t, readings, { timeZone, lang }) -> Element`。
    - 每个读数画一条小的 SVG 折线；
    - 有问题的样本画成空心点；
    - 每个点带 SVG `<title>`，内容是数值和时间（悬停时显示）；
    - 降采样时显示 `chart.downsampled`（带总样本数），有问题样本时显示 `chart.flagged`（带 `flagged_total`）；
    - 没有样本时显示 `chart.empty`。
  - **`stage.js`**，每 15 秒刷新：
    - `GET /stages/{id}`；
    - `GET /stages/{id}/readings?points=600`；
    - `GET /stages/{id}/run-sheet`：显示摘要和校验发现，有阻断性问题时审批按钮停用；
    - `GET /stages/{id}/measurements`：表格，标出更正链 `corrects`；
    - `GET /stages/{id}/history`：时间线。
  - **`stage-actions.js`**：按阶段状态显示可用的操作。服务器仍是最终裁决，被拒绝时显示原因。

    | 阶段状态 | 可用操作 |
    | --- | --- |
    | `pending_review` | approve（需要重新认证）、start；`POST /drafts/run-sheet`（JSON 编辑框，预填当前运行单） |
    | `running` | pause（可选附注）、stop（先确认）、takeover（需要重新认证，先确认） |
    | `paused` | resume（需要重新认证）、stop、takeover |
    | `manual` | `POST /manual/{channel}`（普通表单，通道和取值按 `ManualWrite`）、handback（按 `Handback`）、stop |
    | `recovery_check` | onsite-check（按 `Note`） |

    - `POST /irrigation` 在 `me.entry !== "lan"` 时停用，并说明 `stage.irrigation.lanOnly`。
    - 手动写入和浇水返回 `request_id` 后，每 2 秒查一次 `GET /receipts/{request_id}`，最多查 60 秒，显示 `receipt.applied`、`receipt.unknown` 或 `receipt.failed`。
    - 测量录入用普通表单 `POST /measurements`（`MeasurementIn`）：`experiment_id` 由阶段自动带入，`measured_at` 用 `datetime` 字段。

- [ ] **Step 1: 在浏览器里逐条检查**（开发脚本）：
  - 审批时弹出重新认证，审批后状态变化；
  - 启动后几分钟内出现环境曲线，并标明降采样；
  - 接管后用手动通道调灯光，回执显示"已生效"；
  - 交还和停止都有确认；
  - 录入一条测量，时区标签正确，列表里能看到；
  - 在 overlay 入口浇水按钮停用（可以用 `bench_without_lan` 那样的配置，或者直接从 127.0.0.1:8765 访问来确认）。
- [ ] **Step 2: 实现**
- [ ] **Step 3: 重做检查**，并运行 node 测试和 `node --check`。
- [ ] **Step 4: 提交**：`feat: stage page of the workbench console with readings chart`

### Task 10: 告警、证据卡、计算和安全配置页面

**Files:**
- Create：`src/growbridge/web/workbench/` 下的 `pages/alerts.js`、`pages/evidence.js`、`pages/compute.js`、`pages/safety.js`。
- Modify：`i18n/en.js`、`i18n/zh.js`、`workbench.css`。

**Interfaces:**
- Consumes: 任务 6 的 `configDiff`；任务 7 的页面约定。
- Produces：

  | 页面 | 读取 | 写入 |
  | --- | --- | --- |
  | `alerts` | `GET /alerts` | `POST /alerts/{event_id}/read` |
  | `evidence` | `GET /evidence` | `POST /evidence`：普通表单（`CardIn`）；`POST /evidence/{card_id}/verify`：普通表单（`VerifyIn`） |
  | `compute` | `GET /compute`：余额及录入人、时间，各任务预算与用量，进行中和卡住的尝试 | 以下都需要重新认证：`POST /compute/balance`；`POST /compute/tasks/{task_id}/budget`；`POST /compute/attempts/{attempt_id}/settle`（必须填原因，先确认） |
  | `safety` | `GET /safety` | `POST /safety/approve {config}`（需要重新认证） |

  安全配置页的细节：
  - 编辑框预填当前配置。
  - 还没有配置时，预填一份字段骨架：按 `SafetyConfig` 的字段写出完整结构，所有数值都填 `null`。这样原样提交会被服务器以 422 拒绝，不可能误批。
  - 审批前，`confirmAction` 逐行列出 `configDiff(current, edited)`，格式为"路径：旧值 → 新值"。

- [ ] **Step 1: 在浏览器里逐条检查**：
  - 告警能标为已读；
  - 能录入并核实证据卡；
  - 录入余额时弹出重新认证；
  - 安全配置改一个限值后，确认框里只列出这一项，审批后再读取，显示新值；
  - 没有配置时，原样提交会被拒绝。
- [ ] **Step 2: 实现**
- [ ] **Step 3: 重做检查**，并运行 node 测试和 `node --check`。
- [ ] **Step 4: 提交**：`feat: alerts, evidence, compute and safety pages of the workbench console`

### Task 11: Wiki 和最后一轮浏览器检查

**Files:**
- Modify（`docs/wiki/en/` 和 `docs/wiki/zh-CN/` 两种语言同时改）：
  - `API-Reference.md`：7 条新只读接口，`/wb/me` 的 `timezone`，更新路由总数；
  - `Enable-DiAGRI.md`：怎样打开控制台：在入口地址后加 `/workbench`，先用 `growbridge operator add` 建号；
  - `Status-and-Known-Limitations.md`：控制台已有，但只在模拟设备上检查过；
  - `Development-Setup-Testing-and-CI.md`：`node --test` 这一步和开发脚本；
  - `Code-Structure-and-Extension-Points.md`：新模块；
  - `Configuration-Reference.md`：`report_timezone` 同时决定控制台用的时区。
- Test: `tests/docs`（已有）

- [ ] **Step 1: 改 Wiki。** 用 `grep -rn "42\|38 routes\|38 条"` 找出提到旧路由数的地方，一并更新。
- [ ] **Step 2: 运行**：`.venv/bin/pytest -q tests/docs`，全部通过。
- [ ] **Step 3: 最后一轮浏览器检查**（开发脚本）：
  - 在 1440、1024、768 三种宽度下各走一遍：登录 → 待我处理 → 项目 → 轮次 → 阶段（审批 → 启动 → 出现曲线 → 接管 → 手动写入 → 交还 → 停止 → 轮次选择）→ 计算 → 安全配置；
  - 每种宽度截图，确认没有横向滚动、焦点可见、文字和背景对比度够；
  - 中英各走一遍。
- [ ] **Step 4: 全量检查**：`.venv/bin/pytest -q`、`ruff check src tests scripts`、`ruff format --check src tests scripts`、`node --test tests/web/*.test.mjs`，全部通过。
- [ ] **Step 5: 提交**：`docs: describe the workbench console in the wiki`
