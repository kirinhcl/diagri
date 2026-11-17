# DiAGRI Wiki

[简体中文](../zh-CN/Home.md)

DiAGRI is an AI agent platform for plant-growth research. It takes one research question through a complete experiment: it designs the experiment, runs the approved plan on growing hardware, records every reading and every write, analyzes the result and delivers a report. Four model roles design, analyze and audit. Two deterministic programs carry out the plan and watch it. Every write to the device passes one checkpoint that no model can reach.

GrowBridge is DiAGRI's device bridge: the part that reads and controls a Spider Farmer AC5 grow-tent controller over Bluetooth. It can also be used on its own, with a local dashboard and MCP tools.

> **Status.** DiAGRI mode has been tested on a simulated AC5 only. It has not been run against a real device, a Raspberry Pi, real notification services or CSC. GrowBridge on its own has read and controlled one real AC5. An operator starts and steers a research round through the workbench routes under `/wb`; these have run only in tests with a scripted model, the operator console at `/workbench` is a page over them, and there is no CLI command. See [Status and known limitations](Status-and-Known-Limitations.md).

## Start here

| I want to… | Read |
| --- | --- |
| understand what this is | [Overview](Overview.md) |
| install it and see my tent's readings | [Installation and quick start](Installation-and-Quick-Start.md) |
| try DiAGRI without hardware | [Tutorial: a simulated research round](Tutorial-Simulated-Round.md) |
| set up DiAGRI and run an experiment | [Enable DiAGRI](Enable-DiAGRI.md), then [Run a research round](Run-a-Research-Round.md) |
| take over by hand or water the plants | [Manual takeover, irrigation and handback](Manual-Takeover-and-Irrigation.md) |
| fix something that went wrong | [Troubleshooting runbook](Troubleshooting-Runbook.md) |
| know why it is safe to leave running | [Control and safety model](Control-and-Safety-Model.md) |
| judge whether its conclusions can be trusted | [Research methodology](Research-Methodology.md) |
| change the code | [Development setup, testing and CI](Development-Setup-Testing-and-CI.md), then [Code structure and extension points](Code-Structure-and-Extension-Points.md) |
| look up a word | [Glossary](Glossary.md) |

## All pages

**Getting started**

- [Overview](Overview.md): what DiAGRI is, where GrowBridge fits in it, the two modes, and what the system never does.
- [Installation and quick start](Installation-and-Quick-Start.md): install it and read your tent.
- [Tutorial: a simulated research round](Tutorial-Simulated-Round.md): run a round with no hardware.
- [Example: a complete round with the model roles](Example-Full-Round-With-Claude.md): one recorded round, from the question to the report, with screenshots.

**How-to guides**

- [Enable DiAGRI](Enable-DiAGRI.md): configuration, write host, operators, model roles.
- [Run a research round](Run-a-Research-Round.md): from a goal to a delivered report.
- [Manual takeover, irrigation and handback](Manual-Takeover-and-Irrigation.md): writing by hand and giving control back.
- [Troubleshooting runbook](Troubleshooting-Runbook.md): what you see, what the system did, what you do.
- [Notifications, daily reports and backup](Notifications-Reports-and-Backup.md): channels, the daily report, the heartbeat, backups.

**Concepts and design**

- [Architecture overview](Architecture.md): the parts and who owns what.
- [The agents](The-Five-Agents.md): what each may read and do, and what it cannot.
- [Control and safety model](Control-and-Safety-Model.md): write rights, the action ledger, the pump interlock, the two entries.
- [Workflow and state machines](Workflow-and-State-Machines.md): rounds, stages and research tasks.
- [Data, archive and traceability](Data-Archive-and-Traceability.md): what is recorded and how a number is traced back.
- [Variable catalog](Variable-Catalog.md): the shared standard variable IDs, and how to extend them.
- [Research methodology](Research-Methodology.md): experimental unit, blocks, the test, the confirmatory gate.
- [Design decisions](Design-Decisions.md): the main decisions and their reasons.

**Reference**

- [Configuration reference](Configuration-Reference.md)
- [CLI reference](CLI-Reference.md)
- [HTTP, workbench and MCP interfaces](API-Reference.md)
- [Denial codes and stage events](Denial-Codes-and-Events.md)
- [Glossary](Glossary.md)

**Development**

- [Development setup, testing and CI](Development-Setup-Testing-and-CI.md)
- [Code structure and extension points](Code-Structure-and-Extension-Points.md)
- [Contributing](Contributing.md)

**Project**

- [Status and known limitations](Status-and-Known-Limitations.md)
- [FAQ](FAQ.md)

## Other documents

- [README](../../../README.md) ([中文](../../../README.zh-CN.md)): installation, the dashboard, MCP clients, Raspberry Pi deployment.
- [Architecture design document](../../diagri-agent-architecture.zh-CN.md) (Chinese): the full specification DiAGRI was built from.
- [VALIDATION.md](../../../VALIDATION.md): how the bridge-only mode was validated.
- [How this wiki is organized and edited](../README.md)
