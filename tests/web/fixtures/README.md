# Console page fixtures

Real answers of the workbench API, captured on 2026-11-16 from the data of the round run on
2026-11-15 (simulated device, no secrets, no cookies), at commit 03b5115, with the dev workbench
started without model roles. `report.json` is the same round's report as saved during the run on
2026-11-15 (the copied data directory lacks the report file). `compute.json` is synthetic, written
to the shape of `src/growbridge/compute/overview.py` (the dev workbench has no compute service).

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
