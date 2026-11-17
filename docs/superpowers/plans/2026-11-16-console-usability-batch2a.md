# 控制台可用性改造第二批 2a（服务器消息带代码和参数）：实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 下面这些文字改由服务器发 `code` 加 `params`，由控制台用中英文目录拼出两句话："发生了什么"和"下一步做什么"。
- 告警
- 运行单检查结果
- 写入回执和浇水提前结束的原因
- 计算尝试卡住的原因
- 对话里任务结束的原因
- 报告估计的说明

英文 `message` 保留，供日志、旧客户端和通知使用。研究备注的参数改成结构化数据。另外补三个读字段（预算已用量、计划档位、主要指标），并修掉第一批留下的 5 处小问题。

**架构：**
- **服务器代码登记表：** 新建 `S/codes.py`，按"族 → 代码 → 参数名、有没有下一步"登记。各发出点按表发码。
- **导出与一致性测试：** 一个脚本把登记表导出成 `F/message-codes.json`，Python 测试保证两者一致。
- **控制台：** 新建 `W/messages.js`，按参数名的约定格式化每个参数；id 只进技术详情。目录文字放在新文件 `W/i18n/messages.{en,zh}.js`。
- **目录测试：** 每个代码在中英文里都有正文；声明了有下一步的，也都有下一步；正文里的占位符只能是这个代码声明过、并且有格式化规则的参数。

**技术栈：**
- 控制台：原生 ES 模块，无构建、无依赖；测试用 `node --test tests/web/*.test.mjs`。
- 服务器：Python 3.12 加 FastAPI，用 `pytest`、`ruff`。
- 在 worktree 里跑 Python 测试要加 `PYTHONPATH=src`，因为共用的 `.venv` 指向另一个检出。

**设计：** `docs/superpowers/specs/2026-11-16-console-usability-design.md`，看"第二批"一节和"实现前已定的事项"第 5 条（用户已批准："设计通过"）。
**清单：** `docs/superpowers/specs/2026-11-16-console-usability-inventory.md`。第 3 节的编号是各行的正式编号；第 6 节是第一批的结果，6.1–6.3 是留给第二批的事。

**拆分（控制台负责人的决定，用户可改）：** 第二批拆成两份计划、两个 PR。
- **2a（本计划）：** 消息。
- **2b：** 拒绝原因。范围是全部 `Denied` 加 `reason` 子码和 `params`，没有代码的 HTTP 错误，以及 ERR-01–09。
- **为什么拆：** 两部分合起来约 300 个发出点，是第一批的两倍多，一个 PR 认真审不过来。
- **为什么 2a 在先：** 2b 要复用 2a 的登记表和 `messages.js`。2b 叠在 2a 上。

路径简写：
- `W/` = `src/growbridge/web/workbench/`
- `S/` = `src/growbridge/`
- `T/` = `tests/web/`
- `F/` = `tests/web/fixtures/`
- `<scratchpad>` = `/private/tmp/claude-1618820129/-Users-chenghao-Downloads-diagri/7aef49f1-45c9-4f52-92af-a0e7405f7e16/scratchpad`

各发出点的来源调查报告在 `<scratchpad>/batch2/`（alerts.md、findings-receipts.md、console.md、read-fields.md）。任务的子代理不需要读它们：本计划已经把要用的值写进各任务。

## 本批覆盖的清单行

- **整行（20 行）：**
  - ALT-01 至 ALT-10、ALT-13
  - STG-03 至 STG-06、STG-20
  - TSK-04、RND-16、CMP-04
- **补完第一批的部分行：**
  - P-04、P-11、RND-11、STG-01、STG-02、ENV-02、ALT-12
  - ALT-11 只做服务器分字段的部分，摘要措辞仍在第三批
  - FRM-06 只做告警和检查结果里的时长部分，拒绝文字里的时长在 2b
- **泄漏测试的豁免：** 标为第二批的 6 项全部删掉（Task 7、9、12、14）。
- **清单 6.3 的 5 条遗留：** 由 Task 1 处理。
- **不在本批：** ERR-01 至 ERR-09（2b），以及第三批的 C5、C8、C9 各行。

## Global Constraints

- **G1 名字：** 用户看到的是名字或序号，不是 id。id 只出现在技术详情里，可复制。
- **G2 代码经目录：** 任何代码都通过对照表变成文字；对照表里没有的，显示"未知（技术详情）"，绝不直接显示代码。
- **G3 技术详情：** 全站一个折叠组件，默认收起，展开后每项可复制。
- **G4 数字和时间：** 时长按大小用天、小时、分钟、秒；档位写成"值 / 满档"；日期时间按界面语言格式化，时区只在页头写一次。
- **G5 消息格式：** 错误、告警、检查结果都是两句："发生了什么"加"下一步做什么"。内部异常只显示固定的人话，异常类名进日志和技术详情。
- **英文 `message` 永远保留：**
  - 告警、检查结果、回执的 `message`（或 `error`）和以前一样写入，供日志、旧客户端、邮件和 Telegram 通知使用。
  - 通知内容在本批不变。
  - 控制台把它放进技术详情（标签"服务器原文"）。
- **API 只加不改：** 已有字段一个不删、不改名。新字段都有默认值：`code` 为 `null`，`params` 为 `{}`。
- **旧数据要能读：**
  - 读到旧行、旧报告、旧回执时，控制台显示通用说法，原文放进技术详情，既不报错，也不留空白。
  - 存下来的记录（`ActionRecord`、`TaskRecord`、报告文件）一律不回写。
- **登记表不能挡住发出：** 代码或参数没登记时，`checked()` 只记一条日志，告警照常发出。登记错误由测试抓。
- **目录同步：**
  - 每个代码中英文各有正文；声明有下一步的，中英文都有 `.action`。
  - 键集合由 `T/i18n.test.mjs` 检查一致，`T/messages.test.mjs` 检查完整。
- **测试和代码规范：**
  - 照常 TDD、`pytest`、`ruff check`、`ruff format`。文件不超过 800 行，函数少于 50 行。
  - 测试不用浏览器、服务器和网络。
  - 控制台源码不得出现 `innerHTML`、`outerHTML`、`insertAdjacentHTML`、`document.write`。
- **读文件：** 先 grep，再每次读 30–60 行。
- **提交：** 信息用约定式前缀（`feat:`、`fix:`、`test:`、`docs:`），不加任何署名行，不跳过 pre-commit 钩子。

## 参数约定（服务器和控制台之间的合同）

`W/messages.js` 的 `formatterFor(name)` 按参数名选格式化方式，本表是全部规则。
- 只有表里有规则的参数才能出现在目录正文里，写作 `{名字}` 占位符。
- 规则为"不能做占位符"的参数只进技术详情。
- 服务器给参数起名必须遵守本表。需要新的参数名时，先在本表和 `formatterFor` 里加规则。

| 参数名 | 控制台怎么显示 |
|---|---|
| 以 `_seconds` 结尾，或正好是 `seconds` | `formatDuration(t, v)` |
| 以 `_at` 结尾，或是 `window_start`、`window_end` | `timeText(ctx, v)` |
| `at_local` | 原样（运行单当地时间 "HH:MM"） |
| `sensor` | `labelOr(t, "metric", v)` |
| `channel` | `labelOr(t, "channel", v)` |
| `level`、`min`、`max`、`expected`、`protection_level` | `levelText(t, params.channel, v)` |
| `value` | 先用 `formatNumber`，精度取 `params.sensor` 在 `W/chart-math.js` 传感器表里的精度，再加该传感器的单位。传感器不在表里时只写数字 |
| `op` | `labelOr(t, "safety.op", v)` |
| `state` | `labelOr(t, "state", v)` |
| `action_state` | `labelOr(t, "receipt", v)` |
| `event` | `labelOr(t, "history.event", v)` |
| `role` | `roleLabel(t, v)`（`W/ui/names.js`） |
| `task_kind` | `labelOr(t, "tasks.kind", v)` |
| `source_kind` | `labelOr(t, "findingSource", v)` |
| `step` | `labelOr(t, "tickStep", v)` |
| `signal` | `labelOr(t, "heartbeat", v)` |
| `failures` | 每项 `labelOr(t, "probe", x)`，用 `t("common.listSep")` 连接 |
| `channels` | 每项 `labelOr(t, "channel", x)`，用 `t("common.listSep")` 连接 |
| `problems` | 每项 `t("findingProblem." + kind, {channel: 通道名, level: 档位, other: 其他档位})`，用 `t("common.listSep")` 连接 |
| `treatments` | 每项按"带引号的名字"显示，用 `t("common.listSep")` 连接 |
| `source`、`rule`、`rule_a`、`rule_b`、`protection`、`treatment`、`control`、`block`、`metric`、`name` | 带引号的名字：`t("common.quoted", {text: v})`。这些是人起的名字（运行单条目、规则、处理、文件名），审阅时要靠它们找到对应条目 |
| `count`、以 `_count` 结尾（如 `file_count`、`limit_count`）、`blocks`、`min_blocks`、`flips`、`failed`、`priority`、`round`、`mode`、`top_rowid`、`cursor` | `formatNumber(v, 0, lang)` |
| `fraction`（0–1） | 百分数，`formatNumber(v * 100, 0, lang)` 加 "%" |
| `bytes`、`limit` | 字节数：`formatNumber(v, 0, lang)` 加 `t("common.bytes")`（新键，中英文各一） |
| `device_unit`、`rule_unit` | `unitText(v)`（`W/pages/safety-text.js`，把 `C` 写成 `°C`） |
| 其余全部：以 `_id`、`_ids` 结尾的，以及 `summary`、`evidence`、`detail`、`timezone`、`denied_code`、`stop_reason`、`error_code`、`error_params` 等 | **不能做占位符**，只进技术详情 |

