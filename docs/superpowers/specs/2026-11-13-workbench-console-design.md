# 工作台控制台：设计

**日期：** 2026-11-13 · **状态：** 已批准（2026-11-13） · **分支：** `feat/workbench-console`（实现时新建）

## 1. 意图

DiAGRI 的工作台后端已经有 42 条 `/wb` 接口：审批运行单、启停阶段、人工接管、浇水、录入测量、处理告警、确认性分析、证据卡、留出集、计算预算等。但现在没有任何页面，操作员只能用 curl 调用。系统里设计好的人工把关（审批、近期重新认证、现场入口限制）因此很难真正用起来。

这次要做的是一个**完整的工作台控制台**：操作员坐在电脑前，用它管理整个研究，覆盖全部 42 条接口。（用户的原话：坐下来管理整个研究，就是覆盖全部接口的完整控制台。）

## 2. 目标、非目标、反目标

**目标**

- 每条现有 `/wb` 接口都有对应的界面入口，见第 6 节的对照表。
- 首页是"待我处理"：一眼看到在等人的事。
- 阶段页直接显示这个阶段时间窗内的环境曲线和当前读数（用户选定）。
- 敏感操作在需要时弹出重新认证，成功后自动重试一次原请求。
- 所有拒绝都翻译成人话，并说明下一步该做什么。
- 中英双语，可切换。

**非目标**

- 不新增任何写操作。所有写入都走现有接口，新增的只有只读接口（第 7 节）。
- 不改现有设备控制台（`/`）的行为和认证，只抽出共用的设计变量（第 9 节）。
- 不专门为手机优化。768 px 宽（平板）要能正常使用，不出现横向滚动。
- 不做深色主题：现有界面只有浅色（`color-scheme: light`）。
- 不做报告阅读、Agent 对话、决策日志浏览器。这些没有现成接口，留待以后。
- 不做操作员账号管理：建号仍用 `growbridge operator add`。
- 不改登录和认证代码。所以登录前不显示当前入口（登录后在侧栏显示）；账户被锁定时只提示"稍后再试"，不显示具体剩余时间，因为服务器不提供这个数，而锁定是按滑动窗口计算的。
- 不做实时推送（WebSocket）。可见页面定时刷新，页面隐藏时暂停。

**反目标**（技术上能用，但出现了就算失败）

- 页面显示服务器没有确认过的状态。控制类操作不做乐观更新：等服务器返回后，重新读取受影响的对象再显示。
- 拒绝被吞掉，或者写操作被悄悄重试。唯一的例外是重新认证成功后，对原请求重试一次。
- 密码留在浏览器里：不写 `localStorage`，提交后清空输入框。会话令牌只存在 HttpOnly Cookie 里，脚本读不到。
- 页面从其他来源加载任何东西，包括字体、脚本、样式和图片。
- 把降采样后的曲线当成数据本身展示。图上必须标明"为显示已降采样"，并标出质量有问题或时钟未同步的样本。

## 3. 约束（来自现有代码）

- **安全策略：** `api.py` 的 `browser_headers` 对所有响应设置 CSP：`default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`。
  - 不能用内联脚本，也不能用 `<style>` 和 `style=""` 属性。脚本里通过 `element.style` 设置样式是允许的。
  - 不能从 CDN 加载任何资源。
- **会话：** `POST /wb/login` 设置 Cookie `growbridge_operator`（`workbench/api.py` 的 `COOKIE`），属性为 HttpOnly、`SameSite=strict`、`path=/wb`；从 overlay 入口登录时还带 `Secure`。
- **防跨站：** 所有非 GET 请求都必须带 `x-growbridge-ui: 1` 头，Origin 必须在允许列表里，并且和 Host 一致（`check_browser`）。
- **两种入口：** `GET /wb/me` 返回 `entry`（`lan` 或 `overlay`）。
  - `POST /wb/irrigation` 只开放给现场入口（`on_site`）。
  - 会话绑定登录时的入口地址，换一个地址访问会被拒绝。
- **重新认证：** 下列接口要求 300 秒内重新认证过（`REAUTH_SECONDS`），否则返回 `reauth_required`：
  - 阶段的 approve、resume、takeover；
  - safety approve；项目预算；
  - 冻结分析脚本、启动分析运行；
  - 登记留出集；
  - 计算余额、任务预算、了结尝试。
