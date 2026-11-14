# The five agents

[简体中文](../zh-CN/The-Five-Agents.md)

This page is for readers who want to know what each agent is allowed to do, and for developers who are about to change one. For each agent it says what it is for, what it may read, what it may do, what it can never do, and where its code is.

> **Status.** Tested on the simulated AC5 and with scripted model replies only. See [Status and known limitations](Status-and-Known-Limitations.md).

## Two kinds of agent

| Agent | Kind | In one line |
| --- | --- | --- |
| Orchestrator | model role | Turns a goal into research tasks for the other two model roles. |
| Planner | model role | Drafts run sheets and checks them. |
| Researcher | model role | Freezes data, analyzes it and publishes the report. |
| Executor | deterministic program | Carries out the approved run sheet on the device. |
| Observer and notifier | deterministic program | Watches readings and health, raises alerts, sends notifications. |

The split follows one rule: a model may reason, but only a program with fixed behavior may act on the device. The same inputs always give the same action, so the action can be tested. The split is enforced in code, not in the prompts.

## Rules shared by the three model roles

- **A fixed tool list.** `ROLE_TOOLS` in [`agents/tools.py`](../../../src/growbridge/agents/tools.py) names the tools of each role. The configuration (`roles.<name>.tools`) can only narrow it. `build_role_tools` in [`agents/handlers.py`](../../../src/growbridge/agents/handlers.py) refuses to build a tool set that differs from the list.
- **No control tool, by name.** `CONTROL_TOOLS` lists stage and device tool names such as `start_approved_stage`, `approve_run_sheet`, `set_light` and `run_pump`. Asking for one is `Denied("model_role")`, and no handler exists for any of them.
- **Identity from the server.** Every handler acts as `Actor(kind="model", id=<role>)`. The workflow service refuses that kind for approving, starting, pausing, resuming, stopping and taking over ([`workflow/permissions.py`](../../../src/growbridge/workflow/permissions.py)). Tool inputs forbid unknown fields, so a model that adds `"approved": true` gets a validation error.
- **Tool output is data.** Every tool result goes back to the model inside a `tool_result_data` block marked as untrusted ([`agents/loop.py`](../../../src/growbridge/agents/loop.py)).
- **Reading the web costs the write tools.** After a tool flagged `reads_web` has run, the tools flagged `writes` or `sandbox` disappear for the rest of that run. Web text may carry instructions, so a run that has read it can no longer write anything.

An example. A planner's draft carries the note "approved by the operator". Nothing happens. An approval is an `Approval` record written by `WorkflowService.approve`, which accepts only an operator who re-authenticated within the last 300 seconds (`REAUTH_SECONDS`).

The system prompts are in [`agents/roles.py`](../../../src/growbridge/agents/roles.py). They repeat these limits to the model, but the limits do not depend on the model obeying them.

## Orchestrator

**For.** The single entry point for the user's goal. It decides what the user wants, creates research tasks, hands them to the planner or the researcher, and files validated run sheets for review.

**May read.** Only inside the project of the task it is running: tasks, round state and stage states (`get_project_state`). The state and recent history of one stage (`get_run_status`). The state and artifact ids of the running task and the tasks delegated below it (`get_task_status`). A registered text artifact of a task of the project, checked against its recorded digest (`read_artifact`).

**May do.** Create a task for the planner or the researcher (`create_research_task`, `delegate_task`). File a run-sheet draft for operator review (`submit_run_for_review`).

**Can never.** Approve a run sheet, control a stage or write to the device. Create a project, a research protocol or a round: those methods accept only an operator or workflow identity.

**How a goal reaches it.** An operator states a goal with `POST /wb/goals`, which creates a research task owned by the orchestrator. The project needs a call budget first (`POST /wb/projects/PROJECT_ID/budget`). There is no conversation route: a goal is one request, and the orchestrator has no tool to ask the operator a question. Only the tests have driven this role, with a scripted model.

