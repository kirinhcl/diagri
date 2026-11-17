# 控制台可用性清单（三份审计合并版）

来源：`audit-execution.md`（E，42 条）、`audit-research.md`（R，54 条）、`audit-server.md`（S，38 条），共 134 条原始发现。
标准：`rubric.md`（N1–N10、ISO 9241-110、PD 渐进披露、CC 代码与文案分离）。
新编号由页面前缀加序号组成（如 `INB-01`）；原始编号都保留在"编号"列里。
"改在哪"：**客户端** = 控制台前端；**服务器文案** = 服务器返回的文字或字段；**模型提示词** = `agents/roles.py` 等提示词。

---

## 1. 总览

合并并核实后，共 **116 条**（134 条原始发现，重复的合并，见各表）。

| 严重程度 | 条数 |
|---|---|
| High | 26 |
| Medium | 69 |
| Low | 21 |

按页面：收件箱 7，项目与对话 13，轮次与报告 20，阶段与运行单 21，阶段历史 5，人工任务与测量 7，实时环境 3，安全限值 5，告警 13，证据 2，计算 5，登录与框架 6，错误信息 9。

**整体情况。** 控制台的骨架是好的：状态词诚实、危险操作多数有确认、拒绝原因有中英文目录。问题几乎都出在"最后一步"：把内部数据直接印到屏幕上。
最常见的三种：把 30–40 位的 id 当标题和链接；把事件码、枚举值、字段名当文字；把本该折叠的哈希、JSON、原始报错默认摊开。
第二层问题在服务器和模型：服务器把英文句子连同 id 和数字拼好再发出，控制台无法翻译；模型提示词没有"为操作员写作"的规则，所以报告里出现 epoch 秒数和字段名。
大部分修复只在客户端：一个映射函数加一个"技术详情"折叠，就能解决一半以上的 High。

---

## 2. 根源问题

按"改完后用户看到的变化有多大"排序。条数按**主要原因**计，每条原始发现只归一类；另有 14 条零散项不属于任何一类（134 = 16+20+8+24+8+8+12+5+7+12+14）。

### C1. 用 id 当名字（16 条）
- **用户看到：** 页面标题 "阶段 stage_round_9d38ffa4ca3049948194e0b60315c650-1"；轮次面包屑 "Project project_9d38…"；对话里的下拉框 "round_9d38ffa4… · 阶段审阅中"；收件箱标题 "Compute attempt att_…"。
- **违反：** N2、N6、CC。
- **涉及：** E-11, E-12, E-20, E-25, E-31, E-40, R-11, R-13, R-20, R-21, R-23, R-33, R-34, R-38, R-39, R-42。
- **修法：** 写一个 `displayName(kind, row)`（项目名、"第 2 轮"、"第 1 阶段：营养生长"），所有页面共用；id 只放在小号可复制的说明里。读接口需要补 `ordinal`/`title` 的地方请服务器加字段。**客户端为主，少量服务器字段。**

### C2. 事件码、枚举、字段名原样显示（20 条）
- **用户看到：** "事件：end_condition_met"；检查结果旁的 `manual_task`；安全限值表里的 "temp (°C)"、"gt 30"、"fan → 0"；收件箱里的 "data_gap"。
- **违反：** N2、CC。
- **涉及：** E-01, E-02, E-03, E-06, E-23, E-36, E-37, E-38, E-41, R-09, R-10, R-14, R-18, R-19, R-53, S-12, S-13, S-27, S-28, S-29（R-06 的"缺标签显示 key"也属此类，列在零散项）。
- **修法：** 一个 `labelOr(t, prefix, value)`（已有 `statePill` 的做法），覆盖事件、干预类型、检查码、告警类型、角色、阶段、字段名、工具名；找不到时显示"未知"，不显示 key。加一个测试：服务器能发出的每个码在目录里都有条目。**客户端。**

### C3. 技术细节默认摊开（8 条）
- **用户看到：** 64 位十六进制摘要在运行单事实栏和审批日志里；审批冲突提示要求比较两个 64 位字符串；"写入权 阶段 3 · 照护 3 · 人工 3"；每个拒绝下面多一行英文原始 message。
- **违反：** PD、N2、N6、N9。
- **涉及：** E-10, E-13, E-30, R-04, R-24, R-46, R-50, S-19。
- **修法：** 全站一个"技术详情"折叠组件；默认只显示短指纹（`8bc36a6f…`，可复制）。运行单的 JSON 折叠已经做对了，照这个做法推广。**客户端。**

### C4. 服务器发的是拼好的英文句子（24 条）
- **用户看到：** "Stage st_ab12 is recovery_check after disconnect_affects: {\"reasons\": […], \"seconds\": 412.6}"；"temperature > 30 for 300 s (heat_high)"；"manual irrigation irrigate-daily needs the user at 09:00…"（中文页面里的英文）。
- **违反：** N2、N4、N9、CC。
- **涉及：** E-07, E-22, E-28, E-42, R-03, R-37, R-40, R-45, S-01, S-03, S-04, S-08, S-16, S-17, S-18, S-21, S-23, S-24, S-25, S-26, S-30, S-32, S-33, S-36。
- **修法：** 服务器给 `code` + `params`（传感器、值、单位、秒数、状态），控制台用目录拼句子。`research/notes.py` 已经是这个模式，向告警、检查结果、拒绝、回执推广。**服务器文案（code+params）加客户端映射。**

### C5. 模型提示词没有"为操作员写作"的规则（8 条）
- **用户看到：** 中文报告页里的英文条目："ends at 1796594627, 128 s before…"、"max_missing_fraction 0.2"、"right_number=3 on the end_condition_met/end_actions events: unexplained"；对话回复是英文。
- **违反：** N2、N4、N8、CC。
- **涉及：** R-01, R-02, R-08, S-11, S-31, S-34, S-35, S-37。
- **修法：** 在 `_COMMON_LIMITS` 加一段共用规则：不写 id、字段名、工具名、枚举值；时间写本地日期时间；时长写分钟或天；每个问题一句话说明该做什么；限定长度；使用用户语言。同时把控制台语言传给模型（目前没有任何地方传，见核实记录 R-08），审计任务的问题里不要喂 epoch 秒。**模型提示词，加少量服务器上下文。**

### C6. 数字没有换算也没有单位（8 条）
- **用户看到：** "时长 504.0 小时"；"持续 300"、"有效 600"（秒）；"风扇 1" 不说满档是 10；每个时间格都带 "2026-11-20 10:00 UTC"；预算 "1.8300000000000001"。
- **违反：** N2。
- **涉及：** E-09, E-21, E-24, E-32, R-15, R-30, R-35, S-38。
- **修法：** `format.js` 里统一 `formatDuration`（21 天 / 5 分钟）、`levelText`（3 / 10）、`formatTime`（按语言，区域只在页头写一次，近期用相对时间）、`formatNumber`（含货币）。**客户端。**

### C7. 错误和告警不说"下一步做什么"（12 条）
- **用户看到：** 水泵意外开启的告警只说发生了什么，还提到 "interlock"、"unexpected_watering"；拒绝文字 "请用新的请求编号"（用户从没见过编号）；阻断项只说"设备没有 temp_air"，没说怎么改。
- **违反：** N9、N10。
- **涉及：** E-08, R-47, R-48, S-02, S-05, S-06, S-07, S-09, S-10, S-14, S-20, S-22。
- **修法：** 每个告警、检查码、拒绝码都带"怎么处理"一句话；`state`、`scope`、`approval_invalid` 拆成子码（如 `stage_not_pausable`、`run_sheet_too_old`、`capabilities_changed`），分别配建议；内部异常只写固定的人话，异常类名放日志。**服务器文案（子码、固定文案）加客户端目录。**

### C8. 用整份 JSON 文本框做高风险编辑（5 条）
- **用户看到：** 运行单草稿、安全限值、协议、目标、保留集、冻结分析脚本，全都是 JSON 文本框；脚本要写成 JSON 字符串里的一行；安全限值首次进入是一份全是 `null` 的骨架，页面自己说"原样提交会被服务器拒绝"。
- **违反：** N5、N7、N2、ISO 任务适合性。
- **涉及：** E-17, E-39, R-25, R-28, R-29。
- **修法：** 分字段的表单（带单位和范围，指标和方法从协议里选）；JSON 放进"高级"。目标编辑器直接删（对话框已经能发目标）。首次安全限值给一份已审定的模板，不给 null。**客户端。**

### C9. 有后果的操作没有拦一下、没说后果（7 条）
- **用户看到：** 轮次选择框默认选中"重做阶段"，点一下发送就执行；确认性分析只能跑一次，却在失败后才告诉你（`already_run`）；证据"核验"一键提交；浇水表单直接开泵，任务行里的浇水按钮却会先确认；"启动"在未审批时也可点。
- **违反：** N5、N3、N4。
- **涉及：** E-16, E-18, E-19, E-27, R-22, R-26, R-43。
- **修法：** 用已有的 `confirmAction`；选择框加"请选择…"占位（`evidence.js` 已这样做）；每个选项下一句后果说明；输入框强制 min/max。**客户端。**

### C10. 页面顺序和信息量不跟着任务走（12 条）
- **用户看到：** 阶段页里"审批"按钮在它要审批的运行单上面；项目页一次堆六个表单；历史最早的在最上面；收件箱的标题是整段上一任务的摘要；"还有 12 项未显示"没法点开。
- **违反：** N6、N8、N7、ISO 任务适合性。
- **涉及：** E-04, E-05, E-14, E-15, E-29, E-34, R-16, R-17, R-31, R-32, R-36, R-49。
- **修法：** 按任务排序（先运行单后审批；运行中先看读数）；长文本截两行加"展开"（`questionCell` 已有）；同类项分组并带数量；次要内容折叠。**客户端。**

**零散项（14 条，不归入上面任何一类）：** E-26, E-33, E-35, R-05, R-06, R-07, R-12, R-27, R-41, R-44, R-51, R-52, R-54, S-15。

---

## 3. 逐页清单

编号前缀：`INB` 收件箱，`P` 项目与对话，`RND` 轮次与报告，`STG` 阶段与运行单，`HIS` 阶段历史，`TSK` 人工任务与测量，`ENV` 实时环境，`SAF` 安全限值，`ALT` 告警，`EVI` 证据，`CMP` 计算，`FRM` 登录与框架，`ERR` 错误信息。
严重程度已合并，取较高者；有分歧且要紧的，在表后加脚注。

### 3.1 收件箱

| 编号 | 现在用户看到的 | 违反的标准 | 严重程度 | 建议改法 | 改在哪 |
|---|---|---|---|---|---|
| INB-01 (R-13) | 标题是 "Stage stage_…"、"Round round_…"、"Compute attempt att_…"，元信息里有 "Project project_…"、"Device dev_…" | N2, N6, CC | High | 用含义命名："审阅运行单，莴苣光照试验第 2 轮"；项目名和轮次号放元信息；id 放可复制详情 | 客户端（读接口需带名称） |
| INB-02 (R-14, S-12) | 元信息里直接写 `data_gap`、`threshold`、`frozen_reading`、`task_missed` | CC, N4 | Medium | `alert.kind.<kind>` 目录标签，找不到显示"其他" | 客户端 |
| INB-03 (R-15) | 右侧 "2026-11-16 08:14 Europe/Helsinki"，没说这是什么时间 | N1, N2, N6 | Medium | "已等待 3 小时 20 分"，精确时间放 title | 客户端 |
| INB-04 (R-16) | 任务 `question`（后续任务带着整段上一任务摘要）和告警原因整段当标题 | N8 | Medium | 截两行加"展开"，复用 `questionCell` | 客户端 |
| INB-05 (R-17) | "还有 12 项未显示"，没有入口 | N3, N7 | Medium | 链到对应列表或"显示更多" | 客户端（及服务器上限） |
| INB-06 (R-18) | "负责角色：researcher"，聊天里却是 "Researcher" | CC, N4 | Medium | 复用 `chat.role.<role>`（项目页同样） | 客户端 |
| INB-07 (R-54) | 告警条目链到整个告警页，任务条目链到项目页，要重新找 | N6, N7 | Low | 深链接加锚点或筛选 | 客户端 |

### 3.2 项目、项目页与对话

| 编号 | 现在用户看到的 | 违反的标准 | 严重程度 | 建议改法 | 改在哪 |
|---|---|---|---|---|---|
| P-01 (R-34) | 项目列表里有"ID"列（`project_…`），最新轮次的链接文字是 `round_…` | CC, N6, N8 | Medium | 去掉 ID 列；链接写"第 2 轮" | 客户端 |
| P-02 (R-28) | 创建协议只能改一份预填 JSON（作物、处理、`allocations`、`randomization_seed: 20261118`、`method: "paired_block"`）；示例数据（莴苣、tent-1）可原样保存，`question` 为空也能存（`ResearchProtocol.question: str` 无约束） | N5, N2, N10, PD, CC | High | 分字段表单（问题、假设、作物、处理、区组、终点从列表选）；JSON 放"高级"；`question` 为空时禁止保存 | 客户端 |
| P-03 (R-29) | "目标（JSON）"和"保留集（JSON）"文本框；目标框和对话框重复（两者都 POST `/goals`） | N5, N4, N2, PD | High | 删除目标编辑器；保留集用多选，并解释"保留"与"开发" | 客户端 |
| P-04 (R-30) | "剩余调用 37"，"剩余费用 1.8300000000000001"（`String(float)`），上限无币种 | N2, N10 | Medium | 格式化，写"已用 x / 共 y"，字段下加说明 | 客户端 |
| P-05 (R-31) | 一页叠了对话、轮次、协议、预算、目标、保留集，六个表单，导语里还有 id | N8, N7 | Medium | 标签页或折叠；主操作（对话、轮次）在前 | 客户端 |
| P-06 (R-32) | "研究任务"表里有原始角色和状态；区块叫"目标与任务"，表叫"研究任务" | N4, N2 | Medium | 统一名称；用文字写谁、做什么、结果 | 客户端 |
| P-07 (R-33) | "保留批次""结果字段"列打印 id 数组；"读取次数"是裸数字 | CC, N2 | Medium | 显示名称；解释"读取"的含义 | 客户端 |
| P-08 (R-44) | 预算、目标、保留集、冻结、余额、任务预算保存后都只回答"已完成。" | N1 | Medium | 点名对象："已设置预算：50 次调用，20 欧元" | 客户端 |
| P-09 (R-08, S-34) | 整段编排回复是英文，页面是中文。提示词其实写了"用用户的语言"（`roles.py:59-60`），但没有任何地方把语言告诉模型 | N4, ISO 符合预期 | Medium | 发送目标时带上控制台语言，写进记录；见 RND-17 | 模型提示词＋服务器上下文 |
| P-10 (R-09) | 主日志里每次工具调用一行：角色标签加 `<code>` 工具名，穿插在回答之间 | N2, CC, N8, PD | Medium | 工具名映射成短语；连续调用折叠成"用了 5 个工具" | 客户端 |
| P-11 (R-10, S-36) | "编排 Agent的任务结束：已完成"（缺空格、"Agent"）；失败时附原始原因，如 "model unavailable: APIStatusError…"、"model stopped without finishing: max_tokens"；未知状态显示 `state.xxx` | N2, N9, CC | Medium | 改成"编排助手已完成"/"已停止，需要你处理：…"；原因用 `reason_code` 映射；提示词要求模型说明用户下一步 | 客户端＋服务器文案（reason_code）＋模型提示词 |
| P-12 (R-11) | 下拉框默认选中最新的开放轮次，写成 "round_9d38…（38 位）· 阶段审阅中"，"无轮次"不是默认，一般问题会悄悄挂到轮次上 | N6, N5, N2 | Medium | 默认"无轮次"；轮次写"第 2 轮，等待审阅" | 客户端 |
| P-13 (R-12) | 点发送后最多等约 30 秒，日志里没有待处理条目；提示是常驻两句话 | N1, N8 | Medium | 本地追加"已发送，编排助手稍后接手"；提示缩短 | 客户端 |

