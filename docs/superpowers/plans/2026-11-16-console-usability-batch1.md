# 控制台可用性改造第一批：实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 控制台不再把 id、代码、哈希、epoch 秒和原始 JSON 直接给用户看，改用名字和序号、目录文字、"技术详情"折叠，以及按界面语言格式化的时间和时长（清单 C1、C2、C3、C6、C10，以及零散项里属于显示的部分）。

**架构：** 先做四件共用件：`labelOr`、`format.js` 的格式函数、`techDetails`、`displayName`。同时做一个测试用的假 DOM 和防露出扫描。然后逐页应用。服务器只给读接口加名字字段，只加不改。

**技术栈：** 控制台是原生 ES 模块（无构建、无依赖），测试用 `node --test tests/web/*.test.mjs`。服务器是 Python 3.12 + FastAPI，用 `pytest`、`ruff`。

**设计：** `docs/superpowers/specs/2026-11-16-console-usability-design.md`（用户已批准："设计通过"）。
**清单：** `docs/superpowers/specs/2026-11-16-console-usability-inventory.md`，第 3 节的编号就是各行的正式编号。

路径简写：`W/` = `src/growbridge/web/workbench/`，`S/` = `src/growbridge/`。

## 本批覆盖的清单行

- **整行在本批（65 行）：**
  - INB-01–07
  - P-01、04、05、06、07、08、10、12、13
  - RND-01、02、03、05、08、12、13、14、15、20
  - STG-07–13、18、19、21
  - HIS-01–05
  - TSK-01、02、05、06、07
  - ENV-01–03
  - SAF-01、02、03、05
  - ALT-12、EVI-01
  - CMP-01、02、03、05
  - FRM-01–05
- **本批只做控制台部分（9 行）：** P-11、RND-09、RND-10、RND-11、STG-01、STG-02、ALT-11、FRM-06、ERR-01。其余部分属于第二批（服务器代码加参数）或第三批（提示词）。
- **其余行**（C4、C5、C7、C8、C9 及服务器文案）属于第二、三批。

## Global Constraints

- G1 名字：用户看到的是名字或序号（"项目：生菜光照系列"、"第 1 轮"、"第 1 阶段 · 营养生长"），不是 id。id 只出现在技术详情里，可复制。
- G2 代码经目录：任何代码都通过对照表变成文字；对照表里没有的，显示"未知（技术详情）"，绝不直接显示代码。
- G3 技术详情：全站一个折叠组件；默认收起，展开后显示完整 id、哈希、原始事件，每项可复制。界面正文里需要指代哈希时，只显示短指纹（前 8 位加 "…"）。
- G4 数字和时间：时长按大小用天、小时、分钟、秒；档位写成"值 / 满档"；日期时间按界面语言格式化，时区只在页头写一次；钱按语言格式化，不出现浮点误差。
- 不改视觉风格和版式体系（颜色、字体、整体布局），只改内容、顺序和折叠。
- 不引入前端框架或构建步骤：控制台仍是原生 ES 模块，没有外部依赖。
- 不改业务规则：安全、审批、工作流状态和权限一律不变。
- 不删任何可追溯信息：id、摘要、原始事件都保留在"技术详情"和 API 里。
- 技术详情藏得太深算失败：做审计或追溯时，必须一次点击就能看到并复制。
- 中英文目录必须同步（`tests/web/i18n.test.mjs` 已检查键集合相同、文字非空）；每条新文案都要中英两份。
- API 不兼容算失败：已有字段一个不删、不改名。
- 服务器改动只加读字段。字段缺失（旧数据）时显示"未命名轮次"一类的通用说法，id 放技术详情。照常 TDD、`pytest`、`ruff`；文件不超过 800 行，函数少于 50 行。
- 时区用 `ctx.me.timezone`（服务器的 `report_timezone`），整个界面只写一次。相对时间（"5 分钟前"）只用于 24 小时内的列表时间。技术详情每项可复制，另有"复制全部"。
- 清单里中、低级别的行，先确认还能复现；复现不了就在清单结果里记一笔"关闭：无法复现"，不硬改。
- 测试不用浏览器、服务器和网络；控制台源码不得出现 `innerHTML`、`outerHTML`、`insertAdjacentHTML`、`document.write`（已有测试 `no-html-injection.test.mjs`）。
- 读文件先 grep，再每次读 30–60 行。
- 提交信息用约定式前缀（`feat:`、`fix:`、`test:`、`docs:`），不加任何署名行，不跳过 pre-commit 钩子。

## Review Focus

1. **旧数据缺新字段：** 老轮次没有 `round_number`，协议没有对应生长期，项目被删后没有名字。应显示"未命名轮次"、"第 N 阶段"（无生长期）、"未命名项目"，id 进技术详情，不报错也不显示空白。测试在 Task 6。
2. **服务器发来目录里没有的代码**（新事件、新告警类型、新状态）：显示"未知（技术详情）"，原码进技术详情，永远不显示 `prefix.code` 这样的键。测试在 Task 3 和 Task 8。
3. **浏览器不给剪贴板**（非 https、权限被拒、`navigator.clipboard` 不存在）：按钮改说"复制失败，请手动选择"，文字留在页面上可以手动选中，不抛异常。测试在 Task 4。
4. **时间的边界情况：** 未来时间（时钟偏差）、`me.timezone` 缺失、跨年。不出现"−5 分钟前"，而是显示完整时间；缺时区按 UTC，侧栏写 UTC；不是今年的时间带年份。测试在 Task 2 和 Task 7。
5. **同一秒的多条历史：** 改成"新的在上"以后，转换和干预的相对顺序与原来正好相反、前后一致；超过折叠上限时，最新的仍在最上面。测试在 Task 8。

另外，长值在 375 px 宽度下要换行，页面不能横向滚动。这一条由 Task 19 的截图检查。

---

## 准备（控制台负责人在派 Task 1 之前自己做，不派子代理）

`<scratchpad>` 指本会话的临时目录 `/private/tmp/claude-1618820129/-Users-chenghao-Downloads-diagri/7aef49f1-45c9-4f52-92af-a0e7405f7e16/scratchpad`；它不在仓库里，任务的子代理不需要读它。

数据：2026-11-15 实跑的数据目录 `<scratchpad>/run/data`（模拟设备，含报告）。口令在 `<scratchpad>/run/.secret`，**只通过环境变量传，绝不打印**。

- [ ] 把数据目录复制到 `<scratchpad>/console-data/`（以后重开都从这个副本复制，原目录不动）。
- [ ] 在本分支当前提交（计划提交）上启动：`GROWBRIDGE_DEV_SECRET="$(cat <scratchpad>/run/.secret)" .venv/bin/python scripts/dev_workbench.py --data-dir <scratchpad>/console-data-run1`，不带 `--roles`，所以不调用任何模型。
- [ ] 逐页找出 `ctx.api.get(` 用到的路径，用浏览器会话或 httpx 登录后把每个回答存成 `tests/web/fixtures/<name>.json`。
  - 至少包括：`me`、`inbox`、`projects`、`project`、`holdouts`、`conversation`、`round`、`report`、`analysis`、`stage`、`run-sheet`、`history`、`manual-tasks`、`measurements`、`readings`、`environment`、`safety`、`alerts`、`evidence`、`compute`。
  - 计算服务没有挂载时，按 `S/compute/overview.py` 的结构手写 `compute.json`，并在 README 里标"合成"。
- [ ] 写 `tests/web/fixtures/README.md`：每个文件对应哪条路径（带参数的写成 `/stages/{id}` 这种模式）、来源（2026-11-15 实跑或合成）、截取时的提交号。
- [ ] 用脚本检查口令字符串不在任何 fixture 里（只输出"有/没有"）；cookie 和会话 id 不存。
- [ ] 截"改造前"截图：中文和英文，1440 与 375 两种宽度。页面为收件箱、项目、轮次（含报告）、阶段（待审阅和已结束各一）、环境、安全、告警。存到 `<scratchpad>/console-shots/before/`，**不进仓库**。
- [ ] 关掉服务器。提交 fixtures：`git add tests/web/fixtures && git commit -m "test: add console page fixtures from the 2026-11-15 round"`。

---

### Task 1：测试用假 DOM、页面渲染器和防露出扫描

**Files:**
- Create: `tests/web/support/fake-dom.mjs`
- Create: `tests/web/support/render-page.mjs`
- Create: `tests/web/support/leaks.mjs`
- Create: `tests/web/support/leak-exemptions.mjs`
- Create: `tests/web/leaks.test.mjs`

**Interfaces:**
- 用到：准备阶段的 `tests/web/fixtures/*.json` 和 `README.md`。
- 产出：
  - `installFakeDom({ clipboard } = {}) -> { restore(): void }`：设置 `globalThis.document`、`window`、`navigator`（`clipboard` 可以是 `undefined` 或带 `writeText` 的对象）、`localStorage`、`location`、`requestAnimationFrame`。页面用到什么成员就补什么。
  - `testCtx({ lang = "zh", timezone = "Europe/Helsinki", fixtures, now } = {}) -> ctx`：ctx 结构同 `W/main.js:101-116` 的 `makeCtx`。`api.get(path)` 按 README 的路径表返回 fixture 的深拷贝；没有对应 fixture 时抛 `ApiError(404, null, "HTTP 404")`。`api.post` 记录调用并返回 `{}`。`now` 是固定的 epoch 秒，供相对时间用。
  - `renderPage(page, params = {}, options) -> Promise<{ element, ctx }>`：动态 `import("W/pages/<page>.js")` 后调用 `render(ctx, params)`。
  - `visibleText(node) -> string`：收集文本节点和 `aria-label`，元素之间加空格，跳过 `details.tech-details` 子树，不收 `title` 属性。
  - `findLeaks(text, exempt = []) -> Array<{ kind, match }>`：先把 `exempt` 里的每个字符串从 `text` 删掉，再按下面 6 种形态匹配。结果按 `LEAK_PATTERNS` 的顺序排列，每种形态列出它的全部匹配。
  - `exemptStrings(page, fixtures) -> string[]`：按 `EXEMPTIONS` 里每条的 `{ page, fixture, path }`，取出 fixture 在该路径上的所有字符串。路径语法只支持 `a.b`、`a[*].b`。
  - `assertNoLeaks(node, exempt = [])`：有露出时，失败信息列出每一处。
  - `FIXTURES: Record<string, unknown>`（在 `render-page.mjs`）：文件名（如 `"history.json"`）到解析后 JSON 的映射，测试直接用。
  - `EXEMPTIONS: Array<{ page, fixture, path, batch: 2 | 3 | "keep", why }>`：初始为空数组。
  - `PAGES_CHECKED`：在 `leaks.test.mjs` 里，初始为空数组，各页面任务往里加 `{ page, params }`。

露出形态（设计的验收第 2 条，再加 uuid）：