**Code.** [`agents/handlers_orchestrator.py`](../../../src/growbridge/agents/handlers_orchestrator.py).

## Planner

**For.** Turn a research goal into a run sheet that the device can carry out and an operator can review.

**May read.** Sensors, channels and level ranges (`get_device_capabilities`). Snapshots and measurement counts of an earlier experiment of its own project (`find_prior_runs`). Web search results (`lookup_crop_conditions`, `search_and_verify_sources`); the runtime wires no search backend, so both return `unavailable` today.

**May do.** Check a saved protocol's design (`check_experimental_design`). Estimate the number of blocks or units (`estimate_sample_size`). Validate a run sheet without saving it (`validate_run_sheet`). File a run-sheet draft (`save_plan_draft`): the stage becomes `pending_review` and waits for an operator. A run sheet is the only thing this tool saves. Search the evidence cards (`query_evidence`; each card says whether it is verified) and propose a new one (`propose_evidence_card`) to cite in a run sheet. A proposal is always stored **unverified**, with `model:planner` and the running task as its source, whatever the input says; the card id is made by the server and one task may propose 20 cards at most. A planner that has read web content loses this write tool for the rest of the run, so it proposes before it searches.

**Can never.** Verify an evidence card: an operator does that, as a record of its own, and the review of the run sheet shows the hint `unverified_source` until then. Approve its own draft. Save or change a research protocol: it has no tool for that, and `save_protocol` refuses a model identity. File a draft with blocking findings: the same validation runs again inside the workflow service.

**Code.** [`agents/handlers_planner.py`](../../../src/growbridge/agents/handlers_planner.py); the checks are in [`planning/`](../../../src/growbridge/planning/).

## Researcher

**For.** Freeze the data of a stage, analyze it, and publish the round's report.

**May read.** Evidence cards in the archive (`query_evidence`). A snapshot of its own project, inside the sandbox. The state of a compute job (`get_compute_job`).

**May do.**

| Tool | What it does |
| --- | --- |
| `freeze_dataset` | Freezes a stage's data into a verified snapshot. If the snapshot is complete, moves the round from `data_verification` to `analysis`. |
| `run_local_analysis` | Runs a script on a snapshot in the sandbox. The result is always labelled exploratory. |
| `submit_compute_job`, `fetch_compute_artifacts` | Submit a job from a registered template and fetch its outputs. Return `unavailable` unless the compute service is configured; inputs must be verified snapshots of the task's own project. |
| `publish_research_report` | Writes the report. The label and the numbers are computed from the frozen data. A final report moves the round from `analysis` to `delivered`. |

**Scoped to its task.** `freeze_dataset`, `run_local_analysis` and `publish_research_report` take a `task_id`, and that id must be the task the dispatcher is running (see "Bound to the running task" below), which must be one owned by the researcher. Every stage, round or snapshot id in the same call must then belong to that task's project, or the call is refused with `Denied("scope")` before anything is written, mounted or read. An unknown snapshot and another project's snapshot get the same answer, so the reply reveals nothing. A snapshot that contains outcomes of a held-out batch is refused as well. The reason: a model names ids freely, and without this check a task in one project could read another project's data or advance another project's round. The checks are `own_task` in [`agents/handlers_report.py`](../../../src/growbridge/agents/handlers_report.py) and `require_round` and `scoped_snapshot` in [`agents/handlers_common.py`](../../../src/growbridge/agents/handlers_common.py).

**Bound to the running task.** The model supplies every id in a tool call, so none of them is trusted. The dispatcher binds the task it is running for the whole run, and each tool compares the ids in its input with that binding. The `task_id` a model passes must equal the bound task: a researcher working on one task cannot name another task, in this project or in another, and a tool call made outside a dispatched run is refused. The same holds for the other two model roles. They may name only the project, rounds, stages and experiments of the bound task's project. `get_task_status` answers only for the bound task and the tasks delegated below it, `read_artifact` only for artifacts of tasks of the project, and `delegate_task` accepts only the bound task as parent. Every refusal is `Denied("scope")`. The binding is a context variable set by `Dispatcher` in [`agents/dispatch.py`](../../../src/growbridge/agents/dispatch.py) and read through `bound_task`, `require_bound` and `require_project` in [`agents/handlers_common.py`](../../../src/growbridge/agents/handlers_common.py). A context variable is used because the tools are built once and shared, while runs can overlap: each asyncio task sees only its own binding.