### 3.3 轮次与报告

| 编号 | 现在用户看到的 | 违反的标准 | 严重程度 | 建议改法 | 改在哪 |
|---|---|---|---|---|---|
| RND-01 (R-20) | 轮次页面包屑 "Project project_9d38…"，页面标题 "Round round_9d38ffa4…"（项目页用的是名称） | N4, N6, N2 | High | 项目名；"第 2 轮"（按 `project.rounds` 顺序或服务器 `ordinal`）；id 小字可复制 | 客户端（及服务器字段） |
| RND-02 (R-21) | 摘要里 "Protocol: protocol-1-ab12cd v1"、"Data snapshot: snap_…"、"Report: art_…" | CC, PD, N6 | Medium | 项目名链接；协议显示名；去掉快照和报告 id（见 RND-12） | 客户端 |
| RND-03 (R-23) | 阶段表链接文字是 `stage_…`；"等待选择的阶段"列打印原始 id | CC, N6 | Medium | 写"第 1 阶段：营养生长" | 客户端（及服务器字段） |
| RND-04 (R-22) | 选择框默认选中第一项"重做阶段"（`CHOICES[0]`，无占位），点一下发送即执行；选项没有后果说明；文字里写 "Stage stage_… stopped" | N5, N10, N2 | Medium | 加"请选择…"占位；每项一句后果；去掉 id | 客户端 |
| RND-05 (R-24) | 每个轮次都显示确认性分析块："脚本 SHA-256"、冻结人、脚本文本、`snap_…` 快照选择、原始"运行状态"、退出码、stdout/stderr | PD, N2, N10, CC | High | 折叠到"确认性分析（高级）"；状态用话说（未开始/脚本已锁定/运行完成）；哈希和输出放详情；快照按日期和完整度命名 | 客户端 |
| RND-06 (R-25) | 冻结脚本要把代码写进 JSON 字符串字段 `{"project_id": "...", "script": ""}` | N5, N2, ISO 任务适合性 | High | 纯代码文本框（项目 id 由前端补）；提交前说明冻结不可撤销 | 客户端 |
| RND-07 (R-26) | 确认性分析只能跑一次，只有失败后（`already_run`）才告诉你；"运行"按钮没有确认（`round-analysis.js` 没用 `confirmAction`） | N5, N3 | High | 运行前 `confirmAction`："这个快照上只能做一次" | 客户端 |
| RND-08 (R-27) | "这个块显示协议第 3 版，即最新版；本轮用的是第 1 版。下面的冻结脚本、快照和运行都属于第 3 版。"；"阶段已开始：是" | N2, N8 | Medium | "本轮按第 1 版规划；第 3 版已存在。下面的分析针对第 3 版，不是本轮。"；"已开始采集数据" | 客户端 |
| RND-09 (R-01, S-31) | 报告"局限"是英文条目，夹着 epoch 秒（"ends at 1796594627, 128 s before … 1796594755"）、字段名和字典（"max_missing_fraction 0.2"、"measurements={}, withheld=0"、"paired_block"） | N2, CC, N8, PD | High | 提示词要求平实句子、本地日期、不写字段名、用用户语言；客户端默认只展开前三条 | 模型提示词（客户端折叠） |
| RND-10 (R-02, S-31) | "未解决问题"里有 "Meaning of … right_number=3 on the end_condition_met/end_actions events: unexplained"；"下一轮"是一整段英文 "Proposal only… (1)…(4)" | N2, N8, N9 | High | 提示词：每条一个决定，不提事件名；客户端按 `richText` 拆行 | 模型提示词＋客户端 |
| RND-11 (R-03, S-32) | 估计栏直接显示服务器 `estimate.note`（"fewer than 2 complete blocks; no treatment effect can be estimated"，英文）；可估计时 "Effect 0.231234, p = 0.034" 不舍入、无指标和单位 | N2, N4, CC | Medium | `note` 改 `note_code`＋params，用目录；效应保留 2–3 位有效数字并写明指标；给 p 值一句说明 | 服务器文案＋客户端 |
| RND-12 (R-04) | "报告摘要"后跟 64 位哈希；"数据快照 snap_…"与结论同等权重，摘要块又重复一遍 | PD, N8, N4 | Medium | 快照 id、摘要、报告 id 放"技术详情"折叠，只留一份 | 客户端 |
| RND-13 (R-05) | 中文"报告摘要"指的是 SHA-256 哈希，读起来像"报告摘要（abstract）" | N2, N4 | Medium | 改"报告校验码（SHA-256）"，提示"用于确认报告未被改动" | 客户端 |
| RND-14 (R-06) | "结论等级：描述性"和"结论：不确定"并排，没说各自允许下什么结论；缺标签时显示 key `report.labels.undefined`；缺结论被悄悄写成"不确定" | N10, N2, N5 | Medium | 在标签下加一句"描述性：只描述所见，不支持关于处理的结论"；缺值写"未说明" | 客户端 |
| RND-15 (R-07) | 报告列表是纯文本 `<li>`，聊天回复是富文本 | N4 | Low | 列表项用 `richText`/`inline` | 客户端 |
| RND-16 (S-33) | `research/notes.py` 本身是好模式，但参数里漏进内部内容：`{problems}` 是英文列表（"light was never at 3 (recorded [0, 2])"）、`{channels}` = "light, fan"、`{treatment_id}` 是 id | N2, N4, CC | Medium | 参数改结构化（通道键、各类任务数量、等级列表），在观看者语言里用 `channel.*` 标签渲染 | 服务器文案＋客户端 |
| RND-17 (S-34) | 模型提示词只有两处语言规则（`roles.py:59-60` 编排、`:128` 审计）；规划和研究员没有；没有任何"平实、不写字段名、不写 id、不写原始时间、写下一步、限长"的规则 | N2, N9, N8, CC | High | 在 `_COMMON_LIMITS` 加一段共用的"为操作员写作"规则，并在发布工具的字段说明里重复 | 模型提示词 |
| RND-18 (S-35) | 审计任务问题里写 "Data window 1796590000 to 1796680000 (epoch seconds)"，工具结果带 epoch 浮点数，模型照抄 | N2 | Medium | 给模型已按项目时区格式化的日期；至少禁止引用 epoch | 模型提示词＋服务器文案 |
| RND-19 (S-37) | 写给模型的工具拒绝（"…the operator starts it with POST /wb/analysis/runs"）被模型转述给操作员 | N2, N9 | Low | 提示词加"把工具错误改写成操作员能做的事，不引用接口、id、工具名" | 模型提示词 |
| RND-20 (R-49) | "报告读取失败：请求没有成功……HTTP 500"，多行拼成一句 | N9, N8 | Low | 只留第一行，其余放详情 | 客户端 |

### 3.4 阶段与运行单

| 编号 | 现在用户看到的 | 违反的标准 | 严重程度 | 建议改法 | 改在哪 |
|---|---|---|---|---|---|
| STG-01 (E-06, E-07, S-13) | 每条检查结果旁有 `manual_task`、`no_evidence` 代码，句子是英文且带内部 id（"manual irrigation irrigate-daily needs the user at 09:00…"）；第一行消息掉到药丸下面（布局问题） | N2, N4, N9, CC | High | 不显示 `finding.code`，映射成标题加建议；`Finding` 加 `params`，在用户语言里拼句子；同时把行改成可换行的 flex | 客户端＋服务器文案（params） |
| STG-02 (E-08, S-14) | 检查结果是一长串平级的"提示/阻断"；阻断项只说错在哪，用运行单字段名（"host-controlled"、"validity"、"max gap"），不说怎么改，如 "max gap is shorter than the sampling interval" | N8, N9, N10, CC | High¹ | 阻断在前，按类别分组加计数；每个码配"怎么处理"；受影响的 id 用列表 | 服务器文案（参数、建议）＋客户端 |
| STG-03 (S-15) | 水泵规则那条写得最好（原因加做法），只有 "with seconds" 是术语 | N9 | Low | 保留；去掉 "with seconds" | 服务器文案 |
| STG-04 (S-16) | "protocol round 2 is allocated treatment high (light 3): light is not host-controlled; no timed action sets light to 3"：处理 id 和通道键直接出现，没有建议 | N2, N9, CC | Medium | 传处理名、通道、等级为参数，加"用定时动作把光照设为 3" | 服务器文案＋客户端 |
| STG-05 (S-17) | "timed action light-on: card card_12 is not verified; confirm it"；"…is uncalibrated (未校准)"：英文句子里混着服务器写死的中文 | N2, N4 | Medium | 传卡片 id 和标题为参数，用码映射 | 服务器文案＋客户端 |
| STG-06 (S-18) | "manual measurement canopy-measure needs the user at 10:00"：任务类型和 id 是原始值，时间无时区 | N2, N6 | Low | 传类型、id、时间、时区，复用任务页的标签（拍照/测量/浇水） | 服务器文案＋客户端 |
| STG-07 (E-09) | "时长 504.0 小时" | N2 | Medium | "21 天"；48 小时以下才用小时 | 客户端 |
| STG-08 (E-10) | 64 位摘要默认显示在"摘要（审批时记录）"下；审批日志"摘要 8bc3…37f"；冲突提示让操作员比对两个 64 位字符串 | N2, N6, PD, CC | High | "版本 1 · 指纹 8bc36a6f…"（短，可复制），全文放详情；冲突提示"你审阅的版本与已审批的不同"，附运行单链接 | 客户端 |
| STG-09 (E-11) | "protocol-lettuce-light v1"、设备 "SIMULATED"、时区 "UTC"、版本 "1"（id 和枚举当文字） | N2, CC | Low | 协议名做链接；设备类型用标签（"模拟设备"） | 客户端 |
| STG-10 (E-12) | 页面标题 "阶段 stage_round_9d38ffa4…-1"，面包屑、轮次和项目链接文字、环境页药丸都是原始 id | N2, N6 | Medium | 用实验或轮次标题、"第 2 阶段"；id 放 title 或详情 | 客户端（阶段读接口需带名称） |
| STG-11 (E-13) | "写入权 阶段 3 · 照护 3 · 人工 3"（内部栅栏计数器） | N2, N8, PD | Medium | 移到"技术详情" | 客户端 |
| STG-12 (E-14) | 从没暂停过的阶段显示"暂停时间 —"；"已到结束条件，结束动作尚未确认 否"是整句当标签 | N8, N2 | Low | 无值的行不显示；只在为真时显示横幅 | 客户端 |
| STG-13 (E-15) | 控制区（含审批）在运行单上面，审批提示却说"请先核对下面的运行单"，而运行单在好几屏之后；运行中时曲线在控制区下面 | N6, N8, ISO 任务适合性 | Medium | 待审阅时先运行单、紧接审批；运行中先看读数 | 客户端 |
| STG-14 (E-16) | 待审阅时"审批""开始""提交修改后的运行单"并排，权重相同；"开始"的提示自己写着"未审批时服务器会拒绝" | N5, ISO 任务适合性 | Medium | 只突出下一步；未审批时"开始"置灰并写原因 | 客户端 |
| STG-15 (E-17) | 改运行单的唯一方式是整份 JSON 文本框；被拒后显示"草稿没有保存：…（见下方）"，下面是英文检查结果 | N5, N7, N2, PD | Medium | 常见改动用结构化表单（时间、等级、任务），JSON 作高级模式 | 客户端 |
| STG-16 (E-18) | "档位"是裸数字框，允许范围只在说明里没做成 min/max；水泵可选，需要的等级是 0 | N5, N6, N10 | Medium | 每个通道下写范围并设 min/max；水泵换成"关闭水泵" | 客户端 |
| STG-17 (E-19) | 浇水表单（"秒数（最多 60）"，没有 max）直接开泵，任务行的浇水按钮却先确认 | N4, N5 | Medium | 同一个确认框；输入框强制 max 60 | 客户端 |
| STG-18 (E-20) | "请求 wb-3f2a…（uuid），发送于…"；"重发了较早的请求 wb-…"；"服务器按下面的请求编号保存结果" | N2, N6, PD | Medium | 写"发送于 10:03"；id 放可复制详情；"这是你刚才那次操作的结果" | 客户端 |
| STG-19 (E-21) | "灯光 调到 50"、"风扇 调到 3"、"设备回报档位 3。" 无单位无量程 | N2 | Low | 复用 `levelText`（50 %、3 / 10） | 客户端 |
| STG-20 (E-22, S-30) | "原因：not sent: [Errno 111] …"、"read-back level differs from 3"、"hand-over: recovery number changed"：原始设备或服务器字符串，英文 | N2, N9, CC | Medium | 回执加 `error_code`（`not_sent`、`rejected`、`link_lost`、`readback_level`…），映射成"设备没有执行，什么都没动"并说下一步（"请到现场确认"）；原文放日志 | 服务器文案（error_code）＋客户端 |
| STG-21 (E-23) | 交接差异 "灯光 level：应为 50，实际 0"：原始 `field`，值可能是对象 | N2, CC | Medium | `diff.field.<name>` 标签；值带单位 | 客户端 |

¹ E-08 原为 Medium，S-14 为 High；取 High，因为阻断项正是挡住审批的东西，不说怎么改会让人卡住。

### 3.5 阶段历史

| 编号 | 现在用户看到的 | 违反的标准 | 严重程度 | 建议改法 | 改在哪 |
|---|---|---|---|---|---|
| HIS-01 (E-01, S-27) | "事件：end_condition_met"、"事件：end_actions"、"事件：disconnect_affects"、"事件：readings_stale"、"事件：start"（中英文相同）。目录里只有一个包装模板 `history.event`，没有 `history.event.<id>` | N2, CC | High | 为所有事件加 `history.event.<id>` 句子（"结束条件已满足"）：`StageEventKind` 的 12 个值加 start、pause、resume、stop、takeover、handback 等；没有时显示通用说法 | 客户端 |
| HIS-02 (E-02, S-28) | "confirmed: true · reason: stage ended · right_number: 3"；"reasons: [\"due_action\",\"gap_too_long\"] · seconds: 412.6 · state_unreadable: false"；`differences` 以 JSON 显示 | N2, CC, PD | High | 每种事件一个渲染器，字段带标签，时长换成分钟，通道用 `channel.*`；`right_number` 永不显示；原始字典放"技术详情" | 客户端 |
| HIS-03 (E-03, S-29) | "干预：unexpected_watering"，下面 "status_at: 1796594400.2 · off_confirmed: true · off_confirmed_at: 1796594402.1 · request_id: wb-…"（原始 Unix 时间戳和请求 id）；`SAID_IN_LINE` 只过滤 4 个键 | N2, CC, PD | High² | `history.kind.<kind>` 标签；`*_at` 字段用 `timeText`；只显示白名单字段；请求 id 放详情 | 客户端 |
| HIS-04 (E-04) | 事件结束条件的标题是 "运行中 → 运行中"（自己到自己，含义只在原始事件 id 里） | N1, N2 | Medium | 标题用事件句子；起止状态不同时才显示药丸 | 客户端 |
| HIS-05 (E-05) | 最旧的在最上面，没有上限；三周阶段的最新事件在页面最下面 | N7, N8 | Low | 最新在前，或像任务列表一样折叠旧条目 | 客户端 |

