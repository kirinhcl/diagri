# Run a research round

[简体中文](../zh-CN/Run-a-Research-Round.md)

This page is for an operator who follows one research round from the goal to the delivered report. For each step it says who acts, which workbench request or command the operator uses, and which round state and stage state the step leaves.

> **Status.** An operator can start and steer a round through `/wb`: create the project, the research protocol and the round, set the model call budget, state the goal, read a run sheet before approving it, choose what follows a stopped stage, and abort the round. This path has run only in the tests, on the simulated AC5, with a scripted model and an in-process HTTP client ([`test_e2e_http_round.py`](../../../tests/e2e/test_e2e_http_round.py)). It has not been run against a `serve` process, a real model or a real device. The console at `/workbench` has forms for most of these steps; there is no CLI command. Some reads still have no route; they are marked **no route** and listed again at the end. See [Status and known limitations](Status-and-Known-Limitations.md).

## What the workbench is

The workbench is a set of JSON routes under `/wb`, defined in [`workbench/api.py`](../../../src/growbridge/workbench/api.py) and [`workbench/rounds.py`](../../../src/growbridge/workbench/rounds.py). The dashboard at `/` is the bridge-only one and never calls `/wb`; the console at `/workbench` does. You can also send the requests yourself, with any HTTP client that keeps cookies.

Every request follows these rules:

1. Send it to an entry address: `http://YOUR_LAN_HOST:LAN_PORT` on site, or `https://YOUR_OVERLAY_HOST` over the overlay network. Other addresses are refused with `entry`.
2. Log in once with `POST /wb/login` and the body `{"name": "YOUR_OPERATOR", "secret": "..."}`. The answer sets the cookie `growbridge_operator`, valid for 8 hours and only on the entry it was issued on.
3. Every request that is not a `GET` needs two headers: `Origin`, equal to the address you are using, and `x-growbridge-ui: 1`.
4. Approve, resume, takeover, safety approval, setting the call budget, freezing an analysis script and starting an analysis run need a re-authentication within the last 300 seconds. Login counts. Later, send `POST /wb/reauth` with `{"secret": "..."}` first.
5. A refusal has the body `{"detail": {"code": "...", "message": "..."}}`. The status is `409` for `state`, `401` for `session`, `429` for `locked` and `403` for every other code. A malformed body is `422`.

With `curl`, the first requests look like this. `login.json` holds the login body; keep it private and delete it afterwards.

```sh
BASE=http://YOUR_LAN_HOST:9443
curl -s -c wb.cookies -H "Origin: $BASE" -H 'x-growbridge-ui: 1' \
  -H 'Content-Type: application/json' -d @login.json "$BASE/wb/login"
curl -s -b wb.cookies "$BASE/wb/stages/STAGE_ID"
curl -s -b wb.cookies "$BASE/wb/stages/STAGE_ID/run-sheet"   # read run_sheet_digest from the answer
curl -s -b wb.cookies -X POST -H "Origin: $BASE" -H 'x-growbridge-ui: 1' \
  -H 'Content-Type: application/json' -d '{"expected_digest": "DIGEST_YOU_READ"}' \
  "$BASE/wb/stages/STAGE_ID/approve"
```

These commands are not verified against a running `serve`: the tests in [`tests/workbench/`](../../../tests/workbench/) send the same requests through an in-process test client.

## The round at a glance