值缺失、为 `null` 或类型不对（例如该是数字的地方给了字符串）时，该占位符显示 "—"。界面上永远不出现 `{名字}`。

## Review Focus

1. **旧数据没有代码：** 升级前存下的告警、旧报告的估计说明、旧回执、旧计算尝试，都没有代码。
   - 应显示：类型标签或通用一句，"服务器原文"进技术详情。
   - 不应出现：空白、`{x}`、英文正文。
   - 测试在 Task 4、7、11、12、14。
2. **同一条告警重复发出、参数变了：** 例如阈值告警的新读数、冻结的新数值、失败的探针列表。存储的 `code` 和 `params` 必须跟着更新，控制台显示最新的。测试在 Task 4。
3. **参数缺失或类型不对：** 显示 "—"，不抛异常，不出现 `{x}`。测试在 Task 3。
4. **阶段 id 里带冒号：** 告警指向阶段的链接从 `params.stage_id` 来，按 URL 编码，绝不解析告警的 key。测试在 Task 7。
5. **水泵看门狗的重存节奏：**
   - 同一形态在 60 秒内重复，不重存；形态变了（代码或参数不同），立即重存。
   - 比较的是 `(code, params)`，不是英文 `message`。
   - 测试在 Task 5。

---

### Task 1：第一批遗留（清单 6.3）

**Files:**
- Modify:
  - `W/pages/safety-text.js`（31–36 行 `frozenLine`；55–58 行 `exactText`，未导出）
  - `W/pages/safety.js`（37 行，最长空档）
  - `W/pages/environment.js`（81 行状态行；180–185 行 `draw`）
  - `W/pages/stage.js`（187 行标题药丸）
  - `W/pages/inbox.js`（126 行 `fallback`；133–139 行 `detailEntries`；211 行分组标题）
  - `W/pages.css`（128 行 `.tech-copy`）
  - 清单 6.2 节"对话框"那一条
- Test:
  - `T/config-pages.test.mjs`、`T/environment.test.mjs`、`T/stage-status.test.mjs`、`T/shell.test.mjs`、`T/tech-details.test.mjs`

**Interfaces:**
- Produces：`exactText(t, seconds)` 从 `W/pages/safety-text.js` 导出。

- [ ] **Step 1：写失败的测试**
  - `config-pages.test.mjs`「the frozen threshold and the longest gap say the exact seconds when the words round them」：冻结阈值 150 秒、最长空档 150 秒，两行都包含和规则句子一样的精确秒数写法（`safety.exactSeconds`，数字 150）；120 秒时不加。
  - `environment.test.mjs`「a refresh with the same state keeps an open unknown-state fold open」：
    - 先用 `stage.state: "mystery"` 渲染，把状态行里的技术详情设为 `open`。
    - 用同样的数据刷新后，它仍然 `open`。
    - 换成另一个状态再刷新，这一行重建。
  - `stage-status.test.mjs`「the title pill keeps an open unknown-state fold open across polls」：标题药丸同上。
  - `shell.test.mjs`「an inbox item of an unknown kind keeps its kind code in its details」：条目和分组标题的折叠里都有 kind 原码。
  - `tech-details.test.mjs`「copy buttons cannot be selected in Safari either」：读 `W/pages.css`，`.tech-copy` 规则里同时有 `-webkit-user-select: none` 和 `user-select: none`。
- [ ] **Step 2：运行，确认失败** —— `node --test tests/web/*.test.mjs`，预期上面 5 个测试失败。
- [ ] **Step 3：实现**
  - 导出 `exactText`，用在 `frozenLine` 和最长空档那一行。
  - 环境页状态行和阶段页标题药丸改为只在状态值变化时重建。照 `stage.js` 87–114 行 `part.show(signature, build)` 的做法。
  - 收件箱的 fallback 和分组标题加上 `unknownCode(ctx.t, "inbox.kind", kind)`。
  - CSS 补前缀。
  - 清单 6.2 那句改为点名两个已有的测试：轮次中止的问句、安全审批对话框的变化行（用 grep 找到测试名后写进去）。
- [ ] **Step 4：运行，确认通过** —— `node --test tests/web/*.test.mjs` 全部通过。
- [ ] **Step 5：提交** —— `git commit -m "fix: close the first batch's leftovers (exact frozen seconds, folds that survive polls, unknown inbox kinds, Safari copy)"`

### Task 2：服务器代码登记表和导出

**Files:**
- Create：
  - `S/codes.py`
  - `scripts/export_message_codes.py`
  - `F/message-codes.json`
  - `tests/workbench/test_message_codes.py`

**Interfaces:**
- Produces：
  - `Code`：冻结的 dataclass，`params: tuple[str, ...] = ()`，`action: bool = True`。
  - `CODES: dict[str, dict[str, Code]]`，族正好是这 8 个：`alert`、`finding`、`receipt`、`task_end`、`compute_error`、`compute_stuck`、`chat_end`、`estimate`。本任务里各族都是空字典，由后面的任务填写。
  - `checked(family: str, code: str, params: Mapping[str, object]) -> dict[str, object]`：
    - 返回 `dict(params)`。
    - 没登记的族或代码，记一条 warning："unregistered message code {family}.{code}"。
    - 参数键集合和声明的不一致时，记一条 warning："message {family}.{code} params {实际键} differ from {声明键}"。
    - 永远不抛异常。
  - `export() -> dict[str, dict[str, dict[str, object]]]`：结构是 `{family: {code: {"params": [声明顺序], "action": bool}}}`。
  - `scripts/export_message_codes.py`：把 `export()` 写进 `F/message-codes.json`（`indent=2`、`ensure_ascii=False`、末尾换行）。
  - 测试辅助 `codes_at_calls(root: Path, names: set[str]) -> list[tuple[str, int, str]]`：用 AST 找出函数名（`Name` 或 `Attribute.attr`）在 `names` 里、并带字符串字面量关键字参数 `code=` 的调用，返回（文件、行号、代码）。后面的任务用它检查发出点。

- [ ] **Step 1：写失败的测试**（`tests/workbench/test_message_codes.py`）
  - `test_the_console_list_matches_the_registry`：`json.loads(F/message-codes.json) == codes.export()`。失败信息要写明 "run: PYTHONPATH=src python scripts/export_message_codes.py"。
  - `test_checked_logs_an_unregistered_code_and_keeps_the_params`：用 `caplog`；返回值等于输入；日志里有 "unregistered message code alert.nope"。
  - `test_checked_logs_params_other_than_the_declared_ones`：用 monkeypatch 往 `CODES` 加一个测试代码，再传多一个键和少一个键。
  - `test_checked_accepts_the_declared_params_in_any_order`：没有日志。
  - `test_the_families_are_fixed`：`set(CODES) == {8 个族}`。
  - `test_codes_at_calls_finds_literal_codes`：对一段临时源码，找到 `x.raise_alert(..., code="a")`，并忽略没有 `code=` 的调用。
- [ ] **Step 2：运行，确认失败** —— `PYTHONPATH=src pytest tests/workbench/test_message_codes.py -v`，预期 ImportError。
- [ ] **Step 3：实现 `S/codes.py` 和导出脚本，运行脚本生成 JSON**
- [ ] **Step 4：运行，确认通过** —— `PYTHONPATH=src pytest tests/workbench/test_message_codes.py -v`，以及 `ruff check src tests scripts`。
- [ ] **Step 5：提交** —— `git commit -m "feat: add the server's message code registry and its export for the console"`

### Task 3：控制台消息目录 `W/messages.js`

