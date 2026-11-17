# HTTP, workbench and MCP interfaces

[简体中文](../zh-CN/API-Reference.md)

This page is for developers and operators who call DiAGRI from a program. It lists the bridge HTTP routes, the workbench routes, the MCP tools in both modes, and the tools of each model role.

On this page "bridge-only mode" means `auto_research = false`. The denial codes are explained in [Denial codes and stage events](Denial-Codes-and-Events.md). The tables were checked against the code and its tests, which run on the simulated AC5 only; see [Status and known limitations](Status-and-Known-Limitations.md).

An operator creates a project, a research protocol and a research round, sets a project's call budget and creates the first task of the orchestrator through the workbench routes below; [Run a research round](Run-a-Research-Round.md) shows them in order. No CLI command and no model tool does any of this. `growbridge simulate` makes the same service calls directly, in `_design_and_start` in [`runtime.py`](../../../src/growbridge/runtime.py). `WorkflowService` also has `switch_run_sheet` and `revoke_approval`; no route, command or tool calls them.

## Listeners

| Listener | Address | Mode | What it serves |
| --- | --- | --- | --- |
| loopback | `127.0.0.1:<port>` | both | The bridge routes, and in DiAGRI mode the workbench routes too. A request on this port with a `Host` in `overlay_hosts` is on the overlay entry. |
| LAN | `<lan_bind>:<lan_port>` | DiAGRI mode, when both fields are set | The same application. A request on this port with a `Host` in `lan_hosts` is on the LAN entry. |

A request is answered 400 before any route runs unless its `Host` is `localhost`, `127.0.0.1`, `testserver` (for the test client) or, in DiAGRI mode, one of `lan_hosts` and `overlay_hosts`.

## Bridge HTTP API

Source: `create_app` in [`api.py`](../../../src/growbridge/api.py). There are 14 routes and one static mount.

| Authentication | Meaning |
| --- | --- |
| none | No credential. |
| token | The header `Authorization: Bearer <token>`, with `token` from the configuration file. |
| token or session | The token header. Without an `Authorization` header, the cookie `growbridge_session`; then every method except `GET` and `HEAD` also needs an allowed `Origin` and the header `X-GrowBridge-UI: 1`. |

| Method | Path | Authentication | Input | Returns | In DiAGRI mode |
| --- | --- | --- | --- | --- | --- |
| `GET` | `/` | none | none | The dashboard page `index.html`. | same |
| mount | `/assets` | none | file path | Static files of [`web/`](../../../src/growbridge/web). | same |
| `POST` | `/ui/session` | token | none | `code` and `expires_in` (60). The code works once. | same |
| `POST` | `/ui/session/redeem` | none; the `Origin` must be allowed | body `code` (20 to 100 characters) | `{"connected": true}` and the cookie `growbridge_session` (HttpOnly, SameSite=Strict, 12 hours). | same; the entry addresses are allowed origins too |
| `POST` | `/ui/logout` | token or session | none | `{"connected": false}`. Revokes the session and deletes the cookie. | same |
| `GET` | `/ui/settings` | token or session | none | `stale_seconds`, `max_pump_seconds`, `pump_cooldown_seconds`, `pump_ready_at`, `retention_days`. | same |
| `GET` | `/health` | token or session | none | `connected`, `protocol_version`, `controls_enabled`, `pump_off_unconfirmed`, `last_sample_at`, `age_seconds`, `stale`, `last_error`, `outlet_mapping`. | same |
| `GET` | `/status` | token or session | query `refresh` (boolean, default `false`) | `health`, `data`, `system`. With `refresh` the device is asked first. | same |
| `GET` | `/history` | token or session | query `hours` (more than 0, at most 168, default 24), `limit` (1 to 2000, default 500) | `samples`: a list of `timestamp` and `data`. | same |
| `GET` | `/history/series` | token or session | query `hours` (as above), `points` (2 to 2000, default 600) | `samples`, `window`, `total_samples`, `downsampled`. | same |
| `GET` | `/activity` | token or session | query `limit` (1 to 100, default 20) | `operations`: a list of `request_id`, `action`, `params`, `state`, `requested_at`. | same |
| `GET` | `/history/export.csv` | token or session | query `hours` (as above) | The file `growbridge-history.csv`: `timestamp_utc`, six sensor columns, `outlet_1_on` to `outlet_5_on`, `light_level`, `exhaust_level`, `fan_level`. | same |
| `POST` | `/control/{device}` | token or session | path `device`: `light`, `exhaust` or `fan`; body `request_id`, `level` (integer 0 to 100; the fan takes 0 to 10) | A receipt: `request_id`, `action`, `completed_at` and the confirmed state. | refused: 403 |
| `POST` | `/outlet` | token or session | body `request_id`, `number` (1 to 5), `on` (boolean) | A receipt as above. | refused: 403 |
| `POST` | `/pump` | token or session | body `request_id`, `seconds` (more than 0, at most 60, and at most `max_pump_seconds`) | A receipt as above. | refused: 403 |

`request_id` is 8 to 100 characters from letters, digits, `_` and `-`. A body with an unknown field is refused. The three write routes are refused in DiAGRI mode with the detail `Device writes go through the workbench`, before the body is checked.

| Status | When |
| --- | --- |
| 401 | The token is missing or wrong (`Authentication required`); there is no valid session (`Open the dashboard with growbridge dashboard to connect`); the code was used or has expired. |
| 403 | The `Origin` is not allowed; the header `X-GrowBridge-UI` is missing; a write route in DiAGRI mode. |
| 404 | `device` is not `light`, `exhaust` or `fan`. |
| 409 | The bridge refused or failed the request (`BridgeError`), for example controls disabled, stale data, pump cooldown, or a `request_id` reused with other arguments. The body is `{"detail": "<message>", "code": <code or null>, "reason": <reason or null>, "params": {}}`; `detail` stays a string, and `code`, `reason` and `params` are the fields of the error body described under the table of the workbench errors (a `PumpOffUnconfirmed` error is `interlock` / `pump_unconfirmed` with `"params": {"device_id": null}`, since the bridge does not know the device there; any other has `null` and `{}`). |
| 422 | The body or the query did not pass validation. A NaN or an infinity the request carried is echoed back as text, such as `"nan"`. |
| 429 | 64 codes are waiting, or 64 sessions are open. |

