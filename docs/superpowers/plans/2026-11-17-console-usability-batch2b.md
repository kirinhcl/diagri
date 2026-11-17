# 控制台可用性改造第二批 2b（拒绝原因带子码和参数）：实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 控制台能显示的每一种拒绝，都由服务器发粗码 `code`、细分原因 `reason` 和参数 `params`，控制台用中英文目录拼出两句话："发生了什么"和"下一步做什么"。范围：
- 全部 249 处 `Denied(...)`（2026-11-17 在 main `d7d479a` 上数过，103 处是 `state`）；
- `rejected()` 的 422，以及 `/wb` 上唯一没有码的错误（回执查询的 404）；
- 请求体校验失败的 422：Pydantic 已经给了结构化的 `type` 和 `ctx`，只改控制台；
- 根应用 `/api` 和 dashboard 上没有码的错误：只加字段，`detail` 仍是字符串。

粗码、HTTP 状态和英文 `message` 一律不变。

**架构：**
- **拒绝原因登记表：** 新文件 `S/denial_codes.py`，`DENIAL_CODES: dict[str, Code]`，键是 reason。`Code` 加一个字段 `of`，写它细分的粗码。`S/codes.py` 把它并成第九族 `CODES["denial"]`，导出时每项带上 `of`。
- **`Denied` 带上原因：** `Denied(code, message="", *, reason=None, params=None)`。构造时核对登记表，只记日志，不抛异常。`refusal()` 和 `rejected()` 在 `detail` 里加 `reason`、`params`。
- **防漏：** 一个 AST 测试要求每处 `Denied(...)` 和 `rejected(...)` 都带字面量 `reason=`，这个 reason 已登记，而且属于同一个粗码。还没改的文件列在测试的 `PENDING` 里；每个任务删掉自己的文件，最后一个任务删掉 `PENDING`。
- **控制台：** `ApiError` 带上 `reason`、`params`。`errorLines` 先查 `msg.denial.<reason>`；查不到时，用 `describeDenial(code)` 的粗码文字，这覆盖旧服务器、模型以及还没改的发出点。目录放在新文件 `W/i18n/denials.{en,zh}.js`。
- **校验错误：** 新文件 `W/validation.js`，按 Pydantic 的 `type` 写一句人话，参数取自它的 `ctx`。

**技术栈：**
- 控制台：原生 ES 模块，无构建、无依赖；测试用 `node --test tests/web/*.test.mjs`。
- 服务器：Python 3.12 加 FastAPI，用 `pytest`、`ruff`。
- 在 worktree 里跑 Python 要加 `PYTHONPATH=src`，因为共用的 `.venv` 指向另一个检出。
- **跑 `pytest` 用裸命令（和 CI 一样），不用 `python -m pytest`。** 后者会把当前目录放进 `sys.path`，让 `from tests.… import` 在本地能过、在 CI 上失败（2a 在 CI 上就栽在这里）。测试之间共享帮手，按模块名导入，例如 `from test_planning_design import alloc`（`tests/` 不是包）。

**设计：** `docs/superpowers/specs/2026-11-16-console-usability-design.md`，看"第二批"一节和"实现前已定的事项"第 5 条（用户已批准："设计通过"）。
**清单：** `docs/superpowers/specs/2026-11-16-console-usability-inventory.md`。第 3 节的编号是各行的正式编号；第 7 节是 2a 的结果。
**调研笔记（发出点细节）：**
- `docs/superpowers/research/2026-11-16-console-usability-denials-state.md`
- `docs/superpowers/research/2026-11-16-console-usability-denials-other.md`

  笔记里写着每个发出点所在的函数、现在的英文和能拿到的变量。行号是 2a 之前的，要按文件和函数找。本计划的 reason 表是定稿，和笔记不一致时以本计划为准。
**参数约定的出处：** `docs/superpowers/plans/2026-11-16-console-usability-batch2a.md` 的"参数约定"一节。本计划只做增补。

路径简写：
- `W/` = `src/growbridge/web/workbench/`
- `S/` = `src/growbridge/`
- `T/` = `tests/web/`
- `F/` = `tests/web/fixtures/`
- `<scratchpad>` = `/private/tmp/claude-1618820129/-Users-chenghao-Downloads-diagri/7aef49f1-45c9-4f52-92af-a0e7405f7e16/scratchpad`

## 本批覆盖的清单行

- **整行：** ERR-02 至 ERR-09。
- **补完的部分行：**
  - ERR-01：服务器发码和参数；控制台那一半第一批已做。
  - FRM-06：拒绝文字里的时长；告警和检查结果里的时长 2a 已做。
- **泄漏测试的豁免：** 没有标为 2b 的项。
- **不在本批：**
  - 第三批的 C5、C8、C9 各行；
  - 对话框仍不进防露出测试（清单 6.2）；
  - 旧 dashboard（`S/web/app.js`）的显示。它不属于控制台，本批只让它收到的错误多带几个字段。

## Global Constraints

- **G1 名字：** 用户看到的是名字或序号，不是 id。id 只出现在技术详情里，可复制。
- **G2 代码经目录：** 任何代码都通过对照表变成文字；对照表里没有的，显示"未知（技术详情）"，绝不直接显示代码。
- **G3 技术详情：** 全站一个折叠组件，默认收起，展开后每项可复制。
- **G4 数字和时间：** 时长按大小用天、小时、分钟、秒；档位写成"值 / 满档"；日期时间按界面语言格式化，时区只在页头写一次。
- **G5 消息格式：** 每条拒绝都是两句："发生了什么"加"下一步做什么"。下一步对读的人说（"请在项目页的预算一栏设置预算"），不说"请操作员……"。内部异常只显示固定的人话，异常类名进日志和技术详情。
- **粗码和状态不变：**
  - 每个发出点保留原来的粗码，即使调研笔记说它"用错了码"。例如没挂档案时仍是 `state`。改粗码会改 HTTP 状态（`state` 是 409，其余多是 403），旧客户端会看到不同的结果。
  - `reason`、`params` 只是新增字段。
- **英文 `message` 永远保留：** 日志、旧客户端、模型都读它。控制台把它放进技术详情（标签"服务器原文"）。可以删掉英文里的文档章节号（ERR-06），但不能删掉字段。
- **模型看到的文字不变：** 工具结果仍是 `denied (code): message`（`S/agents/tools.py`）。
- **登记表不能挡住拒绝：** reason 没登记、粗码对不上或参数不符时，`Denied` 只记一条日志，照常抛出。登记错误由测试抓。
- **API 只加不改：**
  - `/wb` 的错误体 `{"detail": {"code", "message"}}` 加上 `reason`（没有时为 `null`）和 `params`（没有时为 `{}`）。
  - 根应用 `/api` 的 `detail` 仍是字符串，`code`、`reason`、`params` 放在顶层。
  - 不要和请求体里已有的 `reason` 字段混淆：暂停的理由、计算尝试结算的理由都是操作员写的文字，与本批无关。