| Step | Who acts | Operator's request | Round state after | Stage state after |
| --- | --- | --- | --- | --- |
| 1. State the goal | operator, then orchestrator | `POST /wb/projects`, `/wb/protocols`, `/wb/rounds`, `/wb/projects/PROJECT_ID/budget`, `/wb/goals` | `designing` | none yet |
| 2. The plan arrives | planner | `GET /wb/rounds/ROUND_ID`, `GET /wb/stages/STAGE_ID/run-sheet` | `stage_review` | `pending_review` |
| 3. Approve the run sheet | operator | `POST /wb/stages/STAGE_ID/approve` | `stage_review` | `pending_review` |
| 4. Start the stage | operator | `POST /wb/stages/STAGE_ID/start` | `stage_running` | `running` |
| 5. The stage runs | executor, observer | read routes, `pause`, `resume`, `takeover` | `stage_running` | `running`, then `ended` |
| 6. Data verification | researcher | `POST /wb/measurements`, `POST /wb/goals` | `data_verification`, then `analysis` | `ended` |
| 7. Analysis | operator, researcher | `GET /wb/protocols/PROTOCOL_ID/analysis`, `POST /wb/analysis/runs`, `GET /wb/rounds/ROUND_ID` | `analysis` | `ended` |
| 8. Report delivered | researcher | `GET /wb/rounds/ROUND_ID` | `delivered` | `ended` |