## Workbench routes

The workbench is the operator's HTTP interface in DiAGRI mode: JSON routes under `/wb`, built by `create_workbench` in [`workbench/api.py`](../../../src/growbridge/workbench/api.py) and mounted only when `auto_research = true`. The routes that start and steer a round are in [`workbench/rounds.py`](../../../src/growbridge/workbench/rounds.py). The operator console is a web page at `/workbench` that only calls these routes (see [Enable DiAGRI](Enable-DiAGRI.md)); the files in `web/` outside `web/workbench/` are the bridge dashboard. There are 55 routes. The seven read routes at the end of the first table are always mounted: [`workbench/reads.py`](../../../src/growbridge/workbench/reads.py) leaves out of the inbox whatever service is not passed. The two alert routes exist when an alert book is passed, the budget and goal routes exist when a task board and a call budget are passed, and the three analysis routes ([`workbench/analysis.py`](../../../src/growbridge/workbench/analysis.py)) exist when a confirmatory runner is passed, and the two holdout routes ([`workbench/holdouts.py`](../../../src/growbridge/workbench/holdouts.py)) exist when a holdout registry is passed. The runtime always passes all of them.

| Caller | Credential | Checks |
| --- | --- | --- |
| operator | The cookie `growbridge_operator`, set by `POST /wb/login`: HttpOnly, SameSite=Strict, path `/wb`, 8 hours, `Secure` on the overlay entry. | The request must arrive on a registered entry, and on the entry the session was opened on. Every method except `GET`, `HEAD` and `OPTIONS` needs an `Origin` that is allowed and names the `Host` of the request, and the header `X-GrowBridge-UI: 1`. The session ends when the recovery number changes. |
| model role | The header `Authorization: Bearer <role token>`. The tokens come from `GROWBRIDGE_ROLE_TOKEN_<ROLE>`. | No entry and no `Origin` are needed. When the header is present the cookie is not looked at. The bridge `token` is not accepted here. |

"Re-auth" in the table means recent re-authentication: the operator logged in, or called `POST /wb/reauth`, within the last 300 seconds (`REAUTH_SECONDS` in [`workflow/permissions.py`](../../../src/growbridge/workflow/permissions.py)). Fields in a body that are not listed below are dropped, so a body cannot claim an identity, a permission or an entry.

Every route that needs an operator can return `session`, `entry` and `model_role`. The last column lists the codes a route can return in addition. "Grant codes" are `host_unregistered`, `right_held` and `scope`, from the control service when a write right is granted. "Write codes" are `controls_disabled`, `host_unregistered`, `right_invalid`, `scope`, `unsettled`, `interlock`, `not_connected`, `stale` and `request_id_reused`, from the control service when an action is submitted.