```js
export const LEAK_PATTERNS = {
  snake: /\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b/,
  hexId: /(?<![0-9a-f])[0-9a-f]{32,}(?![0-9a-f])/i, // 不用 \b：round_9d38… 里下划线和数字之间没有词边界
  uuid: /\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/i,
  epoch: /\b1\d{9}(?:\.\d+)?\b/,
  payload: /\{\s*"/,
  i18nKey: keyPattern(), // 目录键漏出，如 report.labels.undefined
};
```

`keyPattern()` 在加载时从 `en.js` 所有键的第一段（`report`、`state`、`tasks`……）拼出正则：`\b(?:<第一段们>)\.[A-Za-z]+(?:\.[A-Za-z_]+)*\b`。这样网址（`my.csc.fi`）和普通英文不会被误报。

- [ ] **Step 1：写失败的测试**（`tests/web/leaks.test.mjs`）

```js
test("findLeaks names each kind of internal text", () => {
  assert.deepEqual(findLeaks("阶段 stage-round_9d38ffa4ca3049948194e0b60315c650-1").map((l) => l.kind), ["snake", "hexId"]);
  assert.deepEqual(findLeaks("ends at 1796594627").map((l) => l.kind), ["epoch"]);
  assert.deepEqual(findLeaks('detail {"seconds": 412.6}').map((l) => l.kind), ["payload"]);
  assert.deepEqual(findLeaks("请求 wb-3f2a9c1e-0b4d-4e1a-9f2c-1a2b3c4d5e6f").map((l) => l.kind), ["uuid"]);
  assert.deepEqual(findLeaks("显示 report.labels.undefined").map((l) => l.kind), ["i18nKey"]);
  assert.deepEqual(findLeaks("第 1 轮 · 已结束，共 21 天"), []);
  assert.deepEqual(findLeaks("message: data_gap seen", ["message: data_gap seen"]), []);
});

test("visibleText skips technical details but keeps aria-label", () => { /* 用 h() 搭 <div aria-label="x"><p>a</p><details class="tech-details"><summary>技术详情</summary><code>round_1</code></details></div>，断言结果是 "x a 技术详情" 以外不含 round_1：visibleText 跳过整个 details 子树，包括 summary */ });

test("exemptStrings reads strings at a fixture path", () => {
  assert.deepEqual(exemptStrings("p", { "a.json": { rows: [{ m: "x_y" }, { m: "z" }] } }, [{ page: "p", fixture: "a.json", path: "rows[*].m" }]), ["x_y", "z"]);
});

test("every Batch 1 page renders from its fixtures", async () => {
  for (const page of ["inbox", "projects", "project", "round", "stage", "environment", "safety", "alerts", "evidence", "compute"]) {
    const { element } = await renderPage(page, PARAMS[page]); // PARAMS 从 fixture 里取真实 id
    assert.ok(visibleText(element).length > 20, page);
  }
});

test("no Batch 1 page leaks internal text", async () => {
  for (const { page, params } of PAGES_CHECKED) for (const lang of ["zh", "en"]) {
    const { element } = await renderPage(page, params, { lang });
    assertNoLeaks(element, exemptStrings(page, FIXTURES));
  }
});
```

`exemptStrings` 在测试里是第三个参数注入 `EXEMPTIONS` 的形式，签名为 `exemptStrings(page, fixtures, exemptions = EXEMPTIONS)`。

- [ ] **Step 2：运行**：`node --test tests/web/leaks.test.mjs`。预期：因为模块不存在而失败。
- [ ] **Step 3：实现上面四个支持模块。** 假 DOM 只实现页面在渲染时真的用到的成员（`createElement`、`createTextNode`、`createElementNS`、`append`、`appendChild`、`removeChild`、`firstChild`、`childNodes`、`textContent`、`setAttribute`/`getAttribute`、`addEventListener`、`hidden`/`disabled`/`value` 等属性），缺什么由"每页都能渲染"这个测试逼出来。页面里的轮询、计时器在测试里不启动。
- [ ] **Step 4：运行**：`node --test tests/web/*.test.mjs`。预期：全部通过（`PAGES_CHECKED` 为空，所以最后一个测试暂时什么都不查）。
- [ ] **Step 5：提交**：`git add tests/web/support tests/web/leaks.test.mjs && git commit -m "test: render console pages on a fake DOM and scan them for internal text"`

---

### Task 2：格式函数（时长、日期时间、档位、金额、短指纹）

**Files:**
- Modify: `W/format.js`
- Modify: `W/i18n/en.js`、`W/i18n/zh.js`
- Test: `tests/web/format.test.mjs`

**Interfaces:**
- 产出（全部在 `W/format.js`）：
  - `formatDuration(t, seconds) -> string`
  - `formatDateTime(epochSeconds, timeZone, lang, nowSeconds = Date.now() / 1000) -> string`
  - `levelText(t, channel, level, range = DEFAULT_LEVEL_RANGES[channel]) -> string`
  - `DEFAULT_LEVEL_RANGES = { light: [0, 100], exhaust: [0, 100], fan: [0, 10] }`
  - `formatMoney(value, lang) -> string`
  - `shortDigest(hex) -> string`
- 已有的 `formatTime` 不动：它给表单输入框产生 `YYYY-MM-DD HH:mm`（`W/ui/forms.js:114`），不是给人看的显示。

时长规则（先把秒数四舍五入成整数 `s`）：

| 条件 | 中文 | 英文 |
| --- | --- | --- |
| 非有限数或负数 | `—` | `—` |
| `s < 120` | `{n} 秒` | `{n} s` |
| 四舍五入的分钟数 `< 120` | `{n} 分钟` | `{n} min` |
| 四舍五入的小时数 `< 48` | `{h} 小时` 或 `{h} 小时 {m} 分钟` | `{h} h` 或 `{h} h {m} min` |
| 其他 | `{d} 天` 或 `{d} 天 {h} 小时` | `{d} days` 或 `{d} days {h} h` |

小时那一档：分钟数取四舍五入后的总分钟数除以 60 的余数。天那一档：小时数取四舍五入后的总小时数除以 24 的余数。余数为 0 时省略。

新目录键：
- `duration.seconds`、`duration.minutes`、`duration.hours`、`duration.hoursMinutes`、`duration.days`、`duration.daysHours`；
- `level.percent`（`{level} %`）、`level.steps`（`{level} / {max}`）、`level.on`（开 / on）、`level.off`（关 / off）。

日期时间的格式：

| | 当年 | 不是当年 |
| --- | --- | --- |
| 中文 | `11月20日 10:00` | `2025年11月20日 10:00` |
| 英文 | `20 Nov 10:00` | `20 Nov 2025 10:00` |

- 月、日不补零；时、分为 24 小时制并补零。
- "当年"按 `timeZone` 判断。英文月份缩写用代码里固定的 12 个缩写。

- [ ] **Step 1：写失败的测试**

```js
const tz = makeT("zh"), te = makeT("en");
test("formatDuration picks the unit by size", () => {
  assert.equal(formatDuration(tz, 20), "20 秒");
  assert.equal(formatDuration(tz, 119.6), "2 分钟");
  assert.equal(formatDuration(tz, 300), "5 分钟");
  assert.equal(formatDuration(tz, 412.6), "7 分钟");
  assert.equal(formatDuration(tz, 12000), "3 小时 20 分钟");
  assert.equal(formatDuration(tz, 7200), "2 小时");
  assert.equal(formatDuration(tz, 504 * 3600), "21 天");
  assert.equal(formatDuration(te, 49.5 * 3600), "2 days 2 h");
  assert.equal(formatDuration(te, 600), "10 min");
  assert.equal(formatDuration(tz, -5), "—");
  assert.equal(formatDuration(tz, NaN), "—");
});
test("formatDateTime follows the language and shows the year only when it differs", () => {
  const at = Date.UTC(2026, 10, 20, 8, 0) / 1000; // 10:00 in Helsinki
  const now = Date.UTC(2026, 10, 21) / 1000;
  assert.equal(formatDateTime(at, "Europe/Helsinki", "zh", now), "11月20日 10:00");
  assert.equal(formatDateTime(at, "Europe/Helsinki", "en", now), "20 Nov 10:00");
  assert.equal(formatDateTime(at, "Europe/Helsinki", "zh", Date.UTC(2027, 0, 2) / 1000), "2026年11月20日 10:00");
  assert.equal(formatDateTime(Date.UTC(2026, 11, 31, 22, 30) / 1000, "Europe/Helsinki", "en", Date.UTC(2026, 11, 1) / 1000), "1 Jan 2027 00:30");
  assert.equal(formatDateTime(undefined, "UTC", "zh", now), "—");
});
test("levelText writes value over full scale", () => {
  assert.equal(levelText(tz, "fan", 3), "3 / 10");
  assert.equal(levelText(tz, "fan", 3, [0, 8]), "3 / 8");
  assert.equal(levelText(tz, "light", 50), "50 %");
  assert.equal(levelText(tz, "pump", 1), "开");
  assert.equal(levelText(te, "pump", 0), "off");
  assert.equal(levelText(tz, "fan", null), "—");
});
test("formatMoney has no float noise", () => {
  assert.equal(formatMoney(1.8300000000000001, "en"), "1.83");
  assert.equal(formatMoney(1234.5, "en"), "1,234.50");
  assert.equal(formatMoney(null, "zh"), "—");
});
test("shortDigest keeps eight characters", () => {
  assert.equal(shortDigest("8bc36a6f" + "0".repeat(56)), "8bc36a6f…");
  assert.equal(shortDigest(""), "—");
  assert.equal(shortDigest(undefined), "—");
});
```

- [ ] **Step 2：运行**：`node --test tests/web/format.test.mjs`。预期：因为函数不存在而失败。
- [ ] **Step 3：实现。** 日期时间用 `Intl.DateTimeFormat(...).formatToParts` 取数字部件再拼，不依赖 ICU 的本地化整句。金额复用 `formatNumber(value, 2, lang)`。
- [ ] **Step 4：运行**：`node --test tests/web/*.test.mjs`。预期：全部通过。
- [ ] **Step 5：提交**：`feat: format durations, local date-times, levels and money for people`

---

### Task 3：`labelOr`、各类代码的目录和目录完整性测试

**Files:**
- Modify: `W/i18n.js`（加 `labelOr`）
- Modify: `W/ui/status.js`（`label()` 改用 `labelOr`；`STATE_GROUPS` 补状态）
- Modify: `W/i18n/en.js`、`W/i18n/zh.js`
- Modify: `B4` 里所有用服务器值拼目录键的地方（清单代码图 B4 列出）：
  - `W/pages/inbox.js:145`、`W/pages/conversation.js:54,79`、`W/pages/round.js:103-104`
  - `W/pages/stage-tasks.js:49,59`、`W/pages/stage-actions.js:251`、`W/pages/evidence.js:52`
  - `W/pages/alerts.js:29`、`W/ui/layout.js:105`
- Create: `tests/web/fixtures/known-codes.json`
- Create: `tests/web/catalog.test.mjs`
- Create: `tests/workbench/test_console_known_codes.py`

**Interfaces:**
- 产出：`labelOr(t, prefix, value) -> string`。
  - 有文字时返回文字。
  - `value` 为 `null`、`undefined` 或 `""` 时返回 `"—"`。
  - 其余情况返回 `t("common.unknown")`。

