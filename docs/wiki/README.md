# DiAGRI Wiki

**Read in:** [English](en/Home.md) · [简体中文](zh-CN/Home.md)

This folder is the project wiki. It lives in the repository so that pages are versioned and reviewed together with the code they describe. Every page exists in English (`en/`) and Simplified Chinese (`zh-CN/`) under the same file name.

本目录是项目 Wiki。它放在仓库里，页面和所描述的代码一起做版本管理和评审。每个页面都有英文版（`en/`）和简体中文版（`zh-CN/`），两个版本的文件名相同。

## Pages · 页面

| Group · 分组 | File · 文件 | English | 中文 | Kind · 类型 |
| --- | --- | --- | --- | --- |
| | `Home.md` | Home | 首页 | map · 导航 |
| Getting started · 上手 | `Overview.md` | Overview | 项目概览 | explanation · 解释 |
| | `Installation-and-Quick-Start.md` | Installation and quick start | 安装与快速开始 | tutorial · 教程 |
| | `Tutorial-Simulated-Round.md` | Tutorial: a simulated research round | 教程：在模拟器上跑通一轮 DiAGRI | tutorial · 教程 |
| | `Example-Full-Round-With-Claude.md` | Example: a complete round with the model roles | 示例：模型角色跑完整一轮 | tutorial · 教程 |
| How-to guides · 操作指南 | `Enable-DiAGRI.md` | Enable DiAGRI | 启用 DiAGRI | how-to · 操作指南 |
| | `Run-a-Research-Round.md` | Run a research round | 运行一轮研究 | how-to · 操作指南 |
| | `Manual-Takeover-and-Irrigation.md` | Manual takeover, irrigation and handback | 人工接管、灌溉与交还 | how-to · 操作指南 |
| | `Troubleshooting-Runbook.md` | Troubleshooting runbook | 故障处理手册 | how-to · 操作指南 |
| | `Notifications-Reports-and-Backup.md` | Notifications, daily reports and backup | 通知、日报与备份 | how-to · 操作指南 |
| Concepts and design · 概念与设计 | `Architecture.md` | Architecture overview | 架构总览 | explanation · 解释 |
| | `The-Five-Agents.md` | The agents | Agent 一览 | explanation · 解释 |
| | `Control-and-Safety-Model.md` | Control and safety model | 控制与安全模型 | explanation · 解释 |
| | `Workflow-and-State-Machines.md` | Workflow and state machines | 工作流与状态机 | explanation · 解释 |
| | `Data-Archive-and-Traceability.md` | Data, archive and traceability | 数据、档案与可追溯性 | explanation · 解释 |
| | `Variable-Catalog.md` | Variable catalog | 变量目录 | explanation · 解释 |
| | `Research-Methodology.md` | Research methodology | 科研方法 | explanation · 解释 |
| | `Design-Decisions.md` | Design decisions | 设计决策记录 | explanation · 解释 |
| Reference · 参考 | `Configuration-Reference.md` | Configuration reference | 配置参考 | reference · 参考 |
| | `CLI-Reference.md` | CLI reference | CLI 参考 | reference · 参考 |
| | `API-Reference.md` | HTTP, workbench and MCP interfaces | HTTP、工作台与 MCP 接口 | reference · 参考 |
| | `Denial-Codes-and-Events.md` | Denial codes and stage events | 拒绝码与事件类型 | reference · 参考 |
| | `Glossary.md` | Glossary | 术语表 | reference · 参考 |
| Development · 开发 | `Development-Setup-Testing-and-CI.md` | Development setup, testing and CI | 开发环境、测试与 CI | how-to · 操作指南 |
| | `Code-Structure-and-Extension-Points.md` | Code structure and extension points | 代码结构与扩展点 | explanation · 解释 |
| | `Contributing.md` | Contributing | 贡献流程 | how-to · 操作指南 |
| Project · 项目 | `Status-and-Known-Limitations.md` | Status and known limitations | 状态与已知限制 | reference · 参考 |
| | `FAQ.md` | FAQ | 常见问题 | reference · 参考 |

Each language folder also has `_Sidebar.md` (the full table of contents) and `_Footer.md` (when the pages were last checked against the code). The names follow the GitHub Wiki convention, so one language folder can be published to a GitHub Wiki later.

