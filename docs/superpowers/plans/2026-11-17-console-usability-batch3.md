# 控制台可用性改造第三批（表单、确认和模型写作）：实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 第三批收尾控制台可用性改造，分三块。
- **C8 表单：** 要手写 JSON 的地方改成分字段的表单，包括安全上限、研究协议、保留集登记、冻结分析脚本和修改后的运行单，整份 JSON 放进"高级"；删除目标的 JSON 编辑器。
- **C9 确认：** 有后果的操作先确认，确认框写明后果；选择框默认"请选择…"；输入框限范围；未审批时"启动阶段"不可点。
- **C5 模型写作：** 加一段共用的模型写作规则；界面语言随目标传给模型；模型看到的时间是本地时间，不是 epoch 秒。

**架构：**
- **表单零件：** 放在 `W/ui/forms.js`（已有 `simpleForm`）和新文件 `W/ui/field-forms.js`：
  - 字段可以带最小值、最大值、最大长度、提示和单位，并在客户端检查范围；
  - 新增勾选框字段；
  - "每行一项"的列表字段；
  - 可增删行的分组；
  - "高级（JSON）"折叠，里面是原来的 `jsonEditor`。
- **确认被取消时不出声：** 新增 `Cancelled` 标记，`simpleForm` 收到它时什么都不显示。测试用的假 DOM 补上 `<dialog>`，并给测试一个"回答对话框"的帮手。
- **服务器只加三个读字段：**
  - `GET /wb/capabilities`：各通道档位范围、传感器和单位、`max_pump_seconds`；
  - 运行单审阅加 `approval`：当前运行单有没有有效批准；
  - 项目页的协议列表加 `primary_endpoint` 和 `method`：做下拉建议用。
- **模型：**
  - `ResearchTask` 加 `language`，目标带上它，子任务继承，监察任务用项目最近一次目标的语言，没有时用中文；
  - `task_message` 的记录里写明语言；
  - `_COMMON_LIMITS` 加写作规则；
  - 给模型的时间改成本地时间的字符串。

**技术栈：**
- 控制台：原生 ES 模块，无构建、无依赖；测试用 `node --test tests/web/*.test.mjs`，每个文件都要过 `node --check`。
- 服务器：Python 3.12 加 FastAPI，用 `pytest`、`ruff`。
- 在 worktree 里跑 Python 要加 `PYTHONPATH=src`，用共用 venv `/Users/chenghao/Downloads/spiderfarmer-growbridge/.venv/bin/`。
- **`pytest` 一律用裸命令（和 CI 一样），不用 `python -m pytest`。** 测试之间按模块名导入（`from test_x import`），不写 `from tests.…`。

**设计：** `docs/superpowers/specs/2026-11-16-console-usability-design.md`，看"第三批"一节和"实现前已定的事项"第 6、7、8 条（用户已批准："设计通过"）。
- **冲突的裁定：** "第三批"一节说安全上限第一次进入时给一份已审定的模板，第 7 条说绝不发明安全数值。以第 7 条为准，它更晚、更具体，也更安全：
  - 从最近一次已批准的上限预填；
  - 从未批准过时给空的必填项，旁边写设备能力允许的范围。

**清单：** `docs/superpowers/specs/2026-11-16-console-usability-inventory.md`，第 3 节的编号是正式编号；第 6–8 节是前两批的结果。
**调研笔记（发出点和行号的细节）：** `docs/superpowers/research/2026-11-17-console-usability-batch3-{forms,confirmations,prompts}.md`。行号对应 2b 结束时的代码；本计划和笔记不一致时，以本计划为准。

路径简写：
- `W/` = `src/growbridge/web/workbench/`
- `S/` = `src/growbridge/`
- `T/` = `tests/web/`
- `F/` = `tests/web/fixtures/`

## 本批覆盖的清单行

- **C8：** P-02、P-03、SAF-04、STG-15、STG-16、RND-06
- **C9：** EVI-02、RND-04、RND-07、STG-14、STG-17、TSK-03（STG-16 的范围限制也属于 C9）
- **C5：** P-09、RND-17、RND-18、RND-19
- **补完：** ALT-11、RND-09、RND-10。它们的显示第一批已做，剩下模型写的措辞，由写作规则负责。
- **共 19 行。** 做完后清单里分给本次改造的行全部关闭。

## Global Constraints

- **G1 名字：** 用户看到的是名字或序号，不是 id。id 只出现在技术详情里，可复制。
- **G2 代码经目录：** 任何代码都通过对照表变成文字；对照表里没有的，显示"未知（技术详情）"，绝不直接显示代码。
- **G3 技术详情：** 全站一个折叠组件，默认收起，展开后每项可复制。
- **G4 数字和时间：** 时长按大小用天、小时、分钟、秒；档位写成"值 / 满档"；日期时间按界面语言格式化，时区只在页头写一次。
- **G5 消息格式：** 每条消息两句："发生了什么"加"下一步做什么"，对读的人说。
- **G6 有后果的操作：** 先确认，确认框里一句话说明后果；选择框默认"请选择…"；输入框限制范围。
- **绝不发明安全数值（第 7 条）：**
  - 安全表单只从最近一次已批准的上限预填；从未批准过时给空的必填项，旁边写设备能力允许的范围；
  - 审批对话框（差异列表加"期间被改过"的检查）保留，表单交上去的对象和 JSON 编辑器交的完全一样；
  - 协议表单不替用户生成随机分配：分配行从空开始，用户自己填，或者在"高级"里贴 JSON。