**Files:**
- Create：`W/messages.js`、`W/i18n/messages.en.js`、`W/i18n/messages.zh.js`、`T/messages.test.mjs`
- Modify：
  - `W/i18n/en.js`、`W/i18n/zh.js`：像 `codes.*.js` 一样展开进来。
  - 缺 `common.listSep`、`common.quoted` 这两个键就新增。
  - 新增 `tech.serverMessage`、`tech.params`（已有就复用）。

**Interfaces:**
- Consumes：`F/message-codes.json`（Task 2）。
- Produces：
  - `formatterFor(name: string): ((ctx, value, params) => string) | null`：规则见"参数约定"一节。
  - `messageParts(ctx, family, code, params = {})`，返回 `{known: boolean, text: string, action: string | null, details: Array<[string, unknown]>}`：
    - 键是 `msg.<family>.<code>` 和 `msg.<family>.<code>.action`。
    - 键不存在时，`known` 为 false，`text` 为 `t("common.unknown")`。
    - `details` 依次是：代码（`tech.code`）、每个以 `_id`/`_ids` 结尾的参数（标签就用参数名）、整个 `params`（`tech.params`）。
  - `messageView(ctx, family, code, params, { extra = [] } = {})`，返回 Node 数组：
    - `<p class="message-text">`；
    - 有下一步时加 `<p class="message-action">`；
    - 最后是 `techDetails(t, details.concat(extra))`。

- [ ] **Step 1：写失败的测试**（`T/messages.test.mjs`）
  - 「every code the server can send has a text in both languages, and an action exactly when it declares one」：遍历 `message-codes.json`。
  - 「a text names only params its code declares and the console can format」：用 `/\{(\w+)\}/g` 扫中英文正文和下一步，每个名字都要满足：属于声明的参数，`formatterFor(名字) !== null`，并且不匹配 `/_ids?$/`。
  - 「every message text in the catalogs belongs to a registered code」：反向检查。`msg.` 开头的键去掉末尾 `.action` 后，必须是 `msg.<family>.<code>`，并且在 JSON 里。
  - 「durations, sensors, levels, operators and times are written for people」：在 `makeT("en")` 外包一层，加一个测试键 `msg.test.sample` = "{sensor} {op} {value} for {duration_seconds}, {level}"。参数为 `{sensor:"temp", op:">", value:30, duration_seconds:300, channel:"fan", level:3}`，预期正文是 "Air temperature" 加 `safety.op.>` 的标签，接着是 "30 °C for 5 minutes, 3 / 10"。中文同理。
  - 「a missing or malformed param shows a dash, never a brace」：`value:null`、`duration_seconds:"x"` 都显示 "—"，正文里没有 `{`。
  - 「an unknown code says unknown and keeps code and params in the details」。
  - 「ids go to the details, never into the text」：`stage_id`、`task_ids` 出现在 details 里。
  - 「a time param is a date and time in the site's zone」：`due_at`，用 `ctx.me.timezone`。
- [ ] **Step 2：运行，确认失败** —— `node --test tests/web/messages.test.mjs`。
- [ ] **Step 3：实现** `formatterFor`、`messageParts` 和 `messageView`。新建两个空目录文件，并展开进 `en.js`/`zh.js`。先 grep 确认 `msg.` 前缀没有被占用。
- [ ] **Step 4：运行，确认通过** —— `node --test tests/web/*.test.mjs` 全部通过（此时 JSON 里还没有代码，完整性测试是空循环）。
- [ ] **Step 5：提交** —— `git commit -m "feat: build console messages from a code and its params"`

### Task 4：告警的存储、接口和挂钩带上代码和参数

**Files:**
- Modify：
  - `S/observer/alerts.py`：`Alert` 第 108 行；`STEPS` 第 20–29 行；`_alert` 第 123 行；`raise_alert` 第 152 行。
  - `S/runtime.py`：`alert` 第 333 行；`_alert` 第 405 行；`InterventionMirror.alert` 的类型在第 204 行。
  - `S/executor/watchdog.py`：第 52 行，只改挂钩类型。
  - `S/runtime_backup.py`：只改挂钩类型。
  - `S/observer/stage_checks.py`：`_set` 第 122 行，只改签名。
  - `S/workbench/reads.py`：`_alert_items` 第 132 行。
- Test：
  - 现有的告警簿测试文件，用 `grep -rl "AlertBook(" tests` 找到。
  - `tests/workbench/` 里现有的收件箱测试。

**Interfaces:**
- Consumes：`codes.checked`（Task 2）。
- Produces：
  - `Alert.code: str | None = None`。
  - `Alert.params: dict[str, Any]`，默认 `{}`。
  - `STEPS` 末尾追加：
    - `ALTER TABLE observer_alerts ADD COLUMN code TEXT`
    - `ALTER TABLE observer_alerts ADD COLUMN params TEXT`
  - `params` 存 JSON。旧行读出来 `code=None`，`params={}`。
  - `AlertBook.raise_alert(kind, key, severity, message, *, code: str | None = None, params: Mapping[str, object] | None = None) -> Alert`：
    - 没给 `code` 时，存 `kind` 和 `{}`，不调用 `checked`。
    - 给了 `code` 时，先过 `checked("alert", code, params)`。
    - 重复发出时，UPDATE 也要写 `code` 和 `params`。
  - `Runtime._alert(kind, key, message, severity="critical", *, code=None, params=None) -> bool`，`Runtime.alert(...)` 同样加这两个关键字参数。所有挂钩的类型都同步改。
  - 收件箱告警条目的 `detail` 加上 `code` 和 `params`。

- [ ] **Step 1：写失败的测试**
  - `test_an_alert_stores_its_code_and_params`
  - `test_a_repeat_writes_the_new_code_and_params`：同一个 kind 和 key，第二次的 params 不同，读出来是第二次的值，`count == 2`（Review Focus 2）。
  - `test_an_alert_stored_before_codes_reads_with_no_code`：
    - 先只跑旧的前几个 STEPS 建表，插入一行。
    - 再用新的 `AlertBook` 打开，读出来 `code is None`、`params == {}`（Review Focus 1）。
  - `test_an_alert_without_a_code_takes_its_kind_and_no_params`
  - `test_the_inbox_alert_item_carries_code_and_params`
  - `test_runtime_alert_passes_code_and_params_through`
- [ ] **Step 2：运行，确认失败** —— `PYTHONPATH=src pytest <上面的文件> -v`。
- [ ] **Step 3：实现**
- [ ] **Step 4：运行，确认通过** —— `PYTHONPATH=src pytest -q`，再跑 ruff。
- [ ] **Step 5：提交** —— `git commit -m "feat: store a code and params with every alert"`

### Task 5：告警发出点：观察器、冻结读数、阶段检查、水泵看门狗

**Files:**
- Modify：
  - `S/observer/service.py`：79、96、110、124 行。
  - `S/observer/frozen_watch.py`：152 行 `_raise`。
  - `S/observer/stage_checks.py`：116、125 行。
  - `S/executor/watchdog.py`：90、103、109、129 行；134–142 行的重存逻辑。
  - `S/codes.py`
  - `F/message-codes.json`：运行导出脚本生成。
  - `W/i18n/messages.{en,zh}.js`
- Test：
  - 这几个模块现有的测试文件（先 grep）
  - `tests/workbench/test_message_codes.py`

**Interfaces:**
- Consumes：`raise_alert(..., code=, params=)`（Task 4）、`messageParts`（Task 3）。
- Produces：下表的 14 个 `alert` 代码。下一步一栏是要点；中英文措辞由实现者写，每条一句。

| 代码（kind） | params | 下一步要点 |
|---|---|---|
| `data_gap` | `sensor` | 检查传感器和连接；数据恢复前，它的阈值告警暂停 |
| `threshold` | `sensor`, `op`, `value`, `duration_seconds`, `rule` | 去生长室看看；如果这是预期内的，就确认 |
| `frozen_watch` | — | 冻结读数检查没能运行，请管理员看服务器日志 |
| `stage_checks` | — | 阶段检查没能运行，请管理员看服务器日志 |
| `frozen_reading` | `sensor`, `value` | 检查传感器是否卡住或脱落；如果是保护传感器，阶段可能暂停 |
| `task_missed` | `stage_id`, `task_id`, `task_kind`, `due_at` | 把任务记为已做或跳过 |
| `measurement_missing` | `stage_id`, `task_id`, `window_start`, `window_end`, `timezone` | 按实际测量时间补录测量 |
| `measurement_outside_window` | `stage_id`, `measurement_id`, `metric`, `measured_at` | 按正确时间重新录入，或记一条更正 |
| `pump_unexpected_off`（kind `pump_unexpected`，原 OFF_TEXT） | — | 水泵已关、已改回手动；查清它为什么在没浇水时开着 |
| `pump_unexpected_interlocked`（原 UNCONFIRMED_TEXT） | — | 到现场手动关泵；系统已锁住水泵并会继续重试 |
| `pump_unexpected_failed`（原 FAILED_TEXT） | — | 到现场确认水泵已关；下一次读到状态时系统会再试 |
| `pump_unreadable` | — | 检查设备连接和水泵插座；看门狗现在看不到水泵 |
| `pump_watchdog_step`（kind `pump_watchdog`，key `step`） | — | 看门狗停了，请自己盯着水泵并通知管理员 |
| `pump_watchdog_record`（kind `pump_watchdog`，key `intervention`） | — | 这次水泵事件没记下来，请在阶段记录里手动补一条 |