- **目录同步：**
  - 每个 reason 中英文各有正文；声明了下一步的，中英文都有 `.action`。
  - 键集合由 `T/i18n.test.mjs` 检查一致，`T/messages.test.mjs` 检查完整。
- **测试和代码规范：**
  - 照常 TDD、`pytest`、`ruff check`、`ruff format`。文件不超过 800 行，函数少于 50 行。
  - 测试不用浏览器、服务器和网络。
  - 控制台源码不得出现 `innerHTML`、`outerHTML`、`insertAdjacentHTML`、`document.write`。
- **读文件：** 先 grep，再每次读 30–60 行。
- **提交：** 信息用约定式前缀（`feat:`、`fix:`、`test:`、`docs:`），不加任何署名行，不跳过 pre-commit 钩子。

## 参数约定（2b 增补）

2a 的规则全部保留（`W/messages.js` 的 `formatterFor`）。下表是本批新增的参数名；需要别的名字时，先在本表和 `formatterFor` 里加规则。注意 2a 已经占用的名字：`min`、`max`、`level`、`expected` 是档位，`limit`、`bytes` 是字节数。范围、版本、上限不能用这些名字。

| 参数名 | 控制台怎么显示 |
|---|---|
| `phase`、`needed_state` | `labelOr(t, "state", v)`，和 2a 的 `state` 一样。计算尝试的阶段也用这套标签（`statePill`） |
| `status`、`from_status`、`to_status` | `labelOr(t, "tasks.status", v)`（任务状态） |
| `record_kind` | `labelOr(t, "recordKind", v)`。新标签：`project`、`round`、`protocol`、`run_sheet`、`stage`、`task`、`attempt`、`alert`、`evidence_card`、`holdout`、`snapshot`、`template`、`treatment`、`device`、`request` |
| `version`、`current_version`、`attempts`、`depth`，以及以 `max_` 或 `min_` 开头的名字 | `formatNumber(v, 0, lang)`。规则顺序：先看 `_seconds`（时长）、`_at`（时间），再看本条，所以 `max_seconds` 仍是时长 |
| `minimum`、`maximum`、`bound` | 原样的数字：`formatNumber(v, d, lang)`，`d` 是 `v` 本身的小数位数，最多 6 位 |
| `field`、`file` | 带引号的名字，和 2a 的 `rule` 一样：模板参数名和文件名是人起的名字，用户在表单或清单里看到的就是它 |
| `names`、`choices` | 每项按带引号的名字显示，用 `t("common.listSep")` 连接 |
| `sensors` | 每项 `labelOr(t, "metric", x)`，用 `t("common.listSep")` 连接 |
| `resource` | `labelOr(t, "computeUnit", v)`。新标签：`cpu_hours`、`storage_gb` |
| `need_amount`、`available_amount` | `formatNumber(v, 2, lang)` 加空格，再加 `labelOr(t, "computeUnit", params.resource)` |
| `expected_kind` | `labelOr(t, "paramKind", v)`。新标签：`int`、`float`、`str`、`bool` |
| 不能做占位符（只进技术详情）：以 `_digest` 结尾的，`diffs`、`paths`、`choice`、`detail`、`error` | — |

值缺失、为 `null` 或类型不对时，该占位符显示 "—"，界面上永远不出现 `{名字}`。这条 2a 已实现。

## reason 的命名和拆分规则

- **命名：**
  - 一个 reason 只细分一个粗码，全局唯一，用 snake_case。
  - 写情形，不写动作，例如 `stage_not_pausable`，不写 `pause_failed`。
- **合并和拆分：** 含义相同、下一步也相同的发出点合用一个 reason；下一步不同就拆开。
- **单义粗码：** 下面这些粗码只有一种含义，reason 就等于粗码本身（`reason="safety_conflict"`）。
  - `controls_disabled`、`right_held`、`pump_on_forbidden`、`request_id_reused`
  - `reauth_required`、`stale`、`member`、`model_unregistered`
  - `sandbox_unavailable`、`clock_unsynced`、`already_run`、`unavailable`
  - `not_operator`、`safety_conflict`
- **只有模型工具能走到的点：** 也要有 reason，因为设计要求"覆盖全部抛出点"。
  - 能用控制台的 reason 就复用。
  - 正文中英文照样要写；模型自己处理的，`action=False`。
- **登记的先后：** 表里的 reason 由第一个用到它的任务登记，后面的任务直接用。
- **表里没有的发出点：** 按本节规则补一行，参数名遵守参数约定，并在提交说明里点名这一行。
- **参数：** 只放发出点手里已有的值；为了参数去做新的查询，不做。
- **测试：** 每个 reason 至少一个测试，名字按 `test_<reason>_carries_<参数概括>`，断言 `exc.value.reason` 和 `exc.value.params`。同一个 reason 的其他发出点由 AST 测试兜底。

## Review Focus

1. **没有 reason 的拒绝。** 旧服务器、模型路径、还没改的点，以及 reason 不在目录里的：
   - 应显示：粗码的说明和建议，和今天一样；
   - 服务器原文、粗码，以及有的话 reason，进技术详情；
   - 不应出现：空白、英文正文、`{x}`。
   - 测试在 Task 2。
2. **reason 登记在别的粗码下（笔误），或参数和登记的不一致：**
   - 运行时只记日志，照常拒绝；
   - AST 测试抓字面量的粗码对不上；
   - 参数单测抓参数不一致。
   - 测试在 Task 1。
3. **5xx 的响应体里带了 reason：** 仍按"服务器出错，操作可能执行了也可能没有"显示，不当成明确的拒绝（`api.js` 对 5xx 一律给 `server_error`）。测试在 Task 2。
4. **旧客户端：**
   - `/wb` 的拒绝保留 `code`、`message` 和原来的状态码；
   - `/api` 的 `detail` 仍是字符串；
   - 模型的工具结果文字不变。
   - 测试在 Task 1、10、9。
5. **`state` 拒绝后表单会刷新页面（`forms.js` 的 `handleFailure`）：**
   - 刷新仍按粗码 `state` 触发，不受 reason 影响；
   - 提示文字改用 reason 的正文。
   - 测试在 Task 2。

---

### Task 1：服务器：`Denied` 带 reason 和 params，登记表，序列化

**Files:**
- Create: `S/denial_codes.py`
- Modify: `S/codes.py`（`Code` 加 `of`；`CODES["denial"]`；`export()`；新函数 `checked_denial`）、`S/ports.py:32-47`（`Denied`）、`S/workbench/api.py:137-141`（`refusal`）、`S/workbench/common.py`（`rejected`）
- Regenerate: `F/message-codes.json`（`PYTHONPATH=src python scripts/export_message_codes.py`）
- Test: `tests/workbench/test_denial_codes.py`（新）；`T/messages.test.mjs`：`FAMILIES` 加 `"denial"`，测试 "the code file names exactly the 8 families" 改名为 "…the 9 families"。导出文件一多出 `denial` 族，这个测试就会失败，所以和导出同一个任务改。