- **表单不能比服务器更松，也不能更严：** 客户端检查的范围必须和服务器模型一致（`LEVEL_RANGES`、`FrozenCheck` 的上下限、`max_length`、`Irrigation.seconds`），服务器仍是最后的裁判。客户端不要加服务器没有的限制，例如规则的有效期和持续时间，服务器只要求是数字。
- **API 只加不改：**
  - 新的读字段都有默认值，旧字段一个不删、不改名；
  - `GoalIn.language` 可以不填；
  - `ResearchTask.language` 默认 `None`，旧任务照常能读。
- **"高级（JSON）"保留：** 每个表单旁边都有一个折叠的 JSON 编辑器，交的是同一个请求体，草稿键另用一个（`<原键>:json`）。冻结分析脚本除外，它本来就是纯文字。
- **语言：**
  - 控制台语言码只有 `"en"` 和 `"zh"`；
  - 默认用 `S/research/notes.py` 的 `TEXT_LANGUAGE`（`"zh"`）；
  - 判断两次提交是不是"同一个目标"时不比较语言：同一个请求 id 换一种语言重发，仍得到原来的任务。
- **模型写作规则不能出现控制类工具的名字：** `tests/agents/test_agents_roles.py` 已经检查 `CONTROL_TOOLS`。
- **拒绝的粗码、状态码和英文 message 不变（第二批的约束仍然有效）。**
- **测试和代码规范：**
  - 照常 TDD、`pytest`、`ruff check`、`ruff format`。文件不超过 800 行，函数少于 50 行。
  - 测试不用浏览器、服务器和网络。
  - 控制台源码不得出现 `innerHTML`、`outerHTML`、`insertAdjacentHTML`、`document.write`。
- **i18n：**
  - 新的表单文字放在新文件 `W/i18n/forms.{en,zh}.js`，用法同 `denials.*`，并展开进 `en.js` 和 `zh.js`。`en.js`、`zh.js` 现在各 646 行，不再往里加大段内容。
  - 中英文键集合由 `T/i18n.test.mjs` 检查一致。
- **读文件：** 先 grep，再每次读 30–60 行。
- **提交：** 信息用约定式前缀（`feat:`、`fix:`、`test:`、`docs:`），不加任何署名行，不跳过 pre-commit 钩子。

## Review Focus

1. **确认框被取消：** 表单不能显示"完成"，也不能显示错误；按钮恢复可点；草稿不丢。测试在 Task 1（`Cancelled`）和用到它的各任务。
2. **从未批准过安全上限：** 表单全是空的必填项，并写明每项的范围；交上去之前审批对话框照常出现。不能出现任何预填的安全数值。测试在 Task 4。
3. **改了运行单的一部分：** 表单只覆盖常用字段，没出现在表单里的部分（反馈规则、照料规则、通道归属、各种 id、版本、时区）必须原样交回去，一个字节都不能变。测试在 Task 7。
4. **语言随任务流转：**
   - 目标带"en"，委派出的任务、跟进任务和模型收到的记录都是"en"；
   - 旧任务没有语言时用项目最近一次目标的语言，再没有就用"zh"；
   - 监察任务同样适用。
   - 测试在 Task 10。
5. **能力读取失败：** 读 `/capabilities` 失败时，表单照样能填能交；没有范围提示，由服务器的 422 放到字段旁边。不显示猜出来的范围。测试在 Task 3 和 Task 4。

---

### Task 1：测试的对话框支持，以及确认被取消时不出声

**Files:**
- Modify: `T/support/fake-dom.mjs`（加 `<dialog>`：`showModal`、`close`、`open`、`returnValue`、`close` 事件）
- Create: `T/support/dialogs.mjs`
- Modify: `W/ui/forms.js`（`Cancelled`；`formFrame`/`handleFailure` 收到它时清空状态行）
- Test: `T/dialogs.test.mjs`（新）

**Interfaces:**
- Produces:
  - `T/support/dialogs.mjs` 导出 `answerNextDialog(answer: boolean | string | null)`：把下一个打开的对话框按这个答案关掉。`true` 是确认，`false` 或 `null` 是取消；字符串留给 Task 9 的理由输入框。
  - `openDialogs(): Element[]`，测试用来读对话框里的文字。
  - `W/ui/forms.js` 导出 `class Cancelled extends Error`。表单的 `onSubmit` 在确认被取消时 `throw new Cancelled()`：状态行清空隐藏，不显示"完成"，不调用 `keepDraft`，按钮恢复。
  - `W/ui/forms.js` 导出 `confirmOrCancel(ctx, prompt): Promise<void>`：调用 `confirmAction(ctx.t, prompt)`，确认时返回，取消时抛 `Cancelled`。

- [ ] **Step 1：写失败的测试**（`T/dialogs.test.mjs`）
  - "a confirm dialog can be answered yes or no in tests"：`answerNextDialog(true)` 后 `confirmAction` 解析为 `true`；`answerNextDialog(false)` 后解析为 `false`；两次都能读到对话框的标题和每一行。
  - "a cancelled confirm inside a form shows nothing and keeps the button usable"：表单的 `onSubmit` 里调 `confirmOrCancel`，答 `false`：状态行隐藏且为空，没出现"完成"，提交按钮不再是 disabled。
  - "a confirmed form still says done"：答 `true`：状态行显示 `form.done`。