`kind`、`key`、`severity` 和英文 `message` 一律不变。`message` 里的异常文本也不变，但不进 `params`。

- [ ] **Step 1：写失败的测试**
  - 每个代码一个测试，断言 `alert.code` 和 `alert.params` 等于上表（值取自测试里构造的输入）。测试名格式为 `test_<code>_alert_carries_<要点>`，例如 `test_threshold_alert_carries_sensor_operator_value_and_seconds`。
  - `test_the_watchdog_restores_an_alert_only_when_its_code_or_params_change`（Review Focus 5）：
    - 同一形态在 60 秒内重复，不重存；
    - 形态从 `pump_unexpected_off` 变成 `pump_unexpected_interlocked`，立即重存；
    - 英文 `message` 不参与比较。
  - `test_observer_and_watchdog_alerts_name_registered_codes`：在 `S/observer/`、`S/executor/watchdog.py` 上调用 `codes_at_calls(..., {"raise_alert", "_alert", "alert", "_raise", "_enter", "_set"})`，每个代码都在 `CODES["alert"]` 里。
- [ ] **Step 2：运行，确认失败**
- [ ] **Step 3：实现**
  - 各发出点传 `code` 和 `params`。
  - 在 `S/codes.py` 登记这 14 个代码。
  - 运行导出脚本。
  - 在 `W/i18n/messages.{en,zh}.js` 写 `msg.alert.<code>` 和 `.action`。
- [ ] **Step 4：运行，确认通过** —— `PYTHONPATH=src pytest -q` 和 `node --test tests/web/*.test.mjs` 都通过，`T/messages.test.mjs` 覆盖到这 14 个代码。
- [ ] **Step 5：提交** —— `git commit -m "feat: give observer, stage-check and pump watchdog alerts codes and params"`

### Task 6：告警发出点：运行时、模型任务、备份、命令行、监察

**Files:**
- Modify：
  - `S/runtime.py`：174–184、211、287–298、390、443、480、488、554、572 行。
  - `S/runtime_agents.py`：129–161 行。
  - `S/runtime_backup.py`：72 行。
  - `S/cli.py`：105 行。
  - `S/agents/handlers_auditor.py`：160 行。
  - `S/archive/source.py`：50 行，`SourceRewound` 加属性。
  - `S/codes.py`、`F/message-codes.json`、`F/known-codes.json`、`W/i18n/messages.{en,zh}.js`、`W/i18n/codes.{en,zh}.js`
- Test：
  - 这些模块现有的测试文件
  - `tests/workbench/test_message_codes.py`
  - `tests/workbench/test_console_known_codes.py`

**Interfaces:**
- Produces：下表的 19 个 `alert` 代码，加上 Task 5 的 14 个，共 33 个。
  - 另有三组新的标签前缀，写进 `known-codes.json`，并加上 `_sources`：
    - `tickStep`：archive、executor、recovery、observer、outbox、tasks、compute、report、backup、health；
    - `probe`：`S/observer/health.py` 第 17 行的 6 个探针名；
    - `heartbeat`：host、run。
  - `SourceRewound(top_rowid: int, cursor: int)` 带这两个属性，英文文字不变。

| 代码（kind） | params | 下一步要点 |
|---|---|---|
| `backup_unconfigured` | — | 在服务器设置里指定备份目录并重启，否则数据库没有备份 |
| `notify_unconfigured` | — | 设置邮件或 Telegram，否则告警发不出去 |
| `monitor_unconfigured` | — | 设置外部心跳服务，主机或运行停下时才会有人知道。环境变量名只留在 `message` |
| `not_write_host`（kind `runtime`） | — | 从登记的写入主机启动；这台主机不控制设备 |
| `tick_step` | `step` | 看服务器日志里这一步的报错；反复失败就重启并找管理员 |
| `source_rewound` | `top_rowid`, `cursor` | 先停下，请管理员检查旧数据，再开始新的运行 |
| `intervention_mirror` | `intervention_kind`（只进详情） | 告诉管理员有一次人工干预没复制到存档；日志显示丢失的话，重新录入 |
| `stage_waiting` | `stage_id`, `entry_id`, `state`, `event`, `detail`（历史条目的原样 detail） | 打开阶段页，按原因处理后继续运行阶段 |
| `task_deadline` | `task_id`, `project_id`, `role` | 打开项目里的这个任务，处理完或关闭 |
| `run_health` | `failures` | 修好列出的那几项；修好前，这次运行的数据不可信 |
| `external_monitor` | `signal` | 检查这台主机的网络和心跳服务 |
| `backup` | — | 检查磁盘空间和备份目录；下次会自动重试 |
| `agent_task_failed`（kind `agent_task`，形态 A） | `task_id`, `project_id`, `role` | 打开任务，看技术详情里的报错，再重试或关闭 |
| `agent_task_attention`（kind `agent_task`，形态 B） | `task_id`, `project_id`, `role` | 打开任务，回答或关闭 |
| `audit_task_failed`（kind `audit_task`，形态 A） | `stage_id`（任务没有阶段时为 `null`）, `task_id` | 监察只是提醒；可以重试，也可以忽略 |
| `audit_task_attention`（kind `audit_task`，形态 B） | `stage_id`, `task_id` | 同上 |
| `audit_schedule` | — | 请管理员处理；修好前不会安排监察 |
| `model_client` | — | 检查服务器上的模型密钥和软件包；修好前 AI 助手都不工作 |
| `audit_finding` | `stage_id`, `summary`, `evidence` | 读监察备注，决定这个阶段要不要改，再标为已读 |

- `stage_waiting` 的英文 `message` 照旧，`json.dumps` 也照旧。控制台不显示它，只放进技术详情。
- `audit_finding` 的 `message` 仍然是 `summary` 和 `evidence` 用换行连起来，模型的工具 `open_alerts` 照旧读 `message`。

- [ ] **Step 1：写失败的测试**
  - 每个代码一个测试，规则和 Task 5 相同。
  - `test_source_rewound_carries_its_row_numbers`
  - `test_every_alert_in_the_server_names_a_registered_code`：用 `codes_at_calls` 扫整个 `S/`，覆盖 Task 5 和本任务。另外，每个调用 `raise_alert`、`alert`、`_alert` 的地方都要带 `code=`；用 AST 检查，`AlertBook`、`Runtime` 自身的转发除外。
  - 在 `tests/workbench/test_console_known_codes.py` 里加 `test_console_lists_every_tick_step_probe_and_heartbeat`。
- [ ] **Step 2：运行，确认失败**
- [ ] **Step 3：实现**
  - 各发出点传 `code` 和 `params`，登记代码，运行导出脚本。
  - 写 `msg.alert.*` 和这三组标签。
- [ ] **Step 4：运行，确认通过** —— 两套测试都通过，再跑 ruff。
- [ ] **Step 5：提交** —— `git commit -m "feat: give runtime, model task, backup and auditor alerts codes and params"`

### Task 7：告警页和收件箱里的告警（ALT-01 至 ALT-13 的显示部分、ALT-12 的链接）

**Files:**
- Modify：
  - `W/pages/alerts.js`：31 行 `messageCell`；73 行。
  - `W/pages/inbox.js`：99–107 行 `DESCRIBERS.alert`。
  - `T/support/leak-exemptions.mjs`
  - `F/alerts.json`、`F/inbox.json`、`F/README.md`
- Test：`T/alerts-page.test.mjs`、`T/shell.test.mjs`、`T/leaks.test.mjs`