² E-03 原为 Medium，S-29 为 High；取 High，因为 Unix 时间戳原样显示是实际读不懂的内容（代码核实见 5.1）。

### 3.6 人工任务与测量

| 编号 | 现在用户看到的 | 违反的标准 | 严重程度 | 建议改法 | 改在哪 |
|---|---|---|---|---|---|
| TSK-01 (E-25) | "任务"列显示 `irrigate-daily`、`canopy-measure`；提示 "已记录任务 irrigate-daily。" | N2, CC | Medium | 去掉该列（类型列已有浇水/测量/拍照）或显示任务标题 | 客户端 |
| TSK-02 (E-26) | 按钮文字是状态词"已完成"/"已跳过"；已完成的行显示药丸"已完成"，旁边按钮"已跳过"；窄格里竖排换行 | N4, N2, ISO 自描述性 | Medium | 改动词"标记完成"/"跳过"；按钮不换行 | 客户端 |
| TSK-03 (E-27) | 一次点击就追加完成/跳过记录；已完成的行也能点"跳过"；无确认，无法撤销（只能再记一条） | N3, N5 | Medium | 跳过要确认（可选理由）；给"撤销"，或说明后一条记录覆盖前一条 | 客户端 |
| TSK-04 (E-28) | "水泵运行了 20 秒；{ended_early}"打印原始原因；提示里带请求 id（"浇水 wb-… 已完成并记录"） | N2, N9, CC | Medium | 映射 `ended_early`；句子里去掉 id；失败时先说做什么（"请到现场检查水泵"） | 客户端＋服务器文案 |
| TSK-05 (E-29) | 表上方有四句长段（列表规则、2 小时迟到规则、报告怎么计） | N8, PD | Low | 一句话；评分规则放帮助折叠 | 客户端 |
| TSK-06 (E-30) | 测量表 11 列：植株 id、批次、"布局版本"、指标/单位/方法原值、操作员、记录 id、更正 id（"已被 m_…, m_… 更正"） | N2, N8, PD, CC | Medium | 默认 6 列（时间、植株、指标、值、方法、记录人）；指标用标签；id 和布局版本放行展开；更正做成行链接 | 客户端 |
| TSK-07 (E-31) | 测量表单 10 个平级字段；指标、单位、方法、批次、布局版本是自由文本；更正要从表里复制记录 id | N5, N6, N7 | Medium | 指标/单位/方法从协议里选（datalist）；行上加"更正"按钮预填 | 客户端 |

### 3.7 实时环境

| 编号 | 现在用户看到的 | 违反的标准 | 严重程度 | 建议改法 | 改在哪 |
|---|---|---|---|---|---|
| ENV-01 (E-32) | "风扇 1" 无单位无量程（0–10）；水泵格写"运行单此刻没有设定档位"，而水泵本来没有档位 | N2, N10 | Medium | "风扇 档位 1 / 10"；水泵写"运行单没有安排水泵" | 客户端 |
| ENV-02 (E-33) | 每条曲线按自己的最小最大值缩放（18.3–22.9 °C 填满整框，像大幅波动）；没有坐标轴和时间刻度，没有运行单目标带 | N1, N2, ISO 任务适合性 | Medium | 最小/中/最大刻度和起止时间；标出目标范围；设最小跨度 | 客户端 |
| ENV-03 (E-34, E-35) | 曲线下方有降采样、空心点、空档的长说明，窗口里时区出现两次；数值和时间只在 SVG `<title>` 悬停里，键盘和触屏读不到 | N8, N2, N7, ISO 参与度 | Low | 一行状态（"共 145 个读数"），图例按需显示；点可聚焦或提供表格视图 | 客户端 |

### 3.8 安全限值

| 编号 | 现在用户看到的 | 违反的标准 | 严重程度 | 建议改法 | 改在哪 |
|---|---|---|---|---|---|
| SAF-01 (E-36) | 规则表：传感器 "temp (°C)"，触发 "gt 30"，动作 "fan → 0"，持续 "300"，有效 "600"（原始键、运算符代码、裸秒数） | N2, CC, ISO 自描述性 | High | 每条规则一句话："空气温度高于 30 °C 持续 5 分钟 → 风扇调到 0；读数超过 10 分钟没更新则无效"；id 放详情 | 客户端 |
| SAF-02 (E-37) | 冻结阈值里传感器键原样（"tempSoil"），"读数之间最长空档（秒） 300"，分钟是裸数字 | N2, CC | Medium | `metric.<key>` 标签；写"5 分钟" | 客户端 |
| SAF-03 (E-38) | 审批对话框列 `rules.0.trigger.value: 30 → 35`、`frozen.minutes.temp: 10 → 5`，值带 JSON 引号，缺失写"（无）" | N2, N5, CC | High | 用话描述变化并带规则名（"规则 heat-cut：触发温度 30 → 35 °C"）；这个对话框是安全配置的人工关口 | 客户端 |
| SAF-04 (E-39) | 改安全限值只能用 JSON 文本框；首次进入的骨架全是 `null`，页面说"原样提交会被服务器拒绝" | N5, N7, N2 | Medium³ | 按规则分表单（带单位、范围）；首次提供已审定模板；JSON 放高级 | 客户端 |
| SAF-05 (E-40) | "已批准。保护权 7。"（内部计数） | N2 | Low | "已批准，新限值已生效" | 客户端 |

³ E-39 原为 High，下调为 Medium：服务器会拒绝空骨架（`safety-skeleton.js` 注释写明），且有审批对话框作关口，不会悄悄出错；真正会导致误操作的是对话框读不懂（SAF-03，保持 High）。

### 3.9 告警

| 编号 | 现在用户看到的 | 违反的标准 | 严重程度 | 建议改法 | 改在哪 |
|---|---|---|---|---|---|
| ALT-01 (S-01) | "Stage st_ab12 is recovery_check after disconnect_affects: {\"reasons\": [\"due_action\", \"gap_too_long\"], \"seconds\": 412.6, \"state_unreadable\": false}"（`runtime.py:176-184` 用 `json.dumps` 拼出） | N2, N9, CC, PD | High | 告警带 code＋params（状态、事件、原因列表、分钟数）；控制台用 `state.*`、新 `event.*` 标签拼句，再加一句"打开阶段页，记录一次现场检查" | 服务器文案（code/params）＋客户端 |
| ALT-02 (S-02) | 水泵看门狗：五段文字（`watchdog.py:25-41`）里有 "interlock"、"outlet mode"、"unexpected_watering" 一类词，没有一段说操作员该做什么 | N2, N9, CC | High | 每段一个码（`pump_unexpected_on`、`pump_off_unconfirmed` 等）；加"请到现场检查水泵，然后记录现场检查"；去掉内部词 | 服务器文案；客户端映射 |
| ALT-03 (S-03) | 阶段过程检查：测量 id、任务 id、`kind`/`metric` 枚举值出现在文字里；这组告警本身最好（说了怎么做，格式化了时间） | N2, N6, CC | Medium | 把 `kind`、`task_id`、`metric` 作为参数，用任务页的标签写"每日浇水（09:00 到期）" | 服务器文案（params）＋客户端 |
| ALT-04 (S-04) | "temperature > 30 for 300 s (heat_high)"：原始传感器键、运算符、规则 id，无单位，无动作 | N2, N9, CC | Medium | 传传感器、运算、值、单位、持续、规则名；渲染"空气温度高于 30 °C 持续 5 分钟"，加"检查生长室" | 服务器文案＋客户端 |
| ALT-05 (S-05) | "No usable humidity data; threshold alerts for it are suspended"：传感器键原样，无动作 | N2, N9 | Medium | 传 `sensor`，加标签，加"检查传感器连接" | 服务器文案＋客户端 |
| ALT-06 (S-06) | "temperature has reported exactly 24.5 without change (frozen reading)"：无单位，没说后果（阶段可能暂停），无动作 | N2, N9 | Medium | 传传感器、值、单位；加"检查传感器" | 服务器文案＋客户端 |
| ALT-07 (S-07) | 异常类名和原始异常当告警正文："capture: ValueError: …"、"Backup failed: OSError: [Errno 28] No space left on device"、"Model roles are off: AuthenticationError: …"（`observer/service.py`、`runtime_backup.py:72` 等） | N2, N9, CC | High | 每个码一条固定人话（"备份失败，请检查磁盘剩余空间"）；异常文本放日志或"技术详情" | 服务器文案；客户端折叠 |
| ALT-08 (S-08) | "Run health failing: capture, ingest"（探针名） | N2, N9, CC | Medium | `failures` 作为列表，映射成"读数没有进来"，加动作 | 服务器文案＋客户端 |
| ALT-09 (S-09) | "No backup_dir is configured…"、"GROWBRIDGE_HEARTBEAT_HOST_URL and GROWBRIDGE_HEARTBEAT_RUN_URL"：配置键和环境变量名给操作员看，操作员无法处理 | N2, N9 | Medium | 前半句保留人话（"备份没有设置"）；配置名另起一行写给管理员 | 服务器文案 |
| ALT-10 (S-10) | "task_8f21: RuntimeError: …"、"model task task_8f21 needs attention"（`runtime_agents.py:128-154`）：任务 id 取代任务内容，带异常文本，无动作 | N2, N6, N9 | High | 传 `task_id`、`role`、问题标题："规划助手没能完成第 2 轮运行单。请打开任务并决定" | 服务器文案（params）＋客户端 |
| ALT-11 (S-11) | 审计发现把模型写的摘要和证据行用换行拼进一个单元格；类型 `audit_finding` 原样显示 | N2, N8, PD | Medium | 摘要和证据分字段，证据用列表；类型标"审计备注"；文字质量取决于 RND-17 | 客户端＋模型提示词 |
| ALT-12 (R-36) | 告警表里写 "Read by Ana, …; still raised at …, so it is asked about again"、"read before the severity read was recorded; mark it read again"（记账规则）；"次数"列；三个时间列加消息；不链到受影响对象 | N2, N8, N6 | Medium | 每行一个状态："未读"/"Ana 10:02 已读"/"已读，但情况变糟：请再读一次"；链到阶段或传感器 | 客户端 |
| ALT-13 (R-37) | 告警页把 `message` 原样放出，kind 和 key 在这页不显示 | CC, N2 | Medium | 服务器发消息码加参数，客户端映射（与 ALT-01 至 ALT-10 同一修法） | 服务器文案 |

### 3.10 证据

| 编号 | 现在用户看到的 | 违反的标准 | 严重程度 | 建议改法 | 改在哪 |
|---|---|---|---|---|---|
| EVI-01 (R-42) | 卡片标题是 `card.id`（等宽字体）加状态药丸，结论在下面；"录入人 {source}" 打印原始 `source`（可能是模型角色或 id）；元数据是一条 " · " 串 | CC, N8, N2 | Medium | 结论做标题，id 小字；`source` 映射成"你/规划助手…"；字段分开显示 | 客户端 |
| EVI-02 (R-43) | 核验表单"我保证已用本地测量校准过"默认选"否"；按钮只写"核验"；操作点上没有说卡片核验后不可改 | N5, N10 | Medium | 确认对话框写明后果；改成勾选框措辞 | 客户端 |

### 3.11 计算

| 编号 | 现在用户看到的 | 违反的标准 | 严重程度 | 建议改法 | 改在哪 |
|---|---|---|---|---|---|
| CMP-01 (R-19) | 阶段 `failed`、`cancelled` 在目录里没有 `state.*` 文字（`compute/phases.py` 定义了这两个）；药丸在中文页打印英文原词，落进无色的"其他"组 | CC, N4, N1 | Medium | 加 `state.failed`、`state.cancelled` 并分组；未知状态显示"未知状态"，值放 title | 客户端 |
| CMP-02 (R-38) | 预算表单要手动输入任务 id（"任务"文本框），而上面的预算表正列着这些任务 | N6, N5 | High | 下拉选择已知任务，或在行上加"修改预算" | 客户端 |
| CMP-03 (R-39) | "CPU 小时（已用、预留 / 预算）"单元格 "1.00, 2.00 / 10.00"；表里有 `attempt_id`、`template_id`、"远程任务" id | N2, N6, CC | Medium | "已用 1.0 小时，预留 2.0 小时，共 10 小时"或进度条；id 放详情 | 客户端 |
| CMP-04 (R-40) | 卡住的尝试：`reason` 列打印服务器原文；结算说明 "It is charged as unknown use, and this cannot be undone" | N9, N2 | Medium | 服务器发原因码；用预算语言说明后果（保留必填原因和确认框） | 服务器文案 |
| CMP-05 (R-41) | "从 MyCSC 读取后在下面输入"，假设读者知道 MyCSC | N10 | Low | 说明去哪里找（链接或一步说明） | 客户端 |

### 3.12 登录与框架

| 编号 | 现在用户看到的 | 违反的标准 | 严重程度 | 建议改法 | 改在哪 |
|---|---|---|---|---|---|
| FRM-01 (E-24, R-35) | 每个时间格都是 "2026-11-20 10:00 UTC"/"…Europe/Helsinki"（告警表一行三个）；`formatTime` 里 `void lang`，中英文同一格式；任务表里折成两行 | N2, N8 | Low | 区域只在页头说一次；按语言格式（"11月20日 10:00"）；近期用相对时间 | 客户端 |
| FRM-02 (E-41, R-53) | 没有文字时显示 key（`inbox.kind.<新>`、`report.labels.<x>`、`tasks.status.xyz`）或原值（`state.xxx`） | CC, N2, N9 | Low | 一个 `labelOr` 函数，永不打印 key；目录覆盖测试 | 客户端 |
| FRM-03 (R-50) | "页面无法加载。" 后面跟原始 JS 错误信息 | N9, CC | Low | 原因放"详情" | 客户端 |
| FRM-04 (R-51) | 侧栏"入口：现场（实验室网络）/远程/未知"，不说为什么重要（有些操作只能在现场，如浇水） | N10, N2 | Low | 提示"有些操作只能在现场做" | 客户端 |
| FRM-05 (R-52) | 登录框叫"口令（Secret）"；锁定提示"一段时间"，而拒绝文案里写的是 15 分钟 | N4, N9 | Low | 用站点自己的叫法（"密码"）；写出锁定时长 | 客户端 |
| FRM-06 (S-38) | "for 300 s"、"seconds: 412.6"、"600 s between irrigations"、"a 20 s pump run" | N2 | Low | 控制台统一 `formatDuration()`；服务器侧文字超过 120 秒就换成分钟 | 客户端＋服务器文案 |

### 3.13 错误信息