每个语言目录里还有 `_Sidebar.md`（完整目录）和 `_Footer.md`（页面最近一次对照代码核对的时间）。文件名沿用 GitHub Wiki 的约定，以后可以把某一种语言的目录发布到 GitHub Wiki。

## Conventions for editing

1. **Both languages, same commit.** A page exists in `en/` and `zh-CN/` under the same file name. Change both in the same commit. The Chinese page is written as natural Chinese, not as a word-for-word translation.
2. **One kind of content per page.** A tutorial walks a newcomer through one complete run. A how-to guide solves one task for someone who already knows the basics. A reference page is for lookup and states facts without argument. An explanation page says why the system is built the way it is. Do not mix them: put the reason on an explanation page and link to it.
3. **Page header.** Line 1 is the title. Then a language switch line, then one sentence that says who the page is for and what it covers. Pages end with a "See also" list.
4. **The code is the source of truth.** Every command, option, configuration field, route, state name and identifier on a page must exist in the code. Link to the source file so a reader can check. If a fact cannot be checked in the code or the tests, leave it out or mark it as not verified.
5. **Link, do not copy.** The READMEs and the [architecture document](../diagri-agent-architecture.zh-CN.md) stay where they are. Summarize in a few lines and link to them.
6. **Say what is not verified.** The system has been tested on the simulated AC5 only. Any page that describes behavior on real hardware, a Raspberry Pi, real notification channels or CSC says so and links to `Status-and-Known-Limitations.md`.
7. **Terms.** Use the terms in `Glossary.md`. The project is DiAGRI. GrowBridge names only the device bridge, and `growbridge` the package and the command. Write DiAGRI mode for `auto_research = true` and bridge-only mode for `auto_research = false`. Code identifiers, state values and command names stay in English in both languages.
8. **Nothing private.** No tokens, passwords, personal data or machine-specific paths. Use placeholders such as `YOUR_PI_HOST` and `/absolute/path/to/...`.
9. **Links.** Links between wiki pages are relative and keep the `.md` extension, for example `[Glossary](Glossary.md)`. Links to source files are relative to the page, for example `../../../src/growbridge/ports.py`.
10. **Keep pages short.** One topic per page. Split a page that grows past about 300 lines.

## 编写约定

1. **两种语言，同一次提交。** 每个页面在 `en/` 和 `zh-CN/` 下各有一份，文件名相同，修改时两份一起改。中文页面按中文的习惯写，不逐词翻译。
2. **一页只放一类内容。** 教程带新手完整走一遍。操作指南帮已经入门的人完成一个具体任务。参考页用来查，只陈述事实。解释页说明为什么这样设计。不要混写：理由放在解释页，其他页面链接过去。
3. **页首格式。** 第一行是标题，接着是语言切换行，再用一句话说明这页写给谁、讲什么。页尾是"另见"列表。
4. **以代码为准。** 页面上出现的每个命令、选项、配置项、路由、状态名和标识符，都必须能在代码里找到，并链接到源文件，方便读者核对。在代码或测试里查不到的说法，要么不写，要么标明"未验证"。
5. **链接，不复制。** README 和[架构设计文档](../diagri-agent-architecture.zh-CN.md)保持原样。Wiki 里用几行概括，然后链接过去。
6. **写明哪些没有验证。** 系统目前只在模拟的 AC5 上测试过。凡是描述真机、树莓派、真实通知渠道或 CSC 上行为的页面，都要说明这一点，并链接到 `Status-and-Known-Limitations.md`。
7. **术语。** 使用 `Glossary.md` 里的术语。项目叫 DiAGRI；GrowBridge 只指设备桥接部分，`growbridge` 是软件包和命令的名字。`auto_research = true` 称为 DiAGRI 模式，`auto_research = false` 称为仅桥接模式。代码标识符、状态值和命令名在两种语言里都保留英文。
8. **不写私密信息。** 不出现令牌、密码、个人信息和本机路径。用 `YOUR_PI_HOST`、`/absolute/path/to/...` 这样的占位符。
9. **链接写法。** Wiki 页面之间用相对链接并保留 `.md` 后缀，例如 `[术语表](Glossary.md)`。指向源文件的链接相对于页面所在位置，例如 `../../../src/growbridge/ports.py`。
10. **页面要短。** 一页一个主题。超过 300 行左右就拆分。