| 键 | 中文 | 英文 |
| --- | --- | --- |
| `common.unknown` | `未知（技术详情）` | `Unknown (technical details)` |

- 调用方负责把原始值放进技术详情（Task 4 的 `techDetails`）。
- 产出：`known-codes.json` 的结构是 `{ "<prefix>": ["code", ...], "_sources": { "<prefix>": "从哪里找到这些代码（文件和 grep 命令）" } }`。prefix 包括：
  - `state`：全部 `StageState`、`RoundState`、`TaskState`、计算阶段，以及会话状态条目里的值。
  - `history.event`：`S/workflow/service.py`、`recovery.py` 里的 `Plan(...)` 事件名，加上 `S/ports.py:161-173` 的 12 个 `StageEventKind`。
  - `history.kind`：所有干预类型，在服务器里 grep 记录干预的调用。
  - `history.field`：上述事件和干预的 detail 键。
  - `history.reason`：`disconnect_affects` 的 `reasons` 值。
  - `alert.kind`：观察器、运行时、看门狗发出的全部告警类型。
  - `finding`：运行单检查结果的全部 `Finding.code`。
  - `chat.tool`：`ROLE_TOOLS` 里的全部工具名。
  - `safety.op`：`SafetyConfig` 触发条件允许的运算符。
  - `diff.field`：`level`、`mode`。
  - `severity`、`tasks.status`、`tasks.kind`、`entry`、`report.labels`、`report.conclusions`、`inbox.kind`。
- 文字要求：
  - `history.event.*` 是完整的句子（"到达计划时长，阶段结束" 这一类）。
  - `finding.*` 是一个短标题（"人工任务"、"缺少证据"）。
  - `chat.tool.*` 是动宾短语（"读取项目状态"）。
  - `alert.kind.*` 是名词（"数据空档"、"审计备注"）。

- [ ] **Step 1：写失败的测试**

```js
// tests/web/catalog.test.mjs
test("every console-known code has text in both catalogs", () => {
  for (const [prefix, codes] of Object.entries(KNOWN)) {
    if (prefix.startsWith("_")) continue;
    for (const code of codes) for (const table of [en, zh]) assert.ok(table[`${prefix}.${code}`], `${prefix}.${code}`);
  }
});
test("labelOr never prints a key", () => {
  const t = makeT("zh");
  assert.equal(labelOr(t, "state", "running"), "运行中");
  assert.equal(labelOr(t, "state", "brand_new_state"), "未知（技术详情）");
  assert.equal(labelOr(t, "state", null), "—");
});
test("compute phases have labels and colour groups", () => {
  assert.equal(stateGroup("failed"), "onsite");
  assert.equal(stateGroup("cancelled"), "done");
  assert.equal(stateGroup("queued"), "active");
  assert.equal(stateGroup("prepared"), "waiting");
});
test("no page builds a catalog key from a server value without labelOr", () => {
  // 静态扫描 W/pages 与 W/ui：匹配 t(`<prefix>.${...}`)，只允许 KEY_BUILDERS_ALLOWED 里列出的客户端常量前缀
  // （nav、stage.<action>、measure、metric、env.channel、env.window、round.choice）。
  // channel 和 receipt 不在名单里：它们有的值来自服务器（交接差异的通道、回执状态），所以一律走 labelOr。
});
```

```python
# tests/workbench/test_console_known_codes.py
def test_console_lists_every_enumerable_code():
    known = json.loads(Path("tests/web/fixtures/known-codes.json").read_text())
    assert {k.value for k in StageEventKind} <= set(known["history.event"])
    assert {s.value for s in StageState} | {s.value for s in RoundState} | {s.value for s in TaskState} <= set(known["state"])
    assert set(COMPUTE_PHASES) <= set(known["state"])  # S/compute/phases.py 的阶段集合
    assert {name for tools in ROLE_TOOLS.values() for name in tools} <= set(known["chat.tool"])
```

`stateGroup` 的分组规则：`failed` 归 `onsite`（要人去处理），`cancelled` 归 `done`，`queued` 归 `active`，`prepared` 归 `waiting`。

- [ ] **Step 2：运行**：`node --test tests/web/catalog.test.mjs`，再跑 `.venv/bin/python -m pytest tests/workbench/test_console_known_codes.py -q`。预期：失败。
- [ ] **Step 3：实现。**
  - 加 `labelOr`，补目录。
  - 把 B4 列出的拼键处全部改成 `labelOr`。`chat.role.*` 已经回退到 `other`，保持不变。
  - 静态扫描测试里的允许名单只列客户端常量前缀。
- [ ] **Step 4：运行**：`node --test tests/web/*.test.mjs`，再跑 `.venv/bin/python -m pytest tests/workbench -q && .venv/bin/ruff check src tests`。预期：全部通过。
- [ ] **Step 5：提交**：`feat: show every code through the catalog and test that each one has text`

---

### Task 4：技术详情组件，错误只显示人话

**Files:**
- Modify: `W/ui/section.js`（加 `techDetails`、`copyText`）
- Modify: `W/ui/forms.js`（`errorLines` 只返回人话；新增 `errorDetail`；表单状态区附技术详情）
- Modify: `W/main.js:118-176`（`problemView` 附技术详情：FRM-03）
- Modify: `W/pages.css`（`.tech-details` 样式，参照 `.sheet-json`，长值 `overflow-wrap: anywhere`）
- Modify: `W/i18n/en.js`、`W/i18n/zh.js`
- Test: `tests/web/tech-details.test.mjs`；修改 `tests/web/forms.test.mjs:18-31`

**Interfaces:**
- 产出：`techDetails(t, entries) -> HTMLElement | null`。
  - `entries` 是 `Array<[label: string, value: unknown]>`。
  - 值为 `null`、`undefined`、`""` 的项跳过；对象用 `JSON.stringify(value, null, 2)`。
  - 全部为空时返回 `null`。
  - 标记结构：`<details class="tech-details"><summary>技术详情</summary>`，每项一行，内含 `dt`、`<code>` 和 "复制" 按钮，最后一个 "复制全部" 按钮。
  - "复制全部" 复制 `label: value` 各行，用 `\n` 连接。
- 产出：`copyText(text) -> Promise<boolean>`。没有 `navigator.clipboard` 或 `writeText` 被拒时返回 `false`。按钮的文字随之改成 `tech.copied` 或 `tech.copyFailed`。
- 产出：`errorLines(error, lang, t) -> string[]`，最多两行：
  - 已知代码：`[说明, 建议]`；
  - 没有代码的 404：`[t("error.notFound")]`；
  - 代码为 `network`：`[t("error.network")]`；
  - 其他：`[t("error.title")]`。
- 产出：`errorDetail(error) -> Array<[label, value]>`，内容是 `HTTP 状态`、`代码`、`服务器原文`，原文就是原来的第三行。`showErrors`、`formFrame` 的状态区和 `problemView` 都把它交给 `techDetails`。

| 键 | 中文 | 英文 |
| --- | --- | --- |
| `tech.title` | `技术详情` | `Technical details` |
| `tech.copy` | `复制` | `Copy` |
| `tech.copyAll` | `复制全部` | `Copy all` |
| `tech.copied` | `已复制` | `Copied` |
| `tech.copyFailed` | `复制失败，请手动选择` | `Copy failed; select the text by hand` |
| `error.notFound` | `没有找到这一项，可能已被删除。` | `This item was not found; it may have been removed.` |
| `error.network` | `连不上服务器。请检查网络后再试。` | `The server could not be reached. Check the network and try again.` |

- [ ] **Step 1：写失败的测试**

```js
test("techDetails lists each value with a copy button and drops empties", () => {
  installFakeDom();
  const el = techDetails(makeT("zh"), [["轮次 id", "round_1"], ["空", null], ["事件", { a: 1 }]]);
  assert.equal(el.getAttribute("class"), "tech-details");
  assert.match(visibleTextIncludingDetails(el), /round_1/); // 展开后能看到
  assert.equal(countButtons(el), 3); // 两项各一个，加一个复制全部
  assert.equal(techDetails(makeT("zh"), [["x", ""]]), null);
});
test("copy without a clipboard says so and does not throw", async () => {
  installFakeDom({ clipboard: undefined });
  assert.equal(await copyText("abc"), false);
});
test("errorLines keeps only the human lines; the server text goes to the details", () => {
  const t = makeT("zh");
  const err = new ApiError(409, "state", "stage st_91c2 is recovery_check; it cannot pause");
  assert.equal(errorLines(err, "zh", t).length, 2);
  assert.deepEqual(errorDetail(err).map(([, v]) => v), [409, "state", "stage st_91c2 is recovery_check; it cannot pause"]);
  assert.deepEqual(errorLines(new ApiError(404, null, "HTTP 404"), "zh", t), [t("error.notFound")]);
  assert.deepEqual(errorLines(new ApiError(0, "network", "Failed to fetch"), "zh", t), [t("error.network")]);
});
```

`visibleTextIncludingDetails` 和 `countButtons` 是本任务在 `tests/web/support/leaks.mjs` 里加的两个小工具。

- [ ] **Step 2：运行**：`node --test tests/web/tech-details.test.mjs tests/web/forms.test.mjs`。预期：失败。
- [ ] **Step 3：实现。** 网络错误的代码和状态以 `W/api.js:30-57` 的 `toError` 为准。已有调用 `errorLines` 的地方（代码图 ERR-01 列出）不用改调用方式。
- [ ] **Step 4：运行**：`node --test tests/web/*.test.mjs`。预期：全部通过。
- [ ] **Step 5：提交**：`feat: fold ids, hashes and raw server text into a technical-details block`

---

### Task 5：服务器读接口加名字字段（只加不改）

**Files:**
- Create: `S/workflow/naming.py`
- Modify: `S/workbench/rounds.py:92-104`（`round_json`）
- Modify: `S/workbench/api.py:485-499`（阶段读，操作员分支）
- Modify: `S/workflow/listing.py:13-82`（`project_summaries`、`project_detail`）
- Modify: `S/workbench/reads.py:54-175`（收件箱条目）
- Modify: `S/workbench/environment.py:73-100`（`active_stage`）
- Modify: `S/workbench/analysis.py:98-126`（快照）
- Create: `tests/workbench/test_workbench_names.py`
- Modify: `tests/web/fixtures/*.json`（按下面的规则把新字段手工补进 fixture）

**Interfaces:**
- 产出：`round_names(store: WorkflowStore, round_id: str) -> dict[str, Any]`，返回 `{"project_name": str | None, "round_number": int}`。
  - `round_number` 就是 `store.round_number(round_id)`。
  - `project_name` 取法与 `project_detail` 读名字的方式相同。
- 产出：`stage_names(store: WorkflowStore, stage: StageRow) -> dict[str, Any]`，返回 `{"project_name", "round_number", "stage_index": int | None, "phase": str | None}`。
  - `stage_index` 是阶段在 `stages_of_round` 里从 1 开始的位置。
  - `phase` 是该轮协议的 `stages[stage_index - 1]`。协议不存在或阶段不够时为 `None`。
