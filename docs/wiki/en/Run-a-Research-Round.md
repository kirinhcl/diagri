# Run a research round

[简体中文](../zh-CN/Run-a-Research-Round.md)

This page is for an operator who follows one research round from the goal to the delivered report. For each step it says who acts, which workbench request or command the operator uses, and which round state and stage state the step leaves.

> **Status.** An operator can start and steer a round through `/wb`: create the project, the research protocol and the round, set the model call budget, state the goal, read a run sheet before approving it, choose what follows a stopped stage, and abort the round. This path has run only in the tests, on the simulated AC5, with a scripted model and an in-process HTTP client ([`test_e2e_http_round.py`](../../../tests/e2e/test_e2e_http_round.py)). It has not been run against a `serve` process, a real model or a real device. There is no web page and no CLI command for these steps. Some reads still have no route; they are marked **no route** and listed again at the end. See [Status and known limitations](Status-and-Known-Limitations.md).

## What the workbench is

The workbench is a set of JSON routes under `/wb`, defined in [`workbench/api.py`](../../../src/growbridge/workbench/api.py) and [`workbench/rounds.py`](../../../src/growbridge/workbench/rounds.py). It has no web page: the dashboard at `/` is the bridge-only one and never calls `/wb`. You send the requests yourself, with any HTTP client that keeps cookies.

Every request follows these rules:

1. Send it to an entry address: `http://YOUR_LAN_HOST:LAN_PORT` on site, or `https://YOUR_OVERLAY_HOST` over the overlay network. Other addresses are refused with `entry`.
2. Log in once with `POST /wb/login` and the body `{"name": "YOUR_OPERATOR", "secret": "..."}`. The answer sets the cookie `growbridge_operator`, valid for 8 hours and only on the entry it was issued on.
3. Every request that is not a `GET` needs two headers: `Origin`, equal to the address you are using, and `x-growbridge-ui: 1`.
4. Approve, resume, takeover, safety approval and setting the call budget need a re-authentication within the last 300 seconds. Login counts. Later, send `POST /wb/reauth` with `{"secret": "..."}` first.
5. A refusal has the body `{"detail": {"code": "...", "message": "..."}}`. The status is `409` for `state`, `401` for `session`, `429` for `locked` and `403` for every other code. A malformed body is `422`.

With `curl`, the first requests look like this. `login.json` holds the login body; keep it private and delete it afterwards.

```sh
BASE=http://YOUR_LAN_HOST:9443
curl -s -c wb.cookies -H "Origin: $BASE" -H 'x-growbridge-ui: 1' \
  -H 'Content-Type: application/json' -d @login.json "$BASE/wb/login"
curl -s -b wb.cookies "$BASE/wb/stages/STAGE_ID"
curl -s -b wb.cookies -X POST -H "Origin: $BASE" -H 'x-growbridge-ui: 1' \
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
| 7. Analysis | researcher | `GET /wb/rounds/ROUND_ID` | `analysis` | `ended` |
| 8. Report delivered | researcher | `GET /wb/rounds/ROUND_ID` | `delivered` | `ended` |

State names are those in [`workflow/states.py`](../../../src/growbridge/workflow/states.py). Why the states are shaped this way is on [Workflow and state machines](Workflow-and-State-Machines.md).

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

How a real model handles a goal has not been verified. The tests use a scripted model; see [`test_e2e_http_round.py`](../../../tests/e2e/test_e2e_http_round.py).

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

## 3. Approve the run sheet

```http
POST /wb/stages/STAGE_ID/approve
```

You should get the approval record, with `operator`, `run_sheet_version`, `run_sheet_digest` and `recovery_number`. Compare `run_sheet_digest` with the one you read in step 2: if they differ, a new version was filed in between and you approved that one. The stage stays in `pending_review`; approving does not start it.

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

| To do this | Send |
| --- | --- |
| Read the stage | `GET /wb/stages/STAGE_ID` |
| Read open alerts, mark one as read | `GET /wb/alerts`, `POST /wb/alerts/EVENT_ID/read` |
| Read the receipt of a write | `GET /wb/receipts/REQUEST_ID` |
| Record a measurement taken by hand | `POST /wb/measurements` |
| Pause | `POST /wb/stages/STAGE_ID/pause`, optional body `{"reason": "..."}` |
| Resume | `POST /wb/stages/STAGE_ID/resume` (re-authentication) |
| Take over by hand | [Manual takeover, irrigation and handback](Manual-Takeover-and-Irrigation.md) |

A measurement body has `experiment_id`, `batch`, `plant_id`, `layout_version`, `measured_at` (UTC seconds), `position`, `method`, `metric`, `value` and `unit`. Add `corrects` with the id of an earlier measurement to correct it; the earlier record is kept.

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

The researcher freezes a data snapshot of the stage with its `freeze_dataset` tool. When the snapshot is complete (coverage of at least 0.9) and passes verification, the round moves to `analysis`. Otherwise it stays in `data_verification`.

Measurements taken by hand must be recorded with `POST /wb/measurements` before the snapshot is frozen.

The researcher needs a research task to do this. In the end-to-end test the operator states a second goal with `POST /wb/goals`, and the scripted orchestrator hands it to the researcher. Whether a real model does the same has not been verified.

`GET /wb/rounds/ROUND_ID` shows the `snapshot_id` once a snapshot moved the round on. There is **no route** to see the snapshot's content or its coverage.

## 7 and 8. Analysis and the report

The researcher analyzes the frozen snapshot and calls `publish_research_report`. The report is saved as `research_report_<artifact id>.json` under `agent_work/reports/` in the data directory and registered in the project archive as an artifact of kind `research_report`. A final report moves the round to `delivered`. A report that needs review leaves the round in `analysis`. `GET /wb/rounds/ROUND_ID` shows the state and, once the report is published, its `report_artifact_id`.

There is **no route** to read the report, to read or list research tasks, or to settle a task in `needs_review` or `needs_attention`. An alert of kind `agent_task` in `GET /wb/alerts` tells you that a model task failed or needs attention.

## Steps with no route or command today

- List projects or rounds, or read a saved research protocol.
- Read the call budget without setting it.
- Read a research task or list the tasks of a project.
- Read the stage history or the reason for a pause.
- Revoke an approval, or switch the run sheet of a live stage.
- Add an evidence card.
- Read the daily reports, the data snapshot or the research report.

The services already have methods for most of these, many of them in [`workflow/service.py`](../../../src/growbridge/workflow/service.py). The routes and commands do not exist yet. No step of a round has a CLI command.

## See also

- [Enable DiAGRI](Enable-DiAGRI.md)
- [Manual takeover, irrigation and handback](Manual-Takeover-and-Irrigation.md)
- [Troubleshooting runbook](Troubleshooting-Runbook.md)
- [Workflow and state machines](Workflow-and-State-Machines.md)
- [HTTP, workbench and MCP interfaces](API-Reference.md)
- [Denial codes and stage events](Denial-Codes-and-Events.md)