- [ ] **Step 2：运行，确认失败**：`node --test tests/web/dialogs.test.mjs`。预期是 `showModal is not a function`，或者导入不到 `Cancelled`。
- [ ] **Step 3：实现。** fake-dom 的 `dialog` 元素：
  - `showModal()` 把 `open` 设为 `true`；如果有排队的答案，就在微任务里按答案关闭（设 `returnValue`、触发 `close`）；
  - 没有排队的答案时保持打开，测试可以再调 `answerNextDialog`；
  - `W/ui/dialog.js` 现在怎么判断确认和取消，这里就怎么模拟，先读它的 `openDialog`。
- [ ] **Step 4：运行全部 web 测试**：`node --test tests/web/*.test.mjs`，全部 PASS。
- [ ] **Step 5：提交**：`test: let page tests answer confirm dialogs, and let a cancelled confirm leave a form silent`

---

### Task 2：表单零件（范围、提示、单位、勾选框、每行一项、可增删的行、高级 JSON）

**Files:**
- Modify: `W/ui/forms.js`（`control()`、`fieldRow()`、`convert()`；字段规格新增键）
- Create: `W/ui/field-forms.js`（`linesField`、`rowGroup`、`advancedJson`）
- Create: `W/i18n/forms.en.js`、`W/i18n/forms.zh.js`（先只放本任务的通用文字），并在 `W/i18n/en.js`、`zh.js` 里展开
- Test: `T/field-forms.test.mjs`（新）、`T/forms.test.mjs`（加几条）

**Interfaces:**
- Produces:
  - **字段规格新增键：**
    - `min`、`max`：数字，写进 `<input>` 的属性，并在客户端检查；
    - `maxlength`：属性加检查；
    - `hint`：已翻译好的一句话，显示在字段下，用 `aria-describedby` 关联；
    - `unit`：已翻译好的单位，显示在输入框后；
    - `type: "checkbox"`：值是布尔，必填的勾选框没勾时报 `form.required`。
  - **客户端检查不过时**，错误写在字段旁：`form.tooSmall {min}`、`form.tooBig {max}`、`form.tooLong {max}`，新键，中英文都写。
  - `linesField({name, label, hint, maxItems, maxItemLength, required})`：一个 textarea，每行一项；去掉空行和首尾空格后给出 `string[]`；超过条数或某行太长时，在字段旁报错。
  - `rowGroup({ctx, name, label, fields, rows, addLabel, removeLabel, minRows, maxRows})`：
    - 每行是一组字段（规格同上）；有"添加一行"，每行有"删除这行"；
    - 给出 `{element, values(): object[], setRows(rows)}`；
    - 行内的 422 错误按 `loc` 里的下标和字段名放回对应的行。
  - `advancedJson({ctx, label, value, onSubmit, draftKey})`：一个关着的 `<details class="edit-fold">`，标题 `forms.advanced`（"高级（JSON）"/"Advanced (JSON)"），里面是现有的 `jsonEditor`。
  - 表单的值和最终请求体之间，由调用方的 `onSubmit(values)` 负责组装；`simpleForm` 本身不变。

- [ ] **Step 1：写失败的测试**（`T/field-forms.test.mjs`）
  - "a number field refuses a value outside its range beside the field, before anything is sent"：`min: 0, max: 10` 填 11，`onSubmit` 没被调用，字段旁有 `form.tooBig` 的文字（含"10"）。
  - "a field shows its hint and unit"：提示文字在字段下，单位在输入框后，`aria-describedby` 指向提示。
  - "a checkbox gives true or false, and a required one must be ticked"。
  - "a lines field gives the non-empty trimmed lines and refuses too many or too long"。
  - "a row group adds and removes rows and gives one object per row"。
  - "a server error at protocol.treatments.1.name lands beside the second row's name field"。
  - "the advanced fold is closed and holds a JSON editor with the same submit"。
- [ ] **Step 2：运行，确认失败。**
- [ ] **Step 3：实现。** `forms.js` 现在 410 行，改完不超过 480 行；新零件都放 `field-forms.js`。
- [ ] **Step 4：运行全部 web 测试，全部 PASS。**
- [ ] **Step 5：提交**：`feat: give console forms ranges, hints, units, check boxes, line lists, row groups and an advanced JSON fold`

---

### Task 3：服务器的三个读字段（能力、批准、协议摘要）

**Files:**
- Modify:
  - `S/workbench/reads.py` 或 `S/workbench/environment.py`：放 `GET /capabilities`，挑和 `/environment` 相同依赖的那一个；
  - `S/workbench/rounds.py`：`review_json` 加 `approval`；
  - `S/workflow/listing.py`：项目的协议行加 `primary_endpoint`、`method`。
- Modify: `F/project.json`、`F/run-sheet-pending.json`、`F/run-sheet.json`（手工加上新字段，并在 `F/README.md` 写明，写法同前两批）
- Create: `F/capabilities.json`；在 `T/support/render-page.mjs` 的 ROUTES 加 `/capabilities`
- Create: `W/capabilities.js`
- Test: `tests/workbench/` 下对应的测试文件、`T/capabilities.test.mjs`

**Interfaces:**
- Produces:
  - `GET /wb/capabilities` 返回 `{level_ranges: {light:[0,100], exhaust:[0,100], fan:[0,10], pump:[0,1]}, sensors: {temp:"C", ...}, max_pump_seconds: float}`。
    - 值取自服务器已有的 `capabilities()`、`LEVEL_RANGES` 和 `settings.max_pump_seconds`，不另写一份。
    - 权限和其他读接口相同（`anyone`）。
  - `review_json(...)` 新增 `approval: {approved_at: float, run_sheet_version: int} | null`：
    - 由 `workflow.store.valid_approval(stage_id)` 给出，并且要求批准的摘要等于当前运行单的 `digest`；
    - 没有有效批准，或批准的是别的版本时为 `null`。
  - 项目读接口的 `protocols[]` 每项新增 `primary_endpoint: str | null`、`method: str | null`，取自已保存的协议本体，读不到时为 `null`。
  - `W/capabilities.js` 导出 `loadCapabilities(ctx): Promise<{level_ranges, sensors, max_pump_seconds} | null>`。每个页面加载只读一次；失败时返回 `null`，不抛异常，也不用默认值补。