- 各读接口新增的键（键名在所有读接口里一致，控制台按这些键读）：

| 读接口 | 新增 |
| --- | --- |
| `GET /wb/rounds/{id}` | `project_name`、`round_number`；`stages[]` 每行加 `stage_index`、`phase` |
| `GET /wb/stages/{id}`（操作员） | `project_name`、`round_number`、`stage_index`、`phase` |
| `GET /wb/projects/{id}` | `rounds[]` 每行加 `round_number` |
| `GET /wb/projects` | `latest_round` 加 `round_number` |
| `GET /wb/inbox` | 阶段类和 `round_choice` 条目：`project_name`、`round_number`、`stage_index`、`phase`（不适用的为 `null`）；`task` 条目：`project_name` |
| `GET /wb/environment` | `stage` 不为空时加 `project_name`、`round_number`、`stage_index`、`phase` |
| `GET /wb/protocols/{id}/analysis` | `snapshots[]` 每行加 `created_at` |

- [ ] **Step 1：写失败的测试**（用 `tests/workbench/workbench_support.py` 现有的搭建方式）

```python
def test_round_read_names_its_round_and_stages(app):  # 协议 stages=("vegetative","flowering")，同一协议两轮
    first = client.get(f"/wb/rounds/{r1}").json()
    assert first["round_number"] == 1 and first["project_name"] == "Lettuce light"
    assert first["stages"][0] | {} == {"stage_id": s1, "state": "pending_review", "stage_index": 1, "phase": "vegetative"}
    assert client.get(f"/wb/rounds/{r2}").json()["round_number"] == 2

def test_stage_read_names_index_and_phase(app): ...  # stage_index 1, phase "vegetative", round_number, project_name
def test_phase_is_none_beyond_the_protocol_stages(app): ...  # 协议只有 1 个生长期，第 2 个阶段 phase is None
def test_project_reads_carry_round_numbers(app): ...  # detail.rounds[*].round_number；summaries.latest_round.round_number
def test_inbox_items_carry_names(app): ...  # pending_review 条目有 4 个名字键
def test_environment_stage_carries_names(app): ...
def test_analysis_snapshots_carry_created_at(app): ...
def test_existing_keys_are_unchanged(app): ...  # round_json 的原有键集合是新键集合的子集，值不变
```

- [ ] **Step 2：运行**：`.venv/bin/python -m pytest tests/workbench/test_workbench_names.py -q`。预期：因为缺键而失败。
- [ ] **Step 3：实现 `naming.py`，并让各读接口展开它的结果。** 函数不超过 50 行，文件不超过 800 行。
- [ ] **Step 4：运行**：`.venv/bin/python -m pytest tests -q && .venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests`。预期：全部通过。
- [ ] **Step 5：补 fixture。**
  - 2026-11-15 那一轮是项目里该协议的第 1 轮，所以 `round_number` 为 1、`stage_index` 为 1、`phase` 为协议 fixture 里 `stages[0]`。
  - `project_name` 取 `projects.json` 里的名字。
  - 在 `tests/web/fixtures/README.md` 记一行"Task 5 按服务器规则手工补字段"。
  - 运行 `node --test tests/web/*.test.mjs`，预期全部通过。
- [ ] **Step 6：提交**：`feat: name rounds and stages in the console reads`

---

### Task 6：`displayName`、角色名和面包屑（RND-01、STG-10、P-01 的标题部分）

**Files:**
- Create: `W/ui/names.js`
- Modify: `W/pages/conversation.js:10-16`（`roleLabel` 移到 `names.js`）
- Modify: `W/main.js:18-22,150-157`（`ID_CRUMBS` 改成不含 id 的"项目"、"轮次"、"阶段"，等页面读到数据后再换名字）
- Modify: `W/pages/round.js:130-141`、`W/pages/stage.js:178-199`、`W/pages/project.js:107-114`（面包屑、页面标题、导语都不含 id）
- Modify: `W/i18n/en.js`、`W/i18n/zh.js`
- Test: `tests/web/names.test.mjs`

**Interfaces:**
- 用到：Task 5 的键；Task 2 的 `formatDateTime`；Task 3 的 `labelOr`。
- 产出：`displayName(ctx, kind, row) -> string`。
  - kind 为 `"project" | "round" | "stage" | "snapshot" | "researchTask" | "manualTask" | "attempt"`。
  - 用 `ctx` 而不是设计里写的 `t`，因为快照和计算尝试要按时区格式化时间。这是计划层面的决定。

| kind | 有数据 | 缺数据 |
| --- | --- | --- |
| project | `row.name ?? row.project_name` | `未命名项目` / `Unnamed project` |
| round | `第 {n} 轮` / `Round {n}`（`row.round_number`） | `未命名轮次` / `Unnamed round` |
| stage | `第 {n} 阶段 · {phase}` / `Stage {n} · {phase}`；没有 phase 时为 `第 {n} 阶段` / `Stage {n}` | `未命名阶段` / `Unnamed stage` |
| snapshot | `{时间} 的数据快照（完整）` 或 `（不完整）`（`created_at`、`complete`） | `数据快照` / `Data snapshot` |
| researchTask | `row.question` 前 60 个字符，超出加 `…` | `未命名任务` / `Unnamed task` |
| manualTask | `{类型}（{时间} 到期）`：`tasks.kind.*` 加上 `due_at` | 只有类型 |
| attempt | `{时间} 提交的计算`（`created_at ?? since`） | `计算尝试` / `Compute attempt` |

- 产出：`roleLabel(t, role) -> string`，规则同原 `conversation.js:14-16`。
- 产出：`nameDetails(row) -> Array<[label, value]>`。凡是 `row` 里存在的 id 键（`project_id`、`round_id`、`stage_id`、`experiment_id`、`snapshot_id`、`attempt_id`、`task_id`、`id`）都列出来，供 `techDetails` 使用。标签为 `tech.id.<key>`。

- [ ] **Step 1：写失败的测试**

```js
const ctx = testCtx({ lang: "zh", now: Date.UTC(2026, 10, 21) / 1000 });
test("displayName uses names and numbers, never ids", () => {
  assert.equal(displayName(ctx, "round", { round_id: "round_9d38", round_number: 2 }), "第 2 轮");
  assert.equal(displayName(ctx, "round", { round_id: "round_9d38" }), "未命名轮次");
  assert.equal(displayName(ctx, "stage", { stage_index: 1, phase: "vegetative" }), "第 1 阶段 · vegetative");
  assert.equal(displayName(ctx, "stage", { stage_index: 2, phase: null }), "第 2 阶段");
  assert.equal(displayName(ctx, "stage", { stage_id: "stage-x-1" }), "未命名阶段");
  assert.equal(displayName(ctx, "project", { project_id: "project_1" }), "未命名项目");
  assert.equal(displayName(ctx, "researchTask", { question: "a".repeat(80) }), "a".repeat(60) + "…");
});
test("nameDetails lists the ids that exist", () => {
  assert.deepEqual(nameDetails({ round_id: "r", stage_id: null, x: 1 }).map(([, v]) => v), ["r"]);
});
test("round page title and crumbs carry no id", async () => {
  const { element, ctx } = await renderPage("round", { roundId: ROUND_ID });
  assert.match(visibleText(element), /第 1 轮/);
  assert.ok(ctx.crumbs.every((c) => !findLeaks(c.label).length));
});
```

`testCtx` 的 `setBreadcrumbs` 把面包屑记进 `ctx.crumbs`（本任务在 `render-page.mjs` 里加上）。

- [ ] **Step 2：运行**：`node --test tests/web/names.test.mjs`。预期：失败。
- [ ] **Step 3：实现。**
  - 轮次页面包屑：项目名，然后"第 N 轮"。
  - 阶段页面包屑：项目名，然后"第 N 轮"，然后 `displayName(stage)`。
  - 项目页导语去掉 id。
  - 各页把 `nameDetails(...)` 交给本页的技术详情。
- [ ] **Step 4：运行**：`node --test tests/web/*.test.mjs`。预期：全部通过（`conversation.test.mjs` 里依赖 `roleLabel` 的断言照旧成立）。
- [ ] **Step 5：提交**：`feat: show rounds, stages and projects by name and number`

---

### Task 7：时间显示：时区只写一次，列表里用相对时间（FRM-01、FRM-04）

**Files:**
- Modify: `W/ui/section.js:9-13`（`timeText` 改用 `formatDateTime`，不再附时区；新增 `timeCell`）
- Modify: `W/pages/inbox.js:59-63`（删掉私有的 `timeText` 副本）
- Modify: `W/ui/chart.js:17-19`（`timeLabel` 不附时区）
- Modify: `W/ui/layout.js:94-108`（侧栏加一行"时区"；在"入口"下加一句提示：FRM-04）
- Modify: `W/i18n/en.js`、`W/i18n/zh.js`
- Test: `tests/web/time-display.test.mjs`

**Interfaces:**
- 用到：Task 2 的 `formatDateTime`、`formatDuration`。
- 产出：`timeText(ctx, epoch) -> string`。签名不变，输出改为 `formatDateTime(epoch, zone, ctx.lang, ctx.now ?? Date.now()/1000)`。
- 产出：`timeCell(ctx, epoch) -> HTMLElement`。
  - 是一个 `<time>`，`datetime` 为 ISO 时间，`title` 为完整时间。
  - 当 `0 ≤ 现在 − epoch < 86400` 时显示相对时间：不到 60 秒为 `刚刚` / `just now`，否则为 `{duration}前` / `{duration} ago`。
  - 其他情况（包括未来时间）显示完整时间。
  - `ctx.now` 是测试注入的固定秒数；页面里不传，用当前时间。
- 时区为 `ctx.me.timezone`，缺失时为 `"UTC"`。

| 键 | 中文 | 英文 |
| --- | --- | --- |
| `frame.timezone` | `时区` | `Time zone` |
| `entry.onsiteHint` | `浇水等操作只能在现场（实验室网络）进行。` | `Some actions, such as irrigation, work only on site (lab network).` |
| `time.justNow` | `刚刚` | `just now` |
| `time.ago` | `{duration}前` | `{duration} ago` |

- [ ] **Step 1：写失败的测试**

```js
test("timeText shows no zone; the sidebar names it once", async () => {
  const ctx = testCtx({ lang: "zh", timezone: "Europe/Helsinki", now: NOW });
  assert.doesNotMatch(timeText(ctx, NOW - 90000), /Helsinki|UTC/);
  const side = sidebar(ctx, []);
  assert.equal((visibleText(side).match(/Europe\/Helsinki/g) || []).length, 1);
});
test("timeCell is relative within a day, absolute otherwise and for the future", () => {
  const ctx = testCtx({ lang: "zh", now: NOW });
  assert.equal(timeCell(ctx, NOW - 30).textContent, "刚刚");
  assert.equal(timeCell(ctx, NOW - 12000).textContent, "3 小时 20 分钟前");
  assert.equal(timeCell(ctx, NOW - 90000).textContent, timeText(ctx, NOW - 90000));
  assert.equal(timeCell(ctx, NOW + 300).textContent, timeText(ctx, NOW + 300));
  assert.equal(timeCell(ctx, NOW - 12000).getAttribute("title"), timeText(ctx, NOW - 12000));
});
test("a missing zone falls back to UTC and says so", () => {
  const ctx = testCtx({ lang: "en", timezone: undefined, now: NOW });
  assert.match(visibleText(sidebar(ctx, [])), /UTC/);
});
```

