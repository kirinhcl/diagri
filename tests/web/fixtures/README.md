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
| conversation.json | `/projects/{project_id}/conversation?after=0` |
| round.json | `/rounds/{round_id}` (delivered round) |
| report.json | `/rounds/{round_id}/report` |
| analysis.json | `/protocols/{protocol_id}/analysis?project_id={project_id}` |
| stage.json, run-sheet.json, readings.json, measurements.json, history.json, manual-tasks.json | `/stages/{stage_id}`, `/run-sheet`, `/readings?points=120`, `/measurements`, `/history`, `/manual-tasks` of the ended stage |
| round-pending.json, stage-pending.json, run-sheet-pending.json, readings-pending.json, measurements-pending.json, history-pending.json, manual-tasks-pending.json | the same reads for `stage-dev`, the dev seed's stage waiting for review |
| environment.json | `/environment?window=3600&points=360` |
| safety.json | `/safety` |
| alerts.json | `/alerts` |
| evidence.json | `/evidence` |
| compute.json | `/compute` (synthetic) |
