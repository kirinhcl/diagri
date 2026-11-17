# DiAGRI Wiki

[English](../en/Home.md)

DiAGRI 是一个面向植物生长研究的 AI Agent 平台。它把一个研究问题推进成一轮完整的实验：设计实验，在种植设备上执行已批准的方案，记录每一次读数和写入，分析结果并交付报告。四个模型角色负责设计、分析和监察。两个确定性程序负责执行方案并持续观察。所有对设备的写入都经过同一个关口，任何模型都碰不到它。

GrowBridge 是 DiAGRI 的设备桥接部分：通过蓝牙读取并控制 Spider Farmer AC5 种植帐篷控制器。它也可以单独使用，提供本地控制台和 MCP 工具。

> **状态。** DiAGRI 模式目前只在模拟的 AC5 上测试过，没有在真实设备、树莓派、真实通知服务或 CSC 上运行过。单独运行的 GrowBridge 读取并控制过一台真实的 AC5。操作员通过 `/wb` 下的工作台路由发起并掌控一轮研究；这些路由只在测试里用脚本化的模型跑过，`/workbench` 的操作员控制台是它们之上的页面，没有 CLI 命令。见[状态与已知限制](Status-and-Known-Limitations.md)。

## 从这里开始

| 我想…… | 读这一页 |
| --- | --- |
| 了解这个项目是什么 | [项目概览](Overview.md) |
| 装好它，看到帐篷的读数 | [安装与快速开始](Installation-and-Quick-Start.md) |
| 不接硬件先试试 DiAGRI | [教程：在模拟器上跑通一轮研究](Tutorial-Simulated-Round.md) |
| 配置 DiAGRI 并跑一次实验 | 先读[启用 DiAGRI](Enable-DiAGRI.md)，再读[运行一轮研究](Run-a-Research-Round.md) |
| 手动接管，或者给植物浇水 | [人工接管、灌溉与交还](Manual-Takeover-and-Irrigation.md) |
| 处理出了问题的情况 | [故障处理手册](Troubleshooting-Runbook.md) |
| 知道它为什么可以放心长期运行 | [控制与安全模型](Control-and-Safety-Model.md) |
| 判断它给出的结论可不可信 | [科研方法](Research-Methodology.md) |
| 修改代码 | 先读[开发环境、测试与 CI](Development-Setup-Testing-and-CI.md)，再读[代码结构与扩展点](Code-Structure-and-Extension-Points.md) |
| 查一个词的意思 | [术语表](Glossary.md) |

## 全部页面

**上手**

- [项目概览](Overview.md)：DiAGRI 是什么，GrowBridge 在其中的位置，两种模式，以及系统绝不会做的事。
- [安装与快速开始](Installation-and-Quick-Start.md)：安装并读到帐篷的数据。
- [教程：在模拟器上跑通一轮研究](Tutorial-Simulated-Round.md)：不接硬件跑一轮。
- [示例：模型角色跑完整一轮](Example-Full-Round-With-Claude.md)：一轮真实记录，从提问到报告，附截图。

**操作指南**

- [启用 DiAGRI](Enable-DiAGRI.md)：配置、写入主机、操作员、模型角色。
- [运行一轮研究](Run-a-Research-Round.md)：从研究目标到报告交付。
- [人工接管、灌溉与交还](Manual-Takeover-and-Irrigation.md)：手动写入，再把控制权交回去。
- [故障处理手册](Troubleshooting-Runbook.md)：你会看到什么，系统已经做了什么，你需要做什么。
- [通知、日报与备份](Notifications-Reports-and-Backup.md)：通知渠道、日报、心跳和备份。

**概念与设计**

- [架构总览](Architecture.md)：各个部分，以及谁拥有什么。
- [Agent 一览](The-Five-Agents.md)：每个 Agent 能读什么、能做什么、不能做什么。
- [控制与安全模型](Control-and-Safety-Model.md)：写入权、动作账本、关泵联锁、两个入口。
- [工作流与状态机](Workflow-and-State-Machines.md)：轮次、阶段和研究任务。
- [数据、档案与可追溯性](Data-Archive-and-Traceability.md)：记录了什么，一个数字如何追溯到来源。
- [变量目录](Variable-Catalog.md)：共用的标准变量 ID，以及如何扩充。
- [科研方法](Research-Methodology.md)：实验单位、区组、检验方法、确认性分析的门槛。
- [设计决策记录](Design-Decisions.md)：主要决策及其理由。

**参考**

- [配置参考](Configuration-Reference.md)
- [CLI 参考](CLI-Reference.md)
- [HTTP、工作台与 MCP 接口](API-Reference.md)
- [拒绝码与事件类型](Denial-Codes-and-Events.md)
- [术语表](Glossary.md)

**开发**

- [开发环境、测试与 CI](Development-Setup-Testing-and-CI.md)
- [代码结构与扩展点](Code-Structure-and-Extension-Points.md)
- [贡献流程](Contributing.md)

**项目**

- [状态与已知限制](Status-and-Known-Limitations.md)
- [常见问题](FAQ.md)

## 其他文档

- [README](../../../README.zh-CN.md)（[English](../../../README.md)）：安装、控制台、MCP 客户端、树莓派部署。
- [架构设计文档](../../diagri-agent-architecture.zh-CN.md)：DiAGRI 据以实现的完整规格。
- [VALIDATION.md](../../../VALIDATION.md)：仅桥接模式的验证方法。
- [这个 Wiki 的组织方式与编写约定](../README.md)