`testCtx` 需要支持 `timezone: undefined`，表示 `me` 里没有时区。

- [ ] **Step 2：运行**：`node --test tests/web/time-display.test.mjs`。预期：失败。
- [ ] **Step 3：实现。** 代码图 B2 列出的 `timeText` 调用方不用改。`sidebar` 若未导出，就导出它。`inbox.updated`、`stage.updated` 里的 `{seconds}` 改用 `formatDuration`（FRM-06）。
- [ ] **Step 4：运行**：`node --test tests/web/*.test.mjs`。预期：全部通过。
- [ ] **Step 5：提交**：`feat: state the time zone once and show recent list times as relative`

---

### Task 8：阶段历史（HIS-01–05，FRM-06 的历史部分）

**Files:**
- Modify: `W/pages/stage-history.js`
- Create: `W/pages/stage-diff.js`（`differenceText`，Task 10 也用）
- Modify: `W/i18n/en.js`、`W/i18n/zh.js`
- Modify: `tests/web/stage-page.test.mjs`（`timeline`、`detailText` 的断言）
- Test: `tests/web/stage-history.test.mjs`

**Interfaces:**
- 用到：`labelOr`、`formatDuration`、`levelText`、`timeText`、`techDetails`；`known-codes.json` 里的 `history.*`。
- 产出：`timeline(history, interventions) -> entry[]`，**新的在前**。实现方式是把原来稳定的升序结果整个反转，所以同一秒里原来"转换在前、干预在后"，现在变成"干预在前、转换在后"。
- 产出：`detailLines(ctx, entry) -> { lines: string[], raw: Array<[label, value]> }`，替代 `detailText`。
  - 已知键变成"标签：值"的短句，值的写法：
    - `*seconds` 用 `formatDuration`；
    - `*_at` 用 `timeText`；
    - 布尔值用 `common.yes` / `common.no`；
    - `reasons` 逐个用 `labelOr(t, "history.reason", ...)`，用 `、` 或 `, ` 连接；
    - `differences` 逐条用 `differenceText`。
  - `right_number`、`request_id`、未知键和整个原始 detail 放进 `raw`，由 `techDetails` 显示。
- 产出：`differenceText(t, item) -> string`，如 `灯光档位：应为 50 %，实际 0 %`。用 `labelOr(t, "channel", …)`、`labelOr(t, "diff.field", …)`、`levelText`。`actual` 为 `null` 时写 `—`。
- 标题：转换类用 `labelOr(t, "history.event", entry.event)`，没有事件名时用 `history.stateChange`。干预类用 `labelOr(t, "history.kind", entry.kind)`。只有 `from !== to` 时才显示两个状态药丸。
- 折叠：最新的 `HISTORY_SHOWN = 20` 条直接显示，其余放进 `<details>`，标题为 `更早的 {count} 条` / `{count} earlier entries`。

- [ ] **Step 1：写失败的测试**

```js
test("events read as sentences and same-state moves show no pills", () => {
  const ctx = testCtx({ lang: "zh" });
  const view = historyView(ctx, { history: [{ at: 10, from: "running", to: "running", event: "end_condition_met", detail: { confirmed: true, right_number: 3 } }], interventions: [] });
  assert.match(visibleText(view), /结束条件已满足/);
  assert.equal(countPills(view), 0);
  assertNoLeaks(view);
});
test("durations, times and reasons are written for people; raw values go to the details", () => {
  const { lines, raw } = detailLines(testCtx({ lang: "zh" }), { type: "transition", event: "disconnect_affects", detail: { reasons: ["due_action", "gap_too_long"], seconds: 412.6, state_unreadable: false } });
  assert.ok(lines.some((l) => l.includes("7 分钟")));
  assert.ok(!lines.join(" ").includes("due_action"));
  assert.ok(raw.length >= 1);
});
test("unexpected watering shows labelled times, not epoch seconds", () => { /* status_at 1796594400.2 → 断言行里没有 1796594400，request_id 在 raw 里 */ });
test("an unknown event says unknown and keeps the code in the details", () => { /* event "brand_new" → 标题为 "未知（技术详情）"，raw 里有 "brand_new" */ });
test("newest first; a transition and an intervention of the same second keep a fixed order", () => {
  const rows = timeline([{ at: 5, from: "a", to: "b", event: "start" }], [{ at: 5, kind: "takeover" }, { at: 9, kind: "accepted" }]);
  assert.deepEqual(rows.map((r) => r.type + r.at), ["intervention9", "intervention5", "transition5"]);
});
test("beyond twenty entries the newest stay on top and the rest fold away", () => { /* 25 条 → 列表 20 条 + details 写 "更早的 5 条"，第一条是 at 最大的 */ });
test("the history fixture renders without leaks", () => { assertNoLeaks(historyView(testCtx({ lang: "en" }), FIXTURES["history.json"])); });
```

`countPills` 是一个小工具，数 `class` 含 `pill` 的元素个数，本任务加在 `leaks.mjs` 里。

- [ ] **Step 2：运行**：`node --test tests/web/stage-history.test.mjs tests/web/stage-page.test.mjs`。预期：失败。
- [ ] **Step 3：实现。** `history.field.*` 的文字要能读成"标签：值"。
- [ ] **Step 4：运行**：`node --test tests/web/*.test.mjs`。预期：全部通过。
- [ ] **Step 5：提交**：`feat: tell a stage's history in sentences, newest first`

---

### Task 9：运行单审阅与审批（STG-01 客户端部分、STG-02 客户端部分、STG-07、08、09、13）

**Files:**
- Modify: `W/pages/stage.js:115-148,216-230`（`reviewView`、`sections` 的顺序）
- Modify: `W/pages/stage-actions.js:88-163`（`findingsList`、`approveGroup` 的指纹与冲突文字）
- Modify: `W/pages.css`（`.finding` 改为可换行的 flex）
- Modify: `W/i18n/en.js`、`W/i18n/zh.js`
- Modify: `tests/web/support/leak-exemptions.mjs`
- Test: `tests/web/run-sheet-review.test.mjs`

**Interfaces:**
- 用到：`labelOr(t, "finding", code)`、`formatDuration`、`shortDigest`、`techDetails`、`displayName`。
- 产出：`groupFindings(findings) -> Array<{ blocking: boolean, code: string, items: Finding[] }>`。阻断组在前；同一组内按 `code` 分组，组的顺序按代码第一次出现的顺序。
- 产出：`findingsList(ctx, findings)`。
  - 每组一个小标题：`{label}（{count}）`。
  - 每条显示服务器的 `message`（英文整句，第二批处理），不显示 `code`。
  - 每条的 `code` 进本组的技术详情。
- 运行单事实栏：
  - 时长用 `formatDuration`（504 小时显示为"21 天"）。
  - 版本写 `第 {n} 版` / `version {n}`。
  - 摘要一行写 `指纹 {shortDigest}`，完整摘要进技术详情。
  - 设备 `SIMULATED` 写 `模拟设备` / `Simulated device`，其他设备名照写。
  - 协议写 `{protocol_id} 第 {v} 版`。
- 审批：
  - 日志行用短指纹。
  - 冲突对话框文字为 `stage.approve.mismatch`：`你审阅的版本和已批准的不同，请重新查看下面的运行单。`，两份完整摘要只放在技术详情里。
- 顺序：
  - `pending_review`：状态 → 运行单 → 控制区（审批）→ 人工任务 → 测量 → 历史 → 读数。
  - `running` 和 `paused`：状态 → 读数 → 控制区 → 人工任务 → 测量 → 运行单 → 历史。
  - 其他状态：保持现有顺序。
  - 审批提示 `stage.approve.note` 改为 `请先核对上面的运行单，再批准。`。
- 豁免：在 `leak-exemptions.mjs` 加 `{ page: "stage", fixture: "run-sheet.json", path: "findings[*].message", batch: 2, why: "服务器整句（C4，STG-01）" }`。

- [ ] **Step 1：写失败的测试**

```js
test("blocking findings come first, grouped by code with counts", () => {
  const groups = groupFindings([{ code: "manual_task", blocking: false, message: "a" }, { code: "no_evidence", blocking: true, message: "b" }, { code: "manual_task", blocking: false, message: "c" }]);
  assert.deepEqual(groups.map((g) => [g.blocking, g.code, g.items.length]), [[true, "no_evidence", 1], [false, "manual_task", 2]]);
});
test("finding codes are shown as labels, never as code", () => { /* findingsList 的 visibleText 不含 "manual_task"，含 labelOr 的文字 */ });
test("the review shows days, a short fingerprint and no full digest", () => {
  const view = reviewView(testCtx({ lang: "zh" }), FIXTURES["stage.json"], FIXTURES["run-sheet.json"]);
  const text = visibleText(view);
  assert.match(text, /21 天|\d+ 天/);
  assert.match(text, /[0-9a-f]{8}…/);
  assertNoLeaks(view, exemptStrings("stage", FIXTURES));
});
test("pending review puts the run sheet before the controls", () => { /* sectionOrder("pending_review") 中 runSheet 的下标 < controls 的下标；sectionOrder("running") 中 readings 的下标 < controls 的下标 */ });
```

为了测试顺序，本任务从 `stage.js` 导出 `sectionOrder(state) -> string[]`，`sections()` 按它排列各区域。测试里 `reviewView` 的参数以 `stage.js` 现有签名为准，没有导出的就导出。

- [ ] **Step 2：运行**：`node --test tests/web/run-sheet-review.test.mjs`。预期：失败。
- [ ] **Step 3：实现。**
- [ ] **Step 4：运行**：`node --test tests/web/*.test.mjs`。预期：全部通过。
- [ ] **Step 5：提交**：`feat: put the run sheet before its approval and write its facts for people`

---

### Task 10：阶段状态、控制日志与回执（STG-11、12、18、19、21，FRM-06 的阶段操作部分）

**Files:**
- Modify: `W/pages/stage.js:111-131`（`statusView`）
- Modify: `W/pages/stage-actions.js:205-352`（`manualGroup`、`irrigationGroup`、`differenceLines`、`logItem`、`outcomeLines`）
- Modify: `W/i18n/en.js`、`W/i18n/zh.js`
- Test: `tests/web/stage-status.test.mjs`

**Interfaces:**
- 用到：`differenceText`（Task 8）、`levelText`、`formatDuration`、`timeText`、`techDetails`、`displayName`、`nameDetails`。
- 状态栏：
  - 项目、轮次写名字（链接不变），实验 id 不显示。
  - 写入权三个计数（`right_number`、`care_right`、`manual_right`）只在技术详情里。
  - `paused_at` 为空时不显示"暂停时间"这一行。
  - `end_pending` 为真时显示横幅 `已到结束条件，正在确认结束动作。`；为假时不显示这一行。