**Interfaces:**
- Consumes：`messageView`、`messageParts`（Task 3），`detailLines(ctx, entry)`（`W/pages/stage-history.js` 第 68 行）。
- Produces：告警行和收件箱告警条目的新显示。行为：
  - **有代码：** 用 `messageView` 显示正文和下一步。技术详情里另加：kind（标签和原码）、key、服务器原文（`tech.serverMessage`）。
  - **`stage_waiting`：** 正文下面列出 `detailLines(ctx, {type: "transition", event, detail}).lines`，`raw` 部分并入技术详情。
  - **`audit_finding`：** 先一句固定的话（`msg.alert.audit_finding`），下面用 `<blockquote class="model-note">` 引用 `summary`，`evidence` 列成清单。这是模型写的文字，措辞属于第三批。
  - **链接：**
    - 有 `params.stage_id` 时，加"打开阶段"，指向 `#/stages/${encodeURIComponent(id)}`；
    - 有 `params.project_id` 时，加"打开项目"；
    - 绝不解析 key。
  - **没有代码的旧行：** 标题是 `labelOr(t, "alert.kind", kind)`，下面一句新文案 `alerts.legacy`（"这条告警来自更新之前，服务器原文在技术详情里"），原文放进技术详情。
  - **收件箱告警条目：** 标题是 `messageParts` 的正文（未知代码时显示类型标签），下一步作为一行，技术详情同上。

- [ ] **Step 1：转换测试数据**
  - 把 `F/alerts.json` 和 `F/inbox.json` 里的每条告警改成新形态：按 Task 5、6 的表加 `code` 和 `params`，`message` 保持原样。
  - 保留一条没有 `code` 的旧告警。
  - 补一条 `stage_waiting`，它的阶段 id 带冒号（例如 `stage:a-1`），`detail` 里有 `seconds` 和 `reasons`。
  - 在 `README.md` 写明哪些条目是转换来的、按哪张表转换。
- [ ] **Step 2：写失败的测试**
  - 「an alert row says what happened and what to do; the server's words are in the details」
  - 「a waiting stage's alert lists its reasons as sentences and links to the stage even when its id has a colon」（Review Focus 4）：href 等于 `#/stages/stage%3Aa-1`。
  - 「an auditor's note is quoted under a fixed sentence」
  - 「an alert from before codes shows its kind and keeps the message in the details」（Review Focus 1）
  - 「an inbox alert is titled by its text, not by the server's message」
- [ ] **Step 3：删掉豁免**
  - 删掉 `alerts / alerts.json / alerts[*].message` 和 `inbox / inbox.json / items[*].detail.message` 两条。
  - 为 `audit_finding` 的 `params.summary` 和 `params.evidence[*]` 加第三批豁免，原因写"模型写的监察备注（C5，ALT-11）"。路径写法按 `exemptStrings` 支持的 `a[k=v].b` 和 `[*]`。
  - 运行，确认 `leaks.test.mjs` 和上面的新测试失败。
- [ ] **Step 4：实现，运行，确认全部通过** —— `node --test tests/web/*.test.mjs`。
- [ ] **Step 5：提交** —— `git commit -m "feat: alerts and inbox alerts read as sentences with a next step and link to their stage"`

### Task 8：运行单检查结果带参数（服务器；STG-01、STG-02、STG-03–06 的服务器部分）

**Files:**
- Modify：
  - `S/ports.py`：118 行 `Finding`。
  - `S/planning/validate.py`：`_block`、`_hint` 在 23、27 行，标签在 36–47、261 行，各发出点在 58–292 行。
  - `S/planning/design.py`：18、91–152 行。
  - `S/planning/treatment.py`：53–60、84–91、133、138 行。
  - 检查证据的那个函数所在的文件（`grep -rn "def check_evidence" S/`）。
  - `S/codes.py`、`F/message-codes.json`、`F/known-codes.json`、`W/i18n/messages.{en,zh}.js`、`W/i18n/codes.{en,zh}.js`
- Test：`tests/planning/` 里现有的对应文件，`tests/workbench/test_message_codes.py`、`test_console_known_codes.py`

**Interfaces:**
- Produces：
  - `Finding.params: dict[str, Any]`，默认 `{}`。
  - `Finding.variant: str = ""`。
  - 消息代码在 `variant` 为空时是 `code`，否则是 `f"{code}.{variant}"`。`code` 本身（分组和 `finding.<code>` 标题）不变。
  - `_block(code: str, message: str, *, variant: str = "", **params: object) -> Finding`，`_hint` 同样。两者都过 `checked("finding", 消息代码, params)`。
  - "timed action X"、"feedback rule X" 这类英文标签改成两个参数：`source_kind`（`timed_action`、`feedback_rule`、`feedback_release`、`care_step`、`end_action`、`protection_rule`）和 `source`（条目的名字）。英文 `message` 仍由同样的值拼出。
  - 标签前缀 `findingSource`（6 个）和 `findingProblem`（`not_host`、`no_action`、`other_levels`）写进 `known-codes.json`。
  - `uncalibrated` 的英文 `message` 去掉写死的"（未校准）"。

| 消息代码 | params | 下一步要点 |
|---|---|---|
| `device_owned_write` | `source_kind`, `source`, `channel` | 让主机控制这个通道，或删掉这条动作 |
| `pump_action` | `source_kind`, `source` | 删掉自动开泵的步骤，改成写明秒数的人工浇水任务（STG-03：英文里去掉 "with seconds" 这种术语） |
| `level_range` | `source_kind`, `source`, `channel`, `level`, `min`, `max` | 改成范围内的档位 |
| `pump_device_owned` | — | 水泵由设备自己控制，运行单不能写它 |
| `unknown_sensor` | `rule`, `sensor` | 选设备会报告的传感器 |
| `unit_mismatch` | `rule`, `sensor`, `device_unit`, `rule_unit` | 改成设备的单位 |
| `humidity_exhaust_only` | `rule` | 湿度规则只能动排风 |
| `rule_conflict` | `rule_a`, `rule_b`, `channel`, `priority` | 调整两条规则的优先级或档位 |
| `safety_conflict` | `rule`, `protection`, `channel`, `level`, `protection_level` | 改档位，让它不和安全保护冲突 |
| `sampling.validity` | `rule`, `validity_seconds`, `interval_seconds` | 有效期要长于采样间隔 |
| `sampling.interval` | `interval_seconds` | 采样间隔要大于 0 |
| `sampling.max_gap` | `max_gap_seconds` | 最长空档要大于 0 |
| `duration.rule` | `rule`, `duration_seconds`, `min_switch_seconds` | 持续时长不能短于最短切换间隔 |
| `duration.protection` | `protection`, `duration_seconds` | 填一个正的持续时长 |
| `duration.run` | `duration_seconds` | 填一个正的运行时长 |
| `wait` | `max_wait_seconds` | 填一个正的最长等待 |
| `missing_tolerance` | `channel` | 为这个通道写明能容忍的缺失 |
| `manual_task` | `task_kind`, `task_id`, `at_local` | 每天这个时间要有人到场（STG-06） |
| `manual_task.irrigation` | `task_id`, `at_local`, `seconds` | 每天这个时间要有人到场浇水 |
| `no_evidence` | `source_kind`, `source` | 为这条动作附上证据卡 |
| `unverified_source` | `source_kind`, `source`, `card_id` | 先核验这张证据卡（STG-05） |
| `uncalibrated` | `source_kind`, `source`, `card_id` | 先校准这张证据卡依据的测量 |
| `unknown_treatment` | `treatments` | 只用协议里有的处理 |
| `missing_control.undefined` | `control` | 在协议里定义对照 |
| `missing_control.unallocated` | `control` | 把对照分进区组 |
| `no_replication` | `treatments` | 每个处理至少重复两次 |
| `unbalanced_block` | `block` | 让这个区组里每个处理各出现一次 |
| `confounded_with_time` | — | 每一轮里都要混合不同处理 |
| `seed_mismatch.unreproducible` | — | 随机种子无法复现分配，请重新生成分配 |
| `seed_mismatch.differs` | — | 分配和随机种子给出的不同，请用种子重新生成 |
| `treatment_not_applied` | `round`, `treatment`, `problems` | 为处理的每个档位加上定时动作（STG-04） |
| `treatment_not_applied.none` | `round`, `treatments` | 运行单没有实现任何一个处理 |

其中：
- `problems` 是列表，每项是 `{channel, kind, level, other}`。`kind` 取 `not_host`、`no_action`、`other_levels` 之一。
- `treatments` 是名字的列表。
- 如果实现时发现某个发出点不在表里，按同样的规则补一行：参数名遵守"参数约定"，下一步写一句。然后在提交说明里点名这一行。

- [ ] **Step 1：写失败的测试**
  - 表里每一行都有一个测试，断言 `finding.code`、`finding.variant`、`finding.params`。
  - `test_finding_messages_keep_their_english_without_chinese`：没有任何 `message` 含中文字符。
  - `test_every_finding_names_a_registered_message_code`
  - 在 `test_console_known_codes.py` 里加 `test_console_lists_every_finding_source_and_problem_kind`。