- [ ] **Step 1：写失败的测试**
  - 服务器：
    - `test_capabilities_answers_level_ranges_sensors_and_the_pump_cap`：值等于 `LEVEL_RANGES`、`SENSORS`、`settings.max_pump_seconds`；
    - `test_a_review_says_whether_the_current_run_sheet_is_approved`：批准前 `null`；批准后有 `approved_at`；提交新版本运行单后又是 `null`；
    - `test_project_protocol_rows_carry_endpoint_and_method`。
  - 控制台：
    - "capabilities are read once per page and a failed read gives null"：同一页面两次调用只发一次请求；接口失败时得到 `null`。
- [ ] **Step 2：运行，确认失败。**
- [ ] **Step 3：实现。**
- [ ] **Step 4：全部检查。**
  - `PYTHONPATH=src …/pytest -q`（裸命令）
  - `node --test tests/web/*.test.mjs`
  - `ruff check src tests scripts`、`ruff format --check src tests scripts`
- [ ] **Step 5：提交**：`feat: read device capabilities, a stage's approval and protocol summaries for the console forms`

---

### Task 4：安全上限表单（SAF-04）

**Files:**
- Create: `W/pages/safety-form.js`
- Modify: `W/pages/safety.js`（编辑区改用表单，原 `jsonEditor` 进 `advancedJson`；`approver` 不变）、`W/pages/safety-skeleton.js`（不再给编辑器用，见下）
- Modify: `W/i18n/forms.{en,zh}.js`
- Create: `F/safety-none.json`（`{"safety": null}`），并在 `F/README.md` 加一行
- Test: `T/safety-form.test.mjs`（新）、`T/config-pages.test.mjs`（骨架相关的测试改写）

**Interfaces:**
- Consumes:
  - Task 2：`rowGroup`、字段的 `min`/`max`/`hint`/`unit`、`advancedJson`；
  - Task 3：`loadCapabilities`；
  - Task 1：`answerNextDialog`。
- Produces: `safetyForm(ctx, {current, capabilities, onSubmit})`。
  - **组装出的 `edited` 对象：**
    - 形状和原 JSON 编辑器交的一样：`{version, rules[], frozen:{minutes:{...}, max_gap_seconds}}`；
    - 不包含 `approved_by` 和 `approved_at`；
    - `version` 不让用户填，取 `(current?.version ?? 0) + 1`，只读显示。
  - **规则行：**
    - id 是文字，可以留空，留空时用 `<sensor>-<channel>-<序号>`；
    - 传感器从 `capabilities.sensors` 的键里选，标签用 `metric.*`；
    - `unit` 由传感器决定，不让用户填；
    - 比较符号从 `> >= < <=` 里选，标签用 `safety.op.*`；
    - 阈值是数字，带单位；
    - 持续秒数和有效期秒数都是大于等于 0 的数字，没有上限，因为服务器没有；
    - 动作通道只能选 light、exhaust、fan，档位的范围跟着通道的 `level_ranges` 走。
  - **冻结检查：**
    - 每个传感器一行"分钟"，可以留空，留空就是不检查这个传感器，范围大于 0、至多 1440；
    - "最长空档秒数"的范围大于 0、至多 3600。
  - **预填：**
    - 有 `current` 时，用它的规则和冻结设置；
    - 没有时，规则零行，冻结各项留空，`max_gap_seconds` 必填但留空，每项旁边写范围。
  - **交出去**，走现有的 `approver`，差异对话框和"期间被改过"的检查原样保留。
  - **能力读取失败时**，传感器下拉退回 `current` 里出现过的传感器，没有就只能用"高级（JSON）"，不显示猜出来的范围。

- [ ] **Step 1：写失败的测试**（`T/safety-form.test.mjs`）
  - "with an approved set the form is prefilled from it and nothing else"
  - "with nothing approved every rule and frozen field starts empty and shows its allowed range; no safety number appears"：用 `F/safety-none.json`；可见文字里没有 35、120、600 这类默认数值，但有范围提示。
  - "the form builds the same config the JSON editor would send, and the approval dialog still lists the changes"：填一条规则，`answerNextDialog(true)`；`POST /safety/approve` 的请求体等于手写的期望对象，`version` 为 2。
  - "a level outside the channel's range is refused beside the field"：fan 填 11。
  - "the unit follows the sensor and is not typed"
  - "when capabilities cannot be read the form still submits and shows no invented range"
  - 改写 `config-pages.test.mjs` 里三个骨架测试：`safetySkeleton` 若只剩差异基线一个用途，测试改成断言那个基线是 `{version:null, rules:[], frozen:{minutes:{}, max_gap_seconds:null}}`，或者删掉这个函数，由实现者择一，并在提交说明里写明。
- [ ] **Step 2：运行，确认失败。**
- [ ] **Step 3：实现。**
- [ ] **Step 4：运行全部 web 测试，全部 PASS。**
- [ ] **Step 5：提交**：`feat: edit safety limits in a form that never invents a value`

---