- 日志：
  - `receipt.request` 改为 `发送于 {time}` / `Sent {time}`；`request_id` 进该条日志的技术详情。
  - `receipt.resent` 改为 `这是你刚才那次操作的结果。` / `This is the result of the action you just sent.`。
  - `receipt.unsettledNote` 里的秒数用 `formatDuration`，不提"请求编号"。
- 档位：
  - `receipt.manual` 的档位用 `levelText`：`灯光调到 50 %`、`风扇调到 3 / 10`。
  - `receipt.confirmedLevel` 同样用 `levelText`。
  - `receipt.irrigation` 的秒数用 `formatDuration`。
- 交接差异：每条用 `differenceText`。

- [ ] **Step 1：写失败的测试**

```js
test("status hides empty rows and keeps write rights in the details", () => {
  const view = statusView(testCtx({ lang: "zh" }), { ...FIXTURES["stage.json"], paused_at: null, end_pending: false });
  const text = visibleText(view);
  assert.doesNotMatch(text, /暂停时间|写入权/);
  assertNoLeaks(view);
});
test("a level is written against its full scale", () => { /* manualGroup 的标题含 "3 / 10"（风扇）和 "50 %"（灯光） */ });
test("a log item says when it was sent and keeps the request id in the details", () => { /* logItem 的可见文字不含 "wb-"，details 里含 */ });
test("hand-back differences use labels and units", () => { /* differenceLines → "灯光档位：应为 50 %，实际 0 %" */ });
```

`statusView`、`logItem`、`manualGroup` 原来没有导出的，本任务导出它们供测试使用。

- [ ] **Step 2：运行**：`node --test tests/web/stage-status.test.mjs`。预期：失败。
- [ ] **Step 3：实现。**
- [ ] **Step 4：运行**：`node --test tests/web/*.test.mjs`。预期：全部通过。
- [ ] **Step 5：提交**：`feat: keep counters and request ids out of the stage controls`

---

### Task 11：人工任务与测量（TSK-01、02、05、06、07），阶段页整页检查

**Files:**
- Modify: `W/pages/stage-tasks.js`
- Modify: `W/pages/stage-measurements.js`
- Modify: `W/pages.css`（`.task-buttons` 不换行）
- Modify: `W/i18n/en.js`、`W/i18n/zh.js`
- Modify: `tests/web/leaks.test.mjs`（`PAGES_CHECKED` 加 `stage`，params 为待审阅和已结束两个阶段）
- Test: `tests/web/stage-tasks.test.mjs`、新建 `tests/web/measurements.test.mjs`

**Interfaces:**
- 用到：`displayName(ctx, "manualTask", row)`、`techDetails`、`formatDuration`、`timeText`。
- 任务表：
  - 去掉"任务"（`task_id`）这一列。
  - 记录成功的提示为 `已记录：{name}` / `Recorded: {name}`，`name` 是 `displayName(manualTask)`。
  - 按钮文字：`tasks.markDone` 改为 `标记完成` / `Mark done`，`tasks.markSkipped` 改为 `跳过` / `Skip`。
  - `tasks.pumpRun` 的秒数用 `formatDuration`。
- 导语 `tasks.lead` 只留一句：`列出今天和明天的人工任务，最新的在上。`。原来的计分规则移到 `<details>` 里，标题为 `tasks.rules` = `计分规则` / `How tasks are scored`。
- 测量表：
  - 默认 6 列：时间、植株、指标、值（含单位）、方法、记录人。
  - 批次、位置、布局版本、记录 id、更正关系放进每行的技术详情。
  - 更正关系的写法：`更正了 {time} 的记录` 或 `已被 {time} 的记录更正`。
- 测量表单：
  - 指标、单位、方法三个输入框带 `<datalist>`，选项来自本阶段已有测量的去重值。
  - 每行加按钮 `更正` / `Correct`，点了以后表单预填该行，隐藏字段 `corrects` 设为该行 id，并显示 `正在更正 {time} 的 {metric} 记录`。
- 产出：`measurementOptions(measurements) -> { metric: string[], unit: string[], method: string[] }`，各自去重并排序。

- [ ] **Step 1：写失败的测试**

```js
test("the task table has no task-id column and verbs on its buttons", () => { /* tasksView 的表头不含 "任务"，按钮文字为 "标记完成"、"跳过"，visibleText 不含 irrigate-daily */ });
test("measurement options are the distinct values already recorded", () => {
  assert.deepEqual(measurementOptions([{ metric: "canopy", unit: "cm2", method: "ruler" }, { metric: "canopy", unit: "cm2", method: "photo" }]), { metric: ["canopy"], unit: ["cm2"], method: ["photo", "ruler"] });
});
test("the measurement table shows six columns and folds the rest", () => { /* 表头 6 个，记录 id 不在可见文字里 */ });
```

`PAGES_CHECKED` 新增 `{ page: "stage", params: { stageId: <待审阅阶段的 id> } }` 和 `{ page: "stage", params: { stageId: <已结束阶段的 id> } }`，两个 id 都取自 fixture。

- [ ] **Step 2：运行**：`node --test tests/web/stage-tasks.test.mjs tests/web/measurements.test.mjs tests/web/leaks.test.mjs`。预期：失败。
- [ ] **Step 3：实现。** 阶段页整页检查时冒出的剩余露出，在本任务里一并改掉，或者按 Global Constraints 的豁免规则登记（必须写明批次和原因）。
- [ ] **Step 4：运行**：`node --test tests/web/*.test.mjs`。预期：全部通过。
- [ ] **Step 5：提交**：`feat: drop task ids and fold measurement bookkeeping on the stage page`

---

### Task 12：轮次页、报告和确认性分析（RND-02、03、05、08、09c、10c、11c、12、13、14、15、20）

**Files:**
- Modify: `W/pages/round.js`
- Modify: `W/pages/round-analysis.js`
- Modify: `W/i18n/en.js`、`W/i18n/zh.js`
- Modify: `tests/web/round-report.test.mjs`
- Modify: `tests/web/leaks.test.mjs`（加 `round`）
- Modify: `tests/web/support/leak-exemptions.mjs`

**Interfaces:**
- 用到：`displayName`、`nameDetails`、`techDetails`、`shortDigest`、`richText`、`inline`、`labelOr`。
- 摘要：
  - 项目链接文字用项目名，协议写 `{protocol_id} 第 {v} 版`。
  - 快照 id、报告 id 不在摘要里；在报告的技术详情里各出现一次。
- 阶段表：链接文字用 `displayName(stage)`。等待选择的阶段也用它，先按 `stage_id` 在 `round.stages` 里找到那一行。
- 报告：
  - `report.digest` 改为 `报告指纹` / `Report fingerprint`，值为 `shortDigest(sha256)`。完整摘要、快照 id、报告 id 进技术详情。
  - 标签和结论用 `labelOr`。缺标签、缺结论时都写 `未说明` / `Not stated`（结论不再悄悄写成"不确定"）。
  - 每个标签下面加一句说明 `report.labelHelp.<label>`。例如 descriptive：`只描述看到的情况，不能据此对处理下结论。`。
  - 列表项走 `inline()`。
  - "局限"只直接显示前 3 条，其余放进 `<details>`，标题为 `还有 {count} 条` / `{count} more`。
  - `next_round` 走 `richText`。
  - 可以估计时，效应保留 3 位有效数字（`toPrecision(3)`），并加一句 `report.pHelp`：`p 值越小，越不像是偶然造成的差异。`。
  - 读报告失败时只显示 `errorLines` 的第一行，其余进技术详情（RND-20）。
- 确认性分析：
  - 整块放进 `<details>`，标题为 `确认性分析（高级）` / `Confirmatory analysis (advanced)`，默认收起。
  - 状态用一个词：未开始、脚本已锁定、已运行。
  - 脚本 SHA-256、运行 id、退出码、stdout、stderr 进技术详情。
  - 快照选项用 `displayName(snapshot)`。
  - 版本不一致的文字 `analysis.otherVersion` 改为 `本轮按第 {round} 版规划；第 {latest} 版已存在。下面的分析针对第 {latest} 版，不是本轮。`。
  - `analysis.started` 的标签改为 `已开始采集数据` / `Data collection has started`。
- 豁免：
  - `report.json` 的 `report.model_limitations[*]`、`report.unresolved[*]`、`report.next_round`、`report.conclusion_text`：`batch: 3`，原因是"模型写的文字（C5）"。
  - `report.json` 的 `report.estimate.note`：`batch: 2`。

- [ ] **Step 1：写失败的测试**

```js
test("a missing label or conclusion says 'not stated'", () => { /* reportView(ctx, { label: undefined, report: {} }) 的可见文字含 "未说明"，不含 "report.labels" */ });
test("the report shows a short fingerprint and keeps ids in the details", () => { /* 可见文字含 "报告指纹"，含 /[0-9a-f]{8}…/，不含完整 64 位 */ });
test("limitations show three and fold the rest", () => { /* 5 条 → 列表 3 条，details 写 "还有 2 条" */ });
test("estimateText rounds the effect", () => {
  assert.match(estimateText(testCtx({ lang: "en" }), { estimable: true, effect: 0.231234, p_value: 0.034, blocks: 2 }), /0\.231\b/);
});
test("the analysis block is folded by default", () => { /* analysisSection 的根是没有 open 属性的 <details> */ });
```

`PAGES_CHECKED` 加 `{ page: "round", params: { roundId } }`，`roundId` 取自 fixture。

- [ ] **Step 2：运行**：`node --test tests/web/round-report.test.mjs tests/web/leaks.test.mjs`。预期：失败。
- [ ] **Step 3：实现。**
- [ ] **Step 4：运行**：`node --test tests/web/*.test.mjs`。预期：全部通过。
- [ ] **Step 5：提交**：`feat: name the round's parts and fold the report's bookkeeping`

---

### Task 13：项目列表、项目页和对话（P-01、04、05、06、07、08、10、11c、12、13）

**Files:**
- Modify: `W/pages/projects.js`
- Modify: `W/pages/project.js`、`W/pages/project-forms.js`
- Modify: `W/pages/conversation.js`
- Modify: `W/ui/section.js`（`questionCell` 从 `project.js` 移来并改名为 `foldedText`）
- Modify: `W/pages/compute.js:31,65`、`W/pages/round.js:52,61`、`W/pages/round-analysis.js:54,73`（P-08：保存成功的提示点名对象）
- Modify: `W/i18n/en.js`、`W/i18n/zh.js`
- Modify: `tests/web/conversation.test.mjs`、`tests/web/leaks.test.mjs`（加 `projects`、`project`）