- [ ] **Step 2：运行，确认失败**
- [ ] **Step 3：实现。** 登记代码，运行导出脚本，写 `msg.finding.*` 和这两组标签。
- [ ] **Step 4：运行，确认通过** —— 两套测试都通过，再跑 ruff。
- [ ] **Step 5：提交** —— `git commit -m "feat: run sheet findings carry a message code and params"`

### Task 9：检查结果在控制台的显示（STG-01、STG-02 的其余部分）

**控制台负责人在派 Task 9 之前自己做：**
- 用本分支的代码重启开发工作台，按第一批计划的"准备"一节操作，数据从 `<scratchpad>/console-data/` 复制一份新的。
- 重新抓取 `run-sheet.json` 和 `run-sheet-pending.json`。检查结果是每次读的时候现算的，所以抓下来就是新形态。
- 检查口令没有进入测试数据，然后提交：`test: recapture the run sheet fixtures with finding params`。

**Files:**
- Modify：`W/pages/stage-actions.js`（98 行 `groupFindings`、112 行 `findingsList`）、`T/support/leak-exemptions.mjs`
- Test：`T/run-sheet-review.test.mjs`、`T/leaks.test.mjs`

**Interfaces:**
- Consumes：`messageParts`（Task 3）、`Finding.params` 和 `Finding.variant`（Task 8）。
- 行为：
  - 分组照旧，按 `blocking` 和 `code` 分。
  - 每一项的 `<li>` 是 `messageParts(ctx, "finding", 消息代码, item.params).text`。
  - 组内各项的下一步去重后，放在组标题下面，写作"怎么改：……"。
  - 技术详情：代码、每项的服务器原文、id 参数。
  - 消息代码未知时，该项显示 `common.unknown`，服务器原文进技术详情。

- [ ] **Step 1：写失败的测试**
  - 「each finding reads as a sentence and its group says how to fix it once」
  - 「a finding the catalog lacks says unknown and keeps the server's words in the details」
  - 「a name a planner chose is shown in quotes」
- [ ] **Step 2：删掉豁免。** 删掉 `findings[*].message` 的两条。运行，确认失败。
  - 如果抓取的数据里有带下划线的条目名被扫描器标出，加一条 `keep` 豁免，原因写"运行单里规划者起的名字，审阅时要靠它找到对应条目"。
- [ ] **Step 3：实现，运行，确认全部通过**
- [ ] **Step 4：提交** —— `git commit -m "feat: run sheet findings read as sentences with how to fix them"`

### Task 10：写入回执和浇水提前结束带代码（服务器；STG-20、TSK-04）

**Files:**
- Modify：
  - `S/control/device.py`：34–46 行 `changed_nothing` 和 `Outcome`；171–196 行。
  - `S/control/service.py`：129、183–186、274、284、363、377、479、492、517、525–573、621–623 行，以及 `_end_cycle`。
  - `S/archive/models.py`：288 行 `TaskRecord`，454 行 `ActionRecord`。
  - `S/workbench/manual_tasks.py`：79 行。
  - `S/codes.py`、`F/message-codes.json`、`W/i18n/messages.{en,zh}.js`
- Test：`tests/control/` 和 `tests/workbench/` 里现有的对应文件

**Interfaces:**
- Produces：
  - `Outcome` 加 `error_code: str | None = None` 和 `error_params`（默认 `{}`）。
  - `ActionRecord` 加同样的两个字段，默认值相同。
  - `TaskRecord` 加 `ended_early_code: str | None = None` 和 `ended_early_params`（默认 `{}`），英文的 `ended_early` 照旧。
  - `changed_nothing(record)` 先看 `error_code`；`error_code` 为 `None` 的旧记录，仍用原来的英文前缀判断。
  - `receipt` 族 17 个代码，`task_end` 族 6 个代码，见下表。

| 族.代码 | params | 下一步要点 |
|---|---|---|
| `receipt.not_sent` | — | 指令没发出去，设备没变；检查连接后重试 |
| `receipt.device_rejected` | — | 设备拒收了指令，设备没变；检查设备后重试 |
| `receipt.no_receipt` | — | 没收到回执，结果不明；到现场核对，并记一次现场检查 |
| `receipt.link_broke` | — | 连接中途断了，结果不明；处理同上 |
| `receipt.readback_level` | `channel`, `expected` | 读回的档位不对；到现场核对 |
| `receipt.readback_unavailable` | — | 读不回设备状态，结果不明；到现场核对 |
| `receipt.readback_mode` | `mode` | 插座模式不对；到现场核对 |
| `receipt.void_recovery_changed` | — | 恢复编号变了，指令作废，没有执行；需要的话重新提交 |
| `receipt.void_handover` | — | 控制权交接了，指令作废，没有执行；需要的话重新提交 |
| `receipt.void_restart` | — | 指令发出前进程停了，没有执行；需要的话重新提交 |
| `receipt.void_superseded` | `channel` | 被保护写入取代，没有执行 |
| `receipt.void_denied` | `denied_code`（只进详情） | 被拒绝，没有执行；拒绝原因见技术详情 |
| `receipt.internal_error` | — | 服务器内部出错，结果不明；到现场核对，并通知管理员 |
| `receipt.lost_receipt` | — | 回执存下之前进程停了，结果不明；到现场核对 |
| `receipt.pump_off_unconfirmed` | — | 关泵没有确认；到现场手动关泵 |
| `receipt.settled_applied` | `channel`, `level` | 读回确认已生效，无需处理（`action: False`） |
| `receipt.settled_not_applied` | `channel`, `level`, `mode` | 读回确认没有生效；需要的话重新提交 |
| `task_end.handover` | — | 控制权交接，浇水提前结束，无需处理（`action: False`） |
| `task_end.protection_write` | `channel` | 安全保护接管了，浇水提前结束；检查原因 |
| `task_end.pump_off_interlock` | — | 联锁关了水泵；检查原因 |
| `task_end.pump_off_watchdog` | — | 看门狗关了水泵；检查原因 |
| `task_end.not_confirmed` | `action_state` | 浇水没有确认完成；到现场核对 |
| `task_end.other` | — | 浇水提前结束；需要的话到现场核对 |

各发出点的英文 `error` 和 `ended_early` 文字一律不变。异常文本留在英文里，不进 `params`。`_run_cycle` 里"pump off did not run"和"no attempt"两种都归入 `pump_off_unconfirmed`。

- [ ] **Step 1：写失败的测试**
  - 每个发出点一个测试，断言 `error_code` 和 `error_params`（或 `ended_early_code`）。
  - `test_changed_nothing_reads_the_code_and_still_knows_old_records`：没有代码、`error` 以 "not sent" 开头的旧记录，仍判为没有改变。
  - `test_an_action_record_without_the_new_fields_still_reads`：一段旧 JSON 能通过 `model_validate_json`。
  - `test_every_receipt_and_task_end_code_is_registered`
- [ ] **Step 2：运行，确认失败**
- [ ] **Step 3：实现。** 登记代码，运行导出脚本，写 `msg.receipt.*` 和 `msg.task_end.*`。
- [ ] **Step 4：运行，确认通过** —— 两套测试都通过，再跑 ruff。
- [ ] **Step 5：提交** —— `git commit -m "feat: receipts and early irrigation ends carry a code and params"`

### Task 11：回执和任务行在控制台的显示（STG-20、TSK-04 的显示部分）

**Files:**
- Modify：`W/pages/stage-actions.js`（377 行 `outcomeLines`）、人工任务行所在的页面文件（`grep -rn "ended_early\|ran_seconds" W/`）
- Test：`T/receipts.test.mjs`、`T/stage-status.test.mjs`、`T/stage-tasks.test.mjs`

**Interfaces:**
- Consumes：`messageView`（Task 3）、`error_code` 和 `ended_early_code`（Task 10）。
- 行为：
  - **失败的回执：** 用 `messageView(ctx, "receipt", record.error_code, record.error_params)`，不再写 `receipt.error`（"原因：{error}"）。
  - **没有代码的旧回执：** 显示新文案 `receipt.failedUnknown`（"没有执行，原因见技术详情"），`error` 原文进技术详情。
  - **部分完成的浇水任务行：** "水泵运行了 {ran}"，后面接 `task_end` 的正文，再接下一步；不再打印英文 `ended_early`。
  - **完成或失败的提示：** 写任务名，不写请求 id（TSK-04）。请求 id 进技术详情。

- [ ] **Step 1：写失败的测试**
  - 「a failed receipt says what happened and what to do, without the server's words」
  - 「an old receipt without a code keeps its reason in the details」
  - 「a partial irrigation says how long the pump ran and why it stopped」
  - 「irrigation notices name the task, not the request」