### Task 5：研究协议表单、保留集表单，删除目标编辑器（P-02、P-03）

**Files:**
- Create: `W/pages/protocol-form.js`
- Modify:
  - `W/pages/project-forms.js`：协议编辑器换成表单，原 JSON 进 `advancedJson`；保留集改成三个 `linesField`；删除 `goalEditor`；
  - `W/pages/project.js`：去掉 `goalEditor` 的导入和使用，但保留"目标与任务"区和 `tasksTable`；
  - `W/i18n/{en,zh}.js`：删掉 `project.goals.json`、`project.goals.submit`、`project.goals.saved`；
  - `W/i18n/forms.{en,zh}.js`
- Test: `T/protocol-form.test.mjs`（新）、`T/project-page.test.mjs`（折叠个数、保存提示、目标相关的测试按下面改）

**Interfaces:**
- Consumes:
  - Task 2 的零件；
  - Task 3：协议行的 `primary_endpoint`、`method`，做 datalist 建议。
- Produces: `protocolForm(ctx, {project, onSubmit})`，交出 `{protocol: ResearchProtocol}`，字段和服务器的 `ResearchProtocol` 一一对应。
  - **id 和版本：**
    - id 默认沿用 `protocolExample` 的编号规则；
    - `project_id` 取当前项目；
    - `version` 对新的 id 是 1；对已存在的 id 是该 id 最大版本加 1，由项目的 `protocols[]` 算出；
    - 这三项都不让用户填，只读显示。
  - **问题和假设：** "问题"必填（客户端检查），"假设"可以不填。
  - **基本信息：** 作物、批次、实验单位（默认 `tent`）、随机种子（整数）、阶段（每行一个）、轮数、区组数（正整数）。
  - **处理行：** id、名字、说明、因子。因子每行一项，写成 `键=值`，值能转成数字的就转。
  - **对照处理：** 从当前的处理行里选，处理改了它跟着刷新。
  - **分配行：** 轮、区组、单位、处理（从处理行里选），从空开始，不替用户生成。
  - **分析：**
    - 主要终点：datalist 建议来自协议行的 `primary_endpoint` 和 `metric.*` 的键，可以自由填；
    - 目标效应：数字；
    - 方法：datalist 建议 `paired_block`、`two_group` 和协议行的 `method`；
    - 排除规则：每行一条；
    - 最大缺失比例默认 0.2，最大偏离比例默认 0.1，都在 0 到 1 之间。
  - **保留集：** 三个 `linesField`（保留批次、开发批次、结果字段），各 1 到 50 项，每项不超过 100 个字。提示里一句话说明"保留"和"开发"的区别。
  - **目标编辑器删除后**，提目标只走项目对话，这件事写进提交说明。`constraints` 从此只能经对话框以外的接口提交；控制台不再提供它，计划接受这一点。

- [ ] **Step 1：写失败的测试**
  - "the protocol form builds a protocol the server accepts, with version 1 for a new id and the next version for a saved one"
  - "the question is required, the hypothesis is not"
  - "the control treatment is chosen from the treatment rows and follows renames"
  - "allocations start empty; nothing is randomised for the user"
  - "endpoint and method suggest what saved protocols used"
  - "the holdout form takes one batch per line and explains hold-out and development"
  - `project-page.test.mjs`：
    - "the three editors are closed folds titled Edit…"（原来是四个）
    - 保存提示的测试去掉目标
    - 键清单去掉 `project.goals.saved`
    - 新增 "the project page has no goal JSON editor; the goals section still lists tasks"
- [ ] **Step 2：运行，确认失败。**
- [ ] **Step 3：实现。** 删除前先 grep `goalEditor` 和三个键，确认只有上述引用。
- [ ] **Step 4：运行全部 web 测试，全部 PASS。**
- [ ] **Step 5：提交**：`feat: write research protocols and holdouts in forms and drop the goal JSON editor`

---

### Task 6：冻结分析脚本和运行确认性分析（RND-06、RND-07）

**Files:** `W/pages/round-analysis.js`、`W/i18n/forms.{en,zh}.js`、`T/round-report.test.mjs`、`T/project-page.test.mjs`

**Interfaces:**
- Consumes：Task 1（`confirmOrCancel`、`answerNextDialog`）、Task 2（`maxlength`、`hint`）。
- **冻结：**
  - 改成一个等宽 textarea 字段 `script`，必填，`maxlength` 20000；
  - 提示写"冻结后不能修改，只能用新版本协议重来"；
  - `project_id` 由页面补上；
  - 提交前 `confirmOrCancel`：标题"冻结这份分析脚本？"，一行后果"冻结后这个协议版本的分析就固定了，不能再改"。
- **运行：**
  - 快照下拉第一项是 `form.choose` 的占位，必填；
  - 提交前 `confirmOrCancel`：一行写"每个快照只能做一次确认性分析，做完不能重做"，并写出快照的显示名，不写 id。

- [ ] **Step 1：写失败的测试**
  - "freezing asks first and says it cannot be undone; cancelling sends nothing"
  - "the run form starts on 'choose' and asks before the one run a snapshot allows"
  - 原来直接提交这两个表单的测试改用 `answerNextDialog(true)`。
- [ ] **Step 2–4：** 运行确认失败，实现，运行全部 web 测试。
- [ ] **Step 5：提交**：`feat: ask before freezing an analysis script or running the one confirmatory analysis`

---

### Task 7：修改运行单的表单（STG-15）