- **拒绝的格式：** 业务拒绝统一返回 `{"detail": {"code": <拒绝码>, "message": <英文说明>}}`。状态码按 `STATUS_BY_CODE` 取：`state` 409，`session` 401，`locked` 429，其余 403。请求体校验失败则是 FastAPI 的 422，格式为 `{"detail": [...]}`。拒绝码的完整清单见 Wiki 的[拒绝码与事件](../../wiki/zh-CN/Denial-Codes-and-Events.md)。
- **代码规模：** 文件不超过 800 行，函数不超过 50 行。现有 `web/app.js` 已有 1060 行，这次不能照搬单文件写法。
- **测试与 CI：**
  - 先写测试；测试不联网，不碰真实设备和凭据。
  - CI 只装 `dev` 依赖，已有 Node 22（`setup-node`），目前只对 `web/app.js` 做 `node --check`。
  - 不引入任何 npm 依赖。
- **打包：** `pyproject.toml` 的 `package-data` 目前只包含 `web/*.html`、`web/*.css`、`web/*.js`，子目录里的文件需要补上。
- **运行环境：** Python 3.11 和 3.13，树莓派离线也要能用，所以字体只用系统字体。

## 4. 方案

| 方案 | 做法 | 代价 | 结论 |
| --- | --- | --- | --- |
| A. 原生 JS 静态页面 | 和现有控制台同一写法：ES 模块，不需要构建，按功能拆成多个文件 | 没有组件框架，表单和状态要自己写一层小工具 | **选定**（用户选择） |
| B. 框架加构建（Vite 加 Preact 或 Svelte） | 组件化，可以用 TypeScript | Python 项目要多一套 Node 依赖和构建步骤；打包要么提交构建产物，要么依赖 Node；CI 和树莓派部署更复杂 | 不选 |
| C. 服务端渲染 | Python 模板输出 HTML | 现有接口都返回 JSON，防跨站校验是为页面脚本设计的；要再写一层 HTML 路由，后端代码量差不多翻倍，曲线还是得用 JS 画 | 不选 |

环境数据（用户选定 **B**）：

- 不选"只放链接跳到设备控制台"：那边是另一套登录，看研究时要来回切换。
- 不选"把两个控制台合并、共用一套登录"：要改桥接层认证，风险大。
- 选定的做法：阶段页从存档按阶段时间窗读取环境曲线。设备调节仍然走工作台的接管流程。

## 5. 页面与导航

页面地址是 `GET /workbench`（新增，返回 `web/workbench.html`），静态资源在 `/assets/workbench/…`（现有的 `/assets` 挂载已经覆盖子目录）。页面内用 hash 路由（如 `#/projects/p1/rounds/r1`），把当前位置写进 URL，刷新或分享链接时能回到同一处。

```
┌──────────────┬──────────────────────────────────────────────────────────┐
│ DiAGRI 工作台 │ 项目 p1 › 轮次 r1 › 阶段 s2                  中/EN  carol ▾ │
│              ├──────────────────────────────────────────────────────────┤
│ ● 待我处理 3  │  阶段 s2 · 运行中 · 写入权 #14     [暂停] [停止] [接管…]  │
│   项目        │  ┌ 环境（为显示已降采样，共 4 320 个样本）────────────┐   │
│   告警     2  │  │ 温度 ▁▂▃▅▆▅▃  湿度 ▆▅▅▄▄▅▆  VPD …  CO₂ …          │   │
│   证据卡      │  └──────────────────────────────────────────────────────┘   │
│   计算        │  运行单 v3（已批准）   人工测量（12）   状态历史   干预记录 │
│   安全配置    │  ……                                                       │
│              │                                                           │
│ 入口：现场    │                                                           │
└──────────────┴──────────────────────────────────────────────────────────┘
```

