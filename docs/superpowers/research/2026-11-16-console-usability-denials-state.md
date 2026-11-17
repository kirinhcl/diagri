# Denied("state", ...) inventory

> Research notes for console usability batch 2b, written on 2026-11-16 against the code before batch 2a (branch base 998ece2). Line numbers may have drifted since; find a site by its file and function. Site counts were checked again on 2026-11-17 against main d7d479a: 249 `Denied(...)` sites, 103 of them `state`.

Source: `src/growbridge`

Method: grep for `Denied(` on one line and for `Denied(` followed by `"state"` on the next line. No `Denied(variable, ...)` exists anywhere (only the class itself, ports.py:32, and a `raise Denied(  # comment` at workbench/api.py:461, which is code `scope`).
**103 real raise sites** (95 single-line + 8 multi-line). Three further matches are docstrings and are not sites: workflow/service.py:6, workflow/store.py:283, workflow/tasks.py:3.
`control/` has **no** `Denied("state")` sites; its `"state"` hits are `ActionState` dict keys. The brief's "control/" does not apply.

Legend for "Reach": `W` = console route under `/wb` (prefix confirmed by workbench/holdouts.py docstring; routes are in workbench/api.py and workbench/{rounds,manual_tasks,analysis,reads,compute,evidence,holdouts}.py). `M` = model tool only (agents/handlers_*.py). `W+M` = both. `I` = internal only: no route or tool caller found with grep.
Params: `(id)` marks an identifier. Where the message holds no variable but the function has one, I list it as `+name` (it must be added to the call).

## 1. One row per site