**Interfaces:**
- 用到：`displayName`、`roleLabel`、`labelOr`、`formatMoney`、`techDetails`。
- 产出：`foldedText(ctx, text, chars = 240) -> HTMLElement`，行为同原 `questionCell`。
- 项目列表：去掉 ID 列；最新轮次的链接文字为 `displayName(round)`。
- 项目页：
  - 顺序：对话 → 轮次 → 研究任务 → 协议 → 预算 → 保留集。
  - 四个编辑表单（协议、预算、目标、保留集）各自放进默认收起的 `<details>`，标题为 `编辑…`。
  - 区块标题和表格标签统一成 `目标与任务` / `Goals and tasks`。
  - 任务表的角色用 `roleLabel`。
  - 保留集 id 进技术详情；`reads` 写成 `已读取 {n} 次`，表下加一句说明 `project.holdouts.readsHelp`。
- 预算：
  - 次数用 `formatNumber(n, 0, lang)`，费用用 `formatMoney`。
  - 下面加说明 `project.budget.help`：`剩余次数和剩余费用都用完后，模型不会再被调用。`。
  - "已用 / 共"需要服务器给出上限，这次不做。在清单结果里记为"部分：上限读字段留到第二批"。
- 保存成功的提示（P-08）点名对象：

| 位置 | 提示 |
| --- | --- |
| 预算 | `已设置预算：{calls} 次调用，费用上限 {cost}` |
| 目标 | `已提交目标` |
| 保留集 | `已登记保留集` |
| 余额 | `已记录计算余额` |
| 任务预算 | `已设置任务预算` |
| 冻结脚本 | `已锁定分析脚本` |
| 运行分析 | `已运行确认性分析` |
| 轮次选择 | `已选择：{choice}` |
| 中止 | `已中止本轮` |

各条都有英文对应。
- 对话：
  - 工具调用：单次调用的标签用 `labelOr(t, "chat.tool", name)`。连续的工具调用合成一个 `<details>`，标题为 `用了 {count} 个工具` / `Used {count} tools`，展开后逐条列出；原工具名进技术详情。
  - 状态条目：用 `labelOr(t, "state", entry.text)`。中文模板 `chat.taskEnded` 改为 `{role} 的任务结束：{state}`。原始 `detail.reason` 进技术详情，不再拼在句子里（`reason_code` 留到第二批）。
  - 轮次下拉框：默认选"无轮次"；选项文字为 `{displayName(round)} · {labelOr(state)}`。
  - 发送后本地先追加一条待处理条目 `已发送，编排 Agent 稍后接手。` / `Sent. The orchestrator will pick it up shortly.`。下次刷新拿到服务器条目后移除。
  - `chat.hint` 缩成一句。
- 产出：`groupToolEntries(entries) -> Array<entry | { kind: "toolGroup", items: entry[] }>`。只合并相邻的 `tool` 条目。

- [ ] **Step 1：写失败的测试**

```js
test("adjacent tool calls fold into one group", () => {
  const out = groupToolEntries([{ kind: "reply" }, { kind: "tool", text: "a" }, { kind: "tool", text: "b" }, { kind: "reply" }, { kind: "tool", text: "c" }]);
  assert.deepEqual(out.map((e) => e.kind === "toolGroup" ? `g${e.items.length}` : e.kind), ["reply", "g2", "reply", "g1"]);
});
test("the round picker starts at no round and names rounds", () => { /* roundPicker 的 select.value 为 ""，选项文字匹配 /第 \d+ 轮/ */ });
test("a status entry keeps the raw reason in the details", () => { /* statusText 结果不含 "APIStatusError" */ });
test("budget numbers carry no float noise", () => { /* budgetView 可见文字含 "1.83"，不含 "1.8300000000000001" */ });
```

`PAGES_CHECKED` 加 `projects` 和 `{ page: "project", params: { projectId } }`。

- [ ] **Step 2：运行**：`node --test tests/web/conversation.test.mjs tests/web/leaks.test.mjs`。预期：失败。
- [ ] **Step 3：实现。** 项目页导语、`project.roundStarted`、`project-forms.js:40` 的协议选项都不再出现 id；协议选项写成 `{protocol_id} 第 {v} 版`。
- [ ] **Step 4：运行**：`node --test tests/web/*.test.mjs`。预期：全部通过。
- [ ] **Step 5：提交**：`feat: name rounds, roles and tools on the project page and in the conversation`

---

### Task 14：收件箱（INB-01–07）

**Files:**
- Modify: `W/pages/inbox.js`
- Modify: `W/router.js`（解析 `#/alerts?focus=<event_id>`，交给页面的是 `params.focus`）
- Modify: `W/pages/alerts.js`（每行加 `id="alert-<event_id>"`；带 `focus` 时滚动到该行并加高亮类）
- Modify: `W/i18n/en.js`、`W/i18n/zh.js`
- Modify: `tests/web/shell.test.mjs`（`inboxTarget` 的断言）、`tests/web/router.test.mjs`、`tests/web/leaks.test.mjs`（加 `inbox`）
- Modify: `tests/web/support/leak-exemptions.mjs`

**Interfaces:**
- 用到：`displayName`、`nameDetails`、`roleLabel`、`labelOr(t, "alert.kind", …)`、`foldedText`、`formatDuration`、`techDetails`。
- 标题（按类型）：

| 类型 | 标题 |
| --- | --- |
| 阶段待审阅 | `审阅运行单：{project} {round} {stage}` |
| 其他阶段状态 | `{stage}：{state}`，元信息写项目和轮次 |
| `round_choice` | `{project} {round}：等待你选择下一步` |
| `compute_stuck` | `计算尝试卡住：{phase}` |
| `task` | `foldedText(question)` |
| 告警 | `foldedText(message)` |

  每个条目的 id 都进该条目的技术详情（`nameDetails`）。
- 告警的类型用 `labelOr(t, "alert.kind", d.alert_kind)`。
- 右侧时间写 `已等待 {duration}` / `Waiting {duration}`，`title` 为完整时间。
- 负责角色用 `roleLabel`。
- "还有 N 项未显示"做成链接：告警链到告警页；阶段、轮次、任务链到项目列表；计算链到计算页。文字为 `还有 {count} 项，去 {page} 查看`。
- `inboxTarget`：告警条目链到 `#/alerts?focus=<item.id>`。
- 豁免：
  - `inbox.json` 的 `items[*].detail.message`（告警正文）：`batch: 2`。
  - `items[*].detail.question`：`batch: 3`。
  - `items[*].detail.reason`：`batch: 2`。

- [ ] **Step 1：写失败的测试**

```js
test("a stage waiting for review is titled by names", () => { /* describe(ctx, item) 的标题含 "第 1 轮" 和项目名，不含 stage_id */ });
test("an alert kind shows its label; an unknown kind says unknown", () => { /* "data_gap" → 目录文字；"brand_new" → "未知（技术详情）" */ });
test("the waiting time is a duration with the exact time in the title", () => { /* testCtx({ now }) 下，since = now - 12000 → "已等待 3 小时 20 分钟" */ });
test("the 'more' line links to the full list", () => { /* group.hidden=12, kind "alert" → <a href="#/alerts"> */ });
test("alert items deep-link to their row", () => { assert.equal(inboxTarget({ kind: "alert", id: "ev1" }), "#/alerts?focus=ev1"); });
test("the router passes focus to the alerts page", () => { /* parse("#/alerts?focus=ev1") → { page: "alerts", params: { focus: "ev1" } } */ });
```

`PAGES_CHECKED` 加 `inbox`。

- [ ] **Step 2：运行**：`node --test tests/web/shell.test.mjs tests/web/router.test.mjs tests/web/leaks.test.mjs`。预期：失败。
- [ ] **Step 3：实现。** 用到 `describe`/`DESCRIBERS` 的地方，本任务导出它们供测试使用。
- [ ] **Step 4：运行**：`node --test tests/web/*.test.mjs`。预期：全部通过。
- [ ] **Step 5：提交**：`feat: title inbox items by what they are about and link to the full lists`

---

### Task 15：实时环境与曲线（ENV-01、02、03）

**Files:**
- Modify: `W/pages/environment.js`（删掉私有的 `levelText`，改用 `format.js` 的；`planLine` 和水泵的写法；状态行用 `displayName`）
- Modify: `W/ui/chart.js`、`W/chart-math.js`
- Modify: `W/pages.css`（刻度文字样式）
- Modify: `W/i18n/en.js`、`W/i18n/zh.js`
- Test: `tests/web/environment.test.mjs`、`tests/web/chart-math.test.mjs`、新建 `tests/web/chart.test.mjs`；`tests/web/leaks.test.mjs` 加 `environment`

**Interfaces:**
- 用到：`levelText(t, key, level, env.level_ranges[key])`、`displayName`、`formatDateTime`、`formatNumber`。
- 档位与运行单：
  - 风扇显示 `档位 1 / 10`。
  - 水泵在运行单没有安排时，`planLine` 写 `运行单没有安排水泵` / `The run sheet does not schedule the pump`。
  - 状态行写 `正在运行：{displayName(stage)}`。
- 产出：`MIN_SPAN = { temp: 5, humi: 20, vpd: 0.5, co2: 300, ppfd: 200, tempSoil: 5 }`（与读数同单位），放在 `W/chart-math.js`。
  - 产出：`paddedRange(min, max, minSpan) -> [lo, hi]`：跨度小于 `minSpan` 时以中点为中心扩到 `minSpan`。
  - 档位类曲线用 `DEFAULT_LEVEL_RANGES`。
- 曲线：
  - 左侧三个刻度：最小、中间、最大，按 `paddedRange` 计算，用 `formatNumber`，精度沿用各指标现有的精度。
  - 下方两个时间刻度：起、止，用 `formatDateTime`。
  - 下方说明合成一行 `共 {count} 个读数`；降采样、空心点、空档的说明放进 `<details>`，标题为 `图例` / `Legend`。
  - 另加一个 `<details>`，标题为 `数据表` / `Data table`，内含"时间、数值"表格，键盘和触屏也能读到每个点。
- 目标带：环境页没有运行单的目标范围，这次不做。在清单结果里记为"部分：目标带需要运行单读字段"。

- [ ] **Step 1：写失败的测试**

```js
test("paddedRange widens a narrow range around its middle", () => {
  assert.deepEqual(paddedRange(18.3, 22.9, 5), [18.1, 23.1]);
  assert.deepEqual(paddedRange(10, 30, 5), [10, 30]);
});
test("the fan shows its full scale and the pump its plan", () => { /* channelTile 风扇可见文字含 "1 / 10"；pump expected=null → "运行单没有安排水泵" */ });
test("the chart has tick labels, one status line and a data table", () => { /* readingsChart(...) 可见文字含三个刻度值、"共 N 个读数"；有一个 class 含 data-table 的表 */ });
```

`PAGES_CHECKED` 加 `environment`。

- [ ] **Step 2：运行**：`node --test tests/web/environment.test.mjs tests/web/chart-math.test.mjs tests/web/chart.test.mjs tests/web/leaks.test.mjs`。预期：失败。
- [ ] **Step 3：实现。** `paddedRange` 的结果四舍五入到 0.1。
- [ ] **Step 4：运行**：`node --test tests/web/*.test.mjs`。预期：全部通过。
- [ ] **Step 5：提交**：`feat: give the readings chart a scale, a legend and a data table`