| 页面 | 内容 |
| --- | --- |
| 登录 | 姓名和密码；被锁定（`locked`）时提示稍后再试 |
| 待我处理（首页） | 待审批的阶段（`pending_review`）、人工接管中的阶段（`manual`）、待现场核对的阶段（`recovery_check`）、已暂停的阶段（`paused`）、等待停止后选择的轮次（`awaiting_choice`）、未读告警、卡住的计算尝试、待处理的研究任务（`needs_attention`、`needs_review`） |
| 项目列表 | 项目名、创建时间、轮次数和最近一轮的状态；新建项目 |
| 项目详情 | 轮次列表；协议（每个协议的最新版本）；项目预算；研究目标与研究任务；留出集 |
| 轮次详情 | 状态、阶段列表、停止后的选择、中止；确认性分析：冻结脚本、读取冻结状态、启动运行 |
| 阶段详情 | 状态、写入权编号；环境曲线和当前读数；运行单审阅与批准；启动、暂停、续跑、停止；接管、手动通道、交还、现场核对；浇水（仅现场入口）；人工测量的录入和列表；状态历史；干预记录；回执查询 |
| 告警 | 未读告警列表，标为已读 |
| 证据卡 | 列表、录入、核实 |
| 计算 | 余额（录入人和时间）、各任务预算与已用量、进行中和卡住的尝试；录入余额、设预算、了结尝试 |
| 安全配置 | 显示当前配置；编辑框预填**当前配置**，绝不预填示例值，因为 `POST /safety/approve` 会整份替换配置。审批前的确认框逐项列出改动的字段（旧值 → 新值）。还没有配置时，编辑框只给出字段结构，不填任何数值。 |

## 6. 现有接口与界面的对照

全部 42 条现有接口（路径前缀 `/wb`）：

| 页面 | 接口 |
| --- | --- |
| 登录与会话 | `POST /login`、`POST /logout`、`POST /reauth`、`GET /me` |
| 待我处理与告警 | `GET /alerts`、`POST /alerts/{event_id}/read` |
| 项目 | `POST /projects`、`POST /projects/{project_id}/budget`、`POST /protocols`、`POST /goals`、`GET /holdouts`、`POST /holdouts` |
| 轮次 | `POST /rounds`、`GET /rounds/{round_id}`、`POST /rounds/{round_id}/choice`、`POST /rounds/{round_id}/abort`、`GET /protocols/{protocol_id}/analysis`、`POST /protocols/{protocol_id}/analysis`、`POST /analysis/runs` |
| 阶段 | `GET /stages/{stage_id}`、`GET /stages/{stage_id}/run-sheet`、`POST /drafts/run-sheet`、`POST /stages/{stage_id}/approve`、`/start`、`/pause`、`/resume`、`/stop`、`/takeover`、`/handback`、`/onsite-check`、`POST /manual/{channel}`、`POST /irrigation`、`POST /measurements`、`GET /receipts/{request_id}` |
| 证据卡 | `GET /evidence`、`POST /evidence`、`POST /evidence/{card_id}/verify` |
| 计算 | `GET /compute`、`POST /compute/balance`、`POST /compute/tasks/{task_id}/budget`、`POST /compute/attempts/{attempt_id}/settle` |
| 安全配置 | `POST /safety/approve` |

每个请求体的字段以 `workbench/*.py` 里的 Pydantic 模型为准。

**表单策略（我的决定）**

- 字段简单的请求体用普通表单，例如测量、余额、预算、停止后的选择、证据卡、核实、了结原因、手动通道的取值。
- 结构复杂的请求体用 JSON 编辑框，预填当前值或一份最小示例，提交后在对应位置显示服务器的校验错误。这类请求体有：运行单草稿、协议、安全配置、分析脚本、研究目标、留出集。

理由：这些结构本身还在演进，为每个字段单独做表单，工作量大而且容易和模型脱节。

## 7. 新增只读接口

都挂在 `/wb` 下，要求操作员身份（`operator`），只读不写，并按现有习惯给出数量上限。