### workflow/service.py (WorkflowService)
| site / function | reach | condition | exact message | params | reason |
|---|---|---|---|---|---|
| service.py:103 create_project | W POST /projects | name blank | `a project needs a name` | none | project_name_required |
| :111 save_protocol | W POST /protocols | project id unknown | `unknown project {protocol.project_id}` | project_id (id) | record_not_found (kind=project) |
| :117 save_protocol | W POST /protocols | same id+version saved with other content | `protocol {id} v{version} exists: bump version` | protocol_id (id), version (int) | protocol_version_exists |
| :126 create_round | W POST /rounds | no saved protocol | `no protocol {protocol_id} saved for project {project_id}` | protocol_id (id), project_id (id) | protocol_not_found |
| :146 submit_run_sheet | W POST /drafts/run-sheet; M planner (handlers_common.py:103); I runtime.py:751 | round not DESIGNING/STAGE_REVIEW, or awaiting a choice | `round is {rnd.state.value}; no run sheet can be submitted` | state (raw enum) +round_id (id) +awaiting_choice | round_not_accepting_run_sheets |
| :149 submit_run_sheet | same as :146 | sheet project/protocol differs from the round's | `run sheet does not belong to this round's project and protocol` | +round_id, +sheet project_id, protocol_id, protocol_version | run_sheet_mismatch |
| :180 _findings | W via /drafts/run-sheet, /stages/{id}/approve, start; M via planner | round's protocol row missing | `protocol {rnd.protocol_id} is not saved` | protocol_id (id) | protocol_not_found |
| :185 _add_stage | W POST /drafts/run-sheet; M | sheet id+version already stored | `run sheet {sheet.id} v{sheet.version} is already in use` | run_sheet_id (id), version (int) | run_sheet_version_in_use |
| :206 _replace_run_sheet | W POST /drafts/run-sheet; M | existing stage is in another round or not PENDING_REVIEW | `stage {stage_id} is {state}; use a switch` | stage_id (id), state (raw) | run_sheet_needs_switch |
| :210 _replace_run_sheet | same | same version, other content | `same run sheet version with other content: bump version` | +run_sheet_id, version | run_sheet_version_conflict |
| :213 _replace_run_sheet | same | version lower than current | `run sheet v{sheet.version} is older than v{current.version}` | version (int), current_version (int) | run_sheet_too_old |
| :215 _replace_run_sheet | same | id+version already stored | `run sheet {sheet.id} v{sheet.version} is already in use` | run_sheet_id (id), version | run_sheet_version_in_use |
| :225 revalidate | I (no caller found) | stage not PENDING_REVIEW | `stage {stage_id} is {state}` | stage_id (id), state | stage_not_awaiting_approval |
| :243 approve | W POST /stages/{id}/approve | stage not PENDING_REVIEW | `stage {stage_id} is {state}; nothing to approve` | stage_id (id), state | stage_not_awaiting_approval |
| :246 approve | W POST /stages/{id}/approve | caller's expected_digest differs from current sheet | `the run sheet changed since it was reviewed` | +stage_id, +expected_digest, +current_digest (hashes) | run_sheet_changed_since_review |
| :278 revoke_approval | I (no caller found; the console has no revoke route) | stage not PENDING_REVIEW | `stage {stage_id} is {state}; stop it instead` | stage_id (id), state | stage_not_awaiting_approval |
| :320 start_stage | W POST /stages/{id}/start | stage not PENDING_REVIEW (RUNNING returns idempotently) | `stage {stage_id} is {state}; it cannot start` | stage_id (id), state | stage_not_startable |
| :343 _check_startable | W start | another stage on the device is live or in check | `another stage on this device is still live or being checked` | +device_id (id), +blocking_stage_id (id) | device_busy |
| :355 pause_stage | W POST /stages/{id}/pause | stage not RUNNING (PAUSED returns idempotently) | `stage {stage_id} is {state}; it cannot pause` | stage_id (id), state | stage_not_pausable |
| :372 resume_stage | W POST /stages/{id}/resume | stage not PAUSED | `stage {stage_id} is {state}; it cannot resume` | stage_id (id), state | stage_not_resumable |
| :378 resume_stage | W resume | reconcile_unsettled() still has unknown-result actions | `actions with unknown results must be settled first` | +stage_id, +count | unsettled_actions |
| :381 resume_stage | W resume | device levels differ from sheet | `device differs from the run sheet: {describe(diffs)}` | diffs: one string `channel.field expected != actual`, joined by ", " (should become a list of {channel, field, expected, actual}) | device_differs_from_run_sheet |
| :395 stop_stage | W POST /stages/{id}/stop | stage terminal | `stage {stage_id} is already {state}` | stage_id (id), state | stage_already_ended |
| :415 takeover | W POST /stages/{id}/takeover | stage not RUNNING/PAUSED (MANUAL returns idempotently) | `stage {stage_id} is {state}; cannot take over` | stage_id (id), state | stage_not_takeoverable |
| :437 handback | W POST /stages/{id}/handback | stage not MANUAL or no manual right | `stage {stage_id} is {state}; nothing to hand back` | stage_id (id), state | stage_not_in_manual |
| :494 switch_run_sheet | I (no caller found) | stage not RUNNING/PAUSED | `stage {stage_id} is {state}; cannot switch` | stage_id (id), state | stage_not_switchable |
| :525 _check_switch | I | new sheet is for another stage/experiment/project/device | `the new run sheet belongs to another stage or device` | +stage_id | run_sheet_mismatch |
| :528 _check_switch | I | new sheet is for another protocol than the round | `the new run sheet belongs to another protocol than the round` | +stage_id | run_sheet_mismatch |
| :530 _check_switch | I | new version <= current | `the new run sheet needs a higher version` | +version, +current_version | run_sheet_too_old |
| :532 _check_switch | I | id+version already stored | `run sheet {id} v{version} is already in use` | run_sheet_id, version | run_sheet_version_in_use |
| :594 choose_after_stop | W POST /rounds/{id}/choice | no awaiting_choice, or round terminal | `no stopped stage is waiting for a choice` | +round_id (id), +round_state | no_choice_pending |
| :602 choose_after_stop | W choice (`next`) | last stage already done | `no stage is left to move on to; verify the data instead` | +round_id | no_next_stage |
| :605 choose_after_stop | W choice | choice not abort/verify/next/redo (the ChoiceIn schema probably blocks it first) | `unknown choice {choice!r}` | choice (string) | unknown_choice |
| :612 abort_round | W POST /rounds/{id}/abort; also reached from choice=abort | round terminal | `round is already {state}` | state (raw) +round_id | round_already_ended |
| :619 abort_round | same (race re-check in a transaction) | round became terminal meanwhile | `round is already {fresh.state.value}` | state +round_id | round_already_ended |
| :720 _commit | W every stage-changing route (approve, start, pause, resume, stop, takeover, handback) | revision check failed (concurrent change) | `stage {stage_id} changed while the request was running` | stage_id (id) | stage_changed_concurrently |

### workflow/store.py, recovery.py, tasks.py
| site / function | reach | condition | exact message | params | reason |
|---|---|---|---|---|---|
| store.py:194 round | W many (GET /rounds/{id}, report, choice, abort, drafts); M | row missing | `unknown round {round_id}` | round_id (id) | record_not_found (round) |
| store.py:232 run_sheet | W GET /stages/{id}/run-sheet etc. | row missing | `unknown run sheet {sheet_id} v{version}` | run_sheet_id (id), version | record_not_found (run_sheet) |
| store.py:279 stage | W all /stages/{id}/* routes, /manual, /irrigation; M | row missing | `unknown stage {stage_id}` | stage_id (id) | record_not_found (stage) |
| store.py:290 update_stage | W (rev compare-and-set, mirror of service.py:720) | rowcount != 1 | `stage {row.stage_id} changed while the request was running` | stage_id (id) | stage_changed_concurrently |
| recovery.py:119 record_onsite_check | W POST /stages/{id}/onsite-check | stage not RECOVERY_CHECK/PAUSED/MANUAL | `stage {stage_id} is {state}; no check is open` | stage_id (id), state | onsite_check_not_open |
| tasks.py:62 create | W POST /goals; M (orchestrator, dispatch); I (runtime_agents.py:120) | fresh task id already exists | `task id {task.id} already exists` | task_id (id) | task_board_conflict |
| tasks.py:89 get | W/M/I (task reads, inbox, project detail); also `_advance` | row missing | `unknown task {task_id}` | task_id (id) | record_not_found (task) |
| tasks.py:168 record_revision | I | row missing | `unknown task {task_id}` | task_id | record_not_found (task) |
| tasks.py:182 _advance | M/I (agent dispatch events) | event id replayed on another task | `event {event_id} belongs to another task` | event_id (id), +task_id | task_board_conflict |
| tasks.py:200 _check_transition | M/I (agent dispatch; no console route moves a task) | transition not in table, or task terminal | `task {task.id}: {from} -> {to} not allowed` | task_id (id), from_state, to_state (raw enums) | task_transition_not_allowed |
| tasks.py:202 _check_transition | M/I | ending transition without a reason | `task {task.id}: ending from {state} needs a reason` | task_id (id), state | task_end_needs_reason |
| tasks.py:209 _check_depth | W POST /goals (create); M | parent in another project | `parent task belongs to another project` | +task_id, +parent_task_id | task_board_conflict |

### workbench/*
| site / function | reach | condition | exact message | params | reason |
|---|---|---|---|---|---|
| api.py:409 manual_stage | W POST /manual/{channel}, POST /irrigation | stage not MANUAL or no manual right | `the stage is not under manual control` | +stage_id (id), +state | stage_not_in_manual |
| evidence.py:91 verify | W POST /evidence/{card_id}/verify | ValueError from archive | `unknown evidence card {card_id}` | card_id (id) | record_not_found (evidence_card) |
| manual_tasks.py:69 _run_once | W POST /stages/{id}/manual-tasks/irrigate | 5 earlier attempts were each refused or not sent | `{MAX_ATTEMPTS} attempts of this irrigation never reached the device` | attempts (int, 5) +stage_id, +task_id, +due_at | irrigation_attempts_exhausted |
| :89 _window | W manual-tasks POST (record, irrigate), GET | stage has no started_at or window end | `the stage has not started; no manual task is due yet` | +stage_id | stage_not_started |
| :107 _due | W POST manual-tasks | now earlier than due_at minus EARLY_SECONDS | `this task is not due yet` | +task_id, +due_at (epoch s), +early_seconds | manual_task_not_due |
| :115 _check_irrigation | W POST manual-tasks/irrigate | past occurrence deadline | `this irrigation is past its deadline` | +task_id, +due_at, +deadline | irrigation_past_deadline |
| :120 _check_irrigation | W irrigate | a record already holds an irrigation_request_id | `the pump already ran, or may have, for this irrigation` | +task_id, +due_at | irrigation_already_ran |
| :122 _check_irrigation | W irrigate | status already done/late | `this irrigation is already recorded as done` | +task_id, +due_at | irrigation_already_done |
| :223 irrigate | W POST manual-tasks/irrigate | stage not RUNNING or no right_number | `a planned irrigation runs only while the stage is running` | +stage_id, +state | irrigation_stage_not_running |
| reads.py:203 _stage | W GET /stages/{id}/readings, /measurements, /history | stage missing | `unknown stage {stage_id}` | stage_id (id) | record_not_found (stage) |
| reads.py:310 project | W GET /projects/{id} | project missing | `unknown project {project_id}` | project_id (id) | record_not_found (project) |
| rounds.py:119 report_json | W GET /rounds/{id}/report | no research_report artifact | `round {round_id} has no published report` | round_id (id) | report_not_published |
| :123 report_json | same | report file missing on disk | `the report file of round {round_id} is missing` | round_id (id) | report_file_missing |
| :125 report_json | same | file digest differs | `the report of round {round_id} no longer matches its digest` | round_id (id) | artifact_digest_mismatch |
| :186 goal_task | W POST /goals | round belongs to another project | `round {body.round_id} is not in project {body.project_id}` | round_id (id), project_id (id) | round_not_in_project |
| :238 read_report | W GET /rounds/{id}/report | archive is None | `no archive is mounted: reports cannot be read` | none | archive_not_mounted |
| :272 require_project | W POST /projects/{id}/budget, POST /goals, GET /projects/{id}/conversation | project missing | `unknown project {project_id}` | project_id (id) | record_not_found (project) |
| :301 submit_goal | W POST /goals | request_id reused for a different goal | `this request id was already used for another goal` | +request_id, +task_id (the earlier task) | request_id_reused_for_other_goal |
| analysis.py:79 protocol | W POST+GET /protocols/{id}/analysis, POST /analysis/runs | no protocol in project | `no protocol {protocol_id} in project {project_id}` | protocol_id (id), project_id (id) | protocol_not_found |
| :85 freeze | W POST /protocols/{id}/analysis | a stage of the protocol version already started | `STARTED` constant: "a confirmatory analysis must be frozen before outcome data is seen: a stage of this protocol version has already started (architecture doc §6.5)" | +protocol_id, +version | analysis_freeze_too_late |
| :136 require_no_data_yet | W freeze | an experiment already has a snapshot or measurement | `experiment {experiment} already has a snapshot or a measurement: {RULE}` | experiment_id (id) (RULE is constant prose) | analysis_freeze_too_late |
| :164 snapshot_of | W POST /analysis/runs | snapshot invalidated by a correction | `snapshot {snap.id} was invalidated by a later correction` | snapshot_id (id) | snapshot_invalidated |
| :174 start | W POST /analysis/runs | no frozen script | `no analysis script is frozen for this protocol version` | +protocol_id, +version | analysis_script_not_frozen |

### research/, observer/, compute/, runtime_compute.py
| site / function | reach | condition | exact message | params | reason |
|---|---|---|---|---|---|
| research/analysis.py:328 run_frozen | W POST /analysis/runs (after workbench :174) | no frozen script (race guard) | `no analysis script is frozen for this protocol version` | +protocol_id, +version | analysis_script_not_frozen |
| :364 _begin | W POST /analysis/runs | OSError preparing run folder (logged at ERROR; detail is dropped via `from None`) | `the analysis work folder cannot be written` | none | analysis_workdir_unwritable |
| research/preregistration.py:29 require_stages_after | W POST /analysis/runs | a stage behind the snapshot started before the freeze | `snapshot {snapshot_id} holds data of a stage that started before the analysis script was frozen: {RULE}` | snapshot_id (id) (RULE is constant prose) | snapshot_predates_freeze (what=stage) |
| :47 require_measurements_after | W POST /analysis/runs (inside admit) | a measurement recorded before the freeze | `snapshot {snapshot_id} holds a measurement recorded before the analysis script was frozen: {RULE}` | snapshot_id (id) | snapshot_predates_freeze (what=measurement) |
| research/holdout.py:145 register | W POST /holdouts | outcome data for these batches already exists | `outcome data of these batches already exists in the project and may already have been seen: a holdout is registered before its outcome data exists` | +project_id, +batch_ids (list of id), +outcome_fields (list) | holdout_outcomes_exist |
| :165 register | W POST /holdouts (id is server-made, so near-unreachable) | IntegrityError | `holdout {holdout_id} is already registered` | holdout_id (id) | holdout_already_registered |
| :176 _holdout | I (model/read paths; no route found) | row missing | `holdout {holdout_id} is not registered` | holdout_id (id) | record_not_found (holdout) |
| observer/alerts.py:183 get | W POST /alerts/{event_id}/read (probable) | missing | `unknown alert {event_id}` | event_id (id) | record_not_found (alert) |
| compute/service.py:290 _load | W POST /compute/attempts/{id}/settle; M (get/fetch via _owned) | missing | `unknown attempt {attempt_id}` | attempt_id (id) | record_not_found (attempt) |
| :533 cancel | I (no caller found) | phase not prepared/reconcile/polled | `cannot cancel an attempt in phase {phase}` | attempt_id +, phase (raw) | attempt_not_cancellable |
| :622 settle_attempt | W POST /compute/attempts/{id}/settle | phase already final | `an attempt in phase {phase} is already final` | attempt_id +, phase | attempt_already_final |
| :624 settle_attempt | W settle | compare-and-set lost | `the attempt was settled by someone else meanwhile` | +attempt_id | attempt_settled_by_operator |
| :634 fetch_compute_artifacts | M researcher (handlers_researcher.py:305) | phase not fetchable or no remote job | `nothing to fetch in phase {phase}` | +attempt_id, phase | attempt_nothing_to_fetch |
| :636 fetch_compute_artifacts | M | settled_by set | `an operator settled this attempt: it is final` | +attempt_id, +settled_by | attempt_settled_by_operator |
| :658 fetch_compute_artifacts | M | operator settled during the fetch | `an operator settled this attempt during the fetch` | +attempt_id | attempt_settled_by_operator |
| :673 _discard.remove | M | OSError removing downloaded files | `settled during the fetch; the downloaded files remain ({error})` | error: raw OSError text | attempt_settled_by_operator (+ files_remain=true) |
| :684 _output_limit | M | needs_review with OUTPUT_LIMIT_MARK | `the outputs are over the limit: an operator has to settle it` | +attempt_id | attempt_outputs_over_limit |
| :689 _output_limit | M | no stored limit and no template | `no storage limit is known for this attempt: settle it` | +attempt_id, +template_id | attempt_no_storage_limit |
| :711 retry | I (no caller found) | phase != failed | `only a failed attempt can be retried, not {phase}` | attempt_id +, phase | attempt_not_retryable |
| runtime_compute.py:164 guard | M (compute tool admit hook) | snapshot invalidated | `snapshot {snap.id} was invalidated by a later correction` | snapshot_id (id) | snapshot_invalidated |

### agents/handlers_*.py (model tools; see section 3)
| site / function | reach | condition | exact message | params | reason |
|---|---|---|---|---|---|
| handlers_auditor.py:55 _started_stage | M | started_at None | `stage {stage_id} never started; there is no data yet` | stage_id (id) | stage_not_started |
| :157 raise_finding | M | deps.alerts None | `no alert book is available; the finding cannot be recorded` | none | alert_book_unavailable |
| handlers_common.py:124 require_round | M | round state != expected | `round {round_id} is {state}; this needs {expected}` | round_id (id), state, expected (raw enums) | round_wrong_phase |
| handlers_orchestrator.py:108 _stored | M (orchestrator tool; console analogue is rounds.py:301) | trigger_event_id reused by a different task | `trigger_event_id {tid!r} already belongs to task {stored.id} (owner {owner_role}); nothing was created. Use a new trigger_event_id.` | trigger_event_id, task_id (id), owner_role | request_id_reused_for_other_goal |
| :283 _read | M | artifact file digest mismatch | `artifact {artifact_id} no longer matches its recorded digest` | artifact_id (id) | artifact_digest_mismatch |
| handlers_planner.py:116 design | M | protocol missing | `no protocol {protocol_id} in project {project_id}` | protocol_id, project_id (ids) | protocol_not_found |
| handlers_report.py:110 _verified | M | snapshot invalidated | `snapshot {snap.id} was invalidated by a later correction` | snapshot_id (id) | snapshot_invalidated |
| :380 _require_registered_runs | M | confirmatory run of a snapshot is none/running | `the pre-registered confirmatory run of snapshot {snap.id} has not finished; the operator starts it with POST /wb/analysis/runs` | snapshot_id (id) | confirmatory_run_pending |
| :408 _precheck | M | task not IN_PROGRESS | `task {task.id} is {state}; nothing can be published` | task_id (id), state | task_not_in_progress |
| :414 _precheck | M | protocol missing | `no protocol {protocol_id} in project {project_id}` | protocol_id, project_id | protocol_not_found |
| handlers_researcher.py:128 _started_stage | M | stage never started | `stage {stage_id} never started; there is no data yet` | stage_id (id) | stage_not_started |
| :136 _end | M | window_end None | `stage {stage.stage_id} never started; there is no data yet` | stage_id (id) | stage_not_started |

## 2. Distinct reasons (62 reasons for 103 sites)

Param convention: ids are plain strings; `state` should be the enum value, and the console maps it to a label (never print it raw). "Operator" text below is draft English; the console owns the wording.

### Stage lifecycle (each differs in "what to do", so no merging across verbs)
| reason | sites | meaning | what happened | next | params |
|---|---|---|---|---|---|
| stage_not_awaiting_approval | 3 (:225, :243, :278) | verb needs PENDING_REVIEW but stage is elsewhere | "This stage is no longer waiting for approval (it is {state})." | "Reload the stage; if it already started, stop it instead of revoking." | stage_id, state |
| stage_not_startable | 1 | start while not awaiting approval | "This stage cannot be started because it is {state}." | "Approve the run sheet first, or reload to see where the stage is." | stage_id, state |
| stage_not_pausable | 1 | pause while not running | "The stage is {state}, so it cannot be paused." | "Only a running stage can be paused. Reload to check its state." | stage_id, state |
| stage_not_resumable | 1 | resume while not paused | "The stage is {state}, so it cannot be resumed." | "Only a paused stage can be resumed. Reload." | stage_id, state |
| stage_already_ended | 1 | stop on a finished stage | "This stage has already ended ({state})." | "Nothing to do; reload to see the final state." | stage_id, state |
| stage_not_takeoverable | 1 | take over while not running/paused | "You can only take manual control of a running or paused stage; this one is {state}." | "Wait until it runs or pause it, then take over." | stage_id, state |
| stage_not_in_manual | 2 (service :437, api :409) | manual action or handback needs MANUAL | "This stage is not under manual control." | "Take over the stage first, then retry." | stage_id, state |
| stage_not_switchable | 1 (I) | switch while not running/paused | "A run sheet can only be switched on a running or paused stage." | "Reload." | stage_id, state |
| onsite_check_not_open | 1 | no recovery check open | "No on-site check is open for this stage (it is {state})." | "Nothing to confirm; reload." | stage_id, state |
| device_busy | 1 | other stage live on device | "Another stage on this device is still live or being checked." | "Finish or stop the other stage, then start this one." | stage_id, device_id, blocking_stage_id |
| unsettled_actions | 1 | actions with unknown result | "Some device commands have an unknown outcome." | "Check the device on site and settle those actions, then resume." | stage_id, count |
| device_differs_from_run_sheet | 1 | levels differ from sheet | "The device settings differ from the run sheet." | "Fix the device or take over manually, then resume." | stage_id, diffs list [{channel, field, expected, actual}] |
| stage_changed_concurrently | 2 (service :720, store :290) | rev conflict | "Someone else changed this stage while your request ran." | "Reload and retry." | stage_id |
| stage_not_started | 4 (manual_tasks :89; M: auditor :55, researcher :128, :136) | no started_at | "The stage has not started, so there is no data or task yet." | "Start the stage first." | stage_id |
| irrigation_stage_not_running | 1 | planned irrigation needs RUNNING | "A planned irrigation can only run while the stage is running." | "Resume the stage or record the task by hand." | stage_id, state |

### Run sheets and protocols
| reason | sites | meaning | what happened | next | params |
|---|---|---|---|---|---|
| round_not_accepting_run_sheets | 1 | round not in design/review | "This round is {state} and no longer accepts run sheets." | "Open a new round." | round_id, state |
| run_sheet_mismatch | 3 (:149, :525, :528) | sheet's ids do not match target | "This run sheet is for another project, protocol, stage or device." | "Check the ids in the sheet." | round_id or stage_id, what (project\|protocol\|stage\|device) |
| run_sheet_needs_switch | 1 | replace requires PENDING_REVIEW | "This stage is {state}; its run sheet can only be replaced by a switch." | "Use a switch." | stage_id, state |
| run_sheet_version_conflict | 1 | same version, new content | "Version {v} already has different content." | "Raise the version number." | run_sheet_id, version |
| run_sheet_too_old | 2 (:213, :530) | version not above current | "This run sheet (v{version}) is older than the current v{current_version}." | "Raise the version above v{current_version}." | version, current_version |
| run_sheet_version_in_use | 3 (:185, :215, :532) | id+version stored | "Run sheet {id} v{version} already exists." | "Choose a new version." | run_sheet_id, version |
| run_sheet_changed_since_review | 1 | digest mismatch | "The run sheet changed after you reviewed it." | "Review the new version and approve again." | stage_id, expected_digest, current_digest |
| protocol_not_found | 5 (service :126, :180, workbench/analysis :79; M: planner :116, report :414) | no protocol | "Protocol {id} is not saved in project {project_id}." | "Save the protocol first." | protocol_id, project_id |
| protocol_version_exists | 1 | same id+version, other content | "Protocol {id} v{version} already exists with other content." | "Bump the version." | protocol_id, version |
| project_name_required | 1 | blank name | "A project needs a name." | "Enter a name." | none |

(protocol_not_found has 5 sites: service :126, :180, workbench/analysis :79, planner :116, report :414.)

### Rounds, tasks, goals
| reason | sites | meaning | what happened | next | params |
|---|---|---|---|---|---|
| no_choice_pending | 1 | no awaiting_choice | "No stopped stage is waiting for your decision." | "Reload the round." | round_id |
| no_next_stage | 1 | last stage done | "There is no further stage to move to." | "Choose verify data instead." | round_id |
| unknown_choice | 1 | bad enum (likely unreachable) | "That choice is not recognised." | "Reload." | choice |
| round_already_ended | 2 | round terminal | "This round has already ended ({state})." | "Nothing to do." | round_id, state |
| round_wrong_phase (M) | 1 | tool needs another round phase | "The round is {state}; this step needs {expected}." | "Wait or move the round on." | round_id, state, expected |
| round_not_in_project | 1 | goal names a foreign round | "Round {round_id} does not belong to project {project_id}." | "Pick a round of this project." | round_id, project_id |
| request_id_reused_for_other_goal | 2 (rounds :301; M orchestrator :108) | idempotency key collision | "This request id was already used for a different goal." | "Resubmit with a new request id." | task_id, request_id (or trigger_event_id), owner_role |
| task_transition_not_allowed | 1 (M/I) | illegal task move | "A task cannot go from {from} to {to}." | "Reload the task board." | task_id, from_state, to_state |
| task_end_needs_reason | 1 (M/I) | no reason | "Ending this task needs a reason." | "Add one." | task_id, state |
| task_board_conflict | 3 (:62, :182, :209) internal integrity | duplicate/foreign link | "Task link conflict" (internal) | "Report to an admin." | task_id, event_id, parent_task_id |
| task_not_in_progress (M) | 1 | publish while not in progress | "Task {id} is {state}; nothing can be published." | n/a (model) | task_id, state |
| record_not_found | 14 (project 111/310/272; round 194; run sheet 232; stage 279/203; task 89/168; attempt 290; alert 183; evidence card 91; holdout 176) | id does not exist | "That {kind} does not exist (any more)." | "Reload the list and pick it again." | kind (project\|round\|run_sheet\|stage\|task\|attempt\|alert\|evidence_card\|holdout), id, optional version |

### Reports and artifacts
| reason | sites | what happened | next | params |
|---|---|---|---|---|
| report_not_published | 1 | "This round has no published report yet." | "Wait for the analysis round to finish." | round_id |
| report_file_missing | 1 | "The report file is missing from the archive." | "Contact an admin." | round_id |
| artifact_digest_mismatch | 2 (rounds :125; M orch :283) | "The stored file no longer matches its recorded checksum (it was altered or damaged)." | "Do not trust it; contact an admin." | round_id or artifact_id |
| archive_not_mounted | 1 | "No archive is configured, so reports cannot be read." | "Ask an admin to mount the archive." | none |

### Manual tasks
| reason | sites | what happened | next | params |
|---|---|---|---|---|
| manual_task_not_due | 1 | "This task is not due yet." | "Try again from {due_at - early}." | task_id, due_at, early_seconds |
| irrigation_past_deadline | 1 | "The deadline for this irrigation has passed." | "Record it as skipped or late by hand." | task_id, due_at, deadline |
| irrigation_already_ran | 1 | "The pump already ran, or may have run, for this irrigation." | "Check the device on site; do not run it again." | task_id, due_at |
| irrigation_already_done | 1 | "This irrigation is already recorded as done." | "Nothing to do." | task_id, due_at |
| irrigation_attempts_exhausted | 1 | "{n} attempts never reached the device." | "Check the connection to the device." | attempts, stage_id, task_id, due_at |

### Analysis and holdout
| reason | sites | what happened | next | params |
|---|---|---|---|---|
| analysis_freeze_too_late | 2 (:85, :136) | "Data already exists for this protocol, so the analysis can no longer be frozen." | "Freeze before data exists; use a new protocol version." | protocol_id, version or experiment_id |
| analysis_script_not_frozen | 2 (workbench :174, research :328) | "No analysis script is frozen for this protocol version." | "Freeze the script first." | protocol_id, version |
| analysis_workdir_unwritable | 1 | "The analysis could not start: its work folder cannot be written." | "Contact an admin (server log has the cause)." | none |
| snapshot_invalidated | 3 (workbench :164; M: runtime_compute :164, report :110) | "A correction made this snapshot invalid." | "Create a new snapshot." | snapshot_id |
| snapshot_predates_freeze | 2 (prereg :29, :47) | "The snapshot holds data from before the script was frozen." | "Use a protocol version frozen before the data." | snapshot_id, what |
| confirmatory_run_pending (M) | 1 | "The pre-registered confirmatory run has not finished." | "Start it in the console." | snapshot_id |
| holdout_outcomes_exist | 1 | "Outcome data already exists, so a holdout cannot be registered." | "Use batches without outcomes." | project_id, batch_ids, outcome_fields |
| holdout_already_registered | 1 | "This holdout is already registered." | "Reload." | holdout_id |

(snapshot_invalidated sites: workbench/analysis :164, runtime_compute :164, handlers_report :110 = 3.)

### Compute
| reason | sites | what happened | next | params |
|---|---|---|---|---|
| attempt_already_final | 1 | "This attempt is already final ({phase})." | "Nothing to settle." | attempt_id, phase |
| attempt_settled_by_operator | 4 (:624, :636, :658, :673) | "An operator already settled this attempt." | "Nothing to do; reload." | attempt_id, settled_by, files_remain (bool) |
| attempt_not_cancellable | 1 (I) | "An attempt in phase {phase} cannot be cancelled." | "none" | attempt_id, phase |
| attempt_nothing_to_fetch (M) | 1 | "No outputs to fetch in phase {phase}." | n/a | attempt_id, phase |
| attempt_outputs_over_limit (M) | 1 | "The outputs exceed the storage limit." | "An operator must settle the attempt." | attempt_id |
| attempt_no_storage_limit (M) | 1 | "No storage limit is known." | "Settle the attempt." | attempt_id, template_id |
| attempt_not_retryable (I) | 1 | "Only a failed attempt can be retried." | none | attempt_id, phase |

(alert_book_unavailable, 1 M site: "No alert book is available." params none; suggested to use code `unavailable` instead.)

Reason count: 62 distinct names in section 1 (the count includes 8 reasons that exist only for model tools or dead code). One `record_not_found` covers 14 sites; per-kind reasons would add 8 more.

## 3. Sites only a model tool can reach (14)
Their refusal goes to the model, not the console.
- handlers_auditor.py:55 (_started_stage), :157 (raise_finding)
- handlers_common.py:124 (require_round)
- handlers_orchestrator.py:108 (_stored; the console equivalent is a separate site, rounds.py:301), :283 (_read)
- handlers_planner.py:116 (design)
- handlers_report.py:110, :380, :408, :414
- handlers_researcher.py:128, :136
- runtime_compute.py:164 (a compute-tool admit guard)
- compute/service.py:634, :636, :658, :673, :684, :689 (via fetch_compute_artifacts, called only from handlers_researcher.py:305)

Shared functions also reachable by the console: `workflow.submit_run_sheet` (handlers_common.py:103 and POST /drafts/run-sheet), `workflow.store.*` lookups and `tasks.create/get`, `compute._load` (settle route), and the analysis checks (the confirmatory-run check of handlers_report.py:380 has a console twin as POST /analysis/runs).

## 4. Anything odd
- Raw enum values printed: `state` is printed as `rnd.state.value`, `stage.state.value`, `task.state.value`, `attempt.phase`, and `{from} -> {to}`; none is humanized.
- Messages embedding exception text: compute/service.py:673 interpolates the raw OSError (`({error})`). research/analysis.py:364 deliberately hides the cause (`from None`), so no params are possible; the cause is only in the server log.
- Prose with embedded instructions: STARTED constant and the `RULE` constant (in preregistration/analysis) are long architecture-doc sentences; the reason should replace them, with the doc reference as a console help link.
- Embedded API paths in a model message: handlers_report.py:380 says "POST /wb/analysis/runs".
- Embedded constant: manual_tasks.py:69 formats `MAX_ATTEMPTS` (5) into the text.
- workflow/service.py:381 packs a list of diffs into one comma-joined string (`describe(diffs)`); it needs a structured list to be a param.
- Dead or unrouted code: `WorkflowService.revalidate`, `revoke_approval`, `switch_run_sheet` (incl. `_check_switch` 4 sites), `ComputeService.cancel` and `retry` have no caller in src. Their reasons are still needed in case a caller is added; there is no console route for revoke or switch.
- Duplicate of one meaning with different wording: "run sheet ... already in use" appears 3 times; "stage ... never started" 4 times (3 in model tools); "snapshot ... invalidated" 3 times; "unknown project" 3 times; "changed while the request was running" 2 times (service.py:720 and store.py:290).
- `Denied("state")` used for things that are not state, which a finer reason fixes: unknown ids (should be 404-like), idempotency-key reuse (conflict), missing config (`archive_not_mounted`, `alert_book_unavailable`; the code `unavailable` already exists for this in ports.py), validation (blank project name, unknown choice).
- Inconsistent code across near-identical sites: unknown project is `state` at reads.py:310 and rounds.py:272, but `scope` at workbench/holdouts.py:61; `workbench/api.py:461` measurement uses `scope`.
- The stage_not_pausable/resumable messages are asymmetrical to idempotency: pause on PAUSED, resume on RUNNING, takeover on MANUAL, start on RUNNING all return success, so the denial only fires for truly invalid states.