---

### Task 16：安全限值（SAF-01、02、03、05，FRM-06 的安全部分）

**Files:**
- Modify: `W/pages/safety.js`
- Modify: `W/pages/safety-diff.js`
- Modify: `W/i18n/en.js`、`W/i18n/zh.js`
- Modify: `tests/web/config-pages.test.mjs`
- Modify: `tests/web/leaks.test.mjs`（加 `safety`）

**Interfaces:**
- 用到：`labelOr(t, "metric", …)`、`labelOr(t, "safety.op", …)`、`labelOr(t, "channel", …)`、`levelText`、`formatDuration`、`techDetails`。
- 产出：`ruleSentence(t, rule) -> string`。模板 `safety.ruleLine` 为：`{sensor}{op} {value} {unit} 持续 {duration} → {channel}调到 {level}；读数超过 {validity} 没更新则不判定`（英文对应写法）。规则 id 进技术详情。
- 冻结阈值：
  - 每个传感器一行 `{sensor}：{duration} 不变即视为冻结`。分钟换算成秒后交给 `formatDuration`。
  - 最长空档写 `读数之间最长空档：{duration}`。
- 产出：`diffLines(changes, t, { before, after }) -> string[]`（新签名）：
  - `rules.<i>.<field>` 写成 `规则 {rule.id}：{fieldLabel} {before} → {after}`。`rule.id` 从 `before` 或 `after` 的 `rules[i]` 取，值带单位，时长用 `formatDuration`。
  - `frozen.minutes.<sensor>` 写成 `{sensor} 冻结判定：{before} → {after}`。
  - `frozen.max_gap_seconds` 写成 `最长空档：{before} → {after}`。
  - 其他路径保持现有写法：`{path}：{before} → {after}`。这是审批关口，宁可完整也不漏项。
  - 字符串值不带 JSON 引号；缺值写 `（无）`。
- 批准后的提示：`safety.approved` 改为 `已批准，新限值已生效。` / `Approved; the new limits are in force.`，不再提保护权号。

- [ ] **Step 1：写失败的测试**

```js
test("a rule reads as one sentence", () => {
  const s = ruleSentence(makeT("zh"), { id: "heat-cut", sensor: "temp", unit: "°C", trigger: { op: "gt", value: 30 }, duration_seconds: 300, validity_seconds: 600, action: { channel: "fan", level: 0 } });
  assert.match(s, /高于 30 °C 持续 5 分钟/);
  assert.match(s, /10 分钟/);
  assert.doesNotMatch(s, /heat-cut|gt|300|600/);
});
test("the approval dialog describes changes by rule and unit", () => {
  const before = { rules: [{ id: "heat-cut", unit: "°C", trigger: { value: 30 } }] }, after = { rules: [{ id: "heat-cut", unit: "°C", trigger: { value: 35 } }] };
  assert.deepEqual(diffLines([{ path: "rules.0.trigger.value", before: 30, after: 35 }], makeT("zh"), { before, after }), ["规则 heat-cut：触发值 30 °C → 35 °C"]);
});
test("an unknown path is still listed", () => { /* path "extra.flag" → 行里含 "extra.flag" */ });
```

`PAGES_CHECKED` 加 `safety`。规则 id（如 `heat-cut`）是操作员自己起的名字，可以出现在审批对话框里。对话框不在页面渲染范围内，所以不涉及豁免。

- [ ] **Step 2：运行**：`node --test tests/web/config-pages.test.mjs tests/web/leaks.test.mjs`。预期：失败。
- [ ] **Step 3：实现。** 把 `approver` 调 `diffLines` 的地方改成传入 `{ before, after }`。
- [ ] **Step 4：运行**：`node --test tests/web/*.test.mjs`。预期：全部通过。
- [ ] **Step 5：提交**：`feat: write safety rules and their changes as sentences`

---

### Task 17：告警、证据与计算（ALT-11c、ALT-12、EVI-01、CMP-01 的页面部分、CMP-02、03、05）

**Files:**
- Modify: `W/pages/alerts.js`
- Modify: `W/pages/evidence.js`
- Modify: `W/pages/compute.js`、`W/pages/compute-attempts.js`
- Modify: `W/i18n/en.js`、`W/i18n/zh.js`
- Modify: `tests/web/alerts-page.test.mjs`、`tests/web/research-pages.test.mjs`、`tests/web/leaks.test.mjs`（加 `alerts`、`evidence`、`compute`）
- Modify: `tests/web/support/leak-exemptions.mjs`

**Interfaces:**
- 用到：`labelOr`、`timeCell`、`displayName`、`techDetails`、`formatNumber`。
- 告警表：
  - 新增"类型"列：`labelOr(t, "alert.kind", row.kind)`。
  - 正文按换行拆开：第一行是摘要，其余各行是证据列表（ALT-11 的控制台部分）。
  - "次数"列标题改为 `出现次数` / `Occurrences`。
  - 首次和最近两列都用 `timeCell`。
  - 链到受影响的对象（ALT-12 的最后一项）需要服务器把 `key` 拆成参数，这次不做，在清单结果里记为"部分：第二批"。
- 产出：`readLine(ctx, alert)` 只返回一个短语：
  - `未读` / `Unread`；
  - `{who} {time} 已读` / `Read by {who}, {time}`；
  - `已读，但情况变糟：请再读一次` / `Read, but it got worse; please read again`。
- 证据卡片：
  - 标题为结论 `card.claim`。
  - 卡片 id 进技术详情。
  - 录入人：等于 `ctx.me.operator` 时写 `你` / `you`；是代理常量（`S/agents/handlers_evidence.py:73` 的 `SOURCE`）时写对应角色名；其余照写操作员名。
  - 来源类、值、校准状态分开显示，不再用 " · " 串在一起。
- 计算：
  - 任务预算表每行加按钮 `修改预算` / `Change budget`，点了预填下面表单的任务字段。任务字段标签改为 `任务（新任务才需要输入）`。
  - 用量写 `已用 {used} 小时，预留 {reserved} 小时，共 {budget} 小时`，存储同理（GB）。
  - 尝试表：`attempt_id`、`remote_job_id`、`task_id` 进每行的技术详情；模板名照写。
  - `compute.balance.none` 改为：`还没有录入余额。在 CSC 的 MyCSC 网站（my.csc.fi）打开项目页，可以看到计算余额，把它填在下面。`。
- 豁免：`alerts.json` 的 `alerts[*].message`，`batch: 2`。

- [ ] **Step 1：写失败的测试**

```js
test("an alert row has a kind label and splits evidence lines", () => { /* message "Summary\n- a\n- b" → 摘要一段 + 两项列表；kind "audit_finding" → "审计备注" */ });
test("the read column says one thing", () => { /* 三种情况各一个断言，文字里没有 "asked about again" */ });
test("an evidence card is titled by its claim and keeps its id in the details", () => { /* cardView 的第一个标题元素文字 === card.claim */ });
test("compute usage reads as hours", () => { /* "已用 1.00 小时，预留 2.00 小时，共 10.00 小时" */ });
```

`PAGES_CHECKED` 加 `alerts`、`evidence`、`compute`。

- [ ] **Step 2：运行**：`node --test tests/web/alerts-page.test.mjs tests/web/research-pages.test.mjs tests/web/leaks.test.mjs`。预期：失败。
- [ ] **Step 3：实现。**
- [ ] **Step 4：运行**：`node --test tests/web/*.test.mjs`。预期：全部通过。
- [ ] **Step 5：提交**：`feat: label alert kinds, title evidence by its claim and read compute usage in hours`

---

### Task 18：登录文字、覆盖检查和清单结果（FRM-05，第一批收尾）

**Files:**
- Modify: `W/i18n/en.js`、`W/i18n/zh.js`（FRM-05）
- Modify: `W/pages/login.js:10-15`
- Modify: `tests/web/leaks.test.mjs`（加 `login`；加覆盖检查）
- Modify: `docs/superpowers/specs/2026-11-16-console-usability-inventory.md`（新增第 6 节"第一批结果"）

**Interfaces:**
- 用到：前面所有任务。
- FRM-05：
  - 中文"口令"在登录、重新认证对话框、拒绝目录（`reauth_required`、`reauth_failed`、`locked`）里统一改成 `密码`。
  - 英文 `Secret` 改成 `Password`。
  - 锁定提示写明时长：`登录失败次数过多，已锁定 15 分钟。` / `Too many failed sign-ins; locked for 15 minutes.`。
- 覆盖检查：
  - `PAGES_CHECKED` 覆盖 `W/main.js:17` 的 `PAGES` 里每一个页面，加上 `login`。
  - `EXEMPTIONS` 的每一条都有 `batch`（`2`、`3` 或 `"keep"`）和非空的 `why`。
  - `batch: "keep"` 只允许用于操作员自己起的名字（协议里的指标名、批次名、生长期名）。
- 清单第 6 节：一张表列出本批 74 行。每行写状态和证据：
  - 状态：`已改`、`部分（剩余部分在第 N 批，说明）`、`关闭：无法复现`；
  - 证据：测试名，或 Task 19 的截图文件名。
  - 末尾列出 `EXEMPTIONS` 的全部条目，作为第二、三批的待办。

- [ ] **Step 1：写失败的测试**

```js
test("every console page is checked for leaks", () => {
  const checked = new Set(PAGES_CHECKED.map((p) => p.page));
  for (const page of [...PAGES, "login"]) assert.ok(checked.has(page), page);
});
test("every exemption names its batch and reason", () => {
  for (const e of EXEMPTIONS) { assert.ok([2, 3, "keep"].includes(e.batch), e.path); assert.ok(e.why.trim(), e.path); }
});
```

`PAGES` 从 `W/main.js` 导出；没有导出的话，本任务把它导出。

- [ ] **Step 2：运行**：`node --test tests/web/leaks.test.mjs`。预期：失败（`login` 未加）。
- [ ] **Step 3：实现。** 写清单第 6 节时，部分完成的行逐条写明剩下什么、属于哪一批。
- [ ] **Step 4：运行**：`node --test tests/web/*.test.mjs && .venv/bin/python -m pytest tests -q && .venv/bin/ruff check src tests`。预期：全部通过。
- [ ] **Step 5：提交**：`feat: check every console page for leaks and record the first batch's results`

---

### Task 19：改造后截图与对照（控制台负责人自己做，不派子代理）

- [ ] 从 `<scratchpad>/console-data/` 复制一份新的数据目录，在分支末端启动 `scripts/dev_workbench.py --data-dir <copy>`（不带 `--roles`）。
- [ ] 按"准备"一节的同一组页面、语言和宽度截"改造后"截图，存到 `<scratchpad>/console-shots/after/`。
- [ ] 375 px 宽时检查：页面没有横向滚动，技术详情里的 64 位哈希能换行（Review Focus 的补充项）。
- [ ] 拼成前后对照图，用 SendUserFile 发给用户。把对照图文件名补进清单第 6 节的"证据"列，然后提交：`docs: link the before/after screenshots of the first batch`。
- [ ] 关掉服务器，删掉数据副本。