**One owner per experiment.** A snapshot belongs to the project that owns its experiment, found through the stage that runs it. An experiment id belongs to one project: the workflow refuses a run sheet whose `experiment_id` is already used by a stage of another project (`Denied("scope")` in `WorkflowService.submit_run_sheet`), and a lookup on an experiment that stages of two projects claim is refused as well, so such an id can never make one project's data look like another's.

**Can never.** Change a run sheet. Run code outside the sandbox: on macOS the sandbox has no network and cannot read the home or data directory; on other platforms there is no sandbox yet and the tool refuses with `sandbox_unavailable`. Decide that its own result is confirmatory: the flags it may pass can only make the label stricter.

**Code.** [`agents/handlers_researcher.py`](../../../src/growbridge/agents/handlers_researcher.py), `agents/handlers_report.py`, [`research/`](../../../src/growbridge/research/). The method is explained on [Research methodology](Research-Methodology.md).

## How a task passes from one role to another

Roles do not talk to each other. One role leaves a research task on the task board, and the dispatcher later runs the owner of that task.

1. The orchestrator calls `delegate_task`. A `ResearchTask` is stored with `owner_role`, the goal, constraints, evidence references, expected artifacts, a budget, the parent task, a `trigger_event_id` and a `correlation_id`. One task is stored per `trigger_event_id`; a repeated call returns the first task.
2. Every 30 seconds the runtime lists the tasks that are `in_progress` and owned by a model role, and calls `Dispatcher.run_task` for each ([`agents/dispatch.py`](../../../src/growbridge/agents/dispatch.py)).
3. The dispatcher records the trigger in `dispatch_claims` before the model runs. A trigger is run once, also after a crash or a restart.
4. The role receives its system prompt and the task record as JSON. It sees no chat history of the other role. Anything else it needs, it reads with its tools.
5. If the model ends its turn normally, the task becomes `done`, or `needs_review` when the published report needs a human look. Anything else (an error, a refusal, a truncated reply, 20 turns used up, an exhausted budget) moves the task to `needs_attention` with the reason, and raises an alert.

The reason for the task board: a hand-off that lives in a database row survives a restart and can be audited. A hand-off that lives in a conversation does neither.

## Call budget

| Limit | Where | What happens at the limit |
| --- | --- | --- |
| Calls and cost per project, shared by all three roles | `CallBudget` in [`agents/budget.py`](../../../src/growbridge/agents/budget.py) | Each model call is reserved before it is made. `Denied("budget")`; the task goes to `needs_attention`. |
| 20 model turns per run | `max_turns` in `run_agent` | The task goes to `needs_attention`. |
| Delegation depth, 2 by default | `Budget.max_delegation_depth`, checked by `TaskBoard.create` | The new task is refused with `Denied("budget")`. |
| One run per trigger | `dispatch_claims` | The task is not run again. |

A project without a budget is refused at the first call. `Budget.max_revisions` is counted by `TaskBoard.record_revision`, but no tool calls it yet.

## Executor

**For.** Carry out the approved run sheet, and nothing else.

**May read.** The active stage with its run sheet and write-right numbers (`StagePort.active_stage`). Sensor readings, the device state, the safety configuration and the action receipts (`ControlPort`).

**May do.** Submit writes through `ControlPort.submit`, each under the right that matches its purpose: timed actions, feedback rules and end actions under the stage write right; care rules under the care write right; protection rules under the protection write right. Call `pump_off` while the pump interlock is on. The pump watchdog ([`executor/watchdog.py`](../../../src/growbridge/executor/watchdog.py)) does the same, and only that, when the pump reads back as on while DiAGRI is not irrigating: it also raises an alert and records an `unexpected_watering` intervention against the active stage through `StagePort.record_intervention`. Report stage events to the workflow service.