| 接口 | 返回 | 数据来源 |
| --- | --- | --- |
| `GET /inbox` | 第 5 节"待我处理"列出的各类条目，每条带类型、编号、所属项目或轮次、进入该状态的时间 | `stages_in(...)`、`wf_rounds.awaiting_choice`、`AlertBook.open()`、`ComputeService.overview()["stuck"]`、`TaskBoard` |
| `GET /projects` | 项目列表，带轮次数和最近一轮的状态 | `wf_projects`、`wf_rounds` |
| `GET /projects/{project_id}` | 项目、轮次列表、各协议的最新版本、项目预算、研究任务 | `wf_*`、`ProjectBudget`、`TaskBoard.list` |
| `GET /stages/{stage_id}/readings?points=` | 与桥接层 `GET /history/series` 同样的结构：`samples`（时间戳和原始 `data`）、`window`、`total_samples`、`downsampled`。另外每个返回的样本带上自己的 `quality` 和 `clock_synced`，以及 `flagged`：它所在时间桶里有问题的样本数（`quality` 不是 `ok`，或时钟未同步）。顶层再给出 `flagged_total`。这样被降采样省掉的问题样本不会悄无声息地消失（我的决定）。 | 存档 `samples(experiment_id, start, end)`。时间窗从阶段的 `started_at` 到结束时间，未结束则到当前时间。每个时间桶取最后一个样本，与 `store.series` 的做法一致。`points` 默认 600，上限 2000 |
| `GET /safety` | 当前生效的安全配置；还没有配置时返回 `null` | `ControlPort.safety()` |
| `GET /stages/{stage_id}/measurements` | 这个阶段所属实验的人工测量，包含更正链 | 存档 `measurements(...)` |
| `GET /stages/{stage_id}/history` | 状态转换（`wf_history`）和干预记录（`wf_interventions`），按时间排序 | `wf_history`、`wf_interventions` |

唯一改动的现有接口是 `GET /wb/me`：新增 `timezone` 字段，取自设置项 `report_timezone`。只加字段，不改已有字段（见第 8 节"时间"）。

曲线的读数字段与现有控制台一致：`temp`、`humi`、`vpd`、`co2`、`ppfd`、`tempSoil`，对应的取值路径和单位以 `web/app.js` 的 `metrics` 为准。

## 8. 交互规则

- **写操作**
  - 按钮在请求进行中禁用，防止重复提交。
  - 成功后重新读取受影响的对象，例如阶段、轮次、待我处理。
  - 手动通道和浇水返回请求编号，用 `GET /receipts/{request_id}` 跟踪到出结果，界面显示"已生效""结果未知""失败"。
- **重新认证**
  - 收到 `reauth_required` 时弹窗输入密码，调用 `POST /reauth`，成功后对原请求重试一次。
  - 取消则什么也不做。
  - 弹窗里写明是哪个操作需要重新认证。
- **会话失效**（`session`）
  - 跳到登录页，保留当前 hash，登录后回到原处。
  - 填了一半的表单内容保留在内存里，但不自动提交。
- **状态冲突**（`state`，409）
  - 显示服务器的说明，并自动刷新当前对象，因为别人可能刚刚改过它。
- **入口差异**
  - 在 overlay 入口，浇水按钮停用，并说明"只能在现场入口操作"。
  - 服务器照样会拒绝，前端停用只是提前提示。
- **拒绝码翻译**
  - 每个拒绝码在中英两种语言里都有一句说明和一句建议。
  - 遇到未知的拒绝码，原样显示服务器的英文说明。
- **时间**（我的决定）
  - 所有时间的显示和录入都用站点时区，也就是报告所用的设置项 `report_timezone`，默认 UTC。
  - 每个时间旁边都标出时区名，例如"Europe/Helsinki"，避免远程操作员按自己所在地的时间填写。
  - 录入的时间（例如测量的 `measured_at`）在浏览器里换算成 epoch 秒。用 `Intl` 求出这个时区在该时刻的偏移量，再换算；要有跨夏令时切换的单元测试。
- **刷新**
  - 待我处理和阶段页每 15 秒刷新一次，其余页面在进入时读取。
  - 页面隐藏（`visibilitychange`）时暂停刷新。

## 9. 视觉

- **视觉语言：** 沿用现有设备控制台。
  - 颜色：墨绿 `#172e28`、绿 `#23684d`、浅底 `#f4f6ef`、琥珀 `#8d6019`、红 `#a63d36`。
  - 字体：Inter 加系统字体栈，不加载网页字体。
  - 圆角：18px。

  这样做（我的决定）一是两个界面看起来是一个产品；二是离线的树莓派上也不用下载字体。
