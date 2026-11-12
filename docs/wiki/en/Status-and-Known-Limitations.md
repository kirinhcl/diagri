# Status and known limitations

[简体中文](../zh-CN/Status-and-Known-Limitations.md)

This page is for anyone who has to decide how far to trust the system: users, operators and contributors. It lists what has been verified and how, and what has not been verified or is not implemented. Every row names the place where you can check it.

The page was last checked against the working tree on 2026-11-10.

## In three lines

- DiAGRI mode has only ever run on the simulated AC5 ([`sim/device.py`](../../../src/growbridge/sim/device.py)). In that mode nothing has written to a real device.
- GrowBridge on its own (bridge-only mode) has read and controlled one real AC5 from a Mac. That record is older than the rest of the DiAGRI code.
- Nothing has been verified on a Raspberry Pi, with real notification services, or with CSC.

## Verified

| What | How it was verified | Where to check |
| --- | --- | --- |
| The test suite | 1452 code tests pass on macOS with Python 3.14 (last run 2026-11-11). The last run with Python 3.11 was at 1292 tests. The count leaves out `tests/docs/`, which checks the links of this wiki and grows with it. | [`tests/`](../../../tests/), run with `.venv/bin/pytest -q` |
| Continuous integration | Passes on `ubuntu-latest` and `macos-latest` with Python 3.11 and 3.13. It runs `ruff check`, `ruff format --check`, `pytest -q`, `python -m build` and a syntax check of the dashboard script. On macOS it also compiles the Swift helper, but does not run it. | [`ci.yml`](../../../.github/workflows/ci.yml) |
| Coverage | 95 % when it was measured, at 1292 tests. CI does not measure coverage, and it has not been measured again since. | not recorded in the repository |
| A whole research round | From creating the project to `delivered`, with a manual takeover and a handback in the middle, on the simulated AC5. | [`test_e2e_round.py`](../../../tests/e2e/test_e2e_round.py) |
| The model roles, end to end | Orchestrator, planner and researcher driven by a scripted model client, with no network and no key, from a delegation to a delivered round. | [`test_e2e_agents.py`](../../../tests/e2e/test_e2e_agents.py) |
| A round through the workbench routes | From the login to `delivered` on the simulated AC5. Every operator step is an HTTP request to `/wb`, sent by an in-process client to the app that `serve` builds; the model roles are a scripted client. A second test stops a stage, chooses `redo` and aborts the round. No `serve` process and no real model took part. | [`test_e2e_http_round.py`](../../../tests/e2e/test_e2e_http_round.py), [`test_workbench_rounds.py`](../../../tests/workbench/test_workbench_rounds.py) |
| A stage runs without a model | An approved stage runs to its end with no model client, and also while every model call fails. `tick` never calls a model. | [`test_e2e_runtime.py`](../../../tests/e2e/test_e2e_runtime.py), [`test_e2e_agents.py`](../../../tests/e2e/test_e2e_agents.py) |
| Restart and recovery | A restart puts a live stage into `recovery_check`, then `paused`, and the operator resumes it. A stage that was waiting for review goes back to `pending_review` by itself. A lost write reply pauses the stage. A recovery number bump voids approvals and sessions. | [`test_e2e_runtime.py`](../../../tests/e2e/test_e2e_runtime.py), [`test_e2e_reviewed.py`](../../../tests/e2e/test_e2e_reviewed.py) |
| Why a stage waits | A stage that the system pauses or puts into the recovery check raises the alert `stage_waiting`, which names the event and what it carried; the same detail is kept in the stage history. The alert resolves when the stage leaves that state. A wall-clock step pauses a running stage once, and the operator's resume of a stage it paused clears it; starting another stage does not. | [`test_e2e_stage_alerts.py`](../../../tests/e2e/test_e2e_stage_alerts.py), [`test_executor_clock.py`](../../../tests/executor/test_executor_clock.py), [`test_workflow_events.py`](../../../tests/workflow/test_workflow_events.py) |
| Running with no notification channel | Nothing is queued, the warning `notify_unconfigured` stands, and the run health is not affected. Open alerts are sent once a channel is configured. | [`test_e2e_notifications.py`](../../../tests/e2e/test_e2e_notifications.py) |
| `growbridge simulate` | One approved stage runs to `ended` on the simulated AC5, with three confirmed writes. | [Tutorial](Tutorial-Simulated-Round.md), [`test_e2e_cli.py`](../../../tests/e2e/test_e2e_cli.py) |
| GrowBridge alone (bridge-only mode) on a real AC5 | By hand, on macOS, with one AC5 (advertised as SF-GGS-PS5, firmware 3.2, plaintext protocol v1): scan, connect, live telemetry, a light write confirmed by read-back, an MCP client, the dashboard. Recorded on 2026-10-29, before the rest of DiAGRI was added. No later check on a real device is recorded. | [VALIDATION.md](../../../VALIDATION.md) |