| 编号 | 现在用户看到的 | 违反的标准 | 严重程度 | 建议改法 | 改在哪 |
|---|---|---|---|---|---|
| ERR-01 (R-46, S-19, E-42) | 已知错误码：映射好的说明和建议后，还多一行服务器英文原话（`errorLines` 在 message ≠ code 时追加），带 id、枚举值和 "light.level 3 != 5"、"stage st_91c2 is recovery_check; it cannot pause"。没有映射的码或 404 没有码：显示"请求没有成功"加 "HTTP 404"、"Failed to fetch" | N2, N9, CC, PD | High | 第三行只放进"详情"；404 无码时写"没有找到这一项，可能已被删除"；每个服务器码在目录里有条目 | 客户端（PD）＋服务器文案（params） |
| ERR-02 (R-45) | JSON 编辑器里对不到字段的错误显示成 `protocol › treatments › 0 › id: Field required`（服务器路径加英文消息，`forms.js:207`） | N9, CC | High | 把常见路径映射成人话（"处理 1 缺少 id"）；表单化（P-02）后基本消失 | 服务器文案（及客户端映射） |
| ERR-03 (S-20, S-22, R-47) | `state` 一个码覆盖 98 处 `Denied("state", …)` 和 29 处 `Denied("scope", …)`（未知项目、阶段状态不对、版本过旧、轮次已交付、尝试已终结……），只显示一句泛泛的说明；`approval_invalid` 的建议永远是"处理运行单上的问题"，即使原因是"device capabilities changed"、根本没有检查项；术语："写入权"、"recovery number"、"请用新的请求编号"（用户从未见过编号） | N9, N2, ISO 自描述性 | High | 在 `code` 旁加 `reason` 子码（`stage_not_pausable`、`run_sheet_too_old`、`capabilities_changed`、`round_already_delivered`…），先映射子码，`state` 作兜底；重写面向操作员的文字 | 服务器文案（子码）＋客户端 |
| ERR-04 (S-21) | "irrigation must run for more than 0 and at most 120 s"、"the pump needs 600 s between irrigations"、"write right 14 is from an earlier recovery"、"no live BLE connection" | N2, N9 | Medium | ERR-01 修好后默认不显示；需要数字的地方发参数，写"再等 8 分钟" | 服务器文案（params）＋客户端 |
| ERR-05 (S-23) | "limit must be one of ['a', 'b']"、"n_iter outside 1..1000"、"need 4.0, available 1.2"：参数键、Python 列表、预算数字无单位 | N2, N9 | Medium | 传 `field`、范围、单位；用模板字段标题 | 服务器文案（params）＋客户端 |
| ERR-06 (S-24) | "…(architecture doc §6.5)"、"snapshot file differs from manifest: samples.jsonl"、"script differs from the hash in the protocol" | N2, N9 | Medium | 去掉文档章节号；文件名放详情 | 服务器文案 |
| ERR-07 (S-25) | 文字里是状态原词："stage st_91c2 is recovery_check"、"round is stage_review"；控制台已有 `state.*` 标签 | N2, CC | Medium | 传 `state` 作参数，写成"阶段正在等待现场检查" | 服务器文案（params）＋客户端 |
| ERR-08 (S-26) | 不带码的 HTTP 错误："Unknown request id"、"Authentication required"、"Browser origin is not allowed"、"Device writes go through the workbench"（`api.py:78-115,266`、`workbench/api.py:436,470,505`、`rounds.py:158-163`） | N9, CC | Medium | 各给一个码（`unknown_request`、`not_signed_in`、`origin`、`use_workbench`），在 `denials.js` 加行 | 服务器文案（加码）＋客户端 |
| ERR-09 (R-48) | `budget` 的建议 "Stop. An operator should set or raise the budget…" 是对操作员本人说的 | N9 | Low | 面向读者："请在项目的预算区设置预算"，附链接 | 客户端 |

---

## 4. 保留

三份审计的"保留"清单合并、去重后（括号里是来源）：

**审批与确认**
- 审批比较的是实际审阅的那份摘要，先重读再比对，拒绝时有标题（"未审批"、"已审批，但不是你审阅的那份运行单"）；审批按钮置灰时当场写原因（`pages/stage-actions.js:112-141`）（E）。
- 停止、接管、交还、安全审批有确认框，点名阶段和后果；取消、结算的确认框"取消"在前并聚焦；结算要必填原因；中止说明"无法重新开始"（E、R）。
- 证据"核验"是单独的有意动作，有"未核验"状态；录入时校准默认留空（R）。

**状态与提示的诚实措辞**
- "等待设备确认 / 已生效 / 结果未知 / 暂无结果"，"没有收到答复，结果未知"，带时长的陈旧读数提示，"刷新失败，下面显示的内容可能已过时"横幅（E）。
- 回执状态映射（`receipts.js` OUTCOMES 和 `receipt.*`）：`receipt.unknownNote` 说明下一步，请求 id 仍可追溯（S、E）。
- 状态药丸有译名和颜色分组；阶段和轮次状态在所有药丸里都走 `state.*`；告警严重程度是映射后的药丸；告警 `event_id` 不显示（E、S）。
- 读数不跨空档画线，孤立点照常显示（E）。
- 预算未设时的提示说明后果（"无法调用模型"）；空状态带下一步；未配置的服务有平实提示（`not-mounted.js`）（R）。

**目录与文案**
- `denials.js`：`Denied(` 抛出的 33 个码全部映射，另有 4 个客户端码，每个都有中英文说明和"该怎么办"；唯一漏网的是不带码的 `HTTPException`（S）。
- `research/notes.py`：稳定的 `code` + `params` + `text.en/zh`，随报告保存，按观看者语言显示。这是推广到告警和检查结果的模板（S、R）。
- `observer/stage_checks.py` 的文字已说明怎么做（"Record it as done or skipped"）并按运行单时区格式化时间（S）。
- 水泵规则检查项（`validate.py:62-70`）和看门狗 `UNCONFIRMED_TEXT` 把原因和影响放在一句里（S；注意看门狗文字缺"下一步"，见 ALT-02）。
- 报告的"为什么是这个标签"和编码好的说明用控制台语言显示；缺的可选值显示破折号（R）。

**结构与交互**
- 收件箱按紧急程度分组，有现场/等待的色调，"每 15 秒更新"一行，陈旧警告，重绘时保持焦点（R）。
- 草稿在会话丢失时保留，并有"草稿已恢复"提示；`singleFlight` 防重复提交（`intents.js`）（R）。
- 聊天里提示"这里说的任何话都不会批准运行单"；工具输入/输出默认折叠；长任务问题截断加"展开"（`questionCell`）（R）。
- 离开现场入口的浇水按钮置灰并写原因（`irrigationGroup`）（E）。
- 运行单 JSON 放在 `<details>` 后面：这是应推广到 id 和摘要的披露模式（E）。
- 环境页：传感器格有单位，"预期 vs 实际"行带不一致药丸，窗口选择有 `aria-pressed`（E）。
- 测量只追加的更正，两个方向都有"已被…更正"链接（E）。
- 无障碍基础：跳转链接、有标签的区块、aria-live 提示、可聚焦的滚动区、`aria-current`（R）。

---

## 5. 核实记录

**抽查范围：** 33 条原始 High 全部打开代码核对；另核对 11 条存疑的 Medium。共 **44 条**。
结果：**确认 38 条，调整 6 条，丢弃 0 条。**
核实在 `/Users/chenghao/Downloads/spiderfarmer-growbridge-auditor/src/growbridge/` 下进行；"客户端"指 `web/workbench/`。

### 5.1 调整的 6 条

| 原始编号 | 结果 | 说明 |
|---|---|---|
| E-39 | 调整：High → Medium | 代码支持"只有 JSON 文本框"（`pages/safety.js:103-118`），骨架全 `null`（`pages/safety-skeleton.js`）；但服务器会拒绝空骨架，且有审批对话框作关口，不会悄悄出错。真正的风险在 E-38（对话框读不懂），保持 High。 |
| S-02 | 调整：措辞，问题比所述更大 | 审计说"只有 UNCONFIRMED 那条提示动作"。实际 `executor/watchdog.py:25-41` 五段文字里没有一段告诉操作员做什么（UNCONFIRMED 只说"会继续重试"）。仍为 High。所需建议其实已在 `denials.js` 的 `interlock` 条目里，告警本身没有。 |
| R-08 | 调整：原因 | 审计让"提示编排助手用用户语言回答"。实际 `agents/roles.py:59-60` 已有这条规则；缺的是没有任何代码把控制台语言交给模型（`agents/*.py`、`workbench/*.py` 里搜不到 `lang`）。修法改为"把语言传给模型"。仍为 Medium。 |
| S-20 | 调整：规模比所述更大 | 审计写"约 45 处 `Denied("state")`、约 25 处 `Denied("scope")`"。实际在 `src/growbridge` 下是 **98 处**和 **29 处**。结论更强，仍为 High。 |
| S-14 | 调整：引文部分对不上 | 审计引的六条文字里，四条在 `planning/validate.py` 里按字面找到（行 60、154、204、220）；"device has no 'temp_air'"和"sensor 'rh' reports '%'"两条没有按字面找到（可能由别处拼接），表中未再引用。"阻断项没说怎么改"由找到的四条支持；保持 High。 |
| E-03 | 调整：升为 High（合并） | 原为 Medium；与 S-29 合并取 High。核实 `stage-history.js:21-33`：`detailText` 对每个键 `String(value)`，Unix 时间戳和请求 id 原样打印，`SAID_IN_LINE` 只过滤 4 个键；`watchdog.py:96-112` 的载荷里确有 `status_at`、`off_confirmed_at`、`request_id`。 |

另有两处合并后升级，不涉及代码调整：E-08（Medium）并入 S-14 取 High；R-47（Medium）并入 S-20/S-22 取 High。

### 5.2 确认的 High

| 原始编号 | 核对位置 | 结果 |
|---|---|---|
| E-01 / S-27 | `pages/stage-history.js:41,47`；`i18n/zh.js:431` | 确认：只有 `history.event` 包装模板，无 `history.event.<id>`。 |
| E-02 / S-28 | `stage-history.js:30-36` | 确认：键值串，嵌套值 `JSON.stringify`。 |
| E-06 | `pages/stage-actions.js:88-99` | 确认：`h("code", { text: finding.code })`。 |
| E-10 | `stage.js:135-141`；`stage-actions.js:131,133`；`i18n/zh.js:294,309,313` | 确认：摘要默认显示，审批冲突文案带两个摘要。 |
| E-36 | `pages/safety.js:15-25` | 确认：`${row.trigger.op} ${row.trigger.value}`、`String(row.duration_seconds)`。 |
| E-38 | `pages/safety-diff.js:22-24` | 确认：`change.path` 加 `formatValue`。 |
| R-01, R-02 | `pages/round.js:77-116`；`agents/handlers_report.py:69-81`；`agents/roles.py` | 确认：模型写的 `limitations`、`unresolved`、`next_round` 以 `String(item)` 或 `<p>` 原样渲染；提示词没有写作规则。 |
| R-13 | `pages/inbox.js:77-112` | 确认：`ctx.t("inbox.stage", { id: item.id })` 等。 |
| R-20 | `pages/round.js:132-141`；`main.js:150-156` | 确认：面包屑和标题用 `round_id`，默认面包屑也用 id。 |
| R-24 | `pages/round-analysis.js:23-121` | 确认：每个轮次渲染；协议版本、"已开始：是/否"、快照选择。哈希和 stdout/stderr 的渲染行未逐行读，按审计。 |
| R-25 | `round-analysis.js:50-59` | 确认：`jsonEditor`，初值 `{ project_id, script: "" }`。 |
| R-26 | `round-analysis.js:61-76` | 确认：`runForm` 没有确认（`round-analysis.js`、`evidence.js` 中都搜不到 `confirmAction`）。 |
| R-28 | `pages/project-forms.js:7-33,66-75`；`archive/models.py:419-436` | 确认：预填 JSON；`question: str` 无约束，空问题可保存。 |
| R-29 | `project-forms.js:77-97`；`pages/conversation.js:132` | 确认：两个 JSON 编辑器；对话也 POST `/goals`，重复成立。 |
| R-38 | `pages/compute.js:56-68` | 确认：`task_id` 文本框。 |
| R-45 | `ui/forms.js:201-207` | 确认：`loc.filter(...).join(" › ") + ": " + msg`。 |
| R-46 / S-19 | `ui/forms.js:57-63` | 确认：`message !== code` 时追加第三行；无码时 `[error.title, message]`。 |
| S-01 | `runtime.py:176-184` | 确认：`json.dumps(detail, sort_keys=True)`。 |
| S-07 | `observer/service.py:106-125`；`runtime_backup.py:68-72`；`runtime.py:386-392` | 确认：`f"Backup failed: {type(error).__name__}: {error}"`、`f"{name}: {type(error).__name__}: {error}"`。 |
| S-10 | `runtime_agents.py:124-156` | 确认：`f"{task.id}: {type(error).__name__}: {error}"`、`"model task {task.id} needs attention"`。 |
| S-13 | `stage-actions.js:95-97` | 确认（同 E-06）。 |
| S-22 | `workflow/service.py:244-250,296-310`；`denials.js:18` | 确认：能力变化走 `Denied("approval_invalid", problem)`，建议却是"处理运行单上的问题"。 |
| S-28 / S-29 | `executor/engine.py:280-296`；`executor/watchdog.py:96-112` | 确认：载荷里有 `right_number`、`seconds`、`status_at`、`off_confirmed_at`、`request_id`。 |
| S-31 | `agents/handlers_report.py:69-81` | 确认：四个自由文本字段由模型填写。 |
| S-34 | `agents/roles.py:44-150` | 确认：语言规则只有 59-60（编排）和 128（审计）；规划、研究员没有；没有"平实、不写字段名"的规则。 |

### 5.3 确认的 Medium（抽查 11 条，含上面已列的 R-08）

- E-09：`stage.js:132` 用 `formatNumber(seconds / 3600, 1)`，`stage.review.durationValue` 是 "{hours} 小时"。
- E-24：`format.js:45-46` 里 `void lang`。
- E-26、E-27：`stage-tasks.js:108-111`，按钮标签是状态词，已完成行仍显示"跳过"。
- E-42：`forms.js:57-63`，无映射码显示 `error.title` 加原消息。
- R-11：`conversation.js:74-83`，`select.value = open[0].round_id`，文字是原始 id。
- R-19：`i18n/zh.js` 无 `state.failed`/`state.cancelled`；`compute/phases.py` 定义了两者。
- R-22：`round.js:11` `CHOICES = ["redo", …]`；`forms.js:119-126` 无占位，首项被选中。
- R-30：`project.js:46-47` 用 `String(budget.cost_left)`。
- S-26：`api.py:78,89,96,100,115,266` 的裸字符串 `HTTPException`。

### 5.4 未逐条核对的部分

其余 Medium 和 Low 没有逐条打开代码，保留审计的原样。我读到的相邻代码与审计引用没有矛盾。
截图证据（`docs/images/example-round/*`）没有重新查看，只按审计转述。

---

## 6. 第一批结果

第一批覆盖 73 行：61 行全部完成，12 行部分完成。计划里写的“74 行、其中 65 行整行”是数错了：清单实际是 64 行整行加 9 行只做客户端部分，共 73 行，下表逐行核对过。
状态：`已改`；`部分（…，第 N 批）`，写明已做和未做；`关闭：无法复现`（本批没有这样的行）。证据是钉住这条改动的测试文件和测试名（均在 `tests/web/`），没有测试的行直接说明。截图列留给 Task 19 填写。

截图：改造前后的对照图（每页中英文、1440 与 375 两种宽度，`<页面>-<zh|en>-<1440|375>.jpg`）由开发工作台加 2026-11-15 实跑数据生成，未进仓库，已发给用户。375 宽下所有页面（含展开全部折叠后）都没有横向滚动。

