# Denial codes and stage events

[简体中文](../zh-CN/Denial-Codes-and-Events.md)

This page is for operators and developers who need to read a refusal, a stage event or an action state. It lists every denial code, every stage event kind and every action state, with where each one comes from.

The conditions were read from the code and its tests, which run on the simulated AC5 only; see [Status and known limitations](Status-and-Known-Limitations.md).

## Denial codes

A denial is the exception `Denied(code, message)` in [`ports.py`](../../../src/growbridge/ports.py). The docstring of `Denied` names 33 codes, and the code raises exactly those 33. The workbench answers a denial with HTTP 409 for `state`, 401 for `session`, 429 for `locked` and 403 for every other code; see [HTTP, workbench and MCP interfaces](API-Reference.md#workbench-routes).

| Code | Meaning | Raised by | What the caller should do |
| --- | --- | --- | --- |
| `host_unregistered` | This machine is not the registered write host of the device, or another host is already registered. | control service ([`control/service.py`](../../../src/growbridge/control/service.py)); `register_write_host` in [`runtime.py`](../../../src/growbridge/runtime.py) | Write from the registered host. `growbridge host register` registers this machine; it is refused while another host is registered. |
| `controls_disabled` | `controls_enabled` is `false` in the configuration file. | control service | Set `controls_enabled = true` and restart the daemon. |
| `right_invalid` | The write right is unknown, revoked or from an earlier recovery number; a manual write right has no operator; irrigation was asked without a manual write right; or the queued action was voided before it was sent. | control service, [`control/rights.py`](../../../src/growbridge/control/rights.py) | Do not repeat the request. Get a new write right through the workflow (start, resume or take over the stage) and send a new request. |
| `right_held` | A stage or manual write right was asked for while a stage write right is held for the device. | control service | Pause, stop or take over the stage that holds the right first. |
| `scope` | The request is outside what the write right or the caller covers: another device, a channel or level the right does not list, another stage, experiment or operator, an irrigation that is too long or is not "pump on". For model tools: a task id that is not the task the run was started for, a call outside a dispatched run, a task, stage, round, experiment, data snapshot, artifact or compute job of another project or role, an experiment claimed by two projects, or a snapshot that holds holdout outcomes. For the workflow: a run sheet whose `experiment_id` belongs to another project. | control service, `control/rights.py`, compute service, workflow service (`WorkflowService.submit_run_sheet`), model tool handlers ([`agents/`](../../../src/growbridge/agents)) | Change the request. The same request will be refused again. |
| `pump_on_forbidden` | An ordinary write tried to switch the pump on. | `control/rights.py`; `POST /wb/manual/{channel}` in [`workbench/api.py`](../../../src/growbridge/workbench/api.py) | Use `POST /wb/irrigation` on the LAN entry. |
| `interlock` | The pump interlock is on: pump-off is not confirmed. Ordinary writes are refused, and a stage cannot start or resume. | control service; workflow service ([`workflow/service.py`](../../../src/growbridge/workflow/service.py)) | Check the pump on site, then record an on-site check with `POST /wb/stages/{stage_id}/onsite-check`. The executor keeps trying to switch the pump off. |
| `not_connected` | There is no live BLE connection, or the device state could not be read. | control service | Wait for the connection and send the request again. |
| `stale` | The latest sample is older than `stale_seconds`. Stage and manual writes need fresh data. | control service | Wait for fresh samples (`GET /health` shows `stale`) and send the request again. |
| `request_id_reused` | The `request_id` was already used with other arguments. | control service | Use a new `request_id` for a new action. Reuse an id only to repeat the identical request. |
| `not_operator` | The caller is not an operator and is not a model role, or the operator name is empty. | [`workflow/permissions.py`](../../../src/growbridge/workflow/permissions.py); control service (`onsite_check`); `AlertBook.mark_read` | Repeat the action as a logged-in operator. |
| `model_role` | A model role asked for a stage, approval or control action; a role was given a tool outside its set; the role is not a model role; or no model is configured for it. | `workflow/permissions.py`; [`agents/tools.py`](../../../src/growbridge/agents/tools.py); [`agents/dispatch.py`](../../../src/growbridge/agents/dispatch.py) | Nothing a model role can do. An operator has to act. If it comes from `tools` in the configuration, remove the tool name. |
| `reauth_required` | The action needs a re-authentication within the last 300 seconds. | `workflow/permissions.py` | Call `POST /wb/reauth`, then repeat the request. |
| `entry` | The request did not arrive on a registered entry, did not pass the `Origin` and `X-GrowBridge-UI` check, came on another entry than its session, or the action is offered on the LAN entry only. | `workbench/api.py` | Use an address in `lan_hosts` or `overlay_hosts` on the matching port, and send both headers. Irrigate from the LAN entry. |
| `approval_invalid` | The stage has no valid approval; the approval no longer fits (run sheet content or version, stage, experiment, device, capability version or recovery number changed); the run sheet has blocking findings; or a safety configuration has no approver. | workflow service; control service (`approve_safety`) | Resolve the findings and approve the stage again. |
| `state` | The object does not exist, is not in a state that allows the action, or changed while the request was running. For the analysis: freezing a script after a stage under the protocol version has started, running without a frozen script, or running a snapshot that a later correction invalidated. For a report: a script is frozen and the run of a cited snapshot has not ended. Also: a snapshot or a measurement already exists when a script is frozen, or a stage or a measurement behind a snapshot dates from before the freeze. | workflow service, [`workflow/store.py`](../../../src/growbridge/workflow/store.py), [`workflow/tasks.py`](../../../src/growbridge/workflow/tasks.py), `workbench/api.py`, [`workbench/analysis.py`](../../../src/growbridge/workbench/analysis.py), compute service, holdout registry, `AlertBook`, model tool handlers | Read the current state, for example with `GET /wb/stages/{stage_id}`, and decide again. |
| `safety_conflict` | A protection rule of the approved safety configuration acts on a channel that the run sheet does not make host-controlled. | workflow service, from `ControlService.safety_conflicts` | Change the run sheet (a new version) or the safety configuration, then approve again. |
| `budget` | The project's call budget or cost budget is used up or was never set; or a task passed its revision limit or delegation depth. | [`agents/budget.py`](../../../src/growbridge/agents/budget.py); `workflow/tasks.py` | Stop. The task needs a person's decision. An operator sets or raises the project's budget with `POST /wb/projects/PROJECT_ID/budget`; a task that is already in `needs_attention` stays there. |
| `session` | There is no session, or it is invalid, expired or older than the current recovery number; the name or secret is wrong; or a role token does not match. | `workbench/api.py`, [`workbench/auth.py`](../../../src/growbridge/workbench/auth.py) | Log in again with `POST /wb/login`. |
| `member` | The submitter is not mapped to a CSC project member. | compute service ([`compute/service.py`](../../../src/growbridge/compute/service.py)) | Not reachable in the daemon; see the note below. |
| `quota` | No task budget or project balance is recorded; a job would exceed the task budget, the service cap or the project balance; or the retry limit of the template is reached. | compute service | Not reachable in the daemon; see the note below. |
| `param` | A compute job has an unknown template or template version, an unknown or missing parameter, a value of the wrong kind or range, or an input path outside the snapshot. For a report: an experiment listed in two rounds, an unknown treatment, or measurements that do not fit the allocation. For a frozen analysis script: one that is empty, or does not compile (a syntax error or a NUL byte). For a report: cited snapshots from more than one protocol version, or from another protocol. | compute service; [`agents/handlers_report.py`](../../../src/growbridge/agents/handlers_report.py) | Correct the input and send it again. |
| `clock_unsynced` | The clock is not synchronised, so data cannot be frozen. | [`archive/snapshot.py`](../../../src/growbridge/archive/snapshot.py) | Freeze again once the clock is synchronised. |
| `script_hash` | The analysis script differs from the hash in the research protocol, or from the script already frozen for this protocol version (the `POST /wb/protocols/{protocol_id}/analysis` route). | [`research/analysis.py`](../../../src/growbridge/research/analysis.py) | Use the frozen script. |
| `snapshot_incomplete` | The data snapshot is marked incomplete, or its files do not match its manifest. | `research/analysis.py`; [`agents/handlers_researcher.py`](../../../src/growbridge/agents/handlers_researcher.py); `agents/handlers_report.py` | Freeze a new snapshot and use that one. |
| `already_run` | The confirmatory analysis already ran on this snapshot, or is running on it (the `POST /wb/analysis/runs` route). | `research/analysis.py` | Do not run it again; a confirmatory analysis runs once. |
| `batches` | A holdout was registered with fewer than 2 development batches, or with no holdout batch. | [`research/holdout.py`](../../../src/growbridge/research/holdout.py) | Register with at least 2 development batches and at least one holdout batch. |
| `model_unregistered` | The model was not registered for the holdout before it was evaluated, or the model hash given is not a registered one. | `research/holdout.py` | Register the model, its features and its preprocessing first. |
| `sandbox_unavailable` | The platform has no isolation backend, so no analysis script runs. | [`research/sandbox.py`](../../../src/growbridge/research/sandbox.py) | Run the analysis on a platform that has the sandbox (macOS in this code). |
| `unsettled` | The control service has not finished starting; the old write path is not confirmed stopped; or an earlier action has an unknown result. | control service | Wait for startup. Otherwise the result has to be settled by read-back or by an on-site check before ordinary writes continue. |
| `cooldown` | An irrigation is running, or the last one started less than `pump_cooldown_seconds` ago. | control service | Wait, then send the irrigation again. |
| `unavailable` | An optional backend is not configured: search, compute service, sandbox or holdout registry. | [`agents/handlers_common.py`](../../../src/growbridge/agents/handlers_common.py) | Nothing the caller can do; the daemon was built without that backend. |
| `locked` | Too many failed logins in 15 minutes: 5 for one name from one address, or 25 for one name from all addresses. | `workbench/auth.py` | Wait until the failures are older than 15 minutes. |

Notes on reach. `growbridge serve` starts no compute service, so `member`, `quota` and the compute cases of `param`, `scope` and `state` cannot occur in the daemon. `batches` is raised only by `HoldoutRegistry.register`, which nothing in `src/` calls. `script_hash` and `already_run` come from `ConfirmatoryRunner.freeze_analysis` and `run_frozen`, through the two analysis routes of the workbench. The workbench also uses the word `param` as the code in its HTTP 422 body; that is not a `Denied`.

A refusal when a request is first submitted leaves no record in the action ledger, so the same `request_id` can be sent again. A refusal at the re-check just before sending stores the action as `void`; the same `request_id` then returns that record, so a new id is needed.

| Who receives the denial | What it sees |
| --- | --- |
| HTTP client of the workbench | The status above and the body `{"detail": {"code": "<code>", "message": "<text>"}}`. |
| Model role, inside a tool call | An error tool result `Error: denied (<code>): <message>`, cut at 500 characters. |
| Dispatcher, outside a tool call (for example `budget`) | The task moves to `needs_attention` with the reason `<code>: <message>`. |
| Executor | The write is skipped for this tick and `<request_id>: <code>` is added to `TickReport.denied`. A later tick tries again. |
| Workflow service, while it applies a stage event | `state` means the stage moved on and the event is ignored. Any other code is raised to the reporter. |
| `growbridge host register` | The message, and exit code 2. |

## Stage events

`StageEventKind` in `ports.py` has 12 members. The executor ([`executor/engine.py`](../../../src/growbridge/executor/engine.py)) reports 11 of them and the observer ([`observer/service.py`](../../../src/growbridge/observer/service.py)) reports `alert_pause`. Both call `WorkflowService.report`.

| Kind | Reported by | Condition | `detail` fields | What the workflow service does |
| --- | --- | --- | --- | --- |
| `disconnect_affects` | executor | On the tick that sees the link come back, the stage is `running` and at least one reason holds: `due_action`, `device_differs`, `unknown_result`, `gap_too_long`. | `reasons`, `seconds`, `state_unreadable` | pauses the stage |
| `readings_stale` | executor | The stage is `running`, the link is up, and no valid reading arrived within `sampling.max_gap_seconds` of the run sheet. | none | pauses the stage |
| `readings_stale` | executor | The stage is `running`, readings are fresh, and reading back the device state has failed for longer than `sampling.max_gap_seconds`. | `reason` = `"state_unreadable"`, `seconds` | pauses the stage |
| `external_change` | executor | The stage is `running` and the device differs from what the executor last confirmed in this phase. | `differences`: a list of `channel`, `field`, `expected`, `actual` | pauses the stage |
| `external_change` | executor | The stage is `running` and 3 writes in a row on one channel ended `failed`. | `channel`, `level`, `failed` | pauses the stage |
| `clock_anomaly` | executor | The stage is `running` and the wall clock is not trusted: the host is not synchronised, or the clock jumped by more than 5 seconds. | none | pauses the stage |
| `result_unknown` | executor | The stage is `running` and the control service has actions with an unknown, unsettled result. | `request_ids` | pauses the stage |
| `pump_off_unconfirmed` | executor | The pump interlock is on, a stage is active, and this tick's switch-off was not confirmed. | none | moves the stage to `recovery_check` |
| `transport_unconfirmed` | executor | The stage is `running`, `paused` or `manual`, and the old write path is not confirmed stopped. | none | moves the stage to `recovery_check` |
| `end_condition_met` | executor | The stage is `running`, `end_pending` is false, and `duration_seconds` have passed since `started_at`. | none | keeps `running` and sets `end_pending` |
| `end_actions` | executor | `end_pending` is true and every end action on a host-controlled channel was sent. The pump is left out. | `confirmed` | `confirmed` true: ends the stage. `confirmed` false: moves it to `recovery_check`. |
| `alert_pause` | observer | An alert rule with `pause_stage` fired and a stage is active. | `rule`, `alert` | pauses the stage |
| `rule_pause` | executor | The stage is `running` and a feedback rule with `on_missing = "pause"` has no valid reading of its sensor. | `rules` | pauses the stage |
| `max_wait_expired` | executor | The stage is `paused` for longer than `max_wait_seconds` of the run sheet. | none | `on_expiry = "stop"`: stops the stage. Otherwise it stays `paused` and the expiry is written to the history. |

Every event the executor reports for a `running` stage also carries `detail.right_number`, the number of the stage write right it was observed under. The `detail` of an applied event is saved with the stage history (`wf_history.detail`). When an event pauses a stage or puts it into `recovery_check`, the runtime raises the alert `stage_waiting` with the event name and that detail; see the [troubleshooting runbook](Troubleshooting-Runbook.md). `DEFAULT_ALERT_RULES` in `runtime.py` is empty, so the daemon has no alert rule that could report `alert_pause`.

| Outcome in the workflow service | When | Effect |
| --- | --- | --- |
| ignored | The stage is unknown, or the event id was seen before. | none |
| dropped | `detail.right_number` is not the stage write right the stage holds now; or the stage is not in a state the event applies to. | The event is recorded as `dropped`. |
| pauses the stage | The kind is one of the seven pause kinds and the stage is `running`. | State `paused`, the stage write right is revoked, `paused_at` is set. |
| moves the stage to `recovery_check` | The stage is `running`, `paused` or `manual`; for `end_actions`, `running` with `end_pending`. | State `recovery_check`; the stage, manual and care write rights are revoked; `prior_state` keeps the earlier state. |
| ends the stage | `end_actions` with `confirmed` true, on a `running` stage with `end_pending`. | State `ended`, the stage write right is revoked. The round moves to `stage_review` when more stages remain, otherwise to `data_verification`. |
| stops the stage | `max_wait_expired` on a `paused` stage whose run sheet says `on_expiry = "stop"`. | State `stopped`. The round then waits for a choice (`awaiting_choice`). |

An event that is applied is recorded as `applied` in the same transaction as the state change. The same event id advances a stage at most once. The executor builds the id as `<kind>:<stage_id>:<key>:<phase start>` and reports each id once per phase; a phase is one combination of stage, stage state and stage write right.

## Action states

`ActionState` in [`archive/models.py`](../../../src/growbridge/archive/models.py) has 6 members. Each record of the action ledger is in one of them. The Chinese labels are in the [Glossary](Glossary.md#state-values).

| State | Meaning | Set when |
| --- | --- | --- |
| `pending` | The action is in the ledger and nothing was sent. | The control service accepts a request. |
| `maybe_sent` | The write is on its way to the device. | Just before the write is sent. |
| `confirmed` | The read-back showed the planned level, in manual mode. `confirmed_at` and `confirmed_level` are set. | The read-back after the write matched. |
| `unknown` | Result unknown: the effect of the write could not be established. Until it is settled (`settled_at`), ordinary writes are refused with `unsettled`. | No receipt came, the link broke while sending, the read-back was unavailable, the process stopped while the action was `maybe_sent`, or the pump-off after an irrigation was not confirmed. |
| `failed` | The write was not applied. | The write could not be sent, the device rejected it, the read-back level differed, or the read-back mode was not manual. |
| `void` | The action was queued and never sent. | At startup, when its write right was handed over, when the recovery number changed, or when the re-check just before sending refused it. |

An `unknown` action is settled by a read-back of the device (not for the pump), by a confirmed pump-off (for the pump), or by an on-site check. The executor replaces a `failed` or `void` action with a new request that names the old one in `supersedes`.

## See also

- [HTTP, workbench and MCP interfaces](API-Reference.md)
- [Control and safety model](Control-and-Safety-Model.md)
- [Workflow and state machines](Workflow-and-State-Machines.md)
- [Troubleshooting runbook](Troubleshooting-Runbook.md)
- [Glossary](Glossary.md)