**Files:**
- Create: `W/pages/run-sheet-form.js`
- Modify: `W/pages/stage-actions.js` 的 `draftGroup`（现在 474 行，表单逻辑全放新文件）、`W/i18n/forms.{en,zh}.js`
- Test: `T/run-sheet-form.test.mjs`（新）、`T/run-sheet-review.test.mjs`

**Interfaces:**
- Consumes：Task 2 的零件；Task 3 的 `loadCapabilities`（档位范围）。
- Produces: `runSheetForm(ctx, {review, roundId, capabilities, onSubmit})`。
  - **请求体：** `{round_id, run_sheet: {...review.run_sheet, ...改动}}`。表单没有覆盖的键原样交回。
  - **表单覆盖的字段：**
    - `duration_seconds` 和 `max_wait_seconds`：用天、小时、分钟输入，内部换算成秒；
    - `on_expiry`：从两个选项里选，标签写成人话；
    - `sampling.interval_seconds` 和 `sampling.max_gap_seconds`；
    - 每个通道的 `retained_level`（范围跟通道走）和 `max_tolerance_seconds`；
    - `timed_actions` 的行：id、通道、时间（HH:MM）、档位；
    - `manual_tasks` 的行：id、种类、时间、可补做、秒数。秒数只有浇水任务填，范围大于 0、至多 60；
    - `end_actions` 的行：通道、档位。
  - **不在表单里，原样保留：** `feedback_rules`、`care_rules`、通道的 `ownership` 和 `onsite_handling`，以及 id、project/experiment/stage/protocol、protocol_version、device、version、timezone。
  - **检查结果**照旧用 `findingsList` 显示在旁边。
  - **422 的错误位置：** 标量字段的错误放回对应字段；行里的错误按下标放回对应的行；其余写在状态行，用第二批的位置写法。

- [ ] **Step 1：写失败的测试**
  - "an unchanged form sends the run sheet back byte for byte"：用 `F/run-sheet-pending.json`，请求体 `JSON.stringify` 后和原来完全相同。
  - "changing one timed action's level changes only that value"
  - "keys the form does not show (feedback rules, care rules, ownership, ids, timezone) are sent back unchanged"
  - "a level outside the channel's range is refused beside its row"
  - "durations are entered in days, hours and minutes and sent in seconds"
  - "an irrigation task's seconds must be above 0 and at most 60; other kinds have no seconds"
- [ ] **Step 2–4：** 运行确认失败，实现，运行全部 web 测试。
- [ ] **Step 5：提交**：`feat: change a run sheet's common settings in a form and keep everything else as it was`

---

### Task 8：阶段页的操作（STG-14、STG-16、STG-17）

**Files:** `W/pages/stage-actions.js`、`W/pages/stage.js`（`actionKey` 要包含批准状态，否则轮询不会重画）、`W/i18n/forms.{en,zh}.js` 或 `W/i18n/{en,zh}.js`（少量键）、`T/stage-status.test.mjs`、`T/stage-page.test.mjs`

**Interfaces:**
- Consumes：Task 1、Task 2；Task 3 的 `review.approval` 和 `loadCapabilities`。
- **STG-14 启动阶段：**
  - `review.approval` 为 `null` 时，"启动阶段"按钮 `disabled`，旁边写原因"运行单还没有批准，先在上面批准运行单"，用 `aria-describedby` 关联；
  - 有批准时可以点，点后先确认：标题"启动这个阶段？"，一行后果"设备会立即按已批准的运行单运行"，复用 `PLAIN.start` 的 `ask: true` 和 `plainActionLines`；
  - 服务器仍是最后的裁判。
- **STG-16 手动设档位：**
  - 档位字段的 `min`/`max` 跟着所选通道的 `level_ranges` 变，切换通道时更新属性和提示；
  - 通道下拉去掉 pump，另加一个"关闭水泵"按钮，发 level 0，先确认；
  - 能力读取失败时没有 min/max，由服务器的 422 放在字段旁。
- **STG-17 浇水表单：**
  - 秒数大于 0，最大值取 `capabilities.max_pump_seconds`（读不到时用 60）；
  - 提交前确认，写法同任务行的 `irrigationPrompt`：标题带格式化后的时长，一行"水泵运行这么久后会自动关闭"，一行"只能在现场入口操作，现场要有人"。

- [ ] **Step 1：写失败的测试**
  - "start is disabled with the reason while the run sheet is not approved"
  - "start asks first once the run sheet is approved"
  - "the level field's range follows the chosen channel"
  - "the pump is switched off by its own button, after a confirmation"
  - "irrigation seconds are capped at the configured pump limit and asked first, like a task row"
  - 原有直接提交手动表单和浇水表单的测试改用 `answerNextDialog(true)`。
- [ ] **Step 2–4：** 运行确认失败，实现，运行全部 web 测试。
- [ ] **Step 5：提交**：`feat: keep start shut until the run sheet is approved, bound levels per channel and ask before watering`

---

### Task 9：轮次选择、证据核验、跳过任务（RND-04、EVI-02、TSK-03）

**Files:**
- `W/pages/round.js`、`W/pages/evidence.js`、`W/pages/stage-tasks.js`
- `W/ui/dialog.js`：加 `askReason`
- `W/i18n/forms.{en,zh}.js`
- Tests：`T/round-report.test.mjs`、`T/research-pages.test.mjs`、`T/stage-tasks.test.mjs`、`T/project-page.test.mjs`

