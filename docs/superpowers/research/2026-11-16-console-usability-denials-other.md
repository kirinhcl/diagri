# Denials other than `state` — site map for the reason/params design

> Research notes for console usability batch 2b, written on 2026-11-16 against the code before batch 2a (branch base 998ece2). Line numbers may have drifted since; find a site by its file and function. Site counts were checked again on 2026-11-17 against main d7d479a: 249 `Denied(...)` sites, 103 of them `state`.

Source root: `src/growbridge` (paths below are relative to it).
Found by AST scan (all `Denied(...)` calls, multi-line included, first arg checked): **146 non-`state` sites**. No site uses a variable as the code; all codes are string literals.
Counts per code: scope 32, param 30, snapshot_incomplete 7, approval_invalid 7, session 6, right_invalid 6, budget 6, model_role 5, quota 4, entry 4, unsettled 3, script_hash 3, not_operator 3, interlock 3, host_unregistered 3, batches 3, safety_conflict 2, pump_on_forbidden 2, not_connected 2, locked 2, cooldown 2, and 1 each of unavailable, stale, sandbox_unavailable, right_held, request_id_reused, reauth_required, model_unregistered, member, controls_disabled, clock_unsynced, already_run. (Counts differ slightly from the brief's grep, e.g. scope 32 vs 29, param 30 vs 29: the AST finds multi-line raises.)

Legend. Reach: **M** = model tool (agents/handlers_*.py or agents/tools.py/dispatch.py; the refusal goes to the model as text `denied (code): message`, see `agents/tools.py:206`), **R** = route reachable by the console, **I** = internal service method (reaches the console only through a route that calls it; I name the route when known). "Route" is not fully traced for shared service methods; where I write `via workflow/compute/control routes` the same method is called from several routes.
Params: `(id)` = an identifier, others are plain values.

## 1. Site table

### budget (6)
| site | reach | condition / exact message | params | reason |
|---|---|---|---|---|
| agents/budget.py:40 `reserve` | I (dispatch of model calls; `workbench/reads.py:193` swallows `budget` code from `remaining`) | call budget used up: `call budget exhausted for project {project_id}` | project_id(id) | `calls_exhausted` |
| agents/budget.py:42 `reserve` | I | `cost budget exhausted for project {project_id}` | project_id(id) | `cost_exhausted` |
| agents/budget.py:69 `_row` | I | `no budget set for project {project_id}` | project_id(id) | `not_set` |
| workbench/rounds.py:278 `require_budget_left` | R (round routes in rounds.py) | `nothing is left of the call budget of project {project_id}` | project_id(id) | `calls_exhausted` |
| workflow/tasks.py:171 `record_revision` | I (task revisions by model) | `revision limit reached for task {task_id}` | task_id(id), limit(int, not in msg, add) | `revision_limit` |
| workflow/tasks.py:215 `_check_depth` | I | `delegation depth {depth} exceeds the limit` | depth(int), limit(int, add) | `depth_limit` |

### model_role (5)
| site | reach | message | params | reason |
|---|---|---|---|---|
| agents/dispatch.py:233 `_run` | I/M | `no model configured for role {role!r}` | role | `no_model` |
| agents/tools.py:222 `build_toolset` | M | `{role!r} is not a model role` | role | `unknown_role` |
| agents/tools.py:225 `build_toolset` | M | `role {role!r} may not use tool {name!r}` | role, tool | `tool_not_allowed` |
| workflow/permissions.py:15 `require_kind` | R (all approval/stage routes) | `model roles have no stage or approval controls` | none | `model_no_controls` |
| workflow/service.py:143 `submit_run_sheet` | R/M | `only the {MODEL_DRAFTER} files run sheets` | role | `drafter_only` |

### not_operator (3)
workflow/permissions.py:16 `require_kind` R: `{actor.kind} identities may not do this` (actor_kind) ; control/service.py:335 `onsite_check` R: `an on-site check needs an identified operator` ; observer/alerts.py:202 `mark_read` R: `only an operator can mark an alert as read`. Reason: none (one meaning: log in as an operator). Param: `actor_kind` for the first.

### reauth_required (1)
workflow/permissions.py:23 `require_operator` R: `re-authenticate within {REAUTH_SECONDS} seconds` -> param `seconds`(int). Reason none.

### session (6)
| site | message | reason |
|---|---|---|
| workbench/api.py:261 `model_actor` | `authentication required` (model token missing/bad) | `no_token` |
| workbench/api.py:267 `operator_actor` | `authentication required` | `no_session` |
| workbench/auth.py:155 `actor` | `the session is no longer valid` | `expired` |
| workbench/auth.py:171, :174 `_session` | `the session is not valid` (x2) | `expired` |
| workbench/auth.py:193 `_verify` | `invalid credentials` (login) | `bad_credentials` |
All R. No params.

### locked (2)
workbench/auth.py:206, :213 `_require_unlocked` R (login/reauth): `too many failed attempts; try again later`. Reason none. Param `seconds`(int, remaining lock; not in msg, add) — denials.js hardcodes "15 minutes".

### entry (4)
workbench/api.py:241 `entry_of` `this address is not a registered entry` (reason `unknown_address`); :252 `check_browser` `the request did not come from the workbench page` (`not_from_page`); :271 `operator_actor` `this session belongs to another entry address` (`session_other_entry`); :291 `on_site` `this action is only available on the on-site entry` (`onsite_only`). All R, no params.

### host_unregistered (3)
control/service.py:108 `register_host` and runtime.py:145 `register_write_host`: `another host is registered for this device` (`other_host_registered`); control/service.py:115 `_require_host`: `this host is not the registered write host` (`not_write_host`). Params: device_id(id) optional. Mostly R/I (write routes).

### controls_disabled (1) / unsettled (3) / interlock (3) / not_connected (2) / stale (1) / cooldown (2) / request_id_reused (1)
| site | reach | message | params | reason |
|---|---|---|---|---|
| control/service.py:427 `_authorize` | R (all control writes) | `controls are disabled in the local configuration` | none | none |
| control/service.py:448 `_check_gate_state` | R | `the control service has not finished starting up` | none | `starting_up` |
| control/service.py:454 | R | `the old write path is not confirmed stopped` | none | `old_path_running` |
| control/service.py:456 | R | `an earlier action has an unknown result` | none | `unknown_result` |
| control/service.py:452 | R | `pump off is unconfirmed; ordinary writes are blocked` | none | `pump_unconfirmed` |
| workflow/service.py:341 `_check_startable` | R POST stage start | `the pump interlock is on; check the device on site` | none | `pump_unconfirmed` |
| workflow/service.py:376 `resume_stage` | R | same message | none | `pump_unconfirmed` |
| control/service.py:148 `read_state` | R (state read) | `str(error)` (BridgeError text, e.g. "Supported live BLE connection required") | none (message passthrough!) | `read_failed` |
| control/service.py:460 `_check_link` | R | `no live BLE connection` | none | `no_link` |
| control/service.py:462 `_check_link` | R | `fresh device telemetry is required before an ordinary write` (stale) | stale_seconds(int, add) | none |
| control/service.py:410 `_check_cooldown` | R POST irrigation | `an irrigation is already running` | none | `running` |
| control/service.py:412 | R | `the pump needs {cooldown} s between irrigations` | cooldown_seconds(int, `settings.pump_cooldown_seconds`, default 60, ERR-04 showed 600), ready_at(float epoch, add: `store.last_pump()+cooldown`) | `too_soon` |
| control/service.py:419 `_known` | R | `{request_id} was used for other arguments` | request_id(id) | none |

### right_invalid (6) / right_held (1) / pump_on_forbidden (2)
| site | reach | message | params | reason |
|---|---|---|---|---|
| control/rights.py:29 `build_right` | I (grant) | `a manual right is bound to an authenticated operator` | none | `needs_operator` |
| control/rights.py:47 `check_valid` | R | `unknown write right` | none | `unknown` |
| control/rights.py:49 | R | `write right {n} was revoked` | right_number(int) | `revoked` |
| control/rights.py:51 | R | `write right {n} is from an earlier recovery` (ERR-04) | right_number(int) | `old_recovery` |
| control/service.py:433 `_authorize` | R POST irrigation | `irrigation needs a manual write right, or the stage right for a planned one` | none | `wrong_kind` |
| control/service.py:473 `_recheck` | I (queued write) | `the queued action was voided before it was sent` | none | `voided` |
| control/service.py:175 `grant` right_held | R | `a stage write right is already held for this device` | device_id(id) | none |
| control/rights.py:75 `check_pump_not_started` pump_on_forbidden | R | `only an operator-triggered irrigation starts the pump` | none | none |
| workbench/api.py:439 `manual` pump_on_forbidden | R POST /manual/pump | `the pump is only started by an irrigation run` | none | none (same meaning; share) |

### scope (32) — the most overloaded code
| site | reach | condition / message | params | reason |
|---|---|---|---|---|
| agents/handlers_common.py:121 `require_round` | M | `round {round_id} does not belong to this project` | round_id(id) | `not_this_project` |
| :168 `bound_task` | M | `no task is running: tools only work inside a dispatched run` | none | `no_run` |
| :176 `require_bound` | M | `task_id is not the task this run was started for` | none | `not_this_run` |
| :184 `require_project` | M | `that project is not the project of this run` | none | `not_this_project` |
| :204 `require_experiment_project` | M | `that experiment is not available to this run` | none | `not_this_project` |
| :221 `scoped_snapshot` | M | `snapshot {id} is not available to task {task}` | snapshot_id(id), task_id(id) | `not_this_run` |
| handlers_evidence.py:53 `propose_card` | M | `only a planner task may propose evidence cards` | none | `wrong_task_kind` |
| handlers_orchestrator.py:250, :259 `_visible_task` | M | `that task is not available to this run` | none | `not_this_run` |
| :272 `_own_artifact` | M | `artifact {id} is not available to this run` | artifact_id(id) | `not_this_run` |
| :281 `_read` | M | `artifact {id} is outside the project data` | artifact_id(id) | `not_this_project` |
| handlers_report.py:103 `own_task` | M | `this run does not belong to the researcher` | none | `wrong_task_kind` |
| handlers_report.py:438 `_data_protocol` | M | `that protocol is not available to this run` | protocol_id(id) | `not_this_project` |
| handlers_researcher.py:126 `_started_stage` | M | `stage {id} is not available to task {task}` | stage_id, task_id (ids) | `not_this_run` |
| compute/service.py:301 `_owned` | I (compute routes) | `the attempt belongs to another submitter` | none | `other_submitter` |
| control/rights.py:25 `build_right` | I | `a {kind} right must list the values it may write` | kind | `right_incomplete` |
| control/rights.py:58 `check_scope` | R | `{channel} is outside write right {n}` | channel, right_number | `right_channel` |
| control/rights.py:62 | R | `str(error)` (from a value check, unquoted passthrough) | channel? | `right_value` |
| control/rights.py:66 | R | `{channel}={level} is not a listed value` | channel, level(int) | `right_value` |
| control/rights.py:70 | R | `{name} does not match write right {n}` (name = device/stage/round field) | field, right_number | `right_binding` |
| control/service.py:169 `grant` | R | `{device_id} is not the controlled device` | device_id(id) | `unknown_device` |
| control/service.py:402 `_check_irrigation` | R POST irrigation | `irrigation must run for more than 0 and at most {limit} s` (limit=`settings.max_pump_seconds`, default 5, schema cap 60; Pydantic body caps at MAX_IRRIGATION_SECONDS=60 first -> 422) | field=`seconds`, min=0(exclusive), max=limit, unit=s | `seconds_range` |
| control/service.py:404 | R | `irrigation switches the pump on (channel pump, level 1)` | none | `not_pump_on` |
| research/holdout.py:275 `refuse_holdout_rows` | I/M | `snapshot {id} holds outcomes of a held-out batch` | snapshot_id(id) | `holdout_rows` |
| workbench/analysis.py:156 `snapshot_of` | R | `snapshot {id} is not a snapshot of this protocol` | snapshot_id(id) | `not_this_protocol` |
| workbench/analysis.py:158 | R | `the experiment of snapshot {id} belongs to rounds of more than one protocol version` | snapshot_id(id) | `mixed_protocol` |
| workbench/api.py:461 `measurement` | R POST measurements | `a measurement belongs to an experiment of an existing stage` | experiment_id(id, add) | `no_stage_experiment` |
| workbench/compute.py:64 `set_budget` | R POST /compute/tasks/{task_id}/budget | `unknown task {task_id}` | task_id(id) | `unknown_object` |
| workbench/holdouts.py:61 `require_project` | R | `unknown project {project_id}` | project_id(id) | `unknown_object` |
| workbench/manual_tasks.py:102 `_occurrence` | R POST manual tasks | `the run sheet plans no task {task_id} due at that time` | task_id(id), due_at(add) | `no_such_occurrence` |
| workbench/manual_tasks.py:221 `irrigate` | R | `this task is not a planned irrigation (it has no seconds)` | task_id(id) | `not_irrigation` |
| workflow/service.py:168 `_check_experiment_owner` | R | `experiment {id} belongs to another project` | experiment_id(id) | `not_this_project` |

### param (30)
| site | reach | condition / message | params | reason |
|---|---|---|---|---|
| agents/handlers_evidence.py:56 | M | `only an operator can record a local measurement as evidence; propose a handbook or paper card` | none | `operator_only_evidence` |
| agents/handlers_report.py:129 `_freeze_inputs` | M | `experiment {id} listed in two rounds` | experiment_id(id) | `duplicate_experiment` |
| :389 `_table` | M | `unknown treatment {id}` | treatment_id(id) | `unknown_object` |
| :394 | M | `str(exc)` passthrough | none | `table_invalid` |
| :433 `_data_protocol` | M | `the cited snapshots come from more than one protocol version` | none | `mixed_protocol` |
| :435 | M | `the cited snapshots were not collected under {protocol}` | protocol_id(id) | `not_this_protocol` |
| compute/service.py:125 `_check_text` | R POST compute jobs | `{name} is longer than {limit} characters` | field, max(int), unit=characters | `too_long` |
| :127 | R | `{name} must not contain control characters` | field | `bad_characters` |
| :129 | R | `{name} does not match its pattern` | field, pattern(add) | `bad_format` |
| :131 | R | `{name} must be one of {list}` (ERR-05 "limit must be one of ['a','b']") | field, choices(list) | `not_in_choices` |
| :142 `_check_value` | R | `{name} must be {int/float/str/bool}` | field, expected_kind | `wrong_type` |
| :144 | R | `{name} must be a finite number` | field | `not_finite` |
| :149 | R | `{name} outside {min}..{max}` (ERR-05 "n_iter outside 1..1000"; either bound may print None) | field, min?, max?, unit(add from ParamSpec if any) | `out_of_range` |
| :172 `validate_params` | R | `unknown parameters {unknown}` | names(list) | `unknown_fields` |
| :178 | R | `{name} is required` | field | `required` |
| :187 `_require_amount` | R | `{what} must be a finite, non-negative number` (what=cpu hours / storage gb etc.) | field | `negative_amount` |
| :199 `validate_inputs` | R | `input {name} must be a relative path inside the snapshot` | field(name) | `bad_input_path` |
| :403 `submit_compute_job` | R | `unknown template {id}` | template_id(id) | `unknown_object` |
| :422 `_check_inputs` | R | `inputs are unavailable: no input root or scope guard installed` | none | `inputs_unavailable` (server misconfig; see unavailable) |
| :429 | R | `input {name} is not available` | field | `input_missing` |
| :611 `settle_attempt` | R | `a reason is required` | field=`reason` | `required` |
| :714 `retry` | R | `the template version of the attempt is no longer registered` | template_id(add), version(add) | `template_gone` |
| research/analysis.py:152 `_script_text` | R/I (analysis freeze/run) | `the analysis script must be UTF-8 text` | none | `script_not_text` |
| :154 | | `the analysis script is empty` | none | `script_empty` |
| :156 | | `the analysis script is longer than {MAX_SCRIPT_CHARS} characters` | max(int), unit=characters | `script_too_long` |
| :162 | | `the analysis script has a syntax error: {error}` | error(text; Python SyntaxError incl. line) | `script_syntax` |
| :164 | | `the analysis script cannot be compiled: {error}` | error | `script_syntax` |
| research/holdout.py:119 `_check_lists` | R | `name the outcome fields; names are not empty or repeated` | field=`outcome fields` | `bad_name_list` |
| workbench/manual_tasks.py:200 `record_task` | R | `done_at must be in the past and at most an hour before the task` | field=done_at, max_early_seconds=3600 | `done_at_range` |
| :204 | R | `a skipped task has no done_at` | field=done_at | `skipped_has_time` |

### snapshot_incomplete (7)
agents/handlers_report.py:112 `_verified` M, agents/handlers_researcher.py:100 `_local_analysis` M, runtime_compute.py:166 `guard` I (compute input guard): `snapshot {id} fails verification` (snapshot_id) -> reason `fails_verification`. research/analysis.py:441 `_check_snapshot`: `snapshot is marked incomplete` -> `incomplete`; :445 `snapshot manifest differs from its recorded digest` -> `manifest_changed`; :452 `snapshot directory and manifest list different files` -> `files_mismatch`; :456 `snapshot file differs from manifest: {relative}` (ERR-06; param `file`) -> `file_changed`. Analysis ones are R (analysis routes, workbench/analysis.py).

### approval_invalid (7)
control/service.py:211 `approve_safety` R: `the safety configuration needs an approver` -> `needs_approver`; :214: `frozen thresholds name sensors the device does not have: {list}` -> `unknown_sensors` (sensors list). workflow/service.py:248 `approve` R: `the run sheet has blocking findings` -> `blocking_findings`; :304 `_check_approval`: `no valid approval for this stage` -> `none_valid`; :309: `problem` variable passthrough (text composed elsewhere, e.g. digest changed; check source before choosing) -> `changed_since_approval`; :534 `_check_switch`: `recovery number changed; the stage needs review` -> `recovery_changed`; :536: `the new run sheet has blocking findings` -> `blocking_findings`.

### safety_conflict (2)
workflow/service.py:339 `_check_startable`, :538 `_check_switch`: `'; '.join(conflicts)` — free-text list. Reason none; param `conflicts` (list of {sensor/rule, channel}) to replace the joined text.

### Research / compute / misc one-offs
- quota: compute/service.py:260 `no task budget or project balance recorded` (`no_budget_recorded`); :279 `{label}: need {need}, available {available}` (ERR-05; label in 5 variants: cpu hours/storage over task budget, over service cap, cpu hours over project balance) -> reason `over_task_budget` / `over_service_cap` / `over_balance`, params resource(cpu_hours|storage_gb), need(float), available(float), unit(h|GB); :471 `retry limit of {n} reached` (`retry_limit`, params max_retries int).
- member: compute/service.py:284 `{submitter} is not mapped to a CSC project member` (submitter id).
- script_hash: research/analysis.py:195 `script differs from the hash in the protocol` (`not_protocol_script`); :199 `a different script is already frozen` (`other_frozen`); :348 `script does not match the frozen analysis` (`not_frozen_script`). Params none (hashes optional).
- already_run: research/analysis.py:428 `this snapshot was already analysed`. none.
- batches: research/holdout.py:110 `name at least one held-out batch; names are not empty or repeated` (`no_holdout`); :112 `name at least {MIN_DEVELOPMENT_BATCHES} development batches, not empty or repeated` (`few_development`, min=2); :117 `a batch cannot be both held out and a development batch` (`overlap`).
- model_unregistered: research/holdout.py:234 `register model, features and preprocessing`. none.
- sandbox_unavailable: research/sandbox.py:83 `no isolation backend on this platform`. none.
- clock_unsynced: archive/snapshot.py:121 `the clock is not synchronised; data cannot be frozen`. none.
- unavailable: agents/handlers_common.py:65 `unavailable(what)` M: `no {what} configured` (what in search/compute/sandbox/holdouts) -> param `feature`.

## 2. Reasons per code (distinct meanings, operator-facing)

Codes with one meaning to the operator (no reason needed, params only): controls_disabled, right_held, pump_on_forbidden, request_id_reused, reauth_required, stale, member, model_unregistered, sandbox_unavailable, clock_unsynced, already_run, unavailable, locked, not_operator, safety_conflict.

**budget (6 sites, 6 reasons but 2 operator-relevant groups).** `calls_exhausted` (2 sites): "The project's AI call budget is used up." Next: ask an operator to raise it; model work stays paused. params project_id. `cost_exhausted` (1): same for cost. `not_set` (1): "no budget is set for this project" -> set one. `revision_limit` (1; model-internal: a task hit its revision limit) params task_id, limit. `depth_limit` (1): delegation depth; params depth, limit. ERR-09 fix: advice currently tells the operator in third person ("have an operator..."); reword to second person for the operator, and give models only the code/message.

**model_role (5).** `model_no_controls` (1): "AI roles cannot run stages or approvals." Next: an operator does it. `drafter_only` (1): only the drafting role files run sheets; role. `no_model`(1)/`unknown_role`(1)/`tool_not_allowed`(2 tools.py + 0) are model/config side, not seen by operator (M or dispatch). Operator text for all: "an AI role is not allowed to do this".

**session (6).** `no_token`/`no_session` (2): not signed in -> sign in. `expired` (3): session ended -> sign in again. `bad_credentials` (1): wrong name or secret -> retry (distinct from reauth_failed client code).

**entry (4).** `unknown_address` (open from registered address), `not_from_page` (use the workbench page, not a script), `session_other_entry` (sign in again here), `onsite_only` (use on-site address).

**host_unregistered (3).** `other_host_registered` (2): another computer is the write host; `not_write_host` (1): this computer is not the write host. Param device_id.

**interlock/unsettled (3+3).** interlock `pump_unconfirmed` (3): pump off not confirmed; go on site, check, record. unsettled: `starting_up` (1) wait; `old_path_running` (1) wait/stop; `unknown_result` (1) resolve earlier action first.

**not_connected (2).** `read_failed` (1): state cannot be read (passthrough text); `no_link` (1): no live BLE; wait for reconnection.

**cooldown (2).** `running` (1): an irrigation is in progress; wait. `too_soon` (1): wait `cooldown_seconds`, ready at `ready_at`.

**right_invalid (6).** `revoked`(1), `old_recovery`(1) -> request a new right (ERR-04 "right 14 is from an earlier recovery"), `unknown`(1), `wrong_kind`(1): irrigation needs manual or stage right, `voided`(1): queued action cancelled, resubmit, `needs_operator`(1). params right_number.

**scope (32).** Operator-visible groups (R sites): `right_channel`(1), `right_value`(2), `right_binding`(1), `right_incomplete`(1): "the write right does not cover this channel/value/stage"; params channel, level, field, right_number. `seconds_range`(1): irrigation seconds out of range; params field=seconds, min 0 exclusive, max, unit s. `not_pump_on`(1). `unknown_device`(1). `holdout_rows`(1). `not_this_protocol`(1), `mixed_protocol`(1). `no_stage_experiment`(1). `unknown_object`(2). `no_such_occurrence`(1), `not_irrigation`(1). `other_submitter`(1). `not_this_project`(3 R + M sites). Model-only reasons (M, 12 sites): `no_run`, `not_this_run`(5), `not_this_project`(4), `wrong_task_kind`(2) — can share a handful of reasons since the model reads the English message.

**param (30).** Compute template parameters (field names come from the template's `ParamSpec`: `name`, `kind` int/float/str/bool, `minimum`/`maximum`, `max_length`, `pattern`, `choices`; units not carried; no unit field exists, add `unit` to ParamSpec or derive from the template). Reasons and params: `too_long`(field,max,unit=characters), `bad_characters`(field), `bad_format`(field), `not_in_choices`(field,choices), `wrong_type`(field,expected), `not_finite`(field), `out_of_range`(field,min?,max?,unit?), `unknown_fields`(names), `required`(field; 2 sites), `negative_amount`(field), `bad_input_path`(field), `input_missing`(field), `unknown_object`(template_id/treatment_id; 2). Analysis script: `script_not_text`, `script_empty`, `script_too_long`(max,characters), `script_syntax`(error; 2 sites). Others: `done_at_range`(field=done_at, 3600 s), `skipped_has_time`, `bad_name_list`, `template_gone`, `inputs_unavailable`, M-only `duplicate_experiment`, `table_invalid`, `mixed_protocol`, `not_this_protocol`, `operator_only_evidence`.

**snapshot_incomplete (7).** `fails_verification`(3: M,M,I), `incomplete`(1), `manifest_changed`(1), `files_mismatch`(1), `file_changed`(1, param file). Operator advice for all: freeze a new snapshot and re-run (ERR-06: drop "snapshot file differs from manifest: samples.jsonl" jargon, keep file as param).

**approval_invalid (7).** `needs_approver`, `unknown_sensors`(sensors), `blocking_findings`(2), `none_valid`, `changed_since_approval`(:309 passthrough), `recovery_changed`.

**quota (4).** `no_budget_recorded`, `over_task_budget`, `over_service_cap`, `over_balance` (need, available, unit, resource all numeric), `retry_limit`(max_retries).

**script_hash (3).** `not_protocol_script`, `other_frozen`, `not_frozen_script` (ERR-06 "script differs from the hash in the protocol").

**batches (3).** `no_holdout`, `few_development`(min=2), `overlap`.

**ERR-06 `architecture doc §6.5`**: found at `workbench/analysis.py:37` (a module constant, likely a `state` message; other agent's area), not in any non-state Denied.

## 3. HTTP serialization

`workbench/api.py:60`: `STATUS_BY_CODE = {"state": 409, "session": 401, "locked": 429}`; every other code -> **403** (including `param`, `quota`, `budget`, `scope`).

`workbench/api.py:137-155`:
```python
def refusal(error: Denied) -> JSONResponse:
    status = STATUS_BY_CODE.get(error.code, 403)
    return JSONResponse(
        status_code=status, content={"detail": {"code": error.code, "message": str(error)}}
    )

class GuardedRoute(APIRoute):
    """Turns ``Denied`` raised anywhere in a route (dependencies included) into a response."""
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def guarded(request: Request) -> Response:
            try:
                return await handler(request)
            except Denied as error:
                return refusal(error)
```
Body: `{"detail": {"code": "...", "message": "..."}}`. Only the workbench router uses `GuardedRoute`; `api.py` (root app) has no `Denied` handler. Adding `reason`/`params` = extend `refusal()` plus `Denied.__init__` (`ports.py:32`). Models see `denied (code): message` (`agents/tools.py:206`).

Other shapes:
- `workbench/common.py:11-12`: `rejected(message)` -> `HTTPException(422, detail={"code": "param", "message": message})` (a coded body, status 422 not 403, so `param` has two statuses depending on path: `Denied("param")` -> 403, `rejected()` -> 422).
- `api.py:173-175`: `BridgeError` -> 409 `{"detail": "<str>"}` (string, no code). Used by older `/api` control routes.
- `api.py:177-182` validation:
```python
@app.exception_handler(RequestValidationError)
async def unprocessable(request, error: RequestValidationError):
    detail = json_safe(jsonable_encoder(error.errors()))
    return JSONResponse(status_code=UNPROCESSABLE, content={"detail": detail})
```
Body: `{"detail": [{"type": "missing", "loc": ["body","protocol","treatments",0,"id"], "msg": "Field required", "input": ..., "ctx"?: {...}}]}`. No `code`. The console must synthesise code `validation` (exists in denials.js) and render `loc` + `msg` (ERR-02 "protocol › treatments › 0 › id: Field required"). Pydantic `type` (missing, string_too_long, greater_than, less_than_equal, ...) and `ctx` (`max_length`, `gt`, `le`) are already structured: they can drive the same reason/params vocabulary client-side (e.g. `seconds` gt 0 le 60 on `Irrigation`, `workbench/api.py:~110`).
- `client.py:17` reads `response.json().get("detail", ...)` for the CLI.

## 4. Uncoded HTTP errors

| site | status | message | proposed code (reason) |
|---|---|---|---|
| api.py:78 | 403 | `Browser origin is not allowed` | `entry` (`origin_not_allowed`) |
| api.py:89 | 401 | `Authentication required` (API token missing) | `session` (`no_token`) |
| api.py:96 | 401 | `Open the dashboard with growbridge dashboard to connect` | `session` (`no_session`) |
| api.py:100 | 403 | `Browser control header is required` | `entry` (`not_from_page`) |
| api.py:115 | 403 | `Device writes go through the workbench` | `entry` (`use_workbench`) |
| api.py:266 | 404 | `Unknown device` | `state` (other agent's area; `unknown_device`) |
| dashboard.py:30 | 429 | `Too many pending browser connections` | `locked`/new `busy` (`too_many_pending`) |
| dashboard.py:38 | 401 | `Connection link has expired or was already used` | `session` (`link_used`) |
| dashboard.py:40 | 429 | `Too many browser sessions` | new `busy` (`too_many_sessions`) |
| workbench/api.py:508 `receipt` | 404 | `Unknown request id` | `state` (`unknown_request`), param request_id(id) |
| api.py:175 | 409 | `str(BridgeError)` e.g. `Controls disabled in local configuration`, `Pump off is unconfirmed; ...`, `Fresh v1 telemetry is required before control`, `Incomplete configuration; ...`, `Supported live BLE connection required` (service.py:142-200) | map each to existing codes (`controls_disabled`, `interlock`, `stale`, `not_connected`) |
| workbench/rounds.py:164, :166, :169 via `rejected()` | 422 | `protocol and project ids have 1 to {MAX_ID_CHARS} characters`; `the protocol version is between 1 and {MAX_PROTOCOL_VERSION}`; `protocol numbers must be finite; not at {paths}` | `param` (`too_long`/`out_of_range`/`not_finite`; params field, min/max, paths) |
| workbench/api.py:437 | 422 | `rejected(str(error))` from `check_level`: `{channel} level {n} is outside {low}..{high}` (ranges: light 0..100, exhaust 0..100, fan 0..10, pump 0..1) | `param` `out_of_range` (field=level, channel, min, max) |
| workbench/api.py:471 | 422 | `the measurement was not accepted` (swallows a ValueError) | `param` (reason needs the real cause; flag) |

Note: the rounds.py lines moved to :164-169 (earlier notes said :158-163), and `rejected` already carries code `param`. Also the Pydantic `Irrigation.seconds` cap (`MAX_IRRIGATION_SECONDS = 60`, `workbench/api.py:58`) and `settings.max_pump_seconds` (default 5, `config.py:56`) are two different limits; the 120 s in ERR-04 is not either default, so the message variable `limit` is config-driven.

## 5. denials.js shape (`web/workbench/denials.js`, 54 lines)
- `const ROWS`: 37 arrays `[code, zhText, zhAdvice, enText, enAdvice]` (every entry has advice, both languages).
- Codes known: the 33 server codes (host_unregistered, controls_disabled, right_invalid, right_held, scope, pump_on_forbidden, interlock, not_connected, stale, request_id_reused, not_operator, model_role, reauth_required, entry, approval_invalid, state, safety_conflict, budget, session, member, quota, param, clock_unsynced, script_hash, snapshot_incomplete, already_run, batches, model_unregistered, sandbox_unavailable, unsettled, cooldown, unavailable, locked) plus 4 client-side: `validation`, `reauth_failed`, `network`, `server_error`.
- `export const DENIALS`: `Object.fromEntries` -> `{ code: { zh: {text, advice}, en: {text, advice} } }`.
- `export function describeDenial(code, lang)`: returns `{text, advice}` for the language (falls back to `en`), or `null` for an unknown code (uses `Object.hasOwn`). No params, no interpolation, no reason support; caller: `web/workbench/ui/forms.js` (the only file besides denials.js that uses `describeDenial`).
- Server `message` is currently the technical English text; the catalog supplies the localized text/advice per code only.
