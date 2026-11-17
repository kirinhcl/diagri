# Security policy

English | [简体中文](#安全策略)

DiAGRI writes to a real grow tent: lights, fans and a water pump. A security fault here can be a physical fault, so please report it privately and give us a chance to fix it before it is public.

## If something is running that should not be

Make it safe first. Switch the device off at the controller or cut its power, then report. Software cannot guarantee that the pump stops after host power loss, forced termination or a complete Bluetooth failure; see [Data and control boundaries](README.md#data-and-control-boundaries).

## How to report

Use GitHub's private vulnerability reporting: open the repository's **Security** tab and choose **Report a vulnerability**. Do not open a public issue, pull request or discussion with the details.

If that button is not there, open an issue that asks for a private contact and contains no details.

Please include what you did, what happened, what you expected, the commit you tested, and whether you used the simulated AC5 or real hardware. This is a small, early-stage project maintained on a best-effort basis; you will get an answer when a maintainer has read the report.

## Supported versions

There are no releases yet. Fixes go to the latest commit on `main` only.

## What counts as a vulnerability

The limits below are enforced in code ([Control and safety model](docs/wiki/en/Control-and-Safety-Model.md)). A way around any of them is a vulnerability:

- A model role reaches a stage or device control tool, or anything said in a conversation counts as an approval.
- A stage starts without an operator's approval of that exact run sheet version, or an action that needs re-authentication runs without it.
- The pump starts other than when an operator on the lab network starts it (a planned irrigation from the stage page, or a manual takeover), or the pump interlock or the watchdog fails to switch it off.
- A request passes the bridge API or the workbench without a valid token, session or role token, or from an entry or origin that should be refused.
- With `multi_user` on, an operator reads or acts on another operator's project, stage, alert or receipt.
- A token, a secret or a held-out outcome reaches someone or something that should not see it, such as a model role or another project.
- Raw samples are changed, or a frozen data snapshot is changed instead of being superseded by a new version.
- An analysis script leaves the sandbox, where the sandbox exists (macOS in this code).

## Out of scope

- Weaknesses in the Spider Farmer controller or its Bluetooth protocol. GrowBridge uses the plaintext protocol v1 as the device provides it; report device faults to the manufacturer.
- The limits already documented in [Status and known limitations](docs/wiki/en/Status-and-Known-Limitations.md). Reports that show one of them is worse than documented are welcome.

---

# 安全策略

[English](#security-policy) | 简体中文

DiAGRI 会向真实的种植帐篷写入指令：灯、风扇和水泵。这里的安全问题可能变成物理上的问题，所以请私下报告，在公开之前给我们修复的机会。

## 如果有不该运行的设备正在运行

先确保安全：在控制器上关掉设备或切断电源，然后再报告。主机断电、进程被强制终止或蓝牙完全失效时，软件无法保证水泵停止；见[数据与控制边界](README.zh-CN.md#数据与控制边界)。

## 如何报告

请使用 GitHub 的私密漏洞报告：打开仓库的 **Security** 标签页，选择 **Report a vulnerability**。不要在公开的 issue、Pull Request 或讨论里写细节。

如果没有这个按钮，请开一个 issue 索要私下联系方式，issue 里不要写任何细节。

请写明你做了什么、发生了什么、你预期发生什么、测试时的提交，以及用的是模拟 AC5 还是真机。这是一个早期的小项目，维护靠尽力而为；维护者读到报告后会回复。

## 支持的版本

目前还没有发布版本。修复只进入 `main` 的最新提交。

## 什么算漏洞

下面这些限制由代码强制执行（[控制与安全模型](docs/wiki/zh-CN/Control-and-Safety-Model.md)）。能绕过其中任何一条，就是漏洞：

- 模型角色拿到了阶段或设备的控制工具，或者对话里说的话被当成了批准。
- 阶段在操作员没有批准该运行单这一确切版本的情况下启动了，或者需要重新认证的操作没有重新认证就执行了。
- 水泵不是由实验室网络上的操作员启动的（在阶段页面启动的计划灌溉，或人工接管），或者水泵联锁或看门狗没能把它关掉。
- 请求没有有效的令牌、会话或角色令牌，或者来自应当拒绝的入口或来源，却通过了桥接 API 或工作台。
- 打开 `multi_user` 时，一个操作员读到或操作了另一个操作员的项目、阶段、告警或回执。
- 令牌、密钥或留出数据的结果被不该看到它的人或程序看到，例如模型角色或别的项目。
- 原始样本被改动，或者已冻结的数据快照被直接改动，而不是由新版本取代。
- 在有沙箱的平台上（这份代码里是 macOS），分析脚本逃出了沙箱。

## 不在范围内

- Spider Farmer 控制器本身或其蓝牙协议的弱点。GrowBridge 按设备提供的方式使用明文协议 v1；设备本身的问题请报告给厂商。
- [状态与已知限制](docs/wiki/zh-CN/Status-and-Known-Limitations.md)里已经写明的限制。如果你发现某条限制比文档写的更严重，欢迎报告。