| 编号 | 状态 | 证据 | 截图 |
|---|---|---|---|
| INB-01 | 已改 | `shell.test.mjs`「a stage waiting for review is titled by names」；`shell.test.mjs`「an old stage item falls back to the generic names」；`shell.test.mjs`「the other stage kinds and round choice and compute are titled by names」；`shell.test.mjs`「each item's ids go into its own technical details」；`shell.test.mjs`「a round choice names no stage id and keeps it in the item's details」；`shell.test.mjs`「the simulator reads as a simulated device; any device id stays in the item's details」；`shell.test.mjs`「an inbox item with an unknown state keeps the code in its details and no fold inside its link」 | `inbox-*.jpg` |
| INB-02 | 已改 | `shell.test.mjs`「an alert kind shows its label; an unknown kind says unknown」 | `inbox-*.jpg` |
| INB-03 | 已改 | `shell.test.mjs`「the waiting time is a duration with the exact time in the title」；`time-display.test.mjs`「timeCell is relative within a day, absolute otherwise and for the future」；`shell.test.mjs`「a poll with unchanged data still moves the waiting times on and leaves the rows alone」；`shell.test.mjs`「the waiting time counts whole seconds, never tenths」 | `inbox-*.jpg` |
| INB-04 | 已改 | `shell.test.mjs`「a task item is titled by its question and shows the owner role」；`shell.test.mjs`「an open fold stays open across a redraw of the same item」 | `inbox-*.jpg` |
| INB-05 | 已改 | `shell.test.mjs`「the 'more' line links to the full list」；`shell.test.mjs`「inbox counts include what the server cut」 | `inbox-*.jpg` |
| INB-06 | 已改 | `shell.test.mjs`「a task item is titled by its question and shows the owner role」 | `inbox-*.jpg` |
| INB-07 | 已改 | `shell.test.mjs`「each inbox kind links to its page」；`shell.test.mjs`「each alert row has an id and the focused one is highlighted」；`shell.test.mjs`「alerts page survives a hostile or unknown focus and highlights nothing」；`router.test.mjs`「the router passes focus to the alerts page」 | `inbox-*.jpg` |
| P-01 | 已改 | `project-page.test.mjs`「the projects list has no id column and names the latest round」 | `projects-*.jpg` |
| P-04 | 部分（已改：数字无浮点误差；未改：“已用 / 共”要服务器给预算的已用量读字段，第二批） | `project-page.test.mjs`「budget numbers carry no float noise」 | `project-*.jpg` |
| P-05 | 已改 | `project-page.test.mjs`「the project page puts the conversation and rounds first, then tasks, protocols, budget and holdouts」；`project-page.test.mjs`「the four editors are closed folds titled Edit…」；`project-page.test.mjs`「an editor that brings back an unsent draft opens by itself」 | `project-*.jpg` |
| P-06 | 已改 | `project-page.test.mjs`「the task table names the owner role」；`leaks.test.mjs`「no Batch 1 page leaks internal text」（项目页） | `project-*.jpg` |
| P-07 | 已改 | `project-page.test.mjs`「holdouts keep their id in the details and say how often they were read」 | `project-*.jpg` |
| P-08 | 已改 | `project-page.test.mjs`「saving the budget, a goal or a holdout says what was saved」；`project-page.test.mjs`「a new project is announced by its name」；`project-page.test.mjs`「compute, round and analysis writes say what was done」；`project-page.test.mjs`「every new save notice exists in both languages」 | `project-*.jpg` |
| P-10 | 已改 | `conversation.test.mjs`「adjacent tool calls fold into one group」；`conversation.test.mjs`「several tool calls in a row fold into one line that counts them」；`conversation.test.mjs`「one tool call reads as what it did; its name, input and result are in the details」；`conversation.test.mjs`「the captured conversation shows no tool name, input or result outside the details」 | `project-*.jpg` |
| P-11 | 部分（客户端已改：状态句和未知状态的标签；未改：原因码 reason_code 由服务器发，第二批） | `conversation.test.mjs`「a status line says who ended and how; the server's reason is not part of it」；`conversation.test.mjs`「a status entry keeps the raw reason in the details」；`catalog.test.mjs`「a pill for a state or severity the catalog lacks says unknown, not the code」 | `project-*.jpg` |
| P-12 | 已改 | `conversation.test.mjs`「the round picker starts at no round and names rounds」；`conversation.test.mjs`「a message can only be about an open round, newest first as listed」 | `project-*.jpg` |
| P-13 | 已改 | `conversation.test.mjs`「a sent message shows a pending line until its own task answers」；`conversation.test.mjs`「the hint under the message box is one sentence」 | `project-*.jpg` |
| RND-01 | 已改 | `names.test.mjs`「round page title and crumbs carry no id」；`names.test.mjs`「an old round without number or project name shows generic words」 | `round-*.jpg` |
| RND-02 | 已改 | `round-report.test.mjs`「the summary names the project and the protocol version, and lists no snapshot or report id」 | `round-*.jpg` |
| RND-03 | 已改 | `round-report.test.mjs`「stages are linked by name, and the stopped stage is named in the choice」 | `round-*.jpg` |
| RND-05 | 已改 | `round-report.test.mjs`「the analysis block is folded by default」；`round-report.test.mjs`「the analysis says where it stands in one word」；`round-report.test.mjs`「snapshots are named by date and completeness, their ids in the details」；`round-report.test.mjs`「a frozen script keeps its fingerprint and text in folds」；`round-report.test.mjs`「a run's id, exit code and output are in the details; its status is a word」 | `round-*.jpg` |
| RND-08 | 已改 | `round-report.test.mjs`「a round planned on an older version says the analysis is not for it」；`research-pages.test.mjs`「the analysis block says when the protocol's latest version is not the round's」 | `round-*.jpg` |
| RND-09 | 部分（客户端已改：局限折叠（显示三条，其余折起），服务器自己的说明在前；未改：模型写的局限里的英文、epoch 秒和字段名，第三批） | `round-report.test.mjs`「limitations show three and fold the rest」；`round-report.test.mjs`「the server's own limitation notes come before the model's and stay in view」 | `round-*.jpg` |
| RND-10 | 部分（客户端已改：条目与下一轮用简单排版（富文本）；未改：模型措辞，第三批） | `round-report.test.mjs`「report items and the next round keep the model's light markup」；`rich-text.test.mjs`「paragraphs, lists and headings are told apart; wrapped lines stay together」 | `round-*.jpg` |
| RND-11 | 部分（客户端已改：效应取整、说明 p 值含义、没有估计时说原因；未改：note_code 由服务器发，第二批；缺指标名，需要报告里带协议的终点，第二批） | `round-report.test.mjs`「an estimate reads as effect, p value and blocks, or says why there is none」；`round-report.test.mjs`「estimateText rounds the effect」；`round-report.test.mjs`「an estimable effect says what its p value means」；`round-report.test.mjs`「server notes follow the console language; old reports keep their plain text」；`round-report.test.mjs`「a large effect and a tiny p value are written without an exponent, in the page's language」 | `round-*.jpg` |
| RND-12 | 已改 | `round-report.test.mjs`「the report shows a short fingerprint and keeps ids in the details」；`round-report.test.mjs`「a report answer without its own id keeps the round's report id in the details」 | `round-*.jpg` |
| RND-13 | 已改 | `round-report.test.mjs`「the report shows a short fingerprint and keeps ids in the details」 | `round-*.jpg` |
| RND-14 | 已改 | `round-report.test.mjs`「every label and conclusion the server writes has a text」；`round-report.test.mjs`「each label says under it what it allows」；`round-report.test.mjs`「a missing label or conclusion says 'not stated'」；`round-report.test.mjs`「a label or conclusion the catalog lacks is 'unknown', its code in the details」 | `round-*.jpg` |
| RND-15 | 已改 | `round-report.test.mjs`「report items and the next round keep the model's light markup」 | `round-*.jpg` |
| RND-20 | 已改 | `round-report.test.mjs`「a report that could not be read shows the plain lines and folds the server's words」；`error-folds.test.mjs`「a refused chat message keeps the server's words in the fold under the plain lines」 | `round-*.jpg` |
| STG-01 | 部分（客户端已改：检查结果按代码显示为标签并换行；未改：句子和参数（findings 的 params）由服务器发，第二批） | `run-sheet-review.test.mjs`「finding codes are shown as labels with counts, never as code」 | `stage-pending-*.jpg`、`stage-ended-*.jpg` |
| STG-02 | 部分（客户端已改：阻断项在前，按代码分组并带条数；未改：怎么改的说明文字由服务器发，第二批） | `run-sheet-review.test.mjs`「blocking findings come first, grouped by code with counts」；`run-sheet-review.test.mjs`「a code seen first as a hint and later as blocking is grouped by both」 | `stage-pending-*.jpg`、`stage-ended-*.jpg` |
| STG-07 | 已改 | `run-sheet-review.test.mjs`「the review shows days, a short fingerprint, a version and a simulated device」 | `stage-pending-*.jpg`、`stage-ended-*.jpg` |
| STG-08 | 已改 | `run-sheet-review.test.mjs`「the review shows days, a short fingerprint, a version and a simulated device」；`format.test.mjs`「shortDigest keeps eight characters」；`run-sheet-review.test.mjs`「every label of the run sheet's hash calls it a fingerprint, never a digest」；`stage-status.test.mjs`「an approval of another run sheet than the one reviewed keeps both digests folded and sends the reviewed one」 | `stage-pending-*.jpg`、`stage-ended-*.jpg` |
| STG-09 | 已改 | `run-sheet-review.test.mjs`「the review shows days, a short fingerprint, a version and a simulated device」 | `stage-pending-*.jpg`、`stage-ended-*.jpg` |
| STG-10 | 已改 | `names.test.mjs`「stage page title and crumbs carry no id」；`leaks.test.mjs`「a stage read from before stages had names is called an unnamed stage」 | `stage-pending-*.jpg`、`stage-ended-*.jpg` |
| STG-11 | 已改 | `stage-status.test.mjs`「status hides empty rows and keeps write rights in the details」 | `stage-pending-*.jpg`、`stage-ended-*.jpg` |
| STG-12 | 已改 | `stage-status.test.mjs`「status hides empty rows and keeps write rights in the details」；`stage-status.test.mjs`「a pending end shows a banner and a pause time shows its row」 | `stage-pending-*.jpg`、`stage-ended-*.jpg` |
| STG-13 | 已改 | `run-sheet-review.test.mjs`「pending review puts the run sheet before the controls; running puts readings first」；`run-sheet-review.test.mjs`「the pending stage page lists the run sheet before the controls」；`run-sheet-review.test.mjs`「a page refreshed with a running stage rearranges its regions」 | `stage-pending-*.jpg`、`stage-ended-*.jpg` |
| STG-18 | 已改 | `stage-status.test.mjs`「a log item says when it was sent and keeps the request id in the details」；`stage-status.test.mjs`「a resent write is said so in a line under the heading, not in it」；`stage-status.test.mjs`「receipt outcomes write levels, durations and no request id」 | `stage-pending-*.jpg`、`stage-ended-*.jpg` |
| STG-19 | 已改 | `stage-status.test.mjs`「a level is written against its full scale」；`stage-status.test.mjs`「receipt outcomes write levels, durations and no request id」；`format.test.mjs`「levelText writes value over full scale」 | `stage-pending-*.jpg`、`stage-ended-*.jpg` |
| STG-21 | 已改 | `stage-status.test.mjs`「hand-back differences use labels and units」 | `stage-pending-*.jpg`、`stage-ended-*.jpg` |
| HIS-01 | 已改 | `stage-history.test.mjs`「events read as sentences and same-state moves show no pills」；`stage-history.test.mjs`「an unknown event says unknown and keeps the code in the details」 | `stage-ended-*.jpg` |
| HIS-02 | 已改 | `stage-history.test.mjs`「durations, times and reasons are written for people; raw values go to the details」；`stage-history.test.mjs`「differences read as sentences」；`stage-history.test.mjs`「free-text reasons and unknown keys stay in the details」；`stage-history.test.mjs`「an empty list of differences or reasons gives no line; the original detail still holds it」 | `stage-ended-*.jpg` |
| HIS-03 | 已改 | `stage-history.test.mjs`「unexpected watering shows labelled times, not epoch seconds」 | `stage-ended-*.jpg` |
| HIS-04 | 已改 | `stage-history.test.mjs`「events read as sentences and same-state moves show no pills」；`stage-history.test.mjs`「a move between two states shows both pills」 | `stage-ended-*.jpg` |
| HIS-05 | 已改 | `stage-history.test.mjs`「newest first; a transition and an intervention of the same second keep a fixed order」；`stage-history.test.mjs`「beyond twenty entries the newest stay on top and the rest fold away」 | `stage-ended-*.jpg` |
| TSK-01 | 已改 | `stage-tasks.test.mjs`「the task table has no task-id column and verbs on its buttons」；`stage-tasks.test.mjs`「recording a task names it, not its id」 | `stage-ended-*.jpg` |
| TSK-02 | 已改 | `stage-tasks.test.mjs`「the task table has no task-id column and verbs on its buttons」 | `stage-ended-*.jpg` |
| TSK-05 | 已改 | `stage-tasks.test.mjs`「the lead is one sentence and the scoring rules fold away」 | `stage-ended-*.jpg` |
| TSK-06 | 已改 | `measurements.test.mjs`「the measurement table shows six columns and folds the rest」；`measurements.test.mjs`「each row's details tell its corrections by time and keep the ids」 | `stage-ended-*.jpg` |
| TSK-07 | 已改 | `measurements.test.mjs`「the metric, unit and method fields suggest what this stage already recorded」；`measurements.test.mjs`「the form's lead names no experiment id and corrects stays hidden」；`measurements.test.mjs`「Correct fills the form from the row and says which record it corrects」；`measurements.test.mjs`「a refused correction names the corrected record, not the field」；`measurements.test.mjs`「a correction whose time was not touched sends the original epoch, seconds and all」；`measurements.test.mjs`「a correction whose time was changed sends the new minute」 | `stage-ended-*.jpg` |
| ENV-01 | 已改 | `environment.test.mjs`「the fan shows its full scale and the pump its plan」；`environment.test.mjs`「channel levels are read where the device reports them」 | `environment-*.jpg` |
| ENV-02 | 部分（已改：坐标轴、最小跨度、数据表；未改：运行单目标带，需要服务器给运行单读字段，第二批） | `chart-math.test.mjs`「paddedRange widens a narrow range around its middle」；`chart-math.test.mjs`「every sensor has a minimum span in its own unit」；`chart-math.test.mjs`「a fixed domain scales a series against it」；`chart.test.mjs`「the chart has tick labels, one status line and a data table」；`chart.test.mjs`「a level chart is drawn against the channel's full scale」 | `environment-*.jpg` |
| ENV-03 | 已改 | `chart.test.mjs`「the chart has tick labels, one status line and a data table」；`chart.test.mjs`「time labels take the year from the page clock」；`environment.test.mjs`「a live refresh keeps open folds open and closed ones closed」 | `environment-*.jpg` |
| SAF-01 | 已改 | `config-pages.test.mjs`「a rule reads as one sentence」；`config-pages.test.mjs`「a rule unit C is shown as °C and the English sentence reads too」；`config-pages.test.mjs`「a rule's duration and validity say the exact seconds when the words round them」 | `safety-*.jpg` |
| SAF-02 | 已改 | `safety-frozen.test.mjs`「frozenRows lists the sensors in name order」；`config-pages.test.mjs`「dialog lines write durations, levels, frozen limits and gaps as words」 | `safety-*.jpg` |
| SAF-03 | 已改 | `config-pages.test.mjs`「the approval dialog describes changes by rule and unit」；`config-pages.test.mjs`「deleting or reordering rules never names the wrong rule」；`config-pages.test.mjs`「an unknown code is listed raw, and so is every path without the rules」 | `safety-*.jpg` |
| SAF-05 | 已改（无专门测试） | 没有测试钉住这一句：`i18n/zh.js` 的 `safety.approved` 在 c3abf7b 改成“已批准，新限值已生效。”；两种语言的键由 `i18n.test.mjs` 检查 | `safety-*.jpg` |
| ALT-12 | 部分（已改：读取状态和时间；未改：指向受影响对象的链接，需要服务器给参数，第二批） | `alerts-page.test.mjs`「the read column says one thing」；`alerts-page.test.mjs`「a read without a recorded severity is not called worse; a day-old read says why it asks again」 | `alerts-*.jpg` |
| ALT-11 | 部分（客户端已改：告警类型“审计备注”的标签，证据行拆成列表；未改：摘要和证据分字段由服务器发，第二批；模型写的摘要措辞，第三批） | `alerts-page.test.mjs`「an alert row has a kind label and splits evidence lines」 | `alerts-*.jpg` |
| EVI-01 | 已改 | `research-pages.test.mjs`「an evidence card is titled by its claim and keeps its id in the details」；`research-pages.test.mjs`「an evidence card entered by the signed-in operator says you」；`research-pages.test.mjs`「an evidence value is shown exactly as entered」；`research-pages.test.mjs`「the verify and enter notices name the card by its claim, cut to 40 characters」 | —（开发工作台没有证据卡和计算数据，未截图） |
| CMP-01 | 已改 | `catalog.test.mjs`「compute phases have labels and colour groups」；`shell.test.mjs`「every state from the plan's table lands in its colour group」 | —（开发工作台没有证据卡和计算数据，未截图） |
| CMP-02 | 已改 | `research-pages.test.mjs`「the change-budget button fills the task field」；`research-pages.test.mjs`「a task reads the same in every table, and a new budget row does not rename another」 | —（开发工作台没有证据卡和计算数据，未截图） |
| CMP-03 | 已改 | `research-pages.test.mjs`「compute usage reads as hours」 | —（开发工作台没有证据卡和计算数据，未截图） |
| CMP-05 | 已改（无专门测试） | 没有测试钉住这一句：`i18n/zh.js` 的 `compute.balance.none` 在 f4fc131 改成说明 MyCSC 在哪里（my.csc.fi）；键由 `i18n.test.mjs` 检查 | —（开发工作台没有证据卡和计算数据，未截图） |
| FRM-01 | 已改 | `time-display.test.mjs`「timeText shows no zone; the sidebar names it once」；`time-display.test.mjs`「timeCell is relative within a day, absolute otherwise and for the future」；`time-display.test.mjs`「a missing zone falls back to UTC and says so」；`format.test.mjs`「formatDateTime follows the language and shows the year only when it differs」 | 全部 `*.jpg`（侧栏与时间） |
| FRM-02 | 已改 | `catalog.test.mjs`「labelOr never prints a key」；`catalog.test.mjs`「no page builds a catalog key from a server value without labelOr」 | 全部 `*.jpg`（侧栏与时间） |
| FRM-03 | 已改（无直接测试） | `main.js` 启动时就运行，测试无法导入，“页面无法加载”的视图没有直接测试；原因进详情用的是 `errorDetail`，由 `forms.test.mjs`「a known refusal shows its explanation and advice; the server's own words go to the details」、`forms.test.mjs`「an unknown code or a plain error shows only the title; its message is a detail」、`tech-details.test.mjs`「errorDetail labels each fact in the page language and leaves out what is missing」和 `tech-details.test.mjs`「an error made by the console has no HTTP status 0 and its text is not called the server's」钉住 | 全部 `*.jpg`（侧栏与时间） |
| FRM-04 | 已改 | `time-display.test.mjs`「the sidebar says why entry matters」 | 全部 `*.jpg`（侧栏与时间） |
| FRM-05 | 已改 | `denials.test.mjs`「the re-authentication and lock-out denials say password, and a lock-out says how long」；`leaks.test.mjs`「the sign-in page and its denials call the secret a password」 | 全部 `*.jpg`（侧栏与时间） |
| FRM-06 | 部分（客户端已改：所有时长统一用 formatDuration，环境页读数的“多久以前”也是；两分钟以内的时长不是整秒时保留一位小数，安全规则的时长按 R18 在取整时补写准确秒数；未改：服务器句子里的“300 s”类文字，第二批） | `format.test.mjs`「formatDuration picks the unit by size」；`stage-status.test.mjs`「the irrigation heading shows a formatted duration」；`format.test.mjs`「formatDuration keeps one decimal in the seconds band when the value is not whole」；`format.test.mjs`「formatAge counts whole seconds: a clock age has no tenths」；`environment.test.mjs`「sensors follow the chart order and units; ages read as every other duration does」；`stage-tasks.test.mjs`「a planned 2.5 s irrigation asks to run the pump 2.5 s, and 0.4 s is not 0 s」 | 全部 `*.jpg`（侧栏与时间） |
| ERR-01 | 部分（客户端已改：服务器原话进“技术详情”，已知错误码只显示说明和建议，没有码的 404 有自己的文字；未改：服务器仍发不带码的句子，需要错误码和参数，第二批） | `tech-details.test.mjs`「errorLines keeps only the human lines; the server text goes to the details」；`tech-details.test.mjs`「errorParts: the plain lines as paragraphs, then the fold with the server's words」；`forms.test.mjs`「a known refusal shows its explanation and advice; the server's own words go to the details」；`tech-details.test.mjs`「an error made by the console has no HTTP status 0 and its text is not called the server's」 | `round-*.jpg`（报告读取失败的提示与折叠） |