- [ ] **Step 2：运行，确认失败。** 然后实现，再运行，确认全部通过。
- [ ] **Step 3：提交** —— `git commit -m "feat: receipts and partial irrigations read as sentences"`

### Task 12：计算尝试卡住的原因（CMP-04，服务器和控制台）

**Files:**
- Modify：
  - `S/compute/service.py`：建表在 69 行附近，迁移照这个文件已有的做法。各出错点：480–649 行；683 行是 `OUTPUT_LIMIT_MARK` 的判断。
  - `S/compute/overview.py`：97–132 行。
  - `S/workbench/reads.py`：163 行 `compute_stuck`。
  - `S/workbench/compute.py`：81 行。
  - `W/pages/compute-attempts.js`：72–77 行。
  - `W/pages/inbox.js`：109–112 行。
  - `S/codes.py`、两份 JSON、目录文件、`T/support/leak-exemptions.mjs`、`F/inbox.json`、`F/compute.json`
- Test：`tests/compute/` 里现有的对应文件、`T/research-pages.test.mjs`、`T/shell.test.mjs`、`T/leaks.test.mjs`

**Interfaces:**
- Produces：
  - `compute_attempts` 加两列：`error_code TEXT NOT NULL DEFAULT ''` 和 `error_params TEXT NOT NULL DEFAULT '{}'`。
  - 原来的 `error` 列照写英文。判断输出超限改为看 `error_code == "output_limit"`；旧行仍用英文前缀判断。
  - 卡住的行加三个字段：
    - `reason_code`：取 `reconcile_wait`、`not_refreshed`、`error` 之一；
    - `reason_params`；
    - 当 `reason_code == "error"` 时，再带上这次尝试的 `error_code` 和 `error_params`。
  - `reason` 照旧。收件箱条目的 `detail` 同样加上这几个字段。

| 族.代码 | params | 下一步要点 |
|---|---|---|
| `compute_stuck.reconcile_wait` | `age_seconds` | 提交结果不明，正在等核对；可以再等，也可以结算 |
| `compute_stuck.not_refreshed` | `age_seconds` | 很久没刷新；检查集群调度，任务不在了就结算 |
| `compute_stuck.error` | — | 这次计算出错了（下面一行是具体错误） |
| `compute_error.submit_rejected` | — | 集群拒绝了提交；检查任务设置后重试 |
| `compute_error.submit_failed` | — | 提交时出错；稍后重试 |
| `compute_error.orphan_not_cancelled` | — | 远端还有一个没取消的任务；请管理员处理 |
| `compute_error.late_cancelled` | — | 迟到的远端任务已取消，无需处理（`action: False`） |
| `compute_error.backend_error` | — | 和集群通信出错；稍后重试取回 |
| `compute_error.cancelled_no_job` | — | 已取消，远端没有找到任务，无需处理（`action: False`） |
| `compute_error.cancel_unknown` | — | 已请求取消，远端状态不明；稍后再看 |
| `compute_error.outcome_unknown` | — | 结果不明，已按整笔预留计费 |
| `compute_error.cancel_failed` | — | 远端取消失败；请管理员处理 |
| `compute_error.cleanup_failed` | — | 清理失败；请管理员处理 |
| `compute_error.settled_by_operator` | — | 已由操作员结算，无需处理（`action: False`） |
| `compute_error.output_limit` | `limit_kind`（只进详情）、`bytes`、`limit` | 输出超过上限；结算（按未知用量计费） |
| `compute_error.artifact_missing` | `name` | 输出文件缺失或不在输出目录；结算后重新提交 |
| `compute_error.artifact_mismatch` | `name` | 输出文件校验不符；结算后重新提交 |

`bytes` 和 `limit` 按"参数约定"里的字节规则显示（Task 3 已实现）。

- [ ] **Step 1：写失败的测试**
  - 服务器：
    - 每个出错点的 `error_code`；
    - 三种卡住原因的 `reason_code`；
    - `test_an_attempt_stored_before_codes_still_counts_as_over_the_output_limit`；
    - 迁移后，旧行读出来 `error_code == ''`。
  - 控制台：
    - 「a stuck attempt says why and what to do; the server's words are in the details」，计算页和收件箱各一个；
    - 「an old stuck attempt without a code shows a generic line」。
- [ ] **Step 2：转换数据并删掉豁免。** 转换 `F/inbox.json` 的 `compute_stuck` 条目和 `F/compute.json`，删掉 `items[*].detail.reason` 那条豁免。运行，确认失败。
- [ ] **Step 3：实现。** 登记代码，运行导出脚本，写目录。运行，确认全部通过，再跑 ruff。
- [ ] **Step 4：提交** —— `git commit -m "feat: stuck compute attempts say why with a code and params"`

### Task 13：对话里任务结束的原因（P-11）

**Files:**
- Modify：`S/agents/dispatch.py`（`_end`，185–205、298–312 行）、`W/pages/conversation.js`（104 行 `statusText`、110 行 `statusView`）、`S/codes.py`、`F/message-codes.json`、目录文件
- Test：`tests/agents/` 里现有的调度测试、`T/conversation.test.mjs`

**Interfaces:**
- Produces：状态条目的 `detail` 加 `code` 和 `params`，`reason` 照旧。

| 代码 | params | 下一步要点 |
|---|---|---|
| `chat_end.denied` | `denied_code`（只进详情） | 某一步被拒绝了；原因见技术详情 |
| `chat_end.model_unavailable` | — | 模型连不上；检查密钥和预算后再问一次 |
| `chat_end.model_stopped` | `stop_reason`（只进详情） | 模型没做完就停了；把问题说短一点再问一次 |
| `chat_end.undelivered` | `role` | 这个助手没有交出成果；再问一次，或者自己做这一步 |
| `chat_end.run_finished` | — | 无（`action: False`） |

`follow_up` 条目不带原因，保持不变。

- [ ] **Step 1：写失败的测试**
  - 服务器：每种原因一个测试，断言 `detail.code` 和 `detail.params`。
  - 控制台：
    - 「a status line says why the task ended and what to do next」
    - 「a status entry from before codes keeps its reason in the details only」：保留第一批的行为。
- [ ] **Step 2：运行，确认失败。** 然后实现、登记、导出、写目录，再运行，确认全部通过。
- [ ] **Step 3：提交** —— `git commit -m "feat: say why a model task ended in the conversation"`

### Task 14：研究备注的参数、估计说明和主要指标（RND-16、RND-11）

**Files:**
- Modify：
  - `S/research/notes.py`
  - `S/planning/treatment.py`：133、138 行 `delivered()`。
  - `S/planning/manual_tasks.py`：135 行。
  - `S/agents/handlers_report.py`：187、191、204–229、462–466 行。
  - `S/research/stats.py`：24、100–139 行。
  - `S/workbench/rounds.py`：110 行 `report_json`。
  - `W/pages/round.js`：86 行 `estimateText`。
  - `S/codes.py`、`F/message-codes.json`、目录文件、`T/support/leak-exemptions.mjs`、`F/report.json`（还有 round 相关的数据文件）
- Test：`tests/research/`、`tests/agents/`、`tests/workbench/` 里现有的对应文件、`T/round-report.test.mjs`、`T/leaks.test.mjs`

**Interfaces:**
- Produces：
  - **备注参数改成结构化数据，只影响新报告：**
    - `treatment_not_applied.problems` 改成 `[{channel, kind, level, recorded, share}]`。`kind` 取 `never_at` 或 `other_share`；`recorded` 是档位列表；`share` 是 0–1 之间的数。
    - `treatment_unverified.channels` 改成列表。
    - `manual_tasks_missed` 的 `detail` 改为 `by_kind: {task_kind: count}`。
    - `snapshot_incomplete.coverage` 改为 0–1 的数。
    - `treatment_id` 改为 `treatment`，即处理名。
    - `notes.py` 的中英文模板按语言把这些参数写成人话。服务器端放一张小的通道名和任务类型名对照表，中英文各一份。
  - **估计说明：** `BlockEstimate` 加 `note_code: str = ""` 和 `note_params`（默认 `{}`），英文 `note` 照旧。

    | 代码 | params | 下一步要点 |
    |---|---|---|
    | `estimate.too_few_blocks` | `blocks`, `min_blocks` | 再跑几轮，让每个处理至少有两个完整区组 |
    | `estimate.sampled_p` | `flips`, `blocks` | p 值是抽样近似的，无需处理（`action: False`） |

    精确估计不需要说明，代码为空。
  - **主要指标：** `report_json` 返回值加 `primary_endpoint: str | None`，在读的时候从轮次的协议版本取（`store.protocol(rnd.protocol_id, rnd.protocol_version).analysis.primary_endpoint`），协议已经不在时为 `None`。
  - **控制台的 `estimateText`：**
    - 有 `note_code` 时，用 `messageParts(ctx, "estimate", ...)`。
    - 没有 `note_code` 的旧报告，显示 `report.notEstimable`，英文 `note` 进技术详情。
    - 有 `primary_endpoint` 时，写出"指标：{metric}"。