| Method | Path | Who may call | Entry | Re-auth | Further denial codes |
| --- | --- | --- | --- | --- | --- |
| `POST` | `/wb/login` | anyone with an operator name and secret | LAN, overlay | no | only `entry`, `session`, `locked` |
| `POST` | `/wb/logout` | operator | LAN, overlay | no | none |
| `POST` | `/wb/reauth` | operator | LAN, overlay | no | `locked` |
| `GET` | `/wb/me` | operator, role token | LAN, overlay | no | only `session`, `entry` |
| `POST` | `/wb/stages/{stage_id}/approve` | operator | LAN, overlay | yes | `reauth_required`, `state`, `approval_invalid` |
| `POST` | `/wb/stages/{stage_id}/start` | operator | LAN, overlay | no | `state`, `approval_invalid`, `safety_conflict`, `interlock`, grant codes |
| `POST` | `/wb/stages/{stage_id}/pause` | operator | LAN, overlay | no | `state` |
| `POST` | `/wb/stages/{stage_id}/resume` | operator | LAN, overlay | yes | `reauth_required`, `state`, `approval_invalid`, `interlock`, `not_connected`, grant codes |
| `POST` | `/wb/stages/{stage_id}/stop` | operator | LAN, overlay | no | `state`, grant codes |
| `POST` | `/wb/stages/{stage_id}/takeover` | operator | LAN, overlay | yes | `reauth_required`, `state`, grant codes |
| `POST` | `/wb/stages/{stage_id}/handback` | operator | LAN, overlay | no | `state`, `not_connected`, grant codes |
| `POST` | `/wb/stages/{stage_id}/onsite-check` | operator | LAN, overlay | no | `state`, grant codes |
| `POST` | `/wb/drafts/run-sheet` | operator, the planner's role token | LAN, overlay | no | only `session`, `entry`, `state`, and `model_role` for another role's token |
| `POST` | `/wb/manual/{channel}` | operator | LAN, overlay | no | `pump_on_forbidden`, `state`, write codes |
| `POST` | `/wb/irrigation` | operator | LAN only | no | `entry` (not on the LAN entry), `state`, `cooldown`, write codes |
| `POST` | `/wb/measurements` | operator | LAN, overlay | no | `scope` |
| `POST` | `/wb/stages/{stage_id}/manual-tasks` | operator | LAN, overlay | no | `scope` (no such occurrence), `state` (not started, or not due within the hour), `param` (`done_at`) |
| `POST` | `/wb/stages/{stage_id}/manual-tasks/irrigate` | operator | LAN only | no | `entry` (not on the LAN entry), `scope` (not a planned irrigation), `state` (stage not `running`, not due, past its deadline, already done, or the pump already ran for this occurrence), `cooldown`, write codes |
| `POST` | `/wb/safety/approve` | operator | LAN, overlay | yes | `reauth_required`, `host_unregistered` |
| `GET` | `/wb/stages/{stage_id}` | operator, role token | LAN, overlay | no | only `session`, `entry`, `state` |
| `GET` | `/wb/receipts/{request_id}` | operator, role token | LAN, overlay | no | only `session`, `entry` |
| `GET` | `/wb/alerts` | operator, role token | LAN, overlay | no | only `session`, `entry` |
| `POST` | `/wb/alerts/{event_id}/read` | operator | LAN, overlay | no | `state` |
| `POST` | `/wb/projects` | operator | LAN, overlay | no | `state` |
| `POST` | `/wb/protocols` | operator | LAN, overlay | no | `state` |
| `POST` | `/wb/rounds` | operator | LAN, overlay | no | `state` |
| `GET` | `/wb/rounds/{round_id}` | operator | LAN, overlay | no | `state` |
| `GET` | `/wb/rounds/{round_id}/report` | operator | LAN, overlay | no | `state` |
| `POST` | `/wb/rounds/{round_id}/choice` | operator | LAN, overlay | no | `state` |
| `POST` | `/wb/rounds/{round_id}/abort` | operator | LAN, overlay | no | `state` |
| `GET` | `/wb/stages/{stage_id}/run-sheet` | operator | LAN, overlay | no | `state` |
| `POST` | `/wb/projects/{project_id}/budget` | operator | LAN, overlay | yes | `reauth_required`, `state` |
| `POST` | `/wb/goals` | operator | LAN, overlay | no | `budget`, `state` |
| `GET` | `/wb/projects/{project_id}/conversation` | operator | LAN, overlay | no | `state` |
| `POST` | `/wb/protocols/{protocol_id}/analysis` | operator | LAN, overlay | yes | `reauth_required`, `state`, `script_hash`, `param` |
| `GET` | `/wb/protocols/{protocol_id}/analysis` | operator | LAN, overlay | no | `state` |
| `POST` | `/wb/analysis/runs` | operator | LAN, overlay | yes | `reauth_required`, `state`, `scope`, `snapshot_incomplete`, `already_run`, `sandbox_unavailable` |
| `POST` | `/wb/holdouts` | operator | LAN, overlay | yes | `reauth_required`, `scope`, `state`, `batches`, `param` |
| `GET` | `/wb/holdouts` | operator | LAN, overlay | no | `scope` |
| `POST` | `/wb/evidence` | operator | LAN, overlay | no | none |
| `POST` | `/wb/evidence/{card_id}/verify` | operator | LAN, overlay | no | `state` |
| `GET` | `/wb/evidence` | operator | LAN, overlay | no | none |
| `POST` | `/wb/compute/balance` | operator | LAN, overlay | yes | `reauth_required` |
| `POST` | `/wb/compute/tasks/{task_id}/budget` | operator | LAN, overlay | yes | `reauth_required`, `scope` |
| `POST` | `/wb/compute/attempts/{attempt_id}/settle` | operator | LAN, overlay | yes | `reauth_required`, `state` |
| `GET` | `/wb/compute` | operator | LAN, overlay | no | none |
| `GET` | `/wb/inbox` | operator | LAN, overlay | no | none |
| `GET` | `/wb/projects` | operator | LAN, overlay | no | none |
| `GET` | `/wb/projects/{project_id}` | operator | LAN, overlay | no | `state` |
| `GET` | `/wb/stages/{stage_id}/readings` | operator | LAN, overlay | no | `state` |
| `GET` | `/wb/environment` | operator | LAN, overlay | no | — |
| `GET` | `/wb/stages/{stage_id}/measurements` | operator | LAN, overlay | no | `state` |
| `GET` | `/wb/stages/{stage_id}/history` | operator | LAN, overlay | no | `state` |
| `GET` | `/wb/stages/{stage_id}/manual-tasks` | operator | LAN, overlay | no | `state` |
| `GET` | `/wb/safety` | operator | LAN, overlay | no | none |

The last twenty-eight routes, the thirteen reads among them, are for operators only: a role token is refused with `model_role`.

A "stage runtime" below is a `StageRuntime` without its run sheet: `stage_id`, `experiment_id`, `project_id`, `state`, `prior_state`, `right_number`, `care_right`, `manual_right`, `started_at`, `paused_at`, `end_pending`. `RunSheet`, `ResearchProtocol`, `SafetyConfig`, `Approval` and `ActionRecord` are in [`archive/models.py`](../../../src/growbridge/archive/models.py). A `RunSheet` and a `SafetyConfig` refuse NaN and infinity, also spelled as text, in every number they hold, wherever they come from: a route answers `422`, a model tool returns an error result, and nothing is saved or approved.

| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| `POST` | `/wb/login` | `name` (1 to 64 characters), `secret` (1 to 256) | `operator`, `entry`, `reauth_seconds`, and the session cookie |
| `POST` | `/wb/logout` | none | `{"operator": null}`; the cookie is deleted |
| `POST` | `/wb/reauth` | `secret` (1 to 256) | `reauth_seconds` |
| `GET` | `/wb/me` | none | `kind`, `id`, `operator`, `entry`, `reauth_at`, `timezone` (the setting `report_timezone`, the zone the console shows times in) |
| `POST` | `/wb/stages/{stage_id}/approve` | `expected_digest` (required, 1 to 128 characters; no other field): the digest of the run sheet that was reviewed. The route refuses with `state` when the current sheet differs, and with `422` when the body or the field is missing or another field is sent | the `Approval` |
| `POST` | `/wb/stages/{stage_id}/start` | none | stage runtime |
| `POST` | `/wb/stages/{stage_id}/pause` | optional `reason` (at most 200, default `operator request`) | stage runtime |
| `POST` | `/wb/stages/{stage_id}/resume` | none | stage runtime |
| `POST` | `/wb/stages/{stage_id}/stop` | none | stage runtime |
| `POST` | `/wb/stages/{stage_id}/takeover` | none | stage runtime |
| `POST` | `/wb/stages/{stage_id}/handback` | optional `accept_as_intervention` (boolean, default `false`) | `stage` (stage runtime) and `differences` (a list of `channel`, `field`, `expected`, `actual`) |
| `POST` | `/wb/stages/{stage_id}/onsite-check` | `note` (1 to 500) | stage runtime |
| `POST` | `/wb/drafts/run-sheet` | `round_id` (1 to 100), `run_sheet` (a `RunSheet`) | `stage_id` and `findings` (a list of `code`, `variant`, `params`, `message`, `blocking`) |
| `POST` | `/wb/manual/{channel}` | path `channel`: `light`, `exhaust`, `fan` or `pump`; body `stage_id`, `request_id`, `level` (integer: light and exhaust 0 to 100, fan 0 to 10, pump 0 only), optional `note` (at most 200) | the `ActionRecord` |
| `POST` | `/wb/irrigation` | `stage_id`, `request_id`, `seconds` (more than 0, at most 60, and at most `max_pump_seconds`), optional `note` (at most 200) | the `ActionRecord` |
| `POST` | `/wb/stages/{stage_id}/manual-tasks` | `task_id`, `due_at` (the occurrence, as the list gives it), `outcome` (`done` or `skipped`), optional `done_at` (UTC seconds, default now; only for `done`, not in the future, at most an hour before `due_at`), optional `note` (at most 200). Appends a record; the latest counts. | the occurrence as the list shows it |
| `POST` | `/wb/stages/{stage_id}/manual-tasks/irrigate` | `task_id`, `due_at`, optional `note`; the request id is derived from the occurrence (a `request_id` in the body is ignored), so a retry returns the first run instead of starting the pump again. Runs the pump for the task's `seconds` under the stage right while the stage keeps running ([The pump](Control-and-Safety-Model.md#the-pump)); a full confirmed run is recorded as done, a run cut short or not confirmed as `partial` with `ran_seconds` and `ended_early`. | `action` (the `ActionRecord`, with `ran_seconds` and `ended_early`) and `task` (the occurrence, or `null` when the run never reached the device) |
| `POST` | `/wb/measurements` | `experiment_id`, `batch`, `plant_id`, `layout_version`, `measured_at`, `position`, `method`, `metric`, `value`, `unit`; optional `id`, `corrects`; the `experiment_id` must belong to an existing stage, or the route refuses with `scope` | `id` |
| `POST` | `/wb/safety/approve` | `config` (a `SafetyConfig`, including its `frozen` thresholds; left out, they default) | `protection_right` |
| `GET` | `/wb/stages/{stage_id}` | none | stage runtime; for an operator also `round_id`, `project_id` and `state_at` of the stored stage (a role token gets the runtime as before, without `round_id`). An operator also gets `project_name`, `round_number`, `stage_index` and `phase`, as on the round; each is `null` when it cannot be found |
| `GET` | `/wb/receipts/{request_id}` | none | the `ActionRecord`. A failed, voided or unknown write carries `error_code` and `error_params` beside the English `error` (codes of the `receipt` family); an irrigation that ended early carries `ended_early_code` and `ended_early_params` beside `ended_early` (the `task_end` family). Records written before codes have neither. |
| `GET` | `/wb/alerts` | none | `alerts`: the open alerts. Each carries `code` (a message code of the `alert` family, `null` for an alert stored before codes) and `params` (an object, empty when the code takes none) beside the English `message`. |
| `POST` | `/wb/alerts/{event_id}/read` | none | `event_id` |
| `POST` | `/wb/projects` | `name` (1 to 200) | `project_id` |
| `POST` | `/wb/protocols` | `protocol` (a `ResearchProtocol`; `id` and `project_id` 1 to 100, `version` 1 to 1000000, no NaN or infinity) | `protocol_id`, `version`, `digest` |
| `POST` | `/wb/rounds` | `project_id`, `protocol_id` (1 to 100 each) | `round_id`, `state` |
| `GET` | `/wb/rounds/{round_id}` | none | `round_id`, `project_id`, `protocol_id`, `protocol_version`, `state`, `stages_done`, `stage_total`, `awaiting_choice`, `snapshot_id`, `report_artifact_id`, `project_name` and `round_number` (the round's place, from 1, among the project's rounds of the same protocol), and `stages` (a list of `stage_id`, `state`, `stage_index` (its place, from 1, in creation order) and `phase` (the growth phase the protocol version gives that place)). A name the server cannot find (a project or protocol that is gone, a protocol with fewer phases than stages) is `null` |
| `GET` | `/wb/rounds/{round_id}/report` | none | The round's published report: `round_id`, `artifact_id`, `label`, `sha256`, and `report` (the report file: `label`, `reasons`, `conclusion`, `estimate`, `limitations`, `unresolved`, `next_round`, `evidence_chain`, `snapshot_id`; `estimate` carries `note_code` and `note_params` beside `note`, `note_code` empty for an exact estimate) and `primary_endpoint` (the metric the round's protocol names as its primary endpoint, `null` when the protocol is gone). The file is read only when it matches the digest the archive recorded; otherwise, or when the round has no report, the answer is `state`. |
| `POST` | `/wb/rounds/{round_id}/choice` | `choice`: `redo`, `next`, `verify` or `abort` | `round_id`, `state` |
| `POST` | `/wb/rounds/{round_id}/abort` | none | `round_id`, `state` |
| `GET` | `/wb/stages/{stage_id}/run-sheet` | none | `stage_id`, `state`, `run_sheet_version`, `run_sheet_digest`, `run_sheet` (the `RunSheet`), `findings` (a list of `code`, `variant`, `params`, `message`, `blocking`: `variant` is empty or narrows `code` to one sentence, and `params` are the values that sentence names; the validator's findings, then the evidence hints `no_evidence`, `unverified_source` and `uncalibrated` for every set point, which never block), `blocking` |
| `POST` | `/wb/projects/{project_id}/budget` | `max_calls` (integer, 0 to 1000000), `max_cost` (US dollars, 0 to 1000000) | `project_id`, `max_calls`, `max_cost`, `remaining_calls`, `remaining_cost` |
| `POST` | `/wb/goals` | `project_id`, `goal` (1 to 2000 after trimming); optional `round_id`, `constraints` (at most 20 texts of 1 to 500 each), `request_id` | `task_id`, `state`, `reused`. A new goal is also written into the project conversation |
| `GET` | `/wb/projects/{project_id}/conversation` | query `after` (a `seq`, default 0) | `entries`, oldest first, at most 500: `seq`, `task_id`, `role` (`user` or a model role), `kind` (`message`, `reply`, `tool`, `status`), `text`, `detail` (for a tool: `input`, `is_error`, `result`, each cut short; for a `status` entry: `reason`, and `code` and `params` saying why the task ended, absent on entries written before codes), `at` |
| `POST` | `/wb/protocols/{protocol_id}/analysis` | `project_id` (1 to 100), `script` (text, 1 to 20000 characters, compiled but never run) | `protocol_id`, `version`, `script_sha256`, `frozen_at`, `note` (a frozen script cannot be corrected) |
| `GET` | `/wb/protocols/{protocol_id}/analysis` | query `project_id` (1 to 100) | `protocol_id`, `version`, `started`, `frozen` (`null`, or `script_sha256`, `frozen_at`, `frozen_by`, `script`), `snapshots` (a list of `snapshot_id`, `experiment_id`, `complete`, `run_status`, `created_at`) |
| `POST` | `/wb/analysis/runs` | `project_id`, `protocol_id`, `snapshot_id` (1 to 100 each) | `run_id`, `status`, `exit_code`, `timed_out`, `stdout`, `stderr` (the last two cut at 4000 characters) |
| `POST` | `/wb/holdouts` | `project_id`, `batch_ids`, `development_batch_ids`, `outcome_fields` (1 to 50 names each, 1 to 100 characters, none repeated; the two batch lists do not overlap, at least 2 development batches) | `holdout_id` (made by the server), `project_id`, `batch_ids`, `outcome_fields`, `development_batch_ids`, `registered_at`, `registered_by` (the session's operator) |
| `POST` | `/wb/evidence` | `source_class` (`handbook`, `paper` or `local`), `citation` (1 to 500 characters after trimming), `claim` (1 to 1000), optional `value` (a finite number), `unit` (up to 40), `calibrated` (default true) | `id` (made by the server), `verified` (always true: the card is verified by the operator who entered it, in the same step), `source` (`operator:<name>`) |
| `POST` | `/wb/evidence/{card_id}/verify` | optional `note` (up to 500 characters), optional `calibrated` (default false: the operator attests that the value was calibrated against a local measurement) | `card_id`, `verified`, `verified_by`, `verified_at`, `note`, `calibrated`. Verifying a card again returns the first record, attestation included, and writes nothing; a later `calibrated: true` on an already verified card changes nothing. An unknown card is refused with `state` |
| `GET` | `/wb/evidence` | none | `cards`: every card with `source` (`operator:<name>` or `model:planner`), `task_id`, `added_at`, `verified`, `verified_by`, `verified_at`, `note` |
| `GET` | `/wb/holdouts` | query `project_id` | `holdouts`: each registration as above, with `reads`, a list of `reader`, `at`, `label`, `model_sha` |
| `POST` | `/wb/compute/balance` | `cpu_hours` (a finite number, 0 or more; a string or a boolean is refused), optional `note` (up to 500 characters) | the entry: `cpu_hours`, `entered_by` (the session's operator; a name in the body is dropped), `note`, `recorded_at` |
| `POST` | `/wb/compute/tasks/{task_id}/budget` | `cpu_hours`, `storage_gb` (finite numbers, 0 or more) | the task's row: `task_id`, `cpu_hours_budget`, `storage_gb_budget`, `cpu_hours_used`, `storage_gb_used`, `cpu_hours_reserved`, `storage_gb_reserved`. A task that does not exist is refused with `scope`. |
| `POST` | `/wb/compute/attempts/{attempt_id}/settle` | `reason` (1 to 500 characters after trimming) | `attempt_id`, `phase` (`failed`), `task_state`, `used_cpu`, `used_storage`, `settled_by` (the session's operator), `settle_reason`, `error`, `error_code`, `error_params`. A live attempt is charged its whole reservation; one whose usage is already charged keeps that charge. An attempt that is already final, or unknown, is refused with `state`. |
| `GET` | `/wb/compute` | none | `balance` (the latest entry, or `null`), `tasks` (rows as above), `service` (`cpu_hours_cap`, `storage_gb_cap`, `cpu_hours_committed`, `storage_gb_committed`), `jobs` (open attempts: `attempt_id`, `task_id`, `template_id`, `phase`, `task_state`, `remote_job_id`, `created_at`), `stuck` (attempts that need a person: `attempt_id`, `task_id`, `phase`, `reason`, `reason_code`, `reason_params`, `since`; a row whose reason is the attempt's own error also has `error_code` and `error_params`, and a row stored before codes has no codes) |
| `GET` | `/wb/inbox` | none | `items` and `truncated`. Each item has `kind` (`stage_review`, `stage_manual`, `stage_recovery`, `stage_paused`, `alert`, `compute_stuck`, `round_choice` or `task`), `id`, `project_id`, `round_id`, `since` and `detail`, and the names `project_name`, `round_number`, `stage_index` and `phase` (`null` when not found or not meant for the kind: a `stage_*` item has all four, a `round_choice` item has `project_name` and `round_number`, a `task` item has `project_name`). At most 50 items of each kind are kept: alerts by severity first, then never-read before re-asked, then by the latest raise; the other kinds oldest first. An `alert` item's `detail` has `alert_kind`, `severity`, `message`, `count`, `last_at` and `never_read` (`true` when no operator has read it, or the read did not record its severity). An `alert` item's `detail` also has the alert's `code` and `params`; a `compute_stuck` item's `detail` is the same row as `/wb/compute` gives. A `round_choice` item's `detail` has `awaiting_choice` and `since_from`: `stage_stopped` when `since` is when the stage named in `awaiting_choice` stopped, `round_created` when that stage is gone or not stopped and `since` is the round's creation time. The kept items are listed oldest first, and `truncated` maps each kind to the number cut. |
| `GET` | `/wb/projects` | none | `projects`: a summary of each project, at most 200; its `latest_round` also has `round_number` |
| `GET` | `/wb/projects/{project_id}` | none | the project's `project_id`, `name`, `created_at`, `rounds` (newest first, each with `round_number`) and `protocols` (the latest version of each), `budget` (`calls_left`, `cost_left`, `used_calls`, `used_cost`, `max_calls` and `max_cost`, or `null` when no budget is set; `used_cost` can exceed `max_cost` and is shown as it is) and `tasks` (at most 100). An unknown project is refused with `state`. |
| `GET` | `/wb/stages/{stage_id}/readings` | query `points` (2 to 2000, default 600) | `samples` (a list of `timestamp`, `data`, `quality`, `clock_synced`, `flagged`), `window` (`start`, `end`, `bucket_seconds`, or `null` before the stage started), `total_samples`, `flagged_total` and `downsampled`. The newest sample of each time bucket is kept; `flagged` counts the samples of the bucket whose quality is not `ok` or whose clock was not synchronised. A `points` outside the range is refused with 422. |
| `GET` | `/wb/environment` | query `window` (seconds, 300 to 604800, default 21600), `points` (2 to 1000, default 360) | The live environment page's data, read from the archive, never from the device: `now`, `clock_synced`; `latest`, the newest sample (`timestamp`, `age_seconds`, `quality`, `clock_synced`, `experiment_id`, `sensors`, and `channels` with each channel's recorded `level` and `on`), or `null`; `stage`, the active stage with its `project_name`, `round_number`, `stage_index` and `phase` (each `null` when not found), its `state`, each channel's `ownership` and, only while the stage is `running`, the level its run sheet `expected` now (otherwise `null`) and `planned` (the plan over the window: for `light`, `exhaust` and `fan`, a list of `[time, level]` points, one at the window start and one at each planned change; `{}` when the stage is not running; temperature and humidity have no planned values), or `null` when no stage is active; `sensors` and `level_ranges` from the device capabilities; `alerts`, open alerts counted by severity; `readings`, every sample of the window in or outside a stage, in the shape of a stage's readings. |
| `GET` | `/wb/stages/{stage_id}/measurements` | none | `measurements`: the stage's experiment's measurements, corrected ones included |
| `GET` | `/wb/stages/{stage_id}/manual-tasks` | none | `stage_id`, `stage_state`, `timezone`, `on_time_seconds`, `early_seconds`, `now`, and `occurrences`: each daily occurrence of the run sheet's manual tasks in the stage window (`task_id`, `kind`, `due_at`, `make_up_allowed`, `seconds`), with its `status` (`upcoming`, `open`, `done`, `late`, `skipped`, `missed`) and the `record` that counts, or `null`; empty before the stage starts |
| `GET` | `/wb/stages/{stage_id}/history` | none | `history` (the stage's state changes) and `interventions` (the experiment's interventions that belong to this stage) |
| `GET` | `/wb/safety` | none | `safety`: the approved `SafetyConfig` (with `frozen`: `minutes` per sensor and `max_gap_seconds`), or `null` when none is approved |

A saved protocol version is never overwritten: the same `id` and `version` with other content is refused with `state`. `POST /wb/rounds` uses the latest saved version. The `run_sheet_digest` of the read route is the digest an approval records. Setting a budget again changes the limits and keeps the recorded usage. `POST /wb/goals` creates a research task owned by the orchestrator and is refused with `budget` while the project has no budget or nothing is left of it. With a `request_id`, the same operator sending the same request for the same project again gets the first task back with `"reused": true`; another goal text, round or set of constraints under that id is refused with `state`. Without a `request_id` every request creates a task. The ids in the paths of these routes have 1 to 100 characters. The analysis routes freeze the analysis script of the latest protocol version, which is refused with `state` once a stage under that version has started, and run it once on a data snapshot; the order of their checks is in [Run a research round](Run-a-Research-Round.md#run-the-frozen-analysis).

`request_id` follows the same rule as in the bridge API. `POST /wb/manual/{channel}` and `POST /wb/irrigation` need a stage in the state `manual`. On `POST /wb/manual/pump` a `level` of 1 is refused with `pump_on_forbidden`.

The messages the console shows are built from codes, not from the English sentences. A code names a family (`alert`, `finding`, `receipt`, `task_end`, `compute_error`, `compute_stuck`, `chat_end`, `estimate`) and its `params` hold the values the sentence names; the console writes the text in the page language. The complete list of codes for each family is in `tests/web/fixtures/message-codes.json`, which `scripts/export_message_codes.py` exports from `src/growbridge/codes.py`. `message`, `error`, `reason` and `note` stay in English, unchanged, for logs, old clients and notifications. A record stored before codes has no code, and the console then shows a generic line.

Names that people gave are shown and ids stay in the technical details. The treatment findings `treatment_not_applied`, `no_replication` and `missing_control.unallocated` carry the treatments' names in `treatment`, `treatments` or `control`, and their ids in `treatment_id`, `treatment_ids` or `control_id`. `unknown_treatment` and `missing_control.undefined` carry the ids, since no name exists for them. A planned irrigation whose pump was not confirmed off ends with the `task_end` code `pump_off_unconfirmed` (no params), which comes before the run's own early-end code. A fetch refused for too many output files has the `compute_error` code `too_many_files` with `file_count` and `limit_count`; the other output limits keep `output_limit`.

| Status | When | Body |
| --- | --- | --- |
| 401 | denial code `session` | `{"detail": {"code": "<code>", "message": "<text>"}}` |
| 403 | every denial code not named in this table | same shape |
| 409 | denial code `state` | same shape |
| 429 | denial code `locked` | same shape |
| 404 | `GET /wb/receipts/{request_id}` with an unknown id | `{"detail": {"code": "state", "message": "Unknown request id", "reason": "unknown_request", "params": {"request_id": "<id>"}}}` |
| 422 | `level` outside the range of the channel, a measurement that was not accepted, or a protocol with an id or a version out of range or a number that is not finite | `{"detail": {"code": "param", "message": "<text>"}}` |
| 422 | a body that does not pass validation, a run sheet with a number that is not finite among them | the validation errors; a NaN or an infinity the request carried is echoed as text |

Every refusal also says why. In the workbench routes the `detail` object gains `reason` (a code of the `denial` family, `null` for a refusal that has none) and `params` (an object, empty when the reason takes none): `{"detail": {"code": "<code>", "message": "<text>", "reason": "<reason>", "params": {}}}`. In the bridge routes `detail` remains a string and the body gains the top-level `code`, `reason` and `params`. The coarse `code` and the status do not change, and `message` stays the English text. A reason belongs to one coarse code (its `of` entry); the console writes the sentence for the reason in the page language and falls back to the coarse code for an old client or a missing reason. The `denial` family of `tests/web/fixtures/message-codes.json` lists every reason with its `params`, its `action` (the next step the console offers) and `of`. The text a form field shows before a request is sent is the console's own (`msg.validation.*`) and is not part of this API. A model still sees `Error: denied (<code>): <message>`; it does not see the reason.

## MCP tools

Source: [`mcp_server.py`](../../../src/growbridge/mcp_server.py). `growbridge mcp` runs the server `spiderfarmer-growbridge` over stdio. Each tool calls the bridge HTTP API with the token. Bridge-only mode has 8 tools. DiAGRI mode has the 3 read tools only.

| Tool | Bridge-only mode | DiAGRI mode | Inputs | Calls |
| --- | --- | --- | --- | --- |
| `get_health` | yes | yes | none | `GET /health` |
| `get_status` | yes | yes | none | `GET /status` |
| `get_history` | yes | yes | optional `hours` (default 24), `limit` (default 500) | `GET /history` |
| `set_light` | yes | no | `brightness_percent`, `request_id` | `POST /control/light` |
| `set_exhaust` | yes | no | `speed_percent`, `request_id` | `POST /control/exhaust` |
| `set_fan` | yes | no | `level`, `request_id` | `POST /control/fan` |
| `set_outlet` | yes | no | `number`, `on`, `request_id` | `POST /outlet` |
| `run_pump` | yes | no | `seconds`, `request_id` | `POST /pump` |

## Model role tools

Sources: `ROLE_TOOLS` in [`agents/tools.py`](../../../src/growbridge/agents/tools.py) and the handlers in [`handlers_orchestrator.py`](../../../src/growbridge/agents/handlers_orchestrator.py), [`handlers_planner.py`](../../../src/growbridge/agents/handlers_planner.py), [`handlers_researcher.py`](../../../src/growbridge/agents/handlers_researcher.py), [`handlers_report.py`](../../../src/growbridge/agents/handlers_report.py) and [`handlers_common.py`](../../../src/growbridge/agents/handlers_common.py). The orchestrator has 7 tools, the planner 8 and the researcher 7. These tools are called by the model inside the daemon; they are not HTTP routes and not MCP tools.

"Kind" is `read`, `write`, `web` (the result is untrusted web content) or `sandbox`. After a role has called a `web` tool in a run, its `write` and `sandbox` tools are refused for the rest of that run. An unknown input field fails validation. A refusal comes back to the model as an error result of the form `Error: denied (<code>): <message>`.

| Role | Tool | Kind | Required inputs | What it does |
| --- | --- | --- | --- | --- |
| orchestrator | `get_project_state` | read | `project_id` | Reads the tasks of a project and the active stage; with `round_id` also the round state and its stages. |
| orchestrator | `get_run_status` | read | `stage_id` | Reads the state and recent history of one stage. |
| orchestrator | `create_research_task` | write | `project_id`, `owner_role`, `question`, `trigger_event_id`, `correlation_id` | Creates a research task for the planner or the researcher. |
| orchestrator | `delegate_task` | write | `project_id`, `to_role`, `goal`, `budget`, `trigger_event_id`, `correlation_id` | Creates a research task for the planner or the researcher with a full handoff. |
| orchestrator | `get_task_status` | read | `task_id` | Reads the state of the running task, or of a task delegated below it, and the ids of its artifacts. |
| orchestrator | `read_artifact` | read | `artifact_id` | Reads a registered text artifact after checking its digest. |
| planner | `get_device_capabilities` | read | none | Reads the sensors, channels and level ranges of the device. |
| planner | `find_prior_runs` | read | `experiment_id` | Lists the data snapshots and the measurement count of an experiment. |
| planner | `lookup_crop_conditions` | web | `crop` | Searches for the growing conditions of a crop. |
| planner | `search_and_verify_sources` | web | `query` | Searches for sources. |
| planner | `check_experimental_design` | read | `project_id`, `protocol_id` | Checks the design of a saved research protocol. |
| planner | `estimate_sample_size` | read | `effect`, `sd` | Estimates the number of blocks or units needed. |
| planner | `validate_run_sheet` | read | `run_sheet` | Validates a run sheet without saving it. With `round_id` it also checks that the sheet applies the round's allocated treatment, as `save_plan_draft` does. |
| planner | `save_plan_draft` | write | `round_id`, `run_sheet` | Files a run sheet draft for operator review. It does not approve. A sheet that does not apply the round's allocated treatment (`treatment_not_applied`) is not saved. |
| planner | `query_evidence` | read | none | Searches the evidence cards in the archive; each card says whether an operator verified it. |
| planner | `propose_evidence_card` | write | `task_id`, `source_class`, `citation`, `claim` | Stores a source the planner read as an unverified evidence card and returns its `card_id` to cite in a run sheet. It cannot verify a card. |
| researcher | `inspect_stage_data` | read | `task_id`, `stage_id` | Summarises a started stage's data over the window a freeze would use (coverage, gaps, sample counts, channel ranges, measurements per metric, manual tasks done in time, existing snapshots); writes nothing. Held-out measurements are only counted. |
| researcher | `freeze_dataset` | write | `task_id`, `stage_id` | Freezes the data of a stage into a verified data snapshot; with `round_id` it also advances the round when the snapshot is complete. |
| researcher | `query_evidence` | read | none | Searches the evidence cards in the project archive. |
| researcher | `run_local_analysis` | sandbox | `task_id`, `snapshot_id`, `script` | Runs an exploratory script in the sandbox on a data snapshot. |
| researcher | `submit_compute_job` | write | `task_id`, `template_id` | Submits a compute job from a registered template. |
| researcher | `get_compute_job` | read | `attempt_id` | Reads the state of a compute job. |
| researcher | `fetch_compute_artifacts` | write | `attempt_id` | Fetches and verifies the outputs of a compute job. |
| researcher | `publish_research_report` | write | `task_id`, `protocol_id`, `treatment_id`, `snapshots` | Publishes the report of the round; with `round_id` it also delivers the round when the report is final. Returns `treatment_check`: rounds whose recorded device levels contradict their allocated treatment (counted as protocol deviations) and rounds whose samples record no level to compare; `manual_task_check`: per round, the planned manual tasks and how many were not done in time; `server_notes`: each note the server added, in English and Chinese. |

Evidence cards. `propose_evidence_card` needs the task the dispatcher is running, and that task must be a planner task. Whatever the input says, the card is stored unverified, with `model:planner` and the task id as its source: the input has no verification field and unknown fields are rejected. The input has no `calibrated` field either: a model cannot claim calibration, so a proposed card is stored uncalibrated and keeps the `uncalibrated` hint even after an operator verifies it, until the operator attests the calibration with `calibrated: true` when verifying (the attestation is stored with the verification record; the first verification stays). A card an operator enters keeps the `calibrated` value the operator entered. A model cannot propose a `local` card: `source_class` `local` is refused with `param`, because only an operator can record a local measurement as evidence. An unverified card of any class, `local` included, always gets the `unverified_source` hint in the review of the run sheet, until an operator verifies it. The card id is made by the server, one task may propose at most 20 cards (`quota`), and a planner that has read web content loses this write tool for the rest of the run, so it proposes before it searches. Only an operator verifies a card, through `POST /wb/evidence/{card_id}/verify`; that appends a record and the card text is never edited.

The researcher tools that take a snapshot, a stage, a round or a compute submission require `task_id`. The id is checked against the task the dispatcher is running, not trusted: any other id, a task of another role, and a call made outside a dispatched run are refused with `scope`. A stage, round or snapshot of another project is refused with `scope` too.

The other two roles are bound the same way. Every `project_id`, `round_id`, `stage_id` and `experiment_id` in an orchestrator or planner call must belong to the project of the running task, and the experiment must have exactly one owning project. `get_task_status` answers for the running task and the tasks delegated below it only. `read_artifact` answers for artifacts of tasks of the project only. `delegate_task` accepts only the running task as `parent_task_id`. All of these are refused with `scope`.

In the daemon that `growbridge serve` builds, no search backend is passed, so `lookup_crop_conditions` and `search_and_verify_sources` return `denied (unavailable)`. `submit_compute_job`, `get_compute_job` and `fetch_compute_artifacts` work only when the compute service is configured (see [Enable DiAGRI](Enable-DiAGRI.md), step 5); otherwise they return `denied (unavailable)` too. A compute input `ref` is `<snapshot id>` or `<snapshot id>/<file>`, and the service accepts it only for a verified snapshot of the task's own project that holds no held-out outcomes; anything else is refused before a byte leaves the host. The three compute routes of the workbench exist only with the compute service. The sandbox exists on macOS only; elsewhere `run_local_analysis` returns `denied (sandbox_unavailable)`.

`CONTROL_TOOLS` in `agents/tools.py` lists 14 stage and device control tool names that no model role can obtain. None of them has a handler.

## See also

- [Denial codes and stage events](Denial-Codes-and-Events.md)
- [Configuration reference](Configuration-Reference.md)
- [CLI reference](CLI-Reference.md)
- [Control and safety model](Control-and-Safety-Model.md)
- [The agents](The-Five-Agents.md)
- [Glossary](Glossary.md)