注：`leaks.test.mjs` 的“no Batch 1 page leaks internal text”对每个页面的中英文都跑一遍，是所有整行的共同底线（它用 `tests/web/fixtures/` 里抓取的真实读取结果渲染页面，再扫描 id、事件码、epoch 秒、原始载荷和目录键）。

### 6.1 第二、三批待办：泄漏测试的豁免项

`tests/web/support/leak-exemptions.mjs` 里每一条都是页面上仍然原样显示的服务器或模型文字，由对应的批次去掉；`keep` 是操作员自己起的名字，保持原样。

| 页面 | 夹具 | 路径 | 显示方式 | 批次 | 原因 |
|---|---|---|---|---|---|
| stage | run-sheet.json | `findings[*].message` | 原样 | 第 2 批 | 服务器整句（C4，STG-01） |
| stage | run-sheet-pending.json | `findings[*].message` | 原样 | 第 2 批 | 服务器整句（C4，STG-01） |
| stage | measurements.json | `measurements[*].metric` | 原样 | 保留 | 测量指标名由录入人自己填写（TSK-06），照原样显示，也照原样出现在表单的候选和“正在更正”提示里 |
| round | report.json | `report.model_limitations[*]` | 原样 | 第 3 批 | 模型写的文字（C5） |
| round | report.json | `report.unresolved[*]` | 原样 | 第 3 批 | 模型写的文字（C5） |
| round | report.json | `report.next_round` | 原样 | 第 3 批 | 模型写的文字（C5） |
| round | report.json | `report.estimate.note` | 原样 | 第 2 批 | 服务器整句（C4，RND-11） |
| project | conversation.json | `entries[kind=reply].text` | richText | 第 3 批 | 模型写的回复（C5，P-10） |
| project | holdouts.json | `holdouts[*].outcome_fields[*]` | 原样 | 保留 | 结局字段名由操作员登记留出批次时自己填写（P-07），照原样显示 |
| project | project.json | `tasks[*].question` | folded | 第 3 批 | 委派和后续任务的问题是模型写的（C5，P-06）；操作员自己的目标在同一列，本身不含代码 |
| inbox | inbox.json | `items[*].detail.message` | folded | 第 2 批 | 告警正文是服务器整句（INB-01，C4） |
| inbox | inbox.json | `items[*].detail.question` | folded | 第 3 批 | 研究任务的问题是模型写的（C5，INB-01） |
| inbox | inbox.json | `items[*].detail.reason` | 原样 | 第 2 批 | 计算卡住的原因是服务器整句（INB-01，C4） |
| alerts | alerts.json | `alerts[*].message` | 原样 | 第 2 批 | 告警正文是服务器整句（ALT-11，C4） |

### 6.2 其他留到后面的事项

- 草稿运行单的 JSON 编辑器没有被泄漏测试检查（编辑器里本来就是 JSON）；改成结构化表单是第三批（C8）。
- 对话框（确认框、重新认证框）仍不被泄漏测试渲染。带名字的确认文字有单元测试：停止和接管阶段的确认框写阶段名、不写 id（`stage-status.test.mjs`「the stop and take-over dialogs name the stage and never its id」）；轮次中止的问句有测试（`round-report.test.mjs`「the abort question names the round, not its id」），安全审批对话框的变化行也有（`config-pages.test.mjs`「dialog lines write durations, levels, frozen limits and gaps as words」）；其余确认文字没有逐条的测试。
- `visibleText` 跳过隐藏的 textarea 内容，所以文本框里的预填文字（如 JSON 骨架）不在检查范围内。
- `main.js` 在导入时就启动，测试无法导入它；页面清单 `PAGES` 因此放在 `router.js` 并导出，`main.js` 引用它。“页面无法加载”的视图没有直接测试（FRM-03）。

### 6.3 第一批遗留（第二批先处理）

第一批最终审查后留下的小问题，没有在第一批里修（五项都已由第二批 Task 1 处理，证据见 7.3）：

- 安全页的冻结阈值和"最长空档"两行仍用普通的 `formatDuration`（150 秒显示成"3 分钟"）；审批对话框已经显示精确秒数。改成和规则句子一样的精确写法（每处一行）。
- 未知状态旁的技术详情折叠，在环境页状态行（每 5 秒）和阶段页标题药丸（每 15 秒）里会被轮询重建而自动收起；阶段页状态栏里的那一份不受影响。
- 收件箱里未知的条目类型显示"未知（技术详情）"，但条目的折叠里没有那个类型代码。
- 6.2 关于确认文字的说法偏保守：轮次中止的问句和安全审批对话框的变化行其实也有测试。
- `.tech-copy` 的 `user-select: none` 缺少 `-webkit-` 前缀；在没有剪贴板接口的 Safari 上，"复制全部"可能连带复制按钮文字（未在浏览器里验证）。

## 7. 第二批 2a 结果

2a 让服务器给每一类要显示的文字发消息码和参数（八族代码在 `src/growbridge/codes.py`，导出到 `tests/web/fixtures/message-codes.json`），控制台按码拼出句子。本批的 19 个整行都已改，另有 9 个第一批部分完成的行补完。其余部分行（拒绝文字里的时长、不带码的错误句子等）在 2b，模型写的文字在第三批。

状态和证据的写法同第 6 节：证据是钉住这条改动的测试文件和测试名；服务器测试在 `tests/` 下各自的目录，页面测试在 `tests/web/`。截图列：改造后截图（每页中英文、1440 与 375 两种宽度，`<页面>-<zh|en>-<1440|375>.jpg`）由开发工作台加 2026-11-15 实跑数据生成，与第一批的改造后截图并排对照，未进仓库，已发给用户；375 宽下所有页面（展开全部折叠后）都没有横向滚动。“—”表示开发数据里没有这种情况。

“防露出”底线：`tests/web/leaks.test.mjs`「no page leaks internal text」对每个页面的中英文都跑一遍（第 6 节里的“no Batch 1 page leaks internal text”就是它改名前的名字）；「no exemption is left for the second batch」保证 `leak-exemptions.mjs` 里没有第二批的豁免项，6.1 表里“第 2 批”的行因此都已兑现。

### 7.1 整行