**Interfaces:**
- Consumes：Task 1（`confirmOrCancel`、`answerNextDialog`，答案可以是字符串）、Task 2（`checkbox`）。
- Produces：`askReason(t, {title, lines, label, maxlength, confirmLabel}): Promise<string | null>`。
  - 一个可以留空的文字框；
  - 确认时返回去掉首尾空格的文字，可以是空串；取消时返回 `null`；
  - 写法参照 `askSecret`。
- **RND-04 轮次选择：**
  - 下拉第一项是 `form.choose`，必填；
  - 四个选项提交前都确认，每个选项一句后果，例如"重做：再跑一次这个阶段，已有的数据保留"；
  - 中止仍用原来的写法；
  - 顺手把 zh 的 `form.choose` 改成"请选择…"，补上省略号。
- **EVI-02 证据核验：**
  - "我确认它已用本地测量校准"改成勾选框，默认不勾；
  - 提交前确认，后果写"核验后这张卡片不能再改"。
- **TSK-03 跳过任务：**
  - 点"跳过"先弹 `askReason`，后果写"之后再记一次，以最后一次为准"，理由不超过 200 个字，作为 `note` 发出；
  - 任务行的记录信息里，有理由时显示理由；
  - 已完成的行不再显示"跳过"。

- [ ] **Step 1：写失败的测试**
  - "the round choice starts on 'choose' and every choice is asked with its consequence"
  - "verifying evidence is a check box that starts unticked, and asks because it cannot change later"
  - "skipping asks for an optional reason and sends it as the note; cancelling sends nothing"
  - "a done row offers no skip"
  - "the task row shows the reason given"
  - 原有直接提交这些表单的测试改用 `answerNextDialog`。
- [ ] **Step 2–4：** 运行确认失败，实现，运行全部 web 测试。
- [ ] **Step 5：提交**：`feat: ask with consequences before a round choice, an evidence verification or a skipped task`

---

### Task 10：界面语言随目标传给模型（P-09，第 6 条）

**Files:**
- `S/archive/models.py`：`ResearchTask.language`
- `S/workbench/rounds.py`：`GoalIn.language`、`goal_task`
- `S/agents/handlers_orchestrator.py`：`delegate`、`create_task`
- `S/agents/dispatch.py`：`follow_up`、`task_message`
- `S/runtime_agents.py`：`schedule_audits`
- 新的小函数 `task_language`：放在 `S/agents/context.py` 或 `S/workflow/tasks.py`，选更自然的那个
- `W/pages/conversation.js`：发目标时带上 `language: ctx.lang`
- Tests：`tests/workbench/test_workbench_rounds.py`、`tests/agents/test_agents_tools.py`、`tests/agents/test_agents_audit_schedule.py`、`tests/agents/` 下 `task_message` 的测试、`T/conversation.test.mjs`

**Interfaces:**
- Produces:
  - `ResearchTask.language: Literal["en", "zh"] | None = None`。不需要数据库迁移，任务按 JSON 存在 `task_board.data` 里。
  - `GoalIn.language: Literal["en", "zh"] | None = None`。`goal_task` 写入 `body.language or TEXT_LANGUAGE`。
  - `same_goal` 和 `_SAME_TASK_FIELDS` 都不比较 language。
  - `delegate`、`create_task`、`follow_up` 建出的任务继承所属任务的 `language`。
  - `task_language(task, board) -> str`：顺序是任务自己的 `language`，项目最近一次目标任务的 `language`（`owner_role` 为目标角色，`trigger_event_id` 以 `goal:` 开头），最后是 `TEXT_LANGUAGE`。
  - `task_message` 的记录里加键 `"language"`，值是 `task_language` 的结果。
  - `schedule_audits` 建监察任务时写入 `language = task_language(None, board)`，用该项目最近一次目标的语言。

- [ ] **Step 1：写失败的测试**
  - `test_a_goal_stores_the_console_language_and_defaults_to_chinese`
  - `test_a_resent_goal_in_another_language_returns_the_first_task`
  - `test_an_unknown_language_is_refused`（422）
  - `test_delegated_created_and_follow_up_tasks_inherit_the_language`
  - `test_the_model_record_names_the_language`：`json.loads` 解析 `task_message` 的输出
  - `test_an_audit_uses_the_projects_latest_goal_language_or_chinese`
  - `test_an_old_task_without_language_takes_the_latest_goal_language`
  - web：
    - "the conversation sends the console language with a goal"
- [ ] **Step 2–4：** 运行确认失败，实现，全部检查（pytest、web、ruff）。
- [ ] **Step 5：提交**：`feat: carry the console language from a goal to every task the models work on`

---

### Task 11：模型写作规则（RND-17、RND-19；ALT-11、RND-09、RND-10 的措辞部分）

**Files:**
- `S/agents/roles.py`：`_COMMON_LIMITS`
- `S/agents/handlers_report.py`：`PublishInput` 的字段说明
- `S/agents/handlers_auditor.py`：`FindingInput` 的字段说明
- `tests/agents/test_agents_roles.py`

**Interfaces:**
- **`_COMMON_LIMITS` 新增一段"为操作员写作"的规则**，四个角色共用。下面是英文原文，实现者照写，可以调整断行，但不改内容：

```
Writing for the operator (every text a person reads: replies, report limitations, unresolved points,
the next round, finding summaries and evidence, and the goals you delegate):
- Write in the language named by "language" in your task record.
- Never write ids, field names, tool names, enum values, API paths or epoch seconds. Say what a thing
  is by its name or number: "stage 2 of round 1", "the light", "the protocol 'Lettuce light'".
- Dates and times are local times as the record gives them; durations in minutes, hours or days.
- One sentence per problem, saying what the operator should do about it.
- When a tool refuses or fails, tell the operator what to do in the console, in your own words; do not
  quote the error.
- Keep a reply under 120 words and each list item under 30 words unless the operator asks for more.
```