Before step 4 the operator can also freeze the analysis script of the protocol (`POST /wb/protocols/PROTOCOL_ID/analysis`); see [Freeze the analysis script before the first stage](#freeze-the-analysis-script-before-the-first-stage). State names are those in [`workflow/states.py`](../../../src/growbridge/workflow/states.py). Why the states are shaped this way is on [Workflow and state machines](Workflow-and-State-Machines.md).

## 1. State the goal

The operator designs the round, gives the project a model call budget and states the goal. The goal becomes a research task of the orchestrator, which hands the design to the planner.

**Create the project, the protocol and the round.**

```http
POST /wb/projects

{"name": "lettuce light series"}
```

The answer is `{"project_id": "..."}`. Put that id into the research protocol and save it:

```http
POST /wb/protocols

{"protocol": { ... }}
```

The protocol is a `ResearchProtocol` from [`archive/models.py`](../../../src/growbridge/archive/models.py): question, hypothesis, crop, batch, treatments, allocations, the analysis plan, the stage names, and the number of rounds and blocks. `make_protocol` in [`sim/fixtures.py`](../../../src/growbridge/sim/fixtures.py) builds a complete example. The answer is `{"protocol_id": "...", "version": 1, "digest": "..."}`. A saved version is never overwritten: to change the protocol, send it again with a higher `version`. A protocol with a NaN or an infinite number, a `version` outside 1 to 1000000, or an id longer than 100 characters is rejected with `422`. Then create the round. It uses the latest saved version of the protocol.

```http
POST /wb/rounds

{"project_id": "PROJECT_ID", "protocol_id": "PROTOCOL_ID"}
```

The answer is `{"round_id": "...", "state": "designing"}`. Keep the ids: no route lists projects or rounds.

**Set the call budget.** Without a budget every model run is refused with `budget`. This request needs a recent re-authentication.

```http
POST /wb/projects/PROJECT_ID/budget

{"max_calls": 50, "max_cost": 100.0}
```

`max_calls` counts model calls and `max_cost` is in US dollars, computed from token counts at a list price. The answer repeats the limits and adds `remaining_calls` and `remaining_cost`. Setting the budget again changes the limits and keeps the usage already recorded. A limit of `0` stops further model calls of the project, and a new goal is then refused.

**State the goal.**

```http
POST /wb/goals

{"project_id": "PROJECT_ID", "round_id": "ROUND_ID", "goal": "Does more light speed up canopy growth?"}
```

The answer is `{"task_id": "...", "state": "in_progress", "reused": false}`. The goal is now a research task owned by the orchestrator. `serve` runs open model tasks every 30 seconds when `roles` is configured and a model client could be built; see [Enable DiAGRI](Enable-DiAGRI.md). Optional fields are `round_id`, `constraints` (a list of short texts) and `request_id` (8 to 100 letters, digits, `_` or `-`). The same request sent again with the same `request_id` returns the first task with `"reused": true` and creates nothing. Without a `request_id`, every request creates a new task.

| Refused with | What to do |
| --- | --- |
| `budget` | The project has no call budget, or nothing is left of it. Set or raise it, then state the goal again. |
| `state` | The project or the round is unknown, the round belongs to another project, the protocol version exists with other content, or the `request_id` was already used with another goal text, round or constraints. |
| `reauth_required` | Only the budget asks for it. Send `POST /wb/reauth`, then repeat. |

Read the round at any time:

```http
GET /wb/rounds/ROUND_ID
```

The answer has `state`, `awaiting_choice`, `stages_done`, `stage_total`, the protocol id and version, `snapshot_id`, `report_artifact_id` and `stages`, a list of `{"stage_id": "...", "state": "..."}`. A new round is in `designing` and has no stage.

The tests use a scripted model; see [`test_e2e_http_round.py`](../../../tests/e2e/test_e2e_http_round.py). With a real model the step has run on the simulator up to a run sheet waiting for review: see [Status and known limitations](Status-and-Known-Limitations.md).

## Freeze the analysis script before the first stage

A result can be called confirmatory only if its analysis was fixed before the outcome data existed (see [Research methodology](Research-Methodology.md)). In DiAGRI mode the operator fixes it with one request, before any stage of the protocol has started. The request needs a re-authentication within the last 300 seconds.

```sh
curl -s -b wb.cookies -X POST -H "Origin: $BASE" -H 'x-growbridge-ui: 1' \
  -H 'Content-Type: application/json' \
  -d '{"project_id": "PROJECT_ID", "script": "print(\"analysis\")\n"}' \
  "$BASE/wb/protocols/PROTOCOL_ID/analysis"
```

The answer is `{"protocol_id": "...", "version": 1, "script_sha256": "...", "frozen_at": 1800000000.0, "note": "..."}`. The note says that a frozen script cannot be corrected afterwards.

- The `script` is UTF-8 text of 1 to 20 000 characters. It is compiled when it is frozen, never run: a syntax error or a NUL byte is refused with `param`. **A frozen script cannot be corrected afterwards**, and nothing but a new protocol version lets you freeze another one, so read it before you send it. It is stored with the name of the operator who froze it. The name comes from the session, never from the body.
- It applies to the latest saved version of the protocol, the version a new round uses. To change the analysis, save the protocol as a new version first.
- **Data collected before the freeze can never be confirmatory.** Freezing is therefore refused with `state` when any stage of a round that runs this protocol version has started, and also when a snapshot or a manual measurement already exists for an experiment that such a round uses. A run is refused for the same reason (see below).
- Once any stage of any round that runs this protocol version has started, freezing is refused with `state`: the analysis must be fixed before the outcome data can be seen (architecture document, section 6.5).
- Freezing the same text again returns the same answer while no stage has started. Another text for the same version is refused with `script_hash`.
- `GET /wb/protocols/PROTOCOL_ID/analysis?project_id=PROJECT_ID` needs no re-authentication. It shows `started`, `frozen` (`null`, or `script_sha256`, `frozen_at`, `frozen_by` and the `script` itself) and `snapshots`: for each data snapshot of the protocol's rounds its `snapshot_id`, `experiment_id`, `complete` and `run_status` (`none`, `running`, `succeeded` or `failed`).

## Register a holdout before the outcome data exists

A prediction model needs data it has never touched. The operator registers the held-out batches before any outcome measurement of them is recorded. The request needs a re-authentication within the last 300 seconds.

```sh
curl -s -b wb.cookies -X POST -H "Origin: $BASE" -H 'x-growbridge-ui: 1' \
  -H 'Content-Type: application/json' \
  -d '{"project_id": "PROJECT_ID", "batch_ids": ["batch-3"], "development_batch_ids": ["batch-1", "batch-2"], "outcome_fields": ["yield_g"]}' \
  "$BASE/wb/holdouts"
```

The answer holds the `holdout_id` the server made, the three lists, `registered_at` and `registered_by`. Held-out batches and development batches must not overlap, there must be at least 2 development batches, and no name may be empty or repeated (`batches`, or `param` for the outcome fields). The project must exist (`scope`).

If any experiment of the project already has a manual measurement of a held-out batch with one of the outcome fields, registering is refused with `state`: that data may already have been seen. So is an experiment that no stage runs and that holds such a measurement, because it cannot be shown to belong to another project. Register first, then collect. From then on the held-out outcomes are left out of every snapshot and hidden from the model tools. `GET /wb/holdouts?project_id=PROJECT_ID` lists the registrations with their read logs and needs no re-authentication. Nothing scores a model on a holdout yet (see [Research methodology](Research-Methodology.md#holdout-data-for-prediction-models)).

## 2. The plan arrives for review

The planner checks its run sheet with `validate_run_sheet` and files it with `save_plan_draft`. A run sheet with a blocking finding is not saved. A saved one creates the stage in `pending_review` and moves the round to `stage_review`. Nothing has been written to the device.

A model role outside the daemon, or an operator, can file a run sheet over HTTP instead:

```http
POST /wb/drafts/run-sheet

{"round_id": "ROUND_ID", "run_sheet": { ... }}
```

The answer is `{"stage_id": "...", "findings": [...]}`. Words such as "approved" in the body change nothing: a draft is never an approval. A run sheet with a NaN or an infinite number is rejected with `422`, and nothing is saved.

What the operator can do: `GET /wb/rounds/ROUND_ID` lists the new stage in `stages` as `pending_review`. Read what you are asked to approve:

```http
GET /wb/stages/STAGE_ID/run-sheet
```

The answer has the full `run_sheet`, its `run_sheet_version` and `run_sheet_digest`, the validation `findings` as they are now, and `blocking`, which is `true` when a finding stops the approval. Reading changes nothing. A model role cannot call this route. There is **no route** to read a saved research protocol.

The `findings` also carry the evidence hints of every set point (the timed actions, feedback rules and care steps): `no_evidence` when it cites no card (a card id that does not exist counts as no card, and `user:...` means you told the planner yourself), `unverified_source` when no operator has verified the card (this holds for every class of card, `local` included: a card the planner proposed is never `local`, because a model cannot propose a local card, and an unverified card always gets the hint), and `uncalibrated` when the card's value was not calibrated against a local measurement. A model cannot claim calibration: a card the planner proposed is stored uncalibrated, and the hint stays after you verify it until you attest the calibration yourself. These three are hints and never block the approval (the hints about a card's fit are listed under "When a card stops being valid" below). A card counts as verified once an operator has recorded a verification. Read and verify the cards before you approve:

```http
GET /wb/evidence
POST /wb/evidence/CARD_ID/verify
{"note": "checked against the handbook, p. 41", "calibrated": true}
```

Send `"calibrated": true` only when you know the value was calibrated against a local measurement; leave it out otherwise, and the `uncalibrated` hint stays. The attestation is stored with the verification record. The first verification stays: a later call with `"calibrated": true` on a card you already verified changes nothing. A card you enter yourself keeps the `calibrated` value you entered.

The list shows every card with its source (`operator:<name>`, or `model:planner` with the task id when the planner proposed it), whether it is verified, who verified it and when. Verifying is idempotent: a second call keeps the first record. It does not edit the card. To add a card yourself:

```http
POST /wb/evidence
{"source_class": "handbook", "citation": "Handbook of Lettuce Production, 3rd ed., p. 41", "claim": "200 umol m-2 s-1 suits lettuce", "value": 200, "unit": "umol m-2 s-1"}
```

A card you enter is verified by you in the same step; the answer has the new `id` to give the planner. Neither call asks for a recent re-authentication.

### When a card stops being valid

A card is never edited. When a better source replaces it, when two sources disagree, or when you find it was wrong, you record a relation between cards:

```http
POST /wb/evidence/relations
{"kind": "supersedes", "card_id": "NEW_CARD_ID", "other_card_id": "OLD_CARD_ID", "reason": "the 2025 trial repeats it at higher light"}
```

`kind` is `supersedes` (`card_id` replaces `other_card_id`; both must be public, or both in the same project), `contradicts` (the two disagree and both stay; a public card and a project card may be joined, but cards of two different projects may not) or `retracts` (`card_id` is taken back; leave `other_card_id` out). A relation you record takes effect at once. When the planner proposes one it waits for you: list them with `GET /wb/evidence/relations?project_id=PROJECT_ID`, then answer with `POST /wb/evidence/relations/RELATION_ID/review`, body `{"decision": "confirmed", "note": "..."}` (a note is required only to confirm a planner proposal between public cards: it then takes effect in every project, and other projects see your note instead of the planner's reason) or `{"decision": "rejected"}`. Confirming checks the rules again, so a proposal whose old card was superseded in the meantime is refused with `relation_already_superseded`; you can still reject it. To end a confirmed relation, `POST /wb/evidence/relations/RELATION_ID/withdraw` with a `reason`. The first review and the first withdrawal stay.

`GET /wb/evidence` then shows each card's `status`: `retracted`, `dependency_invalid`, `superseded` or `active` (a card that is several at once shows the first of these). Add `as_of` (epoch seconds) to see the cards and their status at an earlier time (a card entered later is left out), `status` or `variable` to narrow the list. The evidence page of the workbench has the same filters, with a date and time field for `as_of`.

What this does to a run sheet:

- **Blocking.** Submitting a run sheet, replacing one, and approving a stage are refused while a set point cites a card that is no longer active. The findings are `superseded_source` (it names the card that replaces it), `retracted_source` and `dependency_invalid_source` (the report or snapshot the card rests on was invalidated).
- **A stage that already runs is not stopped.** Once the stage is past review the same findings only inform. The daily report of a running stage lists up to five such citations under "Evidence no longer valid", with the replacement when there is one.
- **Hints.** `contested_source` (an active card contradicts it), `pending_relation` (a proposal about the card awaits review), `variable_mismatch`, `evidence_unit_mismatch` (the card's variable or unit differs from the rule's; for a sensor name the catalog does not know only the variables are not compared, the units still are; a card that names no catalog variable is not compared, and one that has a value gets `uncataloged_card` instead), `crop_mismatch`, `uncataloged_card` and `exploratory_finding` (the card comes from a round whose report was not confirmatory).

To keep a result for later, turn a delivered round's conclusion into a card:

```http
POST /wb/rounds/ROUND_ID/evidence
{}
```

The body may add `growth_stage`, `conditions`, `conditions_note`, `value` and `unit`. The card is a verified `local` card, visible and citable only in the round's project, and it remembers the report and the snapshots behind it. If a later correction invalidates either, the card becomes `dependency_invalid` and does not recover; a new round gives a new card. A round converts once, and a report with no conclusion is refused.

## 3. Approve the run sheet

```http
POST /wb/stages/STAGE_ID/approve
{"expected_digest": "the run_sheet_digest you read in step 2"}
```

The body is required and holds only that field. If the run sheet changed since you read it, the answer is `409` with code `state`; read it again and decide again.

You should get the approval record, with `operator`, `run_sheet_version`, `run_sheet_digest` and `recovery_number`. `run_sheet_digest` is the one you sent: the server approves only the sheet you read, never a newer version filed in between. The stage stays in `pending_review`; approving does not start it.

| Refused with | What to do |
| --- | --- |
| `reauth_required` | Send `POST /wb/reauth`, then approve again. |
| `approval_invalid` | The run sheet has blocking findings. A new version has to be filed. |
| `state` | The stage is not in `pending_review`. Read its state. |

A new version of the run sheet filed after your approval voids the approval.

## 4. Start the stage

```http
POST /wb/stages/STAGE_ID/start
```

You should get `"state": "running"` with a `right_number` and, when the run sheet has care rules, a `care_right`. The round moves to `stage_running`.

| Refused with | What to do |
| --- | --- |
| `approval_invalid` | There is no valid approval, or the run sheet, the device capabilities or the recovery number changed since. Approve again. |
| `safety_conflict` | A protection rule acts on a channel the run sheet leaves to the device. The run sheet or the safety configuration has to change. |
| `interlock` | Pump-off is unconfirmed. See the [Troubleshooting runbook](Troubleshooting-Runbook.md). |
| `state` | Another stage on this device is still live or being checked. |

## 5. The stage runs

The executor follows the run sheet about once a second: timed actions, feedback rules, protection rules. The observer raises alerts and makes the daily report. No model is involved, so the stage keeps running when model roles are off.

The console's **Live environment** page shows the newest reading of every sensor and the recorded level of each channel, refreshed every 5 seconds. During a stage, each channel the run sheet controls also shows the level the sheet wants at this moment, and a channel at another level is marked **Differs from the run sheet**. Below are the trends of the last hour to seven days, across stages and between them. A reading that stops arriving is said, not shown as current.

| To do this | Send |
| --- | --- |
| Read the stage | `GET /wb/stages/STAGE_ID` |
| Watch the environment live: newest readings, channel levels against what the run sheet wants now, trends | `GET /wb/environment`, or the console's **Live environment** page |
| Read open alerts, mark one as read | `GET /wb/alerts`, `POST /wb/alerts/EVENT_ID/read` |
| Read the receipt of a write | `GET /wb/receipts/REQUEST_ID` |
| Record a measurement taken by hand | `POST /wb/measurements` |
| List the manual tasks due, record one as done or skipped | `GET /wb/stages/STAGE_ID/manual-tasks`, `POST /wb/stages/STAGE_ID/manual-tasks`, or the stage page's **Manual tasks** |
| Run a planned irrigation (on the LAN entry) | `POST /wb/stages/STAGE_ID/manual-tasks/irrigate` |
| Pause | `POST /wb/stages/STAGE_ID/pause`, optional body `{"reason": "..."}` |
| Resume | `POST /wb/stages/STAGE_ID/resume` (re-authentication) |
| Take over by hand | [Manual takeover, irrigation and handback](Manual-Takeover-and-Irrigation.md) |

### Record a measurement

On the console, the measurement form offers the experiment's declared manual variables as a dropdown of metrics (with a "choose a variable" placeholder when there is more than one), and the unit comes from the variable; when there is none, a note takes the place of the form. Over HTTP, `GET /wb/experiments/EXPERIMENT_ID/variables` lists them. `POST /wb/measurements` is refused with 422 `param`, listing every problem found:

| Problem | What to do |
| --- | --- |
| No declared variables: the protocols of the experiment declare none | An experiment whose protocols declare no variables cannot record measurements. Save a protocol version that declares them and run a new round with it: a new version applies to an experiment only once a stage of a new round runs it under that version. |
| The metric is not declared | The message lists the declared IDs. Use one of them, or declare the variable in a new protocol version and run a new round with it. |
| Wrong kind | The variable is a sensor or factor, not a manual one (`manual` kind). Pick a manual variable. |
| Wrong unit | The message names the right unit. Send the value in that unit. |
| Value outside `min` and `max` | The bounds are inclusive. Check the reading; do not widen the catalog to fit a bad value. |

A measurement body has `experiment_id`, `batch`, `plant_id`, `layout_version`, `measured_at` (UTC seconds), `position`, `method`, `metric`, `value` and `unit`. Add `corrects` with the id of an earlier measurement to correct it; the earlier record is kept.

A correction is a new record; it may change the metric as well as the value. Writing a correction marks every data snapshot and every report that holds the original record as invalid, so freeze a new snapshot and rebuild the report afterwards. Manual records always store the standard ID.

### Manual tasks

The run sheet's `manual_tasks` (watering, measurement, photo) need someone on site each day at their time. The stage page lists each occurrence, newest first and up to a day ahead, with its state: upcoming, due now, done, done late, skipped or missed. Record each one:

```http
POST /wb/stages/STAGE_ID/manual-tasks

{"task_id": "photo-noon", "due_at": 1800003600, "outcome": "done", "note": "tray 3"}
```

`due_at` names the occurrence as the list gives it. `done_at` (UTC seconds) is optional and defaults to now; it may not be in the future, nor more than an hour before the task was due, and a task cannot be recorded more than an hour before it is due. A record is never changed: record again and the latest counts. A task done more than two hours after it was due counts as late, unless the run sheet allows a make-up (`make_up_allowed`), which counts until the stage ends. A record entered more than a day after that deadline counts as late whatever `done_at` it states; it is kept and shown. The report counts a round with more than 10 % of its tasks not done in time as a protocol deviation ([Research methodology](Research-Methodology.md)).

An irrigation task with `seconds` is a planned pump run. Started from the stage page on the LAN entry (`POST /wb/stages/STAGE_ID/manual-tasks/irrigate` with `task_id` and `due_at`), it runs the pump for those seconds under the stage right while the stage keeps running. A full confirmed run is recorded as done; a run cut short (the stage paused or handed over, a protection write, an interlock or watchdog switch-off) or not confirmed is recorded as partial, with the seconds the pump ran and why, and counts as not done in time. The pump runs at most once per occurrence (marking it skipped afterwards does not allow a second run) and not after the occurrence's deadline (two hours after it was due, or after the stage end for a task that may be made up). All the irrigation checks apply; see [The pump](Control-and-Safety-Model.md#the-pump). An irrigation task without `seconds` is watering by hand.

The system may pause the stage by itself, for example after a BLE outage that mattered or a change on the device panel. Each case is in the [Troubleshooting runbook](Troubleshooting-Runbook.md). `resume` is refused with `state` while the device differs from the run sheet or a write has an unknown result.

When the run sheet's duration is over, the executor writes the end actions and reads them back. Confirmed end actions move the stage to `ended`. The round goes back to `stage_review` if the protocol lists another stage, and to `data_verification` after the last one. While the next stage waits for review, the care rules of the ended stage keep running.

> **Stopping.** `POST /wb/stages/STAGE_ID/stop` ends the stage as `stopped`. The round then waits for your choice, and no new run sheet can be filed until you make it; see the next section. Pause instead of stop unless you mean to end the stage's work.

### After a stopped stage, and aborting

While a round waits, `GET /wb/rounds/ROUND_ID` shows the stopped stage's id in `awaiting_choice`. Choose what follows:

```http
POST /wb/rounds/ROUND_ID/choice

{"choice": "redo"}
```

| `choice` | What happens | Round state after |
| --- | --- | --- |
| `redo` | The stage is done again: a new run sheet can be filed. | `stage_review` |
| `next` | The stopped stage counts as done, and the run sheet of the protocol's next stage can be filed. Refused with `state` when the protocol has no stage left. | `stage_review` |
| `verify` | The round goes on to data verification with the data collected so far. | `data_verification` |
| `abort` | The same as aborting the round. | `aborted` |

To abort a round that is not `delivered` or `aborted` yet, with or without a stopped stage:

```http
POST /wb/rounds/ROUND_ID/abort
```

Every stage of the round hands back the write rights it holds. Stages that have not ended become `stopped` and their approvals are void. The round is `aborted` and cannot be reopened. After that no end actions are carried out and the round's care rules stop, so the device stays as the last write left it. The one exception is a pump cycle that is still running: it is cut short and its pump-off is written. The protection rules of the safety configuration are not part of a round and stay in force. Neither request asks for a re-authentication. Both are refused with `state` when there is nothing to choose or the round is already final.

## 6. Data verification

The researcher can first look at the stage's data with `inspect_stage_data` (read-only: coverage, gaps, channel ranges, measurements, manual tasks done in time), then freezes a data snapshot of the stage with its `freeze_dataset` tool. The freeze checks coverage and digests itself. When the snapshot is complete (coverage of at least 0.9) and passes verification, the round moves to `analysis`. Otherwise it stays in `data_verification`.

Measurements taken by hand must be recorded with `POST /wb/measurements` before the snapshot is frozen. A measurement belongs to an experiment of an existing stage: for an experiment id that no stage runs, the route refuses with `scope`, so every measurement can be traced to a project.

The researcher needs a research task to do this. In the end-to-end test the operator states a second goal with `POST /wb/goals`, and the scripted orchestrator hands it to the researcher. Whether a real model does the same has not been verified.

`GET /wb/rounds/ROUND_ID` shows the `snapshot_id` once a snapshot moved the round on. There is **no route** to see the snapshot's content or its coverage.

## 7 and 8. Analysis and the report

The researcher analyzes the frozen snapshot and calls `publish_research_report`. The report is saved as `research_report_<artifact id>.json` under `agent_work/reports/` in the data directory and registered in the project archive as an artifact of kind `research_report`. A final report moves the round to `delivered`. A report that needs review leaves the round in `analysis`. `GET /wb/rounds/ROUND_ID` shows the state and, once the report is published, its `report_artifact_id`.

### Run the frozen analysis

When the researcher has frozen a snapshot (step 6), the operator starts the one run of the frozen script on it. The request needs a re-authentication within the last 300 seconds.

```sh
curl -s -b wb.cookies -X POST -H "Origin: $BASE" -H 'x-growbridge-ui: 1' \
  -H 'Content-Type: application/json' \
  -d '{"project_id": "PROJECT_ID", "protocol_id": "PROTOCOL_ID", "snapshot_id": "SNAPSHOT_ID"}' \
  "$BASE/wb/analysis/runs"
```

The answer has `run_id`, `status` (`succeeded` or `failed`), `exit_code`, `timed_out`, and `stdout` and `stderr`, each cut at 4000 characters. The answer comes when the run is over, after at most 600 seconds. The rest of the daemon, the protection rules and the pump-off included, keeps running meanwhile.

The request is refused before the sandbox starts, in this order:

1. `state`: there is no such protocol in the project.
2. `scope`: the snapshot is not a snapshot of a round that runs this protocol, or its experiment belongs to rounds of more than one protocol version. `state`: a later correction invalidated the snapshot. The version that counts is the one the snapshot was collected under, not the latest saved one, so a later version with no script yet does not matter.
3. `state`: no script is frozen for that version.
4. `state`: a stage behind the snapshot started before the script was frozen. Data collected before the freeze can never be confirmatory.
5. `snapshot_incomplete`: the snapshot is incomplete, or a file no longer matches its manifest.
6. `scope`: the snapshot holds an outcome of a held-out batch. Held-out data goes into no analysis. `state`: a manual measurement in the snapshot was recorded before the script was frozen (the archive's own recording time counts, not the `measured_at` you typed in), or has no recording time because it predates the archive keeping one.
7. `already_run`: this snapshot was run before. A run that failed or timed out also used up the attempt.
8. `sandbox_unavailable`: this platform has no sandbox (it exists on macOS only). The attempt is not used up.

A report is analysed under the protocol version its data was collected under, read from the rounds of the snapshots it cites; snapshots of more than one version are refused with `param`. While a script is frozen for that version, the researcher's `publish_research_report` is refused with `state` as long as the run of any snapshot it cites is `none` or `running`. If every run has ended, the report is published: it can be confirmatory when all runs succeeded and nothing else lowers the label, and it is exploratory when one run failed. Without a frozen script nothing changes: the report is exploratory.

There is **no route** to read the report, to read or list research tasks, or to settle a task in `needs_review` or `needs_attention`. An alert of kind `agent_task` in `GET /wb/alerts` tells you that a model task failed or needs attention; for an audit it is `audit_task`, a warning, one per stage.

## Steps with no route or command today

- List projects or rounds, or read a saved research protocol.
- Read the call budget without setting it.
- Read a research task or list the tasks of a project.
- Read the stage history or the reason for a pause.
- Revoke an approval, or switch the run sheet of a live stage.
- Register a model for a holdout, or score one.
- Read the daily reports or the data snapshot.

The services already have methods for most of these, many of them in [`workflow/service.py`](../../../src/growbridge/workflow/service.py). The routes and commands do not exist yet. No step of a round has a CLI command.

## See also

- [Enable DiAGRI](Enable-DiAGRI.md)
- [Manual takeover, irrigation and handback](Manual-Takeover-and-Irrigation.md)
- [Troubleshooting runbook](Troubleshooting-Runbook.md)
- [Workflow and state machines](Workflow-and-State-Machines.md)
- [HTTP, workbench and MCP interfaces](API-Reference.md)
- [Denial codes and stage events](Denial-Codes-and-Events.md)
