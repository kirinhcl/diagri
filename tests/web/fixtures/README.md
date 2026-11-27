# Console page fixtures

Real answers of the workbench API, captured on 2026-11-16 from the data of the round run on
2026-11-15 (simulated device, no secrets, no cookies), at commit 03b5115, with the dev workbench
started without model roles. `report.json` is the same round's report as saved during the run on
2026-11-15 (the copied data directory lacks the report file). `compute.json` is synthetic, written
to the shape of `src/growbridge/compute/overview.py` (the dev workbench has no compute service).

Task 5 of console usability batch 1 added the server's new name fields to these answers by hand,
following the server's rules: `project_name`, `round_number`, `stage_index` and `phase` in
round.json, round-pending.json, stage.json, stage-pending.json and inbox.json (the stage item),
`round_number` in project.json and projects.json, and `created_at` on the snapshots in
analysis.json. Each round here is the first of its protocol in its project and each stage the
first of its round, so both numbers are 1; both protocols (`protocol-lettuce-light` and the dev
seed's `protocol-1`) list the single phase `vegetative`. The snapshot's `created_at` is in no
captured answer: analysis.json uses the time conversation.json records for the `freeze_dataset`
call that froze it (entry seq 30), a close stand-in, not the stored value. environment.json has no
active stage, so it gained nothing.

Task 7 of console usability batch 2a gave every alert the server's new `code` and `params`, by hand.
Converted from captured entries (same `message`, `code` = `kind`, `params` `{}`, per the code tables
in tasks 5 and 6): the three `*_unconfigured` alerts in alerts.json, and their three alert items in
inbox.json (as `detail.code` and `detail.params`). Synthetic, written by hand from the server's code
tables (`src/growbridge/codes.py`) and not captured: in alerts.json a `stage_waiting` alert for the
stage id `stage:a-1` (a colon, to test the link; `params.detail` holds `seconds` and `reasons`), an
`audit_finding` with a summary and two evidence lines, a `threshold` alert, and a `data_gap` alert
with no `code` or `params` (a row stored before codes); in inbox.json the `stage_waiting` and the
code-less `data_gap` alert items.

Before task 9 of batch 2a, run-sheet.json and run-sheet-pending.json were captured again from the
same data, at commit 134e8c3, with the dev workbench started without model roles. Findings are
computed on every read, so they now carry the server's `variant` and `params`. Nothing else in the
two files changed (checked by comparing them without `findings`).

Task 12 of batch 2a (CMP-04) converted the stuck attempts in `compute.json` by hand and added
five `compute_stuck` items to `inbox.json` (their `detail` is the same row, as the server copies it).
Each carries the server's new `reason_code` and `reason_params`; a row whose reason is an error
also carries `error_code` and `error_params` (one with a code, `output_limit`, and one without, as
from before codes). `reason` is unchanged. One row of each file has no `reason_code`, as stored
before codes. These are synthetic, written to the shape of `src/growbridge/compute/overview.py`.

Task 13 of batch 2a (P-11) gave five of the six "run finished" status entries in conversation.json
(seq 5, 15, 18, 26, 38) the server's new `detail.code` (`run_finished`) and `detail.params` (`{}`) by
hand, keeping `reason`. The one at seq 41 stays as captured, with no code, so the leak test covers
both shapes. No captured entry ended in a refusal, a model failure or an undelivered result; those
shapes are tested in tests/web/conversation.test.mjs.

`known-codes.json` is not an API answer: it lists, per catalog prefix, the codes the server can
send, and says in `_sources` where each list was found. `tests/web/catalog.test.mjs` checks that
each code has text in both catalogs; `tests/workbench/test_console_known_codes.py` checks the lists
against the server's enums and literals.

| File | Path (pattern) |
| --- | --- |
| me.json | `/me` |
| inbox.json | `/inbox` |
| projects.json | `/projects` |
| project.json | `/projects/{project_id}` (Lettuce light series) |
| holdouts.json | `/holdouts?project_id={project_id}` |
| greenhouses.json | `/greenhouses` (multi-user; synthetic) |
| admin-operators.json | `/admin/operators` (multi-user; synthetic) |
| admin-locks.json | `/admin/locks` (multi-user; synthetic) |
| guide-session.json | `/guide/sessions/{session_id}` (a new session, nothing answered; shape of the real answer, synthetic ids) |
| guide-options-crop.json | `/guide/sessions/{session_id}/steps/crop` (four of the real crop options; `guide-options-question.json` is the real answer for the question step, with no options; other steps read `guide-options-<step>.json`, which a test supplies) |
| conversation.json | `/projects/{project_id}/conversation?after=0` |
| round.json | `/rounds/{round_id}` (delivered round) |
| report.json | `/rounds/{round_id}/report` |
| analysis.json | `/protocols/{protocol_id}/analysis?project_id={project_id}` |
| stage.json, run-sheet.json, readings.json, measurements.json, history.json, manual-tasks.json | `/stages/{stage_id}`, `/run-sheet`, `/readings?points=120`, `/measurements`, `/history`, `/manual-tasks` of the ended stage |
| round-pending.json, stage-pending.json, run-sheet-pending.json, readings-pending.json, measurements-pending.json, history-pending.json, manual-tasks-pending.json | the same reads for `stage-dev`, the dev seed's stage waiting for review |
| environment.json | `/environment?window=3600&points=360` |
| capabilities.json | `/capabilities` (synthetic, see below) |
| device-notes.json | `/devices/{device_id}/notes` |
| safety.json | `/safety` (`highest_version` added by hand, see below) |
| safety-none.json | `/safety` when no limits are approved yet (`{"safety": null, "highest_version": null}`, synthetic; give it as `fixtures: {"safety.json": ...}`) |
| alerts.json | `/alerts` |
| evidence.json | `/evidence` |
| evidence-relations.json | `/evidence/relations` (synthetic, no relations) |
| compute.json | `/compute` (synthetic) |
| variables.json, variables-pending.json | `/experiments/{experiment_id}/variables` of the ended stage's and of `stage-dev`'s experiment (synthetic) |

## report.json (task 14)

`report.estimate` carries `note_code: "too_few_blocks"` and `note_params: {blocks: 0, min_blocks: 2}`
beside the unchanged English `note`, as the server now writes them. The top-level `primary_endpoint`
is the answer's new field; its value `canopy_area_growth` is the metric the project's protocol names
in project.json (the protocol itself is not among the captured answers), so the value is that
protocol's endpoint but the field was added by hand, not captured.

## project.json budget (task 15)

The top-level `budget` gained `used_calls`, `used_cost`, `max_calls` and `max_cost` by hand, as the
server now answers (beside the captured `calls_left` and `cost_left`). Values are synthetic but
consistent with the captured left-overs: 103 left of 120 calls (17 used), 97.06714 left of 100 cost
(2.93286 used).

## capabilities, approval, protocol summary (batch 3, task 3)

All three are additive server fields, added to the fixtures by hand (not captured):

- capabilities.json is new. `level_ranges` and `sensors` are copied from environment.json
  (the server reads both from the same `capabilities()`). `max_pump_seconds: 5.0` is the server's default setting.
- run-sheet.json and run-sheet-pending.json gained `approval` beside `state`. The ended stage's run
  sheet was approved: `{approved_at: 1794780100.5, run_sheet_version: 1}` (about two minutes before
  the stage's `started_at`, version 1 as the sheet's). The pending stage is not approved, so its
  `approval` is `null`. The server only sets `approval` when the approval's digest equals the current
  run sheet's digest.
- project.json: each `protocols[]` row gained `primary_endpoint: "canopy_area_growth"` and
  `method: "paired_block"`, the values of the protocol body the dev project was frozen with (the same
  endpoint report.json names). Both are `null` on the server when the stored body has none.

## variables.json and variables-pending.json (variable catalog, task 5)

Synthetic, not captured: the answer of the new `/experiments/{experiment_id}/variables` read, written
by hand to the shape of `src/growbridge/workbench/api.py`. Both experiments' protocols name the
primary endpoint `canopy_area_growth` (the dev seed's `protocol-1` is `make_protocol`, which declares
it), so each file lists that one variable with the packaged catalog's labels, unit `cm2/d` and
method. The measurements captured before the catalog keep their recorded unit `cm2/day`.

## safety.json and safety-none.json (server input checks after batch 3)

`/safety` gained `highest_version`, the highest safety version ever approved on the device, in force
or not (`null` before the first approval); a new approval must go above it. Added by hand, not
captured: safety.json's set is version 1 and the only one approved, so its `highest_version` is `1`;
safety-none.json has nothing approved, so `null`. A recovery leaves `safety` null while
`highest_version` keeps its number; safety-form.test.mjs gives that case inline.