- **字段说明：** `PublishInput` 的 `limitations`、`unresolved`、`next_round` 和 `FindingInput` 的 `summary`、`evidence`，各加一句 `Field(description=...)`，大意是"一条一件事，给操作员看，遵守写作规则"。
- **RND-19：**
  - 由上面"tool refuses or fails"一条负责；
  - `handlers_report.py` 里那条拒绝的英文 message 保持不变，第二批的约束。

- [ ] **Step 1：写失败的测试**（`test_agents_roles.py`）
  - `test_every_role_carries_the_writing_rules`：参数化四个角色，断言含有 `"language"`、`"epoch seconds"`、`"what the operator should do"`、`"in your own words"`。
  - 原有的"不含控制类工具名"的测试照样要过。
  - `test_publish_and_finding_fields_describe_operator_text`：读 pydantic 的 `model_json_schema()`，相应字段有 description。
- [ ] **Step 2–4：** 运行确认失败，实现，全部检查。
- [ ] **Step 5：提交**：`feat: give every model role the rules for writing to the operator`

---

### Task 12：给模型的时间改成本地时间（RND-18）

**Files:**
- `S/agents/handlers_common.py`：`Deps.timezone`；新函数 `local_time`
- `S/runtime_agents.py`：建 `Deps` 的地方，以及监察任务的问题
- `S/agents/handlers_auditor.py`：`get_stage_records`
- `S/agents/handlers_orchestrator.py`：`get_run_status`
- Tests：`tests/agents/test_agents_audit_schedule.py`、`tests/agents/` 下相应的工具测试

**Interfaces:**
- Produces:
  - `Deps.timezone: str = "UTC"`，由运行时用 `settings.report_timezone` 填入。
  - `local_time(epoch: float | None, timezone: str) -> str | None`：返回 `"YYYY-MM-DD HH:MM"`，`None` 进 `None` 出。
- **工具结果：**
  - 每个 `*_at` 和 `window` 的 epoch 旁边加一个 `*_local` 字符串，例如 `started_at_local`、`window_local: [起, 止]`；
  - epoch 本身保留，工具内部可能要用它计算；
  - 写作规则让模型只引用本地时间。
- **监察任务的问题：**
  - 不再写 epoch，改成 `Data window <起> to <止> (<时区>)`，两端都是本地时间；
  - 阶段 id 可以保留，现有测试依赖它，模型的写作规则不让它把 id 写给人看。

- [ ] **Step 1：写失败的测试**
  - `test_an_audit_question_has_no_epoch_seconds_and_says_the_window_in_local_time`：断言问题文字里没有 10 位数字，并且有当地时间。
  - `test_stage_records_and_run_status_carry_local_times_beside_epochs`
  - `test_local_time_formats_in_the_reporting_time_zone_and_passes_none_through`
- [ ] **Step 2–4：** 运行确认失败，实现，全部检查。
- [ ] **Step 5：提交**：`feat: give the models local times instead of epoch seconds`

---

### Task 13：收尾：防露出测试、API 参考、清单结果

**Files:**
- `T/support/leak-exemptions.mjs`、`T/leaks.test.mjs`：新表单页面都要过防露出测试；"高级（JSON）"折叠里的内容按技术详情处理，豁免要写明理由
- `docs/wiki/en/API-Reference.md`、`docs/wiki/zh-CN/API-Reference.md`：新的读字段（`/capabilities`、`approval`、协议行两字段）和 `GoalIn.language`
- `docs/superpowers/specs/2026-11-16-console-usability-inventory.md`：第 9 节"第三批结果"
- 研究笔记：`docs/superpowers/research/2026-11-17-console-usability-batch3-*.md`（控制器在开始执行前已提交）

- [ ] **Step 1：防露出测试。** 每个新表单页（安全、项目、阶段草稿、轮次分析）在中英文下都过 `no page leaks internal text`。
- [ ] **Step 2：API 参考。** 中英文都写，内容相同。
- [ ] **Step 3：清单第 9 节。**
  - 格式同第 7、8 节：19 行，每行写状态、钉住它的测试名和截图；
  - 截图一栏先写"—（Task 14 补）"。
- [ ] **Step 4：全部检查。** 和 CI 一样：
  - 每个控制台文件 `node --check`；
  - `node --test tests/web/*.test.mjs`；
  - `ruff check src tests scripts`、`ruff format --check src tests scripts`；
  - 裸 `pytest -q`。
- [ ] **Step 5：提交**：`docs: record batch 3 in the API reference and the inventory`

---

### Task 14：改造前后截图（控制台负责人自己做，不派子代理）

和 2b 一样：
- 用开发工作台和 `console-data-run4` 的副本，改造前是第二批 2b 的头，改造后是本分支；
- 不调用模型，密钥只经 `GROWBRIDGE_DEV_SECRET` 传，不打印；
- 1440 和 375 宽，中英文。

要截的场景：
1. 安全页：有批准时的表单；没有批准时的空表单，用新数据目录，或者在测试数据里渲染；
2. 项目页：协议表单、保留集表单；
3. 阶段页：未批准时置灰的"启动阶段"加原因；运行单表单；
4. 轮次页：选择下拉的"请选择…"，以及确认对话框。

截图列写进清单第 9 节。模型写作规则的效果没法在不调用模型的情况下截图，第 9 节写明"由提示词测试覆盖"。