- **共用设计变量：** 把 `style.css` 里的 `:root` 变量抽到新文件 `web/tokens.css`，两个页面都引用。取值不变，所以现有控制台的外观不变，抽取前后各截图对比确认。
- **信息层级：** 桌面布局是左侧导航加主区域，主区域顶部是面包屑和当前对象的状态条。
- **状态配色有语义：**
  - 等人处理（`pending_review`、`manual`、`paused`、`awaiting_choice`）用琥珀色；
  - 需要现场处理（`recovery_check`）和告警用红色；
  - 运行中用绿色；
  - 已结束或已停止用灰色。
- **曲线：** 用 SVG 画，每个读数一条小曲线，鼠标悬停显示数值和时间。质量有问题或时钟未同步的样本用空心点标出。

## 10. 文件布局（我的决定，实现者可在不违背约束的前提下调整）

```
src/growbridge/web/
  tokens.css                 # 新：共用设计变量（从 style.css 抽出）
  workbench.html             # 新：控制台页面
  workbench/                 # 新：ES 模块
    main.js                  # 启动与 hash 路由
    api.js                   # fetch 封装：UI 头、拒绝解析、重新认证后重试
    denials.js               # 拒绝码到说明和建议的映射
    i18n/en.js, i18n/zh.js   # 文案
    ui/                      # 表单、对话框、表格、曲线、格式化
    pages/                   # inbox、projects、round、stage、alerts、evidence、compute、safety、login
    workbench.css            # 样式（超过 800 行就再拆）
src/growbridge/workbench/reads.py   # 新：第 7 节的只读接口
tests/workbench/test_workbench_reads.py
tests/web/*.test.mjs                # 新：node:test，测纯逻辑
```

## 11. 测试

- **pytest：**
  - 第 7 节每条接口：未登录被拒、模型令牌被拒（只限操作员）、返回结构、数量上限、空数据；
  - `readings` 的时间窗和降采样；被省掉的问题样本反映在 `flagged` 和 `flagged_total` 里；
  - `GET /safety` 在有配置和没有配置时的返回；`GET /me` 带上 `timezone`；
  - `GET /workbench` 返回页面并带上安全头；
  - 打包清单包含新的静态文件。
- **node:test**（用 Node 自带的测试模块，不装依赖）：
  - `api.js` 对 401、403、409、422、429 和 `reauth_required` 的处理，以及重试只发生一次；
  - 两种语言的文案键一一对应；
  - 每个已知拒绝码在两种语言里都有说明；
  - hash 路由的解析；格式化函数；曲线的坐标换算；
  - 站点时区的时间换算，包括 Europe/Helsinki 夏令时切换前后；
  - 安全配置改动清单（旧值 → 新值）的计算。
- **CI：**
  - 对所有控制台脚本做 `node --check`；
  - 增加一步 `node --test tests/web/`。
- **浏览器检查：** 在内置浏览器里，用模拟的 AC5 跑一遍"登录 → 待我处理 → 项目 → 轮次 → 阶段"的主要流程。
  - 在 1440、1024、768 三种宽度截图，检查无横向滚动、键盘可达、对比度。
  - 如果现在还没有能在模拟设备上常驻运行工作台的办法，实现者需要补一个开发脚本，放在 `scripts/` 下。

## 12. 留给实现者

- 第 7 节各接口返回的具体字段名和数量上限的取值。
- 表格的分页方式；JSON 编辑框里的示例内容。
- CSS 的具体拆分方式和组件的命名。
- 开发脚本怎么启动模拟环境。

## 13. 最容易出问题的地方

1. **重复提交控制操作。** 网络慢时连点两次按钮会发出两个请求。按钮禁用是第一道防线；手动通道这类写入还有请求编号和回执兜底。
2. **别人刚改过同一个对象。** 两位操作员同时操作，后提交的一方会收到 409。必须刷新并说明，不能让页面停在过时的状态上。
3. **会话在填表途中过期。** 重新登录后，表单内容要还在，但不能自动提交。
4. **很长的阶段。** 一个阶段可能持续好几周，样本数以万计。`readings` 必须在服务端降采样并设上限，否则一次读取就会拖垮树莓派。
5. **两种入口的差异。** 同一个页面在 overlay 入口能做的事更少。测试要分别覆盖 `lan` 和 `overlay`。