| 编号 | 状态 | 证据 | 截图 |
|---|---|---|---|
| ALT-01 | 已改 | `tests/e2e/test_e2e_stage_alerts.py` `test_runtime_alert_passes_code_and_params_through`；`tests/workbench/test_message_codes.py` `test_every_alert_in_the_server_names_a_registered_code`；`alerts-page.test.mjs`「a waiting stage's alert lists its reasons as sentences and links to the stage even when its id has a colon」；`shell.test.mjs`「an inbox alert is titled by its text, not by the server's message」 | —（开发数据里没有这种情况，由页面测试覆盖） |
| ALT-02 | 已改 | `tests/executor/test_watchdog.py` `test_pump_unexpected_off_alert_carries_its_code`、`test_pump_unexpected_interlocked_alert_carries_its_code`、`test_pump_unexpected_failed_alert_carries_its_code`、`test_pump_unreadable_alert_carries_its_code`、`test_pump_watchdog_step_alert_carries_its_code_and_no_error_text`、`test_pump_watchdog_record_alert_carries_its_code`；`alerts-page.test.mjs`「an alert row says what happened and what to do; the server's words are in the details」 | —（开发数据里没有这种情况，由页面测试覆盖） |
| ALT-03 | 已改 | `tests/observer/test_stage_checks.py` `test_task_missed_alert_carries_stage_task_kind_and_due_time`、`test_measurement_missing_alert_carries_the_window_and_timezone`、`test_measurement_outside_window_alert_carries_the_measurement_and_time`；`tests/observer/test_observer_service.py` `test_stage_checks_alert_carries_no_params`；`alerts-page.test.mjs`「an alert row says what happened and what to do; the server's words are in the details」 | —（开发数据里没有这种情况，由页面测试覆盖） |
| ALT-04 | 已改 | `tests/observer/test_observer_service.py` `test_threshold_alert_carries_sensor_operator_value_and_seconds`；`alerts-page.test.mjs`「an alert row says what happened and what to do; the server's words are in the details」 | —（开发数据里没有这种情况，由页面测试覆盖） |
| ALT-05 | 已改 | `tests/observer/test_observer_service.py` `test_data_gap_alert_carries_the_sensor`；`alerts-page.test.mjs`「an alert row says what happened and what to do; the server's words are in the details」 | —（开发数据里没有这种情况，由页面测试覆盖） |
| ALT-06 | 已改 | `tests/observer/test_frozen_watch.py` `test_frozen_reading_alert_carries_the_sensor_and_value`；`tests/observer/test_observer_service.py` `test_frozen_watch_alert_carries_no_params_and_keeps_the_error_out_of_them`；`alerts-page.test.mjs`「an alert row says what happened and what to do; the server's words are in the details」 | —（开发数据里没有这种情况，由页面测试覆盖） |
| ALT-07 | 已改 | `tests/workbench/test_message_codes.py` `test_the_alert_codes_the_runtime_picks_by_outcome_are_registered`、`test_every_alert_in_the_server_names_a_registered_code`；`tests/e2e/test_e2e_runtime.py` `test_failing_tick_step_raises_an_alert_and_later_steps_still_run`（`tick_step` 带 `step`，异常文字不进参数）；`tests/e2e/test_e2e_reviewed.py` `test_a_failing_backup_raises_an_alert`；`alerts-page.test.mjs`「an alert row says what happened and what to do; the server's words are in the details」 | —（开发数据里没有这种情况，由页面测试覆盖） |
| ALT-08 | 已改 | `tests/e2e/test_e2e_reviewed.py` `test_capture_goes_stale_when_no_sample_arrives`（`run_health`）；`alerts-page.test.mjs`「an alert row says what happened and what to do; the server's words are in the details」 | —（开发数据里没有这种情况，由页面测试覆盖） |
| ALT-09 | 已改 | `tests/e2e/test_e2e_heartbeat.py` `test_the_standing_warning_has_its_own_code`；`tests/e2e/test_e2e_reviewed.py` `test_capture_is_always_probed_and_missing_backups_are_a_standing_warning`、`test_failed_external_heartbeats_raise_alerts`（`external_monitor` 带 `signal`）；`tests/workbench/test_console_known_codes.py` `test_console_lists_every_tick_step_probe_and_heartbeat` | `alerts-*.jpg`、`inbox-*.jpg` |
| ALT-10 | 已改 | `tests/e2e/test_e2e_agents.py` `test_a_task_past_its_deadline_raises_an_alert_with_its_ids`；`tests/agents/test_agents_audit_schedule.py` `test_the_schedule_alert_resolves_after_a_scheduling_that_did_not_raise`（`audit_schedule`）、`test_an_audit_that_fails_on_two_stage_days_is_one_warning`（`audit_task_attention`）、`test_an_audit_run_that_raises_is_a_warning_not_a_critical_alert`、`test_an_audit_task_without_a_stage_reference_is_keyed_by_its_task`（`audit_task_failed`）；`alerts-page.test.mjs`「an alert row says what happened and what to do; the server's words are in the details」 | —（开发数据里没有这种情况，由页面测试覆盖） |
| ALT-13 | 已改 | `alerts-page.test.mjs`「an alert row has a kind label and the column headings; a coded row's message is not split by lines」；`alerts-page.test.mjs`「an alert from before codes shows its kind and keeps the message in the details」；`alerts-page.test.mjs`「an alert with an unknown code says unknown and keeps the code in the details」；`tests/observer/test_observer_alerts.py` `test_an_alert_stores_its_code_and_params`、`test_an_alert_stored_before_codes_reads_with_no_code` | `alerts-*.jpg`、`inbox-*.jpg` |
| STG-03 | 已改 | `tests/planning/test_planning_finding_params.py` `test_a_pump_start_says_which_step_and_drops_the_seconds_term`、`test_a_pump_left_to_the_device_has_no_params`；`run-sheet-review.test.mjs`「each finding reads as a sentence and its group says how to fix it once」 | —（开发数据里没有这种情况，由页面测试覆盖） |
| STG-04 | 已改 | `tests/planning/test_planning_finding_params.py` `test_an_unknown_treatment_lists_the_names`、`test_a_missing_level_gives_a_no_action_problem`、`test_a_device_owned_channel_gives_a_not_host_problem`、`test_a_round_without_a_single_allocation_lists_the_treatments_it_could_not_apply`；`run-sheet-review.test.mjs`「a name a planner chose is shown in quotes」 | —（开发数据里没有这种情况，由页面测试覆盖） |
| STG-05 | 已改 | `tests/planning/test_planning_finding_params.py` `test_an_unverified_card_names_the_source_and_the_card`、`test_an_uncalibrated_card_has_no_chinese_in_its_message`；`run-sheet-review.test.mjs`「each finding reads as a sentence and its group says how to fix it once」 | `stage-pending-*.jpg`、`stage-ended-*.jpg` |
| STG-06 | 已改 | `tests/planning/test_planning_finding_params.py` `test_a_manual_task_names_its_kind_id_and_time`、`test_a_manual_irrigation_carries_the_seconds`；`run-sheet-review.test.mjs`「each finding reads as a sentence and its group says how to fix it once」 | `stage-ended-*.jpg` |
| STG-20 | 已改 | `tests/control/test_control_message_codes.py` `test_a_write_that_could_not_be_built_is_not_sent`、`test_a_rejected_write_says_the_device_rejected_it`、`test_a_wrong_level_on_read_back_names_the_channel_and_the_level`、`test_a_hand_over_voids_with_its_code`、`test_a_restart_voids_queued_and_loses_the_receipt_of_the_sent`；`stage-status.test.mjs`「a failed receipt says what happened and what to do, without the server's words」、「an old receipt without a code keeps its reason in the details」、「an unknown receipt code is shown as unknown, never as the code」、「a failed receipt in the activity log has one fold」 | —（开发数据里没有这种情况，由页面测试覆盖） |
| TSK-04 | 已改 | `tests/workbench/test_workbench_manual_tasks.py` `test_a_cut_short_run_keeps_its_end_code_and_params_on_the_task_record`、`test_a_run_that_was_not_confirmed_says_which_state_it_reached`；`tests/control/test_control_message_codes.py` `test_a_hand_over_ends_a_run_with_the_handover_code`、`test_a_full_run_has_no_early_end_code`；`stage-tasks.test.mjs`「a partial irrigation says how long the pump ran and why it stopped」、「an old partial record without a code reads as 'ended early' and keeps its English in the details」、「irrigation notices name the task, not the request」 | —（开发数据里没有这种情况，由页面测试覆盖） |
| RND-16 | 已改 | `tests/research/test_research_notes.py` `test_treatment_problems_are_data_and_read_in_both_languages`、`test_unverified_channels_and_missed_tasks_are_lists_and_counts`、`test_a_coverage_share_reads_as_a_percentage` | —（开发数据的报告生成于更新前，备注参数仍是旧形状，由服务器测试覆盖） |
| CMP-04 | 已改 | `tests/compute/test_compute_error_codes.py` `test_a_stuck_attempt_waiting_for_reconciliation_says_reconcile_wait`、`test_a_stuck_attempt_with_an_error_carries_the_errors_code_and_params`、`test_a_stuck_attempt_with_an_old_error_has_an_empty_error_code`、`test_after_the_migration_an_old_row_reads_with_no_code`、`test_the_settle_response_carries_the_code`；`research-pages.test.mjs`「a stuck attempt says why and what to do; the server's words are in the details」、「a stuck error without a known error code says unknown and keeps the English in the details」、「an old stuck attempt without a code shows a generic line」；`shell.test.mjs`「a stuck attempt in the inbox says why and what to do; the server's words are in the details」 | —（开发工作台没有计算服务，由页面测试覆盖） |

### 7.2 补完的部分行

| 编号 | 状态 | 证据 | 截图 |
|---|---|---|---|
| P-04 | 已改 | `tests/workbench/test_workbench_reads.py` `test_the_project_read_shows_used_and_total_budget`、`test_used_cost_can_exceed_the_total_and_is_shown_as_it_is`、`test_budget_usage_is_none_without_a_budget`；`project-page.test.mjs`「the budget reads as used of total, and an overspent cost is shown as it is」 | `project-*.jpg` |
| P-11 | 已改 | `tests/dispatch/test_dispatch_end_codes.py` `test_a_refused_step_says_denied_with_the_refusals_own_code`、`test_a_model_that_cannot_be_reached_says_model_unavailable`、`test_a_model_that_stops_early_says_model_stopped_with_the_stop_reason`、`test_a_role_that_hands_back_nothing_says_undelivered_with_its_role`、`test_a_normal_end_says_run_finished`；`conversation.test.mjs`「a status line says why the task ended and what to do next」、「a status entry from before codes keeps its reason in the details only」 | —（对话里的状态条目生成于更新前，只走旧路径，由页面测试覆盖） |
| RND-11 | 已改 | `tests/research/test_research_stats.py` `test_an_estimate_with_too_few_blocks_carries_a_note_code`、`test_a_sampled_estimate_names_its_flips_and_exact_has_no_code`；`tests/workbench/test_workbench_rounds.py` `test_the_report_read_names_the_primary_endpoint`、`test_a_report_whose_protocol_is_gone_has_no_primary_endpoint`；`round-report.test.mjs`「an estimate note follows the console language and says what to do」、「an old report's note stays in the details」、「the estimate names the measured quantity」 | `round-*.jpg` |
| STG-01 | 已改 | `tests/workbench/test_message_codes.py` `test_every_finding_names_a_registered_message_code`；`tests/planning/test_planning_finding_params.py` `test_a_write_to_a_device_owned_channel_names_its_source_and_channel`、`test_an_action_without_evidence_names_its_source`；`run-sheet-review.test.mjs`「each finding reads as a sentence and its group says how to fix it once」、「a finding without params or variant still reads (old data)」、「a finding the catalog lacks says unknown and keeps the server's words in the details」 | `stage-pending-*.jpg`、`stage-ended-*.jpg` |
| STG-02 | 已改 | `tests/planning/test_planning_finding_params.py` `test_rule_validity_shorter_than_the_interval`、`test_a_max_gap_shorter_than_the_interval`、`test_conflicting_rules_name_both_rules_the_channel_and_priority`、`test_a_safety_conflict_names_the_rule_the_protection_and_both_levels`；`run-sheet-review.test.mjs`「each finding reads as a sentence and its group says how to fix it once」 | `stage-pending-*.jpg`、`stage-ended-*.jpg` |
| ENV-02 | 已改 | `tests/workbench/test_workbench_planned.py` `test_planned_levels_step_at_each_local_action_time`、`test_planned_levels_cross_midnight_from_the_previous_days_last_action`、`test_planned_levels_on_the_day_clocks_change`、`test_a_running_stage_returns_its_plan_clipped_to_the_window`、`test_a_stage_that_is_not_running_has_no_plan`；`chart.test.mjs`「a level chart draws the plan as a dashed step line with a legend」、「without a plan there is no plan line and no legend」；`environment.test.mjs`「the page draws the stage's planned levels on the level charts, and none when there is no plan」 | —（开发数据里没有运行中的阶段，由页面测试覆盖） |
| ALT-11 | 部分（已改：摘要和证据作为参数由服务器发，页面分行显示；未改：模型写的摘要措辞，第三批） | `tests/agents/test_agents_auditor.py`（`audit_finding` 码和参数的断言）；`alerts-page.test.mjs`「an auditor's note is quoted under a fixed sentence」 | —（开发数据里没有这种情况，由页面测试覆盖） |
| ALT-12 | 已改 | `alerts-page.test.mjs`「a waiting stage's alert lists its reasons as sentences and links to the stage even when its id has a colon」、「an alert with a project id links to the project」；`shell.test.mjs`「each alert row has an id and the focused one is highlighted」 | —（开发数据里没有这种情况，由页面测试覆盖） |
| FRM-06 | 部分（拒绝文字里的时长在 2b；告警里的时长已由参数写出） | `tests/observer/test_observer_service.py` `test_threshold_alert_carries_sensor_operator_value_and_seconds`；`tests/control/test_control_message_codes.py` `test_a_pump_off_that_never_confirmed_says_so`；`messages.test.mjs`「durations, sensors, levels, operators and times are written for people」 | —（开发数据里没有这种情况，由页面测试覆盖） |

### 7.3 说明

- 6.3 的五项遗留已由 Task 1 处理，各有测试：冻结阈值和最长空档写精确秒数（`config-pages.test.mjs`「the frozen threshold and the longest gap say the exact seconds when the words round them」）；未知状态的折叠在轮询中保持展开（`environment.test.mjs`「a refresh with the same state keeps an open unknown-state fold open」、`stage-status.test.mjs`「the title pill keeps an open unknown-state fold open across polls」）；未知条目类型的代码进详情（`shell.test.mjs`「an inbox item of an unknown kind keeps its kind code in its details」）；Safari 里的复制按钮（`tech-details.test.mjs`「copy buttons cannot be selected in Safari either」）；6.2 的说法已在 6.2 改过。
- 温度和湿度在运行单里只有触发阈值，没有计划值，所以 ENV-02 的计划虚线只画光照、排风和风扇三个档位通道。
- 照护模式和反馈规则的覆盖不属于画出来的计划，这与 `expected` 一致。
- `stage_waiting` 的下一步是一句通用的话，不按原因分别写。
- 6.1 表是第一批结束时的快照：表里“第 2 批”的行已不再有对应的豁免项，`leak-exemptions.mjs` 现在只剩“第 3 批”和“保留”。

## 8. 第二批 2b 结果

2b 让每个拒绝都说明原因。服务器的每个 `Denied(...)` 和 `rejected(...)` 现在带 `reason`（`denial` 族）和 `params`，`/api` 与 dashboard 上没有码的错误也各有码和原因；粗码和状态码不变，`/wb` 的 `detail` 多出 `reason` 和 `params`，`/api` 的 `detail` 仍是字符串，顶层多出 `code`、`reason` 和 `params`，模型仍读到 `denied (code): message`。控制台按原因拼出说明和下一步，请求体校验错误由控制台自己的文字（`msg.validation.*`）写出。原因清单在 `src/growbridge/denial_codes.py`，导出到 `tests/web/fixtures/message-codes.json` 的 `denial` 族；临时的 `PENDING` 记账已删，`tests/workbench/test_denial_codes.py` 对每个文件一视同仁。

状态和证据的写法同第 7 节。截图是在开发工作台上用 2026-11-15 实跑数据的副本做出的真实拒绝，改造前用 main `d7d479a`，改造后用本分支，1440 和 375 宽、中英文各一张：`start-stage-*.jpg` 是在待审批的阶段上点“启动阶段”（`approval_invalid` / `approval_none_valid`），`protocol-json-*.jpg` 是在项目页的协议 JSON 里删掉一个处理的 `id` 再保存（校验错误）。登录时输错密码也截了，但登录页用自己的目录文字，改造前后一样，所以不放对照。

| 编号 | 状态 | 证据 | 截图 |
|---|---|---|---|
| ERR-01 | 已改 | `tests/workbench/test_denial_codes.py` `test_every_refusal_names_a_registered_reason_of_its_code`、`test_every_registered_reason_is_sent_somewhere`、`test_the_refusal_body_adds_reason_and_params_and_keeps_the_status`；`tests/web/denials.test.mjs`「a refusal with a known reason reads as its text and next step, with its params filled」、「a refusal without a reason, or with a reason the catalog lacks, falls back to the code's text」、「a refusal's reason and params are in the technical details, beside the server's words」、「every registered reason, filled with sample params, shows no code, id, hash or epoch outside the details」；`tests/web/api.test.mjs`「a denial carries its reason and params; params that are not an object become {}」 | `start-stage-*.jpg`、`protocol-json-*.jpg` |
| ERR-02 | 已改（只在控制台，服务器的 422 body 不变） | `tests/web/validation.test.mjs`「a missing field next to its input says it is required, in the reader's language」、「a too-long text says the maximum length」、「a number bound says the bound as written」、「a path in the JSON editor reads as positions: item numbers count from 1, keys stay as typed」、「an unknown validation type falls back to a general sentence and keeps Pydantic's words in the details」、「every validation type has a text in both languages」 | `protocol-json-*.jpg` |
| ERR-03 | 已改 | `tests/workflow/test_workflow_denial_reasons.py` `test_run_sheet_too_old_carries_both_versions`、`test_capabilities_changed_carries_the_stage_and_the_original_sentence`、`test_approval_recovery_changed_carries_the_stage`、`test_stage_state_reasons_carry_the_stage_and_its_state`；`tests/tasks/test_tasks_denial_reasons.py` `test_task_transition_not_allowed_carries_the_task_and_both_statuses`；`tests/workbench/test_workbench_denial_reasons.py` `test_round_not_in_project_carries_the_round_and_the_project`；`tests/agents/test_agents_denial_reasons.py` `test_round_wrong_phase_carries_both_states`；`tests/web/denials.test.mjs`「a refused form still reloads the page on a state refusal, and says the reason's text」 | `start-stage-*.jpg` |
| ERR-04 | 已改 | `tests/control/test_control_denial_reasons.py` `test_irrigation_seconds_range_carries_the_request_and_the_limit`、`test_irrigation_too_soon_carries_the_wait_and_the_ready_time`、`test_right_from_old_recovery_carries_the_right_id`、`test_no_live_link_carries_the_device`、`test_stale_carries_the_device_and_the_age`；`tests/web/denials.test.mjs`「the 2b param names format as the contract says」 | —（开发数据里做不出这种拒绝，由测试覆盖） |
| ERR-05 | 已改 | `tests/compute/test_compute_reasons.py` `test_param_not_in_choices_carries_the_field_and_the_choices`、`test_param_out_of_range_carries_both_bounds`、`test_param_below_minimum_carries_only_the_minimum`、`test_param_above_maximum_carries_only_the_maximum`、`test_quota_over_carries_the_resource_and_both_amounts`、`test_quota_over_balance_carries_the_cpu_hours`、`test_param_required_carries_the_field`；`tests/workbench/test_workbench_entry_reasons.py` `test_level_out_of_range_carries_the_channel_the_level_and_its_range` | —（开发数据里做不出这种拒绝，由测试覆盖） |
| ERR-06 | 已改 | `tests/research/test_research_denial_reasons.py` `test_snapshot_file_changed_carries_the_snapshot_and_the_file_name`、`test_snapshot_manifest_changed_carries_the_snapshot`、`test_script_other_frozen_carries_the_protocol`、`test_script_syntax_carries_the_compiler_text_as_detail`；`tests/web/denials.test.mjs`「every registered reason, filled with sample params, shows no code, id, hash or epoch outside the details」（文档章节号只剩在代码注释和文档字符串里，消息和说明里没有） | —（开发数据里做不出这种拒绝，由测试覆盖） |
| ERR-07 | 已改 | `tests/workflow/test_workflow_denial_reasons.py` `test_stage_not_awaiting_approval_carries_the_stage_and_its_state`、`test_run_sheet_needs_switch_carries_the_stage_and_its_state`、`test_stage_not_startable_carries_the_stage_and_its_state`、`test_stage_already_ended_carries_the_stage_and_its_state`、`test_round_already_ended_carries_the_round_and_its_state`；`tests/workbench/test_workbench_entry_reasons.py` `test_stage_not_in_manual_carries_the_stage_and_its_state`、`test_irrigation_stage_not_running_carries_the_stage_and_its_state` | —（开发数据里做不出这种拒绝，由测试覆盖） |
| ERR-08 | 已改 | `tests/workbench/test_workbench_entry_reasons.py` `test_not_signed_in_carries_no_params`、`test_unknown_request_is_a_404_with_the_full_body`、`test_not_from_page_carries_no_params`；`tests/test_api_mcp.py` `test_a_missing_bearer_is_not_signed_in`、`test_a_page_write_from_another_origin_is_origin_not_allowed`、`test_the_closed_write_endpoints_are_use_workbench`、`test_old_clients_still_read_a_string_detail`；`tests/test_dashboard.py` `test_no_session_is_dashboard_not_connected` | —（工作台控制台不调用 `/api`，由服务器测试覆盖） |
| ERR-09 | 已改 | `tests/web/denials.test.mjs`「the budget advice speaks to the reader, not about an operator」；`tests/agents/test_agents_denial_reasons.py` `test_budget_not_set_carries_the_project` | —（开发数据里做不出这种拒绝，由测试覆盖） |
| FRM-06 | 已改（拒绝文字里的时长由参数写出；告警里的时长 2a 已做） | `tests/control/test_control_denial_reasons.py` `test_irrigation_too_soon_carries_the_wait_and_the_ready_time`、`test_irrigation_seconds_range_carries_the_request_and_the_limit`；`tests/web/denials.test.mjs`「the 2b param names format as the contract says」；`tests/web/messages.test.mjs`「durations, sensors, levels, operators and times are written for people」 | —（开发数据里做不出这种拒绝，由测试覆盖） |