- [ ] **Step 1：写失败的测试**
  - 服务器：
    - `test_treatment_problems_are_data_and_read_in_both_languages`：中文文本里没有英文句子，也没有方括号列表。
    - `test_unverified_channels_and_missed_tasks_are_lists_and_counts`
    - `test_an_estimate_with_too_few_blocks_carries_a_note_code`
    - `test_the_report_read_names_the_primary_endpoint`
    - `test_a_report_whose_protocol_is_gone_has_no_primary_endpoint`
  - 控制台：
    - 「an estimate note follows the console language and says what to do」
    - 「an old report's note stays in the details」（Review Focus 1）
    - 「the estimate names the measured quantity」
- [ ] **Step 2：转换数据并删掉豁免。** 转换 `F/report.json` 的 `estimate`，加上 `note_code` 和 `note_params`。round 相关的数据加上 `primary_endpoint`。删掉 `report.estimate.note` 那条豁免。运行，确认失败。
- [ ] **Step 3：实现、登记、导出、写目录。** 运行，确认全部通过，再跑 ruff。
- [ ] **Step 4：提交** —— `git commit -m "feat: structured research note params, coded estimate notes and the primary endpoint"`

### Task 15：项目预算的已用量（P-04）

**Files:**
- Modify：`S/agents/budget.py`、`S/workbench/rounds.py`（45–50 行 `ProjectBudget`）、`S/workbench/reads.py`（188–197 行 `_budget_view`）、`W/pages/project.js`（53–54 行）
- Test：`tests/workbench/` 里现有的项目读取测试（实现了 `remaining` 的假对象也要补新方法：`grep -rn "def remaining" tests`）、`T/project-page.test.mjs`

**Interfaces:**
- Produces：
  - `CallBudget.usage(project_id: str) -> BudgetUsage | None`。`BudgetUsage` 有四个字段：`used_calls: int`、`used_cost: float`、`max_calls: int`、`max_cost: float`。
  - `ProjectBudget` 协议加上这个方法。
  - `_budget_view` 在原来的 `calls_left`、`cost_left` 之外，再加这四个字段。
  - 控制台显示"已用 {used} / 共 {max}"：调用次数是整数，费用用 `formatMoney`。
  - 只有项目层面的模型调用。不要显示按轮次的用量或计算时数。
- [ ] **Step 1：写失败的测试**
  - `test_the_project_read_shows_used_and_total_budget`
  - `test_used_cost_can_exceed_the_total_and_is_shown_as_it_is`：费用可能超出总额，照实显示，不夹到总额以内。
  - 「the budget reads as used of total」
- [ ] **Step 2：运行，确认失败。** 然后实现，再运行，确认全部通过。
- [ ] **Step 3：提交** —— `git commit -m "feat: show how much of a project's model budget is used"`

### Task 16：环境页画出运行单计划的档位（ENV-02）

**Files:**
- Create：`S/workbench/planned.py`
- Modify：`S/workbench/environment.py`（70–103 行 `active_stage`，134 行的调用）、`W/ui/chart.js`、`W/pages/environment.js`
- Test：`tests/workbench/test_workbench_planned.py`（新建）、`T/chart.test.mjs`、`T/environment.test.mjs`

**Interfaces:**
- Consumes：`RunSheet.expected_levels(at)`（`S/archive/models.py` 374 行）。
- Produces：
  - `planned_series(sheet: RunSheet, start: float, end: float) -> dict[str, list[tuple[float, int]]]`：
    - 只算主机控制的通道。
    - 第一个点在 `start`，之后在每个本地 `HH:MM` 动作边界对应的 UTC 时刻各取一个点。
    - 每个点都用 `expected_levels(t)` 求值，不对分钟数做算术，这样换夏令时的那天也对。
    - 相邻两点档位相同的，去掉后一个。
  - `active_stage(workflow, now, window)`：阶段为 RUNNING 时，`stage` 加 `planned: {channel: [[epoch, level], ...]}`，时间范围裁到 `[max(now - window, 阶段开始), now]`；不在运行时，`planned` 为 `{}`。
  - **控制台：** 档位曲线图上，用虚线画出计划的阶梯线，图例写"计划"，数据表加一列"计划档位"。
  - 温度和湿度在运行单里没有目标值，只有触发阈值，**不画**。这一点写进清单结果。

- [ ] **Step 1：写失败的测试**
  - `test_planned_levels_step_at_each_local_action_time`
  - `test_planned_levels_cross_midnight_from_the_previous_days_last_action`：午夜前后接上前一天最后一个动作的档位。
  - `test_planned_levels_on_the_day_clocks_change`：时区 Europe/Helsinki，日期 2026-10-25。
  - `test_planned_levels_start_at_the_stage_start`
  - `test_a_stage_that_is_not_running_has_no_plan`
  - 「a level chart draws the plan as a dashed step line with a legend」
  - 「without a plan there is no plan line and no legend」
- [ ] **Step 2：运行，确认失败。** 然后实现，再运行，确认全部通过，再跑 ruff。
- [ ] **Step 3：提交** —— `git commit -m "feat: draw the run sheet's planned levels on the environment charts"`

### Task 17：收尾：防露出测试、API 参考、清单结果

**Files:**
- Modify：
  - `T/leaks.test.mjs`：212 行附近的测试名。
  - `T/support/leak-exemptions.mjs`
  - `docs/wiki/en/API-Reference.md`、`docs/wiki/zh-CN/API-Reference.md`
  - 清单（新增第 7 节）
  - `F/README.md`

- [ ] **Step 1：写失败的测试**
  - 测试名「no Batch 1 page leaks internal text」改为「no page leaks internal text」。
  - 新增「no exemption is left for the second batch」：`EXEMPTIONS.every((e) => e.batch !== 2)`。
- [ ] **Step 2：运行，确认通过。** 如果有第二批的豁免没删掉，回到它所属的任务去删，不要在这里删。
- [ ] **Step 3：写 API 参考（中英文）。** 新字段：
  - 告警的 `code`、`params`；
  - 检查结果的 `variant`、`params`；
  - 回执的 `error_code`、`error_params`；
  - 任务记录的 `ended_early_code`、`ended_early_params`；
  - 计算尝试的 `error_code`、`error_params`，卡住行的 `reason_code`、`reason_params`；
  - 对话状态的 `detail.code`、`detail.params`；
  - 估计的 `note_code`、`note_params`；
  - 报告读取的 `primary_endpoint`；
  - 预算的四个用量字段；
  - 环境读取的 `stage.planned`。
  - 另外写一段：各族代码的完整清单在 `tests/web/fixtures/message-codes.json`，由 `scripts/export_message_codes.py` 从 `src/growbridge/codes.py` 导出。
- [ ] **Step 4：在清单里新增第 7 节"第二批 2a 结果"。** 格式和第 6 节相同，逐行写状态和证据（测试文件和测试名）：
  - 本批的 20 个整行；
  - 补完的部分行：P-04、P-11、RND-11、STG-01、STG-02、ENV-02、ALT-11、ALT-12、FRM-06。FRM-06 写"部分（拒绝文字里的时长在 2b）"。
  - 另外记下：温湿度没有计划值；`stage_waiting` 的下一步是通用一句。
- [ ] **Step 5：运行全部检查** —— `node --test tests/web/*.test.mjs`、`PYTHONPATH=src pytest -q`、`ruff check src tests scripts`、`ruff format --check src tests scripts`，全部通过。
- [ ] **Step 6：提交** —— `git commit -m "docs: record the second batch's message codes in the API reference and the inventory"`

### Task 18：改造后截图与对照（控制台负责人自己做，不派子代理）

- [ ] 用本分支的代码重启开发工作台，数据从 `<scratchpad>/console-data/` 复制一份新的，不带 `--roles`。
- [ ] 截图页面：告警、收件箱、待审阅的阶段（检查结果）、轮次（报告）、环境、项目。每页中英文，1440 和 375 两种宽度。存到 `<scratchpad>/console-shots/after-2a/`，**不进仓库**。
- [ ] 和第一批的 after 截图并排对照。
- [ ] 在 375 宽、展开全部折叠的状态下，检查没有横向滚动。
- [ ] 把对照图发给用户。在清单第 7 节的截图列写上文件名。

**注意：** 存量数据里的告警是旧行，在截图里会显示成旧行的样子。重启时，运行时会重新发出"未配置"类告警，这几条会带上代码。