**Interfaces:**
- Produces:
  - `Code(params: tuple[str, ...] = (), action: bool = True, of: str | None = None)`。
  - `DENIAL_CODES: dict[str, Code]`，本任务为空，各任务往里加。`CODES["denial"] = DENIAL_CODES`。
  - `export()` 里 denial 族的每项是 `{"params": [...], "action": bool, "of": "<粗码>"}`；其他族不变。
  - `checked_denial(code: str, reason: str, params: Mapping[str, object]) -> dict[str, object]`：行为同 `checked("denial", …)`；另外，登记的 `of` 不等于 `code` 时记一条警告。永不抛异常。
  - `Denied(code: str, message: str = "", *, reason: str | None = None, params: Mapping[str, object] | None = None)`。属性 `code`、`reason`、`params`；`params` 是 dict，没给时为 `{}`。有 reason 时调用 `checked_denial`。
  - `refusal(error)` 的体：`{"detail": {"code": …, "reason": … | None, "params": {...}, "message": …}}`，状态仍按 `STATUS_BY_CODE`。
  - `rejected(message: str, *, reason: str | None = None, params: Mapping[str, object] | None = None) -> HTTPException`，体 `{"code": "param", "reason", "params", "message"}`，状态 422。
  - 测试模块里：
    - `REFUSAL_CALLS = {"Denied", "rejected"}`；
    - `refusal_sites(root: Path) -> list[Site]`，`Site` 是 `(path, line, code, reason)`，`code` 取第一个参数（`rejected` 记为 `"param"`），`reason` 取字面量关键字参数，没有时为 `None`；
    - `PENDING: set[str]`：本任务开始时，所有还有不带 reason 的拒绝的文件，路径相对 `src/growbridge`。

- [ ] **Step 1: 写失败的测试**（`tests/workbench/test_denial_codes.py`）

```python
def test_a_denial_keeps_code_and_message_and_carries_reason_and_params() -> None:
    error = Denied("state", "stage s1 is paused; it cannot pause",
                   reason="stage_not_pausable", params={"stage_id": "s1", "state": "paused"})
    assert error.code == "state" and str(error) == "stage s1 is paused; it cannot pause"
    assert error.reason == "stage_not_pausable"
    assert error.params == {"stage_id": "s1", "state": "paused"}

def test_an_old_style_denial_has_no_reason_and_empty_params() -> None:
    error = Denied("state", "x")
    assert error.reason is None and error.params == {}

def test_a_reason_under_another_code_is_logged_and_still_raised(monkeypatch, caplog) -> None:
    monkeypatch.setitem(DENIAL_CODES, "demo_reason", Code(("stage_id",), of="state"))
    error = Denied("scope", "m", reason="demo_reason", params={"stage_id": "s"})
    assert error.reason == "demo_reason"
    assert "demo_reason" in caplog.text and "scope" in caplog.text

def test_the_refusal_body_adds_reason_and_params_and_keeps_the_status() -> None:
    response = refusal(Denied("state", "m", reason="stage_not_pausable",
                              params={"stage_id": "s1", "state": "paused"}))
    assert response.status_code == 409
    assert json.loads(response.body)["detail"] == {
        "code": "state", "reason": "stage_not_pausable",
        "params": {"stage_id": "s1", "state": "paused"}, "message": "m"}

def test_an_old_style_refusal_body_has_a_null_reason_and_empty_params() -> None:
    detail = json.loads(refusal(Denied("budget", "m")).body)["detail"]
    assert detail == {"code": "budget", "reason": None, "params": {}, "message": "m"}

def test_rejected_carries_the_param_code_a_reason_and_params() -> None:
    error = rejected("too long", reason="id_length", params={"max_length": 64})
    assert error.status_code == 422
    assert error.detail == {"code": "param", "reason": "id_length",
                            "params": {"max_length": 64}, "message": "too long"}

def test_every_refusal_outside_pending_names_a_registered_reason_of_its_code() -> None:
    for site in refusal_sites(SRC):
        if site.path in PENDING:
            continue
        assert site.reason in DENIAL_CODES, site
        assert DENIAL_CODES[site.reason].of == site.code, site

def test_pending_lists_only_files_that_still_have_a_refusal_without_reason() -> None:
    open_files = {s.path for s in refusal_sites(SRC) if s.reason is None}
    assert PENDING == open_files

def test_every_registered_reason_is_sent_somewhere() -> None:
    sent = {s.reason for s in refusal_sites(SRC)} | sent_elsewhere()
    assert set(DENIAL_CODES) <= sent
```

`sent_elsewhere()` 本任务返回空集合。Task 10 让它再收集 `S/api.py`、`S/dashboard.py` 里新错误帮手的字面量 reason。`PENDING` 写成显式的集合字面量，初值就是本任务开始时 `open_files` 的结果：35 个有 `Denied` 的文件，再加上 `workbench/rounds.py` 和 `workbench/api.py` 里的 `rejected`，两者已在其中。

- [ ] **Step 2: 运行，确认失败**

Run: `PYTHONPATH=src pytest -q tests/workbench/test_denial_codes.py`
Expected: FAIL（`Denied() got an unexpected keyword argument 'reason'`、`cannot import name 'DENIAL_CODES'`）

- [ ] **Step 3: 实现上面 Interfaces 里的签名**

`ports.py` 从 `growbridge.codes` 导入 `checked_denial`。`codes.py` 不导入 `ports`，所以没有循环导入。`Denied` 的文档字符串加一段：说明 `reason`、`params` 的含义，并指向 `S/denial_codes.py`。

- [ ] **Step 4: 运行本文件、2a 的码测试和全部测试**

Run: `PYTHONPATH=src pytest -q tests/workbench/test_denial_codes.py tests/workbench/test_message_codes.py && PYTHONPATH=src pytest -q && node --test tests/web/*.test.mjs`
Expected: 全部 PASS。导出文件里多了空的 `"denial": {}`；2a 的一致性测试 `test_the_console_list_matches_the_registry` 仍过；`messages.test.mjs` 认 9 个族。

- [ ] **Step 5: 提交**

```bash
git add src/growbridge/denial_codes.py src/growbridge/codes.py src/growbridge/ports.py src/growbridge/workbench/api.py src/growbridge/workbench/common.py tests/web/fixtures/message-codes.json tests/workbench/test_denial_codes.py tests/web/messages.test.mjs
git commit -m "feat: let a refusal carry a registered reason and params"
```

---

### Task 2：控制台：拒绝原因的显示（ERR-01 控制台部分、ERR-09）

**Files:**
- Create: `W/i18n/denials.en.js`、`W/i18n/denials.zh.js`（导出空对象；各任务往里加 `msg.denial.<reason>`、`msg.denial.<reason>.action`）
- Modify:
  - `W/api.js:4-12,30-42`：`ApiError` 和 `toError`；
  - `W/ui/forms.js:58-90`：`errorLines`、`errorDetail`；
  - `W/messages.js`：参数约定的增补；
  - `W/i18n/en.js`、`W/i18n/zh.js`：展开 `denials`，加新键 `tech.reason`；
  - `W/i18n/codes.en.js`、`W/i18n/codes.zh.js`：`recordKind.*`、`computeUnit.*`、`paramKind.*`；
  - `W/denials.js`：`budget` 一行，ERR-09；
  - `W/ui/section.js`、`W/ui/layout.js`、`W/pages/login.js`、`W/pages/stage.js`、`W/pages/safety.js`、`W/main.js`：调用 `errorLines` 的地方，有 ctx 的传 ctx。