---

## 9. 第三批结果

第三批把剩下的表单、确认和模型措辞做完：安全限值、协议、留出批次和运行单改成分字段表单（带单位、范围、提示，JSON 收进“高级（JSON）”折叠）；设备能力（`GET /wb/capabilities`）、运行单审阅的 `approval`、协议行的 `primary_endpoint` 和 `method` 三个新的读字段让表单用得上真实的范围，而不是客户端猜的数；不可撤销的操作在做之前说明后果；目标带上控制台语言（`GoalIn.language`、`ResearchTask.language`），模型的每个角色都有“为操作员写作”的规则，给模型的时间改成本地时间。本批覆盖 19 行，做完后清单里分给这次改造的行全部关闭。

状态和证据的写法同第 7 节。每个新表单页在中英文下都过防露出测试（`tests/web/leaks.test.mjs`「no page leaks internal text」和「the batch 3 form pages show their forms in both languages」）；“高级（JSON）”折叠起始是空的，没有触发扫描，所以没有加豁免。模型写的措辞没法不调用模型就钉住，这几行的证据是提示词测试（写作规则、字段说明、语言和本地时间的输入），模型是否照做靠评估而不是单元测试。截图用开发工作台加 2026-11-15 实跑数据的副本，改造前用 2b 的头 `cf50922`，改造后用本分支，1440 和 375 宽、中英文各一张，编辑折叠展开后整页截取，未进仓库，已发给用户：`safety-*.jpg` 是安全配置页（表单在上，JSON 收进“高级（JSON）”），`project-*.jpg` 是项目页（协议表单和留出批次表单），`stage-pending-*.jpg` 是待审批的阶段页（运行单表单、置灰的“启动阶段”）；`safety-dialog-*.png` 只有改造后：把“最长空档”加一秒再点“批准限值”弹出的确认框，改造前这里是 JSON 编辑器，没有这个对话框。“—”后面写着为什么没有截图。

| 编号 | 状态 | 证据 | 截图 |
|---|---|---|---|
| P-02 | 已改（不再预填示例数据；`question` 在表单里必填，服务器仍不要求） | `tests/web/protocol-form.test.mjs`「the protocol form builds a protocol the server accepts, with version 1 for a new id and the next version for a saved one」、「the question is required, the hypothesis is not」、「allocations start empty; nothing is randomised for the user」、「the protocol form shows no ids or field names」、「the JSON fold starts from an empty skeleton and invents nothing」、「the JSON fold refuses a version that is not above the saved ones, before sending」；`tests/web/project-page.test.mjs`「the protocol fold keeps the JSON editor under Advanced, and an old JSON draft still opens the fold」 | `project-*.jpg`（项目页的协议表单） |
| P-03 | 已改（目标编辑器已删；留出批次一行一个批次，不是多选，并解释“留出”与“开发”） | `tests/web/project-page.test.mjs`「the project page has no goal JSON editor; the goals section still lists tasks」；`tests/web/protocol-form.test.mjs`「the holdout form takes one batch per line and explains hold-out and development」、「each holdout list needs 1 to 50 items of at most 100 characters」、「the holdout fold keeps an Advanced (JSON) editor that posts the same body」 | `project-*.jpg`（留出批次表单；目标编辑器已不在） |
| SAF-04 | 已改（已批准时按它预填，没有已批准的集合时每个值都空着，不发明任何安全数值；“首次提供已审定模板”没做，因为那会替人定安全数值） | `tests/web/safety-form.test.mjs`「with an approved set the form is prefilled from it and nothing else」、「with nothing approved every rule and frozen field starts empty and shows its allowed range; no safety number appears」、「the form builds the same config the JSON editor would send, and the approval dialog still lists the changes」、「the unit follows the sensor and is not typed」、「the JSON editor sits closed in an Advanced (JSON) fold and sends through the same approval」、「two approvals in a row never send the same version」、「adding a rule and removing a middle one lists plain sentences only, in both languages」 | `safety-*.jpg`；批准确认框 `safety-dialog-*.png`（只有改造后） |
| STG-15 | 已改（常见改动用表单，整份 JSON 收进关闭的折叠；表单不显示的键原样送回） | `tests/web/run-sheet-form.test.mjs`「an unchanged form sends the run sheet back byte for byte」、「changing one timed action's level changes only that value」、「keys the form does not show (feedback rules, care rules, ownership, ids, timezone) are sent back unchanged」、「durations are entered in days, hours and minutes and sent in seconds」、「rows can be added, and removing one keeps the others exactly as stored」、「a draft kept on another run sheet is dropped with a note, never put on the new one」；`tests/web/run-sheet-review.test.mjs`「the stage page changes a run sheet with a form, the full JSON stays in a closed fold, and an unchanged form posts the sheet as read」 | `stage-pending-*.jpg`（运行单表单，整份 JSON 在关闭的折叠里） |
| STG-16 | 已改（范围来自设备能力；读不到时浏览器不检查范围，由服务器判断；水泵由“关闭水泵”按钮关闭） | `tests/web/run-sheet-form.test.mjs`「a level outside the channel's range is refused beside its row」、「without level ranges no range is checked in the browser (the server judges)」、「end action rows follow their channel's range, and a row's 422 lands on that row」；`tests/web/stage-status.test.mjs`「the level field's range follows the chosen channel」、「the pump is switched off by its own button, after a confirmation」；`tests/web/capabilities.test.mjs`「capabilities are read once per page and a failed read gives null」；`tests/workbench/test_workbench_reads.py` `test_capabilities_answers_level_ranges_sensors_and_the_pump_cap` | —（截图里没有越界的档位，由测试覆盖） |
| RND-06 | 已改（只剩代码文本框，项目由页面补；冻结前说明不可撤销，取消不发请求） | `tests/web/round-report.test.mjs`「freezing asks first and says it cannot be undone; cancelling sends nothing」 | —（开发数据里这一轮已交付，分析折叠没有展开，由测试覆盖） |
| EVI-02 | 已改（核验是勾选框，起始未勾；提交前说明核验后不可改） | `tests/web/research-pages.test.mjs`「verifying evidence is a check box that starts unticked, and asks because it cannot change later」 | —（本批没有截证据卡页，由测试覆盖） |
| RND-04 | 已改（选择框起始是“请选择…”，每个选择在发出前带着后果询问；文字里的 id 第一批已去掉） | `tests/web/round-report.test.mjs`「the round choice starts on 'choose' and every choice is asked with its consequence」、「stages are linked by name, and the stopped stage is named in the choice」 | —（开发数据里这一轮已交付，没有要做的选择，由测试覆盖） |
| RND-07 | 已改（快照选择起始是“请选择…”，运行前说明这个快照上只能做一次） | `tests/web/round-report.test.mjs`「the run form starts on 'choose' and asks before the one run a snapshot allows」 | —（开发数据里这一轮已交付，分析折叠没有展开，由测试覆盖） |
| STG-14 | 已改（运行单未审批时“开始”置灰并写原因，批准后点“开始”先确认；审阅读不到时保持可点，由服务器判断；按钮的排布没有另测） | `tests/web/stage-status.test.mjs`「start is disabled with the reason while the run sheet is not approved」、「start asks first once the run sheet is approved」、「start with a review that could not be read stays enabled and asks first」；`tests/workbench/test_workbench_reads.py` `test_a_review_says_whether_the_current_run_sheet_is_approved`、`test_an_approval_start_would_refuse_is_not_reported_as_approved` | `stage-pending-*.jpg`（“启动阶段”置灰，写着原因） |
| STG-17 | 已改（浇水先确认，和任务行同一个确认框；秒数上限取设备配置的水泵上限） | `tests/web/stage-status.test.mjs`「irrigation seconds are capped at the configured pump limit and asked first, like a task row」、「the manual form asks first, and a channel must be chosen」、「the pump is switched off by its own button, after a confirmation」；`tests/workbench/test_workbench_reads.py` `test_capabilities_answers_level_ranges_sensors_and_the_pump_cap` | —（截图的阶段在待审批，没有浇水和手动控件，由测试覆盖） |
| TSK-03 | 已改（跳过要确认，可写理由，理由记在记录上；已完成的行没有“跳过”；没有加“撤销”，仍是再记一条） | `tests/web/stage-tasks.test.mjs`「skipping asks for an optional reason and sends it as the note; cancelling sends nothing」、「a done row offers no skip」、「the task row shows the reason given」 | —（开发数据里的运行单没有人工任务，由测试覆盖） |
| P-09 | 已改（控制台把页面语言随目标发出，服务器写进任务，模型的记录里写明语言，委派和后续任务沿用）；模型是否真用这种语言回复由提示词测试覆盖：`test_every_role_carries_the_writing_rules` | `tests/web/conversation.test.mjs`「the conversation sends the console language with a goal」；`tests/workbench/test_workbench_rounds.py` `test_a_goal_stores_the_console_language_and_defaults_to_chinese`、`test_a_resent_goal_in_another_language_returns_the_first_task`、`test_an_unknown_language_is_refused`；`tests/dispatch/test_dispatch_conversation.py` `test_the_model_record_names_the_language`、`test_an_old_task_without_language_takes_the_latest_goal_language`、`test_without_any_goal_the_record_names_chinese`；`tests/dispatch/test_dispatch_orchestrator.py` `test_delegated_created_and_follow_up_tasks_inherit_the_language`；`tests/agents/test_agents_audit_schedule.py` `test_an_audit_uses_the_projects_latest_goal_language_or_chinese` | —（随目标发出的字段，页面上看不见，由测试覆盖） |
| RND-17 | 已改（每个角色都带共用的“为操作员写作”规则，发布和发现字段的说明也写明是给操作员看的）；模型照不照做由提示词测试覆盖，不能不调用模型就钉住 | `tests/agents/test_agents_roles.py` `test_every_role_carries_the_writing_rules`、`test_publish_and_finding_fields_describe_operator_text` | —（模型写的措辞，由提示词测试覆盖） |
| RND-18 | 部分已改（审计问题里不再有 epoch 秒，窗口用本地时间写；审计员读到的阶段记录和运行状态在 epoch 旁带本地时间）；研究员的 `inspect_stage_data`、`stage_preview` 等其他工具输出仍带裸 epoch，规则只能禁止模型引用 | `tests/agents/test_agents_audit_schedule.py` `test_an_audit_question_has_no_epoch_seconds_and_says_the_window_in_local_time`；`tests/agents/test_agents_auditor.py` `test_stage_records_and_run_status_carry_local_times_beside_epochs`、`test_local_time_formats_in_the_reporting_time_zone_and_passes_none_through` | —（模型读到的工具输出，由测试覆盖） |
| RND-19 | 已改（规则写明“工具拒绝或失败时用自己的话告诉操作员在控制台里怎么做，不引用错误”）；模型是否照做由提示词测试覆盖 | `tests/agents/test_agents_roles.py` `test_every_role_carries_the_writing_rules`（钉住“what the operator should do”和“in your own words”两句） | —（模型写的措辞，由提示词测试覆盖） |
| ALT-11 | 已改（显示第一批已做；剩下模型写的摘要和证据措辞，由 RND-17 的规则负责，由提示词测试覆盖） | `tests/web/alerts-page.test.mjs`「an alert row has a kind label and the column headings; a coded row's message is not split by lines」；`tests/web/catalog.test.mjs`（`alert.kind.audit_finding` 读作“审计备注”）；`tests/agents/test_agents_roles.py` `test_publish_and_finding_fields_describe_operator_text` | —（模型写的措辞，由提示词测试覆盖） |
| RND-09 | 已改（显示第一批已做；模型写的局限措辞由写作规则负责，由提示词测试覆盖） | `tests/web/round-report.test.mjs`「limitations show three and fold the rest」、「report items and the next round keep the model's light markup」；`tests/agents/test_agents_roles.py` `test_every_role_carries_the_writing_rules`、`test_publish_and_finding_fields_describe_operator_text` | —（模型写的措辞，由提示词测试覆盖） |
| RND-10 | 已改（显示第一批已做；“未解决问题”和“下一轮”的措辞由写作规则负责，由提示词测试覆盖） | `tests/web/round-report.test.mjs`「report items and the next round keep the model's light markup」；`tests/agents/test_agents_roles.py` `test_every_role_carries_the_writing_rules`、`test_publish_and_finding_fields_describe_operator_text` | —（模型写的措辞，由提示词测试覆盖） |

**留给用户的服务器端跟进（不在第三批内，客户端已各自拦住）。** `SafetyConfig` 接受重复的规则 id、负的有效期和时长、不递增的版本；`RunSheet` 接受 `timed_actions`、`manual_tasks`、`end_actions` 里重复的 id，`ChannelPlan.retained_level` 没有范围检查。其他 API 调用方仍可提交这些。另外，证据的“录入”表单会直接建一张已核验、之后不能改的卡片，没有确认（EVI-02 只覆盖核验表单）。