## Not verified or not implemented

"Not verified" means the code exists but has never run under the real condition. "Deployment item" means the design needs it and the code leaves room for it, but nothing in the repository sets it up. "Not implemented" means the code is missing.

| Area | State | Detail | Where to check |
| --- | --- | --- | --- |
| DiAGRI mode on a physical AC5 | not verified | Never run. This includes a Bluetooth interruption in the middle of a stage, power loss of the host or of the AC5, and long unattended runs. | [VALIDATION.md](../../../VALIDATION.md) |
| Raspberry Pi and Linux Bluetooth | not verified | `BleakTransport` (Bleak on BlueZ) has only run against a fake client in the tests. No run on a physical Raspberry Pi is recorded. | [`transport.py`](../../../src/growbridge/transport.py), [`tests/transport/`](../../../tests/transport/) |
| The Swift helper's exit when its event channel closes | not verified | On macOS the helper is meant to drop its queued writes and exit when the Python side hangs up (`watchChannel`). CI only compiles the helper. | [`BLEHelper.swift`](../../../src/growbridge/native/BLEHelper.swift) |
| Other controllers, other firmware, encrypted protocol v2 | not verified | Only one AC5 with plaintext protocol v1 has been used. Control requires protocol version 1 and is refused otherwise. | [`service.py`](../../../src/growbridge/service.py), [VALIDATION.md](../../../VALIDATION.md) |
| The background tasks of `serve` | no automated test | The 1 Hz tick loop (`_tick_forever`), the model-role polling every 30 seconds (`_agents_forever`) and the second listener for the LAN entry (`_serve_listeners`) are not covered by any test. The tests call `Runtime.tick()` and `Runtime.run_agents()` directly. | [`cli.py`](../../../src/growbridge/cli.py) |
| Real Telegram and email delivery | not verified | `TelegramChannel` and `EmailChannel` have only been exercised with fake transports. | [`observer/channels.py`](../../../src/growbridge/observer/channels.py), [`test_observer_channels.py`](../../../tests/observer/test_observer_channels.py) |
| External heartbeat | not implemented in `serve` | `HeartbeatChannel` and `ExternalMonitor` exist and are tested with fakes, but `serve` builds the runtime without heartbeat endpoints, so no heartbeat is sent. With endpoints, the runtime would beat once every 60 seconds and at once when the run health turns. | [`runtime.py`](../../../src/growbridge/runtime.py) (`build_runtime`, argument `heartbeats`) |
| Host time synchronisation | not implemented | Nothing checks whether the host clock is synchronised: `SystemClock.synced` stays true. The only clock check is a step of more than 5 seconds between the wall clock and the monotonic clock, which pauses a running stage until an operator resumes it. A host that sleeps looks like such a step when it wakes. | [`archive/clock.py`](../../../src/growbridge/archive/clock.py), [`executor/outage.py`](../../../src/growbridge/executor/outage.py) |
| `data` and `provider` of a model role | not enforced | Both fields are checked on load and read by no code. `data` does not restrict what a role can read; what a role can reach is set by its tools. | [`config.py`](../../../src/growbridge/config.py), [`agents/tools.py`](../../../src/growbridge/agents/tools.py) |
| Model prices | not verified | The built-in price of the default model (`DEFAULT_PRICE`) is a constant in the code and has not been checked against the provider's current price list. Every other model takes its price from the configuration. | [`agents/llm.py`](../../../src/growbridge/agents/llm.py), [Configuration reference](Configuration-Reference.md) |
| OS-account isolation | deployment item | The code is one process. It keeps one SQLite file per service (`control`, `workflow`, `archive`, `observer`, `compute`, `agents`), which is what separate accounts would be built on. | [`runtime.py`](../../../src/growbridge/runtime.py) (`DATABASES`) |
| Overlay network | deployment item | The daemon listens on `127.0.0.1` and expects a proxy in front of it for the overlay entry. The repository contains no proxy or network configuration. | [`workbench/auth.py`](../../../src/growbridge/workbench/auth.py) (`entry_for`) |
| Passkeys | not implemented | An operator signs in with a secret of at least 12 characters, stored as a salted scrypt hash. | [`workbench/auth.py`](../../../src/growbridge/workbench/auth.py) |
| Entering a research goal | not verified with a real model | An operator creates the project, the research protocol and the round, sets the call budget and states the goal through `/wb` routes. These routes have run only in tests, with a scripted model and an in-process HTTP client. What a real model does with a goal has never been run. There is no CLI command and no web page for these steps. | [`workbench/rounds.py`](../../../src/growbridge/workbench/rounds.py), [Run a research round](Run-a-Research-Round.md) |
| Workbench routes that are still missing | not implemented | No route adds an evidence card, lists projects or rounds, reads a saved research protocol, reads or settles a research task, reads the stage history, the data snapshot or a report, revokes an approval, or switches the run sheet of a live stage. Nothing records which operator created a project, a protocol or a round, or set a budget. | [`workbench/api.py`](../../../src/growbridge/workbench/api.py), [`workbench/rounds.py`](../../../src/growbridge/workbench/rounds.py), [`workflow/service.py`](../../../src/growbridge/workflow/service.py) |
| A web page for the workbench | not implemented | The workbench is a set of HTTP routes under `/wb`. The only page is the bridge dashboard, which is read-only in DiAGRI mode. | [`workbench/api.py`](../../../src/growbridge/workbench/api.py), [`web/`](../../../src/growbridge/web/) |
| Jobs on CSC | not implemented | Every remote operation of `FirecrestBackend` raises `NotImplementedError`. `serve` builds no compute service, so the compute tools answer `unavailable`. The lists of compute templates and members are empty. | [`compute/firecrest.py`](../../../src/growbridge/compute/firecrest.py), [`runtime.py`](../../../src/growbridge/runtime.py) |
| Literature search | not implemented | There is no search backend. The planner tools `lookup_crop_conditions` and `search_and_verify_sources` answer `unavailable`. | [`agents/handlers_planner.py`](../../../src/growbridge/agents/handlers_planner.py), [`runtime_agents.py`](../../../src/growbridge/runtime_agents.py) |
| Sandbox for model-written code | macOS only | The sandbox uses `sandbox-exec`. Everywhere else, Linux and the Raspberry Pi included, it refuses to run anything, with the denial `sandbox_unavailable`. That stops local analysis and the confirmatory analysis there. | [`research/sandbox.py`](../../../src/growbridge/research/sandbox.py) |
| Alert rules | empty by default | `DEFAULT_ALERT_RULES` is empty and there is no configuration field for alert rules, so the observer raises no threshold alert. | [`runtime.py`](../../../src/growbridge/runtime.py) |
| Camera capture | not implemented | There is no camera code. Growth observations are entered as manual measurements. | [`observer/report.py`](../../../src/growbridge/observer/report.py) |
| Backup | SQLite databases only | A backup copies the six DiAGRI databases. It does not copy the bridge history file `growbridge.sqlite3`, or the files under `archive/` in the data directory, such as snapshots. There is no image capture yet, so there are no images to back up. Without `backup_dir` nothing is backed up, and a standing warning says so. | [`runtime_backup.py`](../../../src/growbridge/runtime_backup.py), [`archive/backup.py`](../../../src/growbridge/archive/backup.py) |
| Skipped tests | skipped, not passed | Tests that need `sandbox-exec` are skipped where it is missing, which is the case on Linux CI. Tests that build the Anthropic client are skipped where the `anthropic` package is missing; CI installs only the `dev` extra, so they are skipped on both CI systems. | [`test_research_sandbox.py`](../../../tests/research/test_research_sandbox.py), [`test_e2e_assembly.py`](../../../tests/e2e/test_e2e_assembly.py), [`test_agents_llm.py`](../../../tests/agents/test_agents_llm.py) |

## How to check again

```sh
.venv/bin/python -m pip install -c constraints-tested.txt -e '.[dev]'
.venv/bin/pytest -q
.venv/bin/growbridge simulate
```

The first command installs the test tools. The second runs the whole suite on the simulated AC5; add `-rs` to list the skipped tests and the reason for each. The third runs one simulated stage, as described in the [tutorial](Tutorial-Simulated-Round.md).

Checks on real hardware are recorded in [VALIDATION.md](../../../VALIDATION.md). A row moves to the first table once its check is recorded there.

## See also

- [Overview](Overview.md)
- [Development setup, testing and CI](Development-Setup-Testing-and-CI.md)
- [Troubleshooting runbook](Troubleshooting-Runbook.md)
- [FAQ](FAQ.md)