- Test: `T/denials.test.mjs`（新）、`T/api.test.mjs`（5xx 一条）

**Interfaces:**
- Consumes: Task 1 的错误体 `detail.reason`、`detail.params`；`F/message-codes.json` 的 `denial` 族。
- Produces:
  - `new ApiError(status, code, message, fields = [], { reason = null, params = {} } = {})`，属性 `reason`、`params`。`toError` 只在 `detail` 是对象时读这两个字段；`params` 不是普通对象时当作 `{}`。
  - `errorLines(error, lang, t, ctx = { lang, t })`，规则依次是：
    - 有 `error.reason` 且 `messageParts(ctx, "denial", reason, params).known` 时，返回 `[text, action]`（没有 action 时只有 `[text]`）；
    - 否则按原来的粗码规则。
  - `errorDetail` 在"代码"一行后面加两行：`[t("tech.reason"), reason]`；有参数时再加 `[t("tech.params"), params]`。

- [ ] **Step 1: 写失败的测试**（`T/denials.test.mjs`）

测试用的 `t` 是真实中文目录加两条演示键，因此不依赖真实目录里已有哪些 reason：
- `"msg.denial.demo_paused": "阶段现在是{state}，不能再暂停。"`
- `"msg.denial.demo_paused.action": "只有运行中的阶段能暂停。"`

`ctx` 照 `T/tech-details.test.mjs` 里表单测试的样子：`{ t, lang: "zh", me: { timezone: "UTC" }, notify, reload }`。

```js
test("a refusal with a known reason reads as its text and next step, with its params filled", () => {
  const error = new ApiError(409, "state", "stage s1 is paused; it cannot pause", [], { reason: "demo_paused", params: { state: "paused", stage_id: "s1" } });
  assert.deepEqual(errorLines(error, "zh", t, ctx), [`阶段现在是${t("state.paused")}，不能再暂停。`, "只有运行中的阶段能暂停。"]);
});
test("a refusal without a reason, or with a reason the catalog lacks, falls back to the code's text", () => {
  for (const reason of [null, "not_in_catalog"]) {
    const lines = errorLines(new ApiError(409, "state", "m", [], { reason }), "zh", t, ctx);
    assert.deepEqual(lines, [DENIALS.state.zh.text, DENIALS.state.zh.advice]);
  }
});
test("a refusal's reason and params are in the technical details, beside the server's words", () => { /* errorDetail rows: 原因代码 demo_paused, 参数 {…}, 服务器原文 m */ });
test("a refused form still reloads the page on a state refusal, and says the reason's text", () => {
  /* 照 T/tech-details.test.mjs 第 198 行附近的表单测试：提交被拒（409、code state、reason demo_paused）后，
     notify 收到 reason 的正文，reload 被调用一次 */
});
test("every registered reason, filled with sample params, shows no code, id, hash or epoch outside the details", () => {
  /* 遍历 F/message-codes.json 的 denial 族；每个参数按名字给样例值（时长 600、时间 1794821400、计数 3、
     state "running"、列表 ["a"] 等）；对 text 和 action 调 T/support/leaks.mjs 的 findLeaks，结果为空 */
});
test("the 2b param names format as the contract says", () => {
  /* formatterFor 表驱动：phase、from_status、record_kind、max_retries、minimum(0.25)、field、names、
     sensors、need_amount(2.5, resource cpu_hours)、expected_kind；*_digest、diffs、paths 返回 null */
});
test("the budget advice speaks to the reader, not about an operator", () => {
  assert.doesNotMatch(DENIALS.budget.zh.advice, /操作员/);
  assert.doesNotMatch(DENIALS.budget.en.advice, /an operator/i);
});
```

`T/api.test.mjs` 加一条，照该文件的 "a denial becomes an ApiError with its code"，用 `createApi({ fetchImpl })` 发请求：

```js
test("a 5xx answer with a reason in its body is still a server error", async () => {
  /* fetchImpl 返回 500，体为 { detail: { code: "state", reason: "demo_paused", message: "m" } } */
  assert.equal(error.code, "server_error");
  assert.equal(error.reason, null);
});
```

`messages.test.mjs` 的完整性测试（Task 1 已让它认 `denial` 族）会自动覆盖以后登记的每个 reason：中英文都有正文，`action` 和声明一致，占位符只用声明过、有规则的参数。

- [ ] **Step 2: 运行，确认失败**

Run: `node --test tests/web/denials.test.mjs tests/web/api.test.mjs`
Expected: FAIL（`ApiError` 没有 `reason`；`errorLines` 不认 reason）

- [ ] **Step 3: 实现**

- `errorLines` 的新分支放在 `network` 和 `OWN_REFUSAL` 之后、粗码查表之前。
- 新的标签值：
  - `recordKind.*` 用名词，例如"阶段"/"stage"；
  - `computeUnit.cpu_hours` 写"CPU 小时"/"CPU hours"，`storage_gb` 写"GB"；
  - `paramKind.*` 写"整数"、"数字"、"文字"、"是或否"，英文对应。
- ERR-09，`budget` 一行的建议改为：
  - zh："请在项目页的预算一栏设置或提高预算；在此之前，模型的工作会暂停。"
  - en："Set or raise the budget in the project's budget section; model work stays paused until then."

- [ ] **Step 4: 运行全部控制台测试**