**Can never.** Call a model. Switch the pump on. Change a stage's state: it only reports, and the workflow service decides. Write a channel that the run sheet leaves to the device.

**Why it never calls a model.** The engine decides from four inputs: the run sheet, the safety configuration, the readings and the clock. Given the same four, it always does the same thing, so every decision can be replayed in a test and explained afterwards from the action ledger. It also means that overheating protection and the pump interlock do not wait for a network call.

Each tick does six things in order: pump-off interlock (followed by the pump watchdog); protection rules; link outage accounting; the `running` stage (checks first, then timed actions, feedback rules, end condition and end actions); care rules when the stage is neither `running` nor `manual`; the longest wait of a `paused` stage.

**Code.** [`executor/engine.py`](../../../src/growbridge/executor/engine.py), with pure rule evaluation in [`executor/rules.py`](../../../src/growbridge/executor/rules.py) and clock and outage handling in [`executor/outage.py`](../../../src/growbridge/executor/outage.py). See [Control and safety model](Control-and-Safety-Model.md).

## Observer and notifier

**For.** Notice what needs a person, and tell them.

**May read.** Sensor readings and the active stage. For the daily report, the samples and action records in the archive and the interventions recorded by the workflow service.

**May do.** Evaluate threshold alert rules and keep the alert book (`AlertBook`). Queue each alert once per channel in the outbox and retry delivery with backoff (`Outbox`). Report an `ALERT_PAUSE` stage event for a rule marked `pause_stage`; the workflow service then pauses a `running` stage. Render the daily report from a template: every figure comes from `compute_daily_metrics`. Check run health with six probes (`RunHealthCheck`).

**Can never.** Write to the device. Resume, stop or approve anything. Put a number into a report that the metrics did not compute.

**Why it never calls a model.** An alert that depends on a model would be silent exactly when the model is down. The daily report is template-only: `render_daily_report` accepts an optional model-written narrative, but `Runtime._report_text` never passes one.

**Not started yet.** The runtime ships with an empty alert-rule list (`DEFAULT_ALERT_RULES`), and the external monitor (`ExternalMonitor`) runs only when both heartbeat URLs are set in the environment. Delivery to real Telegram and email has not been verified.

**Code.** [`observer/`](../../../src/growbridge/observer/): `service.py`, `alerts.py`, `outbox.py`, `metrics.py`, `report.py`, `health.py`, `channels.py`. See [Notifications, daily reports and backup](Notifications-Reports-and-Backup.md).

## What still works when the model API is down

`Runtime.tick` never calls a model, so everything on the tick continues: sample ingestion, the executor, recovery follow-up, alerts, notification delivery, the daily report, backups and the health check. An approved stage runs to its end, with its end actions. Care rules, protection rules and the pump interlock keep working. The operator can still approve, start, pause, resume, take over and irrigate through the workbench.

What waits is the work only a model does: new drafts, analysis and reports. A failed model call moves that one task to `needs_attention` and raises an alert. If no model client can be built at start-up, the daemon raises a `model_client` alert and serves without the model-role loop.

The tests that state this are `test_tick_never_calls_a_model` and `test_stage_runs_to_its_end_while_the_model_fails_on_every_call` in [`tests/e2e/test_e2e_agents.py`](../../../tests/e2e/test_e2e_agents.py).

## See also

- [Architecture overview](Architecture.md)
- [Control and safety model](Control-and-Safety-Model.md)
- [Workflow and state machines](Workflow-and-State-Machines.md)
- [Research methodology](Research-Methodology.md)
- [HTTP, workbench and MCP interfaces](API-Reference.md)
- [Configuration reference](Configuration-Reference.md)
- [Architecture document](../../diagri-agent-architecture.zh-CN.md), sections 2 and 5 to 9