Run: `node --test tests/web/*.test.mjs`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add src/growbridge/web/workbench tests/web
git commit -m "feat: show a refusal's reason as text and next step in the console"
```

---

### 发出点任务的共同步骤（Task 3 至 Task 9）

每个任务处理一组文件里的全部拒绝。下面每个任务只写文件、reason 表和特别说明，步骤都是这五步：

- [ ] **Step 1: 写失败的测试。** 每个 reason 至少一个，按"reason 的命名和拆分规则"里的测试规则，放在该模块已有的测试目录（例如 `tests/workflow/`）。另外从 `tests/workbench/test_denial_codes.py` 的 `PENDING` 里删掉本任务的文件。
- [ ] **Step 2: 运行，确认失败。** `PYTHONPATH=src pytest -q <本任务的测试文件> tests/workbench/test_denial_codes.py`。预期新测试 FAIL；AST 测试列出本任务里还没带 reason 的点。
- [ ] **Step 3: 实现。**
  - 在 `S/denial_codes.py` 登记本任务第一次用到的 reason；
  - 给每个发出点加 `reason=` 和 `params=`；
  - 在 `W/i18n/denials.{en,zh}.js` 写正文和下一步，遵守 G5；
  - 重新导出 `F/message-codes.json`。
- [ ] **Step 4: 运行全部测试。**
  - `PYTHONPATH=src pytest -q`
  - `node --test tests/web/*.test.mjs`
  - `ruff check src tests scripts`
  - `ruff format --check src tests scripts`

  预期全部 PASS。
- [ ] **Step 5: 提交。** `git commit -m "feat: give <区域> refusals a reason and params"`

表中"参数"一列不写 id 以外的类型：名字决定显示方式，见参数约定。粗码不是 `state` 的在"粗码"列写明。

---

### Task 3：工作流服务的拒绝（`S/workflow/service.py`，47 处；ERR-03、ERR-07）

| reason | 粗码 | 参数 | 情形 |
|---|---|---|---|
| `stage_not_awaiting_approval` | state | stage_id, state | 批准、撤回批准、改运行单时，阶段已不在待审 |
| `stage_not_startable` | state | stage_id, state | 启动时阶段不在待启动 |
| `stage_not_pausable` | state | stage_id, state | 暂停时阶段不在运行 |
| `stage_not_resumable` | state | stage_id, state | 继续时阶段不在暂停 |
| `stage_already_ended` | state | stage_id, state | 停止一个已结束的阶段 |
| `stage_not_takeoverable` | state | stage_id, state | 接管时阶段既不在运行也不在暂停 |
| `stage_not_in_manual` | state | stage_id, state | 手动操作或交还时阶段不在手动 |
| `stage_not_switchable` | state | stage_id, state | 切换运行单时阶段既不在运行也不在暂停（目前没有调用者） |
| `onsite_check_not_open` | state | stage_id, state | 确认现场检查时没有打开的检查 |
| `device_busy` | state | stage_id, device_id, other_stage_id | 同一设备上另一个阶段还在运行或检查中 |
| `unsettled_actions` | state | stage_id, count | 有结果未知的设备命令 |
| `device_differs_from_run_sheet` | state | stage_id, channels, diffs | 设备设置和运行单不同；`describe(diffs)` 的拼接改成结构化的 `diffs`（只进详情），`channels` 列出不同的通道 |
| `stage_changed_concurrently` | state | stage_id | 请求进行中别人改了这个阶段（版本冲突） |
| `irrigation_stage_not_running` | state | stage_id, state | 计划浇水只能在运行中执行 |
| `round_not_accepting_run_sheets` | state | round_id, state | 轮次已过设计和审阅，不再收运行单 |
| `run_sheet_mismatch` | state | run_sheet_id, record_kind | 运行单写的项目、协议、阶段或设备和目标不符；`record_kind` 是不符的那一项 |
| `run_sheet_needs_switch` | state | stage_id, state | 阶段已开始，运行单只能用切换来换 |
| `run_sheet_version_conflict` | state | run_sheet_id, version | 同一版本号已有不同内容 |
| `run_sheet_too_old` | state | run_sheet_id, version, current_version | 版本号不高于现行版本 |
| `run_sheet_version_in_use` | state | run_sheet_id, version | 这个版本已经存在 |
| `run_sheet_changed_since_review` | state | stage_id, expected_digest, current_digest | 审阅之后运行单变了 |
| `protocol_not_found` | state | protocol_id, project_id | 项目里没有这个协议 |
| `protocol_version_exists` | state | protocol_id, version | 同一协议版本已有不同内容 |
| `project_name_required` | state | — | 项目名为空 |
| `no_choice_pending` | state | round_id | 没有停下等决定的阶段 |
| `no_next_stage` | state | round_id | 已是最后一个阶段 |
| `unknown_choice` | state | choice | 选项不认识 |
| `round_already_ended` | state | round_id, state | 轮次已结束 |
| `round_not_in_project` | state | round_id, project_id | 目标里的轮次不属于这个项目 |
| `record_not_found` | state | record_kind, record_id | 按 id 找不到对象（各任务共用） |
| `approval_needs_approver` | approval_invalid | stage_id | 批准缺少批准人 |
| `approval_unknown_sensors` | approval_invalid | stage_id, sensors | 运行单用到设备没有的传感器 |
| `approval_blocking_findings` | approval_invalid | stage_id, count | 运行单还有阻断的检查结果 |
| `approval_none_valid` | approval_invalid | stage_id | 没有有效的批准 |
| `capabilities_changed` | approval_invalid | stage_id, detail | 批准之后设备能力变了（ERR-03 点名的情形）；原句进 `detail` |
| `approval_recovery_changed` | approval_invalid | stage_id | 批准之后恢复状态变了 |
| `safety_conflict` | safety_conflict | stage_id | 单义 |
| `pump_unconfirmed` | interlock | device_id | 水泵关闭没有确认 |
| `model_no_controls` | model_role | role | 模型角色不能运行阶段或批准 |

`service.py` 里的 1 处 `scope`，按调研笔记确定含义后补一行。如果它和 Task 4 的 `not_this_project` 同义，就在本任务先登记 `not_this_project`。

---

### Task 4：任务板、存储、权限、轮次和读接口（32 处 `Denied` 加 3 处 `rejected`；ERR-03、ERR-05）

**Files:**
- `S/workflow/tasks.py`、`store.py`、`recovery.py`、`permissions.py`
- `S/workbench/rounds.py`（含 3 处 `rejected`）、`reads.py`、`evidence.py`、`holdouts.py`、`compute.py`
- `S/observer/alerts.py`

| reason | 粗码 | 参数 | 情形 |
|---|---|---|---|
| `task_transition_not_allowed` | state | task_id, from_status, to_status | 任务不能从这个状态转到那个状态 |
| `task_end_needs_reason` | state | task_id | 结束任务没有写理由 |
| `task_board_conflict` | state | task_id, parent_task_id | 任务链接重复或指向别处（内部一致性问题） |
| `task_not_in_progress` | state | task_id, status | 任务不在进行中，不能发布 |
| `request_id_reused_for_other_goal` | state | task_id, request_id | 这个请求 id 已用于另一个目标 |
| `report_not_published` | state | round_id | 轮次还没有发布报告 |
| `report_file_missing` | state | round_id | 档案里没有报告文件 |
| `artifact_digest_mismatch` | state | round_id, artifact_id | 存储的文件和记录的校验值不符 |
| `archive_not_mounted` | state | — | 没有配置档案 |
| `budget_calls_exhausted` | budget | project_id | 模型调用次数用完 |
| `budget_cost_exhausted` | budget | project_id | 费用预算用完 |
| `budget_not_set` | budget | project_id | 项目没有预算 |
| `budget_revision_limit` | budget | task_id, max_revisions | 任务达到修改次数上限 |
| `drafter_only` | model_role | role | 只有起草角色能提交运行单 |
| `not_operator` | not_operator | — | 单义 |
| `reauth_required` | reauth_required | — | 单义 |
| `not_this_project` | scope | project_id | 对象不属于这个项目（留出、计算等） |
| `id_length` | param | max_length | 协议和项目 id 的长度不在 1 到 `max_length` 之间（`rejected`） |
| `protocol_version_range` | param | max_version | 协议版本不在 1 到 `max_version` 之间（`rejected`） |
| `numbers_not_finite` | param | paths | 协议里有非有限的数字；位置列表只进详情（`rejected`） |

另外复用 `record_not_found` 和 `stage_changed_concurrently`。`store.py` 的版本冲突用 `stage_changed_concurrently`。

---

### Task 5：设备控制（`S/control/service.py`、`S/control/rights.py`、`S/runtime.py`，33 处；ERR-04、FRM-06）

| reason | 粗码 | 参数 | 情形 |
|---|---|---|---|
| `other_host_registered` | host_unregistered | device_id | 另一台电脑是这台设备的写入主机 |
| `not_write_host` | host_unregistered | device_id | 这台电脑不是写入主机 |
| `controls_disabled` | controls_disabled | — | 单义 |
| `right_revoked` | right_invalid | right_id | 写入权已收回 |
| `right_from_old_recovery` | right_invalid | right_id | 写入权来自更早的一次恢复（ERR-04） |
| `right_unknown` | right_invalid | right_id | 不认识这个写入权 |
| `right_wrong_kind` | right_invalid | right_id | 浇水要用手动或阶段的写入权 |
| `right_voided` | right_invalid | right_id | 排队的动作已取消 |
| `right_needs_operator` | right_invalid | right_id | 这个写入权要操作员本人用 |
| `right_held` | right_held | device_id, stage_id | 单义 |
| `right_channel` | scope | right_id, channel | 写入权不包括这个通道 |
| `right_value` | scope | right_id, channel, level | 写入权不允许这个档位 |
| `right_binding` | scope | right_id, stage_id | 写入权不属于这个阶段 |
| `right_incomplete` | scope | right_id | 写入权缺少必要的范围 |
| `irrigation_seconds_range` | scope | seconds, max_seconds | 浇水时长不在"大于 0、至多 `max_seconds`"之内 |
| `unknown_device` | scope | device_id | 不认识这台设备 |
| `pump_on_forbidden` | pump_on_forbidden | — | 单义 |
| `state_unreadable` | not_connected | device_id, detail | 读不到设备状态；原因进 `detail` |
| `no_live_link` | not_connected | device_id | 没有可用的蓝牙连接（ERR-04） |
| `stale` | stale | device_id | 单义；发出点有数据年龄时加 `age_seconds` |
| `request_id_reused` | request_id_reused | request_id | 单义 |
| `still_starting` | unsettled | — | 服务还在启动 |
| `old_path_running` | unsettled | — | 旧的控制路径还在运行 |
| `unknown_result` | unsettled | count | 之前的动作结果未知 |
| `irrigation_running` | cooldown | device_id | 正在浇水 |
| `irrigation_too_soon` | cooldown | wait_seconds, ready_at | 两次浇水之间要等；写"再等 8 分钟"（ERR-04、FRM-06） |

另外复用 `pump_unconfirmed`（interlock）和 `not_operator`。`control/service.py` 里的 2 处 `approval_invalid`，复用 Task 3 的 reason；如果没有同义的，按规则补一行。

---

### Task 6：工作台入口、登录和人工任务（`S/workbench/api.py`、`auth.py`、`manual_tasks.py`，26 处 `Denied` 加 2 处 `rejected` 加 1 处 404；ERR-04、ERR-05、ERR-08）

| reason | 粗码 | 参数 | 情形 |
|---|---|---|---|
| `not_signed_in` | session | — | 没有登录 |
| `session_expired` | session | — | 会话已结束 |
| `bad_credentials` | session | — | 名字或密钥不对 |
| `login_locked` | locked | wait_seconds（发出点有时） | 登录失败太多次 |
| `unknown_address` | entry | — | 要从登记的地址打开 |
| `not_from_page` | entry | — | 要用工作台页面，不是脚本 |
| `session_other_entry` | entry | — | 会话属于另一个入口，要重新登录 |
| `onsite_only` | entry | — | 只能在现场地址做 |
| `manual_task_not_due` | state | task_id, due_at, opens_at | 任务还没到时间 |
| `irrigation_past_deadline` | state | task_id, due_at, deadline_at | 这次浇水已过期限 |
| `irrigation_already_ran` | state | task_id, due_at | 水泵已经（或可能已经）为这次浇水运行过 |
| `irrigation_already_done` | state | task_id, due_at | 这次浇水已记为完成 |
| `irrigation_attempts_exhausted` | state | task_id, stage_id, attempts | 多次尝试都没送到设备；`MAX_ATTEMPTS` 不再拼进英文 |
| `stage_not_started` | state | stage_id | 阶段还没开始 |
| `no_such_occurrence` | scope | task_id, due_at | 没有这个时间的任务 |
| `not_irrigation` | scope | task_id | 这个任务不是浇水 |
| `not_this_stage` | scope | stage_id | 测量不属于这个阶段 |
| `done_at_window` | param | window_seconds | 完成时间不在允许的范围内 |
| `skipped_has_time` | param | — | 跳过的任务不能带完成时间 |
| `level_out_of_range` | param | channel, level, min, max | 档位超出通道范围（`rejected`，来自 `check_level`） |
| `measurement_rejected` | param | detail | 测量没被接受；把被吞掉的 `ValueError` 文字放进 `detail` |
| `unknown_request` | state | request_id | 回执查询找不到请求 id |

`unknown_request` 那一处是 `HTTPException(404, "Unknown request id")`（`receipt` 路由）。它改成 `refusal()` 同样形状的体，状态仍是 404。

做法：
- 在 `S/workbench/api.py` 加 `def not_found(error: Denied) -> JSONResponse`。体和 `refusal` 相同，状态 404。
- 路由里**不要让这个 `Denied` 抛出去**，因为 `GuardedRoute` 会把它变成 409。要直接 `return not_found(Denied("state", "Unknown request id", reason="unknown_request", params={"request_id": …}))`。
- 不要改 `STATUS_BY_CODE`。
- AST 测试照样看得到这个字面量 reason。

测试断言状态 404，以及体里的 `code`、`reason`、`params` 和 `message`。

另外复用 `stage_not_in_manual`、`pump_on_forbidden`、`record_not_found`。

---

### Task 7：计算服务（`S/compute/service.py`，32 处；ERR-05）

| reason | 粗码 | 参数 | 情形 |
|---|---|---|---|
| `param_too_long` | param | field, max_length | 文字参数太长 |
| `param_bad_characters` | param | field | 文字参数含不允许的字符 |
| `param_bad_format` | param | field | 文字参数格式不对（`pattern`） |
| `param_not_in_choices` | param | field, choices | 不在可选值里 |
| `param_wrong_type` | param | field, expected_kind | 类型不对 |
| `param_not_finite` | param | field | 数字不是有限值 |
| `param_out_of_range` | param | field, minimum, maximum | 超出范围；只有一侧时只给那一侧 |
| `param_unknown_fields` | param | names | 模板没有这些参数 |
| `param_required` | param | field | 缺少必填参数 |
| `param_negative_amount` | param | field | 数量不能为负 |
| `param_bad_input_path` | param | field | 输入路径不对 |
| `param_input_missing` | param | field | 输入文件不存在 |
| `attempt_already_final` | state | attempt_id, phase | 尝试已结束 |
| `attempt_settled_by_operator` | state | attempt_id | 操作员已结算这个尝试 |
| `attempt_not_cancellable` | state | attempt_id, phase | 这个阶段的尝试不能取消 |
| `attempt_nothing_to_fetch` | state | attempt_id, phase | 这个阶段没有输出可取 |
| `attempt_outputs_over_limit` | state | attempt_id | 输出超过存储上限 |
| `attempt_no_storage_limit` | state | attempt_id, template_id | 不知道存储上限 |
| `attempt_not_retryable` | state | attempt_id, phase | 只有失败的尝试能重试 |
| `quota_not_recorded` | quota | task_id | 没有记录任务预算或项目余额 |
| `quota_over_task_budget` | quota | resource, need_amount, available_amount | 超过任务预算 |
| `quota_over_service_cap` | quota | resource, need_amount, available_amount | 超过服务上限 |
| `quota_over_balance` | quota | resource, need_amount, available_amount | 超过项目余额 |
| `quota_retry_limit` | quota | max_retries | 重试次数已到上限 |
| `member` | member | — | 单义 |

另外复用 `record_not_found`（`record_kind` 用 `template`、`treatment`、`attempt`）和 `not_this_project`。

配额检查是一个循环，对 `checks` 里的五项依次比较。把每项的英文标签换成 `(reason, resource)`，英文 `message` 照旧拼出来。`resource` 是 `cpu_hours` 或 `storage_gb`。

`compute/service.py:673` 把原始 `OSError` 拼进英文：保留在英文里，参数里不放。

---

### Task 8：研究、分析和留出（`S/research/analysis.py`、`holdout.py`、`preregistration.py`、`sandbox.py`、`S/archive/snapshot.py`、`S/workbench/analysis.py`，35 处；ERR-05、ERR-06）

| reason | 粗码 | 参数 | 情形 |
|---|---|---|---|
| `script_not_text` | param | — | 分析脚本不是文字 |
| `script_empty` | param | — | 分析脚本为空 |
| `script_too_long` | param | max_length | 分析脚本太长 |
| `script_syntax` | param | detail | 分析脚本有语法错误；错误文字进 `detail` |
| `snapshot_fails_verification` | snapshot_incomplete | snapshot_id | 快照没通过校验 |
| `snapshot_not_complete` | snapshot_incomplete | snapshot_id | 快照不完整 |
| `snapshot_manifest_changed` | snapshot_incomplete | snapshot_id | 快照清单变了 |
| `snapshot_files_mismatch` | snapshot_incomplete | snapshot_id | 快照文件和清单不一致 |
| `snapshot_file_changed` | snapshot_incomplete | snapshot_id, file | 快照里某个文件变了（ERR-06：文件名作参数） |
| `script_not_protocol_script` | script_hash | protocol_id | 脚本和协议里记录的不是同一个 |
| `script_other_frozen` | script_hash | protocol_id | 已冻结的是另一个脚本 |
| `script_not_frozen_script` | script_hash | protocol_id | 运行的不是冻结的脚本 |
| `already_run` | already_run | — | 单义 |
| `analysis_freeze_too_late` | state | protocol_id, version | 已有数据，不能再冻结分析 |
| `analysis_script_not_frozen` | state | protocol_id, version | 这个协议版本还没有冻结脚本 |
| `analysis_workdir_unwritable` | state | — | 分析的工作目录不能写 |
| `snapshot_invalidated` | state | snapshot_id | 一次更正让快照失效 |
| `snapshot_predates_freeze` | state | snapshot_id | 快照含冻结之前的数据 |
| `holdout_outcomes_exist` | state | project_id | 已有结果数据，不能再登记留出 |
| `holdout_already_registered` | state | holdout_id | 留出已登记 |
| `batches_no_holdout` | batches | — | 没有留出批次 |
| `batches_too_few_development` | batches | min_batches | 开发批次太少 |
| `batches_overlap` | batches | — | 批次重叠 |
| `not_this_protocol` | scope | protocol_id | 对象不属于这个协议 |
| `mixed_protocol` | scope | — | 混合了几个协议的数据 |
| `holdout_rows` | scope | holdout_id | 读取会碰到留出的行 |
| `model_unregistered` | model_unregistered | — | 单义 |
| `sandbox_unavailable` | sandbox_unavailable | — | 单义 |
| `clock_unsynced` | clock_unsynced | — | 单义 |

另外复用 `record_not_found` 和 `protocol_not_found`。

ERR-06：把英文里的文档章节号删掉，例如 `S/workbench/analysis.py` 常量里的 "(architecture doc §6.5)"。`research/analysis.py:364` 故意用 `from None` 隐藏原因，它的 reason 不带参数。

---

### Task 9：模型工具和计算运行时（`S/agents/*`、`S/runtime_compute.py`，44 处）

只有模型能走到的点，正文仍要中英文都写；`action` 一般为 `False`。下表以外，尽量复用前面任务的 reason：
- `record_not_found`、`stage_not_started`、`snapshot_invalidated`、`protocol_not_found`；
- `request_id_reused_for_other_goal`、`artifact_digest_mismatch`、`task_not_in_progress`；
- `attempt_*`、`quota_*`、`not_this_project`、`not_this_protocol`、`mixed_protocol`；
- `budget_calls_exhausted`、`budget_cost_exhausted`、`budget_revision_limit`。

| reason | 粗码 | 参数 | 情形 |
|---|---|---|---|
| `no_run` | scope | — | 工具需要一个正在进行的运行 |
| `not_this_run` | scope | — | 对象不属于当前运行 |
| `wrong_task_kind` | scope | task_kind | 任务类型不对 |
| `round_wrong_phase` | state | round_id, state, needed_state | 轮次不在这一步需要的状态 |
| `confirmatory_run_pending` | state | snapshot_id | 预注册的确认运行还没完成 |
| `budget_depth_limit` | budget | depth, max_depth | 委托层数到了上限 |
| `tool_not_allowed` | model_role | role | 这个角色不能用这个工具 |
| `no_model` | model_role | role | 这个角色没有配置模型 |
| `unknown_role` | model_role | role | 不认识这个角色 |
| `alert_book_unavailable` | unavailable | — | 没有告警簿（粗码保持现状；笔记建议的 `unavailable` 只在它本来就是时才用） |
| `duplicate_experiment` | param | experiment_id | 实验重复 |
| `table_invalid` | param | detail | 表格不合格 |
| `operator_only_evidence` | param | — | 这类证据只能由操作员添加 |

`handlers_report.py` 里的英文写着 API 路径 "POST /wb/analysis/runs"，它是给模型看的，保留。

再加一个测试：`tests/agents/` 下一个工具拒绝后，工具结果的文字仍是 `denied (<code>): <message>`，不含 reason。

---

### Task 10：根应用 `/api` 和 dashboard 上没有码的错误（ERR-08）

**Files:** `S/api.py:76-115,173-175,266`、`S/dashboard.py:30-40`、`S/service.py`（`BridgeError` 子类）、`tests/workbench/test_denial_codes.py`（`sent_elsewhere`）、`tests/` 下根应用和 dashboard 已有的测试文件

**Interfaces:**
- Produces:
  - `class CodedHTTPError(Exception)`，放在 `S/api.py`，构造为 `CodedHTTPError(status: int, message: str, *, code: str, reason: str, params: Mapping[str, object] | None = None)`。
  - 处理函数返回 `{"detail": message, "code", "reason", "params"}`：`detail` 仍是字符串。
  - `dashboard.py` 用同一个类。

| 发出点 | 状态 | 粗码 | reason |
|---|---|---|---|
| `check_origin` | 403 | entry | `origin_not_allowed` |
| `bearer` | 401 | session | `not_signed_in` |
| `authorize`（没有会话） | 401 | session | `dashboard_not_connected` |
| `authorize`（缺控制头） | 403 | entry | `not_from_page` |
| `writes_closed` | 403 | entry | `use_workbench` |
| 未知设备（`api.py:266`） | 404 | state | `record_not_found`（`record_kind` 用 `device`） |
| dashboard 待连接太多 | 429 | locked | `too_many_pending_connections` |
| dashboard 链接过期或已用 | 401 | session | `link_used` |
| dashboard 会话太多 | 429 | locked | `too_many_sessions` |
| `BridgeError` 的 409 | 409 | 按子类 | 每个有专门含义的子类映射到已有粗码和 reason（例如 `PumpOffUnconfirmed` 是 `interlock`/`pump_unconfirmed`）；没有专门子类的，`code` 和 `reason` 为 `null` |

**测试：**
- 每一行都断言状态码、`detail` 是原来的字符串，以及顶层的 `code`、`reason`、`params`。
- `test_old_clients_still_read_a_string_detail`：`/api` 的每个错误体，`detail` 都是 `str`。
- `sent_elsewhere()` 扫描 `CodedHTTPError(` 的字面量 `reason=`。

本任务新登记的 reason 也要有中英文正文。工作台控制台不调用 `/api`，但目录完整性测试要求每个登记过的 reason 都有正文。

---

### Task 11：请求体校验错误（ERR-02，只改控制台）

**Files:**
- Create: `W/validation.js`
- Modify:
  - `W/api.js:34-37`：`fields` 每项加 `type` 和 `limits`；`limits` 取 Pydantic 的 `ctx`，只留数字和字符串值；
  - `W/ui/forms.js:244-257`：`placeFieldErrors`；
  - `W/i18n/denials.{en,zh}.js`：加 `msg.validation.*`。
- Test: `T/validation.test.mjs`（新）

**Interfaces:**
- Produces:
  - `VALIDATION_TYPES: string[]`。
  - `problemText(ctx, { type, limits, msg }) -> string`：用 `msg.validation.<type>`，占位符取自 `limits`；类型不在表里时，用 `msg.validation.other`。
  - `positionText(ctx, loc) -> string`：去掉 `"body"`；数字写成 `t("validation.item", {n: i + 1})`，键名写成带引号的原名。JSON 编辑器里看到的就是这个键名，用户靠它找到那一处。

`VALIDATION_TYPES` 的值：
- `missing`、`extra_forbidden`
- `string_type`、`string_too_short`、`string_too_long`、`string_pattern_mismatch`
- `int_type`、`int_parsing`、`float_type`、`float_parsing`、`bool_type`、`bool_parsing`
- `greater_than`、`greater_than_equal`、`less_than`、`less_than_equal`、`finite_number`
- `literal_error`、`enum`、`list_type`、`dict_type`、`too_short`、`too_long`
- `value_error`、`json_invalid`

`limits` 里的名字按参数约定显示：
- `min_length`、`max_length` 按 `min_`/`max_` 规则显示为整数；
- `gt`、`ge`、`lt`、`le` 改名为 `bound`，正文按类型写"大于"、"至少"等，`bound` 用"原样的数字"规则。

**测试（在 `T/validation.test.mjs`）：**
- "a missing field next to its input says it is required, in the reader's language"
- "a too-long text says the maximum length"
- "a number bound says the bound as written"
- "a path in the JSON editor reads as positions: item numbers count from 1, keys stay as typed"
- "an unknown validation type falls back to a general sentence and keeps Pydantic's words in the details"
- "every validation type has a text in both languages"

---

### Task 12：收尾：删掉 `PENDING`、API 参考、清单结果

**Files:**
- `tests/workbench/test_denial_codes.py`
- `docs/wiki/en/API-Reference.md`、`docs/wiki/zh-CN/API-Reference.md`（文件名以仓库为准）
- `docs/superpowers/specs/2026-11-16-console-usability-inventory.md`

- [ ] **Step 1：删掉 `PENDING`。**
  - `PENDING` 和 `test_pending_lists_only_files_that_still_have_a_refusal_without_reason` 一起删掉。
  - `test_every_refusal_outside_pending_names_a_registered_reason_of_its_code` 改名为 `test_every_refusal_names_a_registered_reason_of_its_code`，不再跳过任何文件。
  - 运行，确认 PASS。
- [ ] **Step 2：API 参考。** 中英文都写，内容是：
  - 错误体的新字段（`/wb` 的 `detail.reason`、`detail.params`；`/api` 的顶层 `code`、`reason`、`params`）；
  - reason 的含义和 `F/message-codes.json` 的 `denial` 族；
  - "粗码和状态不变"。
- [ ] **Step 3：清单第 8 节"第二批 2b 结果"。**
  - 格式同第 7 节：ERR-01 至 ERR-09、FRM-06 各一行，写状态、钉住它的测试名和截图。
  - 每一行都要有测试或截图对照（设计的"验收"一节）。
- [ ] **Step 4：全部检查。** 和 CI 一样：
  - 每个控制台文件 `node --check`；
  - `node --test tests/web/*.test.mjs`；
  - `ruff check src tests scripts`、`ruff format --check src tests scripts`；
  - 裸 `pytest -q`。
- [ ] **Step 5：提交。** `git commit -m "docs: record batch 2b's refusal reasons in the API reference and the inventory"`

---

### Task 13：改造后截图与对照（控制台负责人自己做，不派子代理）

和 2a 一样，用开发工作台和复制出来的数据目录（不调用模型，密钥只经 `GROWBRIDGE_DEV_SECRET` 传，不打印）。

截下面几种拒绝在改造前（main `d7d479a`）和改造后的样子，1440 和 375 宽，中英文：
1. 登录时密钥错误（`bad_credentials`）；
2. 暂停一个待审的阶段（`stage_not_pausable`，或开发数据里能做到的同类阶段操作）；
3. 浇水太快（`irrigation_too_soon`）或手动任务未到时间（`manual_task_not_due`），看开发数据能做到哪个；
4. JSON 编辑器里提交缺字段的协议（校验错误）。

开发数据做不出来的拒绝，就用测试里的合成数据渲染到页面上截图，并在清单里写明"合成"。对照图放 `<scratchpad>/console-shots-2b/compare`，截图列写进清单第 8 节。
