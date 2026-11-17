# Development setup, testing and CI

[简体中文](../zh-CN/Development-Setup-Testing-and-CI.md)

This page is for contributors. It takes you from a fresh clone to a green test run, then lists every check CI runs, how the tests are laid out and the rules a new test must follow.

Everything on this page runs on simulators. Apart from the install and the package build, no step needs the network, and no step needs an AC5, a Bluetooth radio or a model API key. What has been tested on real hardware and what has not is on [Status and known limitations](Status-and-Known-Limitations.md).

## Prerequisites

| You need | Used for | Where it is set |
| --- | --- | --- |
| Python 3.11 or newer | everything | `requires-python = ">=3.11"` in [`pyproject.toml`](../../../pyproject.toml) |
| Node.js | a syntax check of the dashboard and console scripts, and the console's unit tests (`node --test`, no npm packages). CI uses Node 22. | [`.github/workflows/ci.yml`](../../../.github/workflows/ci.yml) |
| Xcode Command Line Tools, macOS only | compiling the native BLE helper, the last CI step | the same file |

CI runs four jobs: `ubuntu-latest` and `macos-latest`, each with Python 3.11 and 3.13. The test run recorded on this page was made on macOS with Python 3.14, which is outside that matrix.

## Create the environment

```sh
git clone <repository-url>
cd diagri
python3 -m venv .venv
.venv/bin/python -m pip install -c constraints-tested.txt -e '.[dev]'
```

What the install line does:

- `-c constraints-tested.txt` pins the runtime dependencies (`bleak`, `fastapi`, `httpx`, `mcp`, `pydantic`, `starlette`, `uvicorn`) to the versions in [`constraints-tested.txt`](../../../constraints-tested.txt). It does not pin the development tools or the optional extras.
- `-e` installs the package in editable mode, so the `growbridge` command and the tests use the files under `src/`.
- The `dev` extra adds `pytest`, `pytest-asyncio`, `pytest-cov`, `ruff` and `build`.
- `bleak` is installed on Linux only. On macOS the BLE link goes through the Swift helper in [`native/BLEHelper.swift`](../../../src/growbridge/native/BLEHelper.swift).

The environment lives in `.venv/`, which [`.gitignore`](../../../.gitignore) excludes.

### Optional extras

| Extra | Installs | What it is for | Without it |
| --- | --- | --- | --- |
| `agents` | `anthropic` | `AnthropicClient` in [`agents/llm.py`](../../../src/growbridge/agents/llm.py), the client the model roles call. | The package still imports and runs. In DiAGRI mode with `roles` configured, `growbridge serve` raises an alert and leaves the model roles off. Two tests are skipped. |
| `csc` | `pyfirecrest` | Constructing `FirecrestBackend` in [`compute/firecrest.py`](../../../src/growbridge/compute/firecrest.py). | `FirecrestBackend()` without an injected client raises `BackendUnavailable`. No test needs the package: they pass a fake client. |

The `csc` extra installs only the client library. The adapter follows its documentation and has only been tested against a fake client; it has never talked to CSC. See [Status and known limitations](Status-and-Known-Limitations.md).

To add an extra, list it next to `dev`:

```sh
.venv/bin/python -m pip install -c constraints-tested.txt -e '.[dev,agents]'
```

## Run the checks CI runs

CI runs these steps in this order. Run them the same way before you push. CI calls the tools without the `.venv/bin/` prefix.

| Step | Command | What it checks |
| --- | --- | --- |
| 1 | `for f in src/growbridge/web/app.js $(find src/growbridge/web/workbench -name '*.js'); do node --check "$f"; done` | The dashboard script and every console script parse. |
| 2 | `node --test tests/web/*.test.mjs` | The console's unit tests (148 on 2026-11-14): the pure parts of the console, such as routing, formatting, denial messages and the chart maths, and a guard that no console script writes HTML with `innerHTML`. They run in Node without a browser, a server or a network. |
| 3 | `.venv/bin/python -m pip install -c constraints-tested.txt -e '.[dev]'` | The package installs with the pinned versions. |
| 4 | `.venv/bin/ruff check src tests scripts` | Lint. Rule sets `E`, `F`, `I`, `B` and `UP`, line length 100, set in `pyproject.toml`. |
| 5 | `.venv/bin/ruff format --check src tests scripts` | Formatting. |
| 6 | `.venv/bin/pytest -q` | The whole test suite. |
| 7 | `.venv/bin/python -m build` | The source distribution and the wheel build into `dist/`. |
| 8 | `xcrun swiftc src/growbridge/native/BLEHelper.swift -o /tmp/growbridge-ble -framework CoreBluetooth -framework AppKit` | macOS only. The native helper compiles. The helper is not started, so no radio is used. |

Notes on single steps:

- **Steps 4 and 5.** `.venv/bin/ruff check --fix src tests scripts` and `.venv/bin/ruff format src tests scripts` repair most findings.
- **Step 6.** The suite collects the code tests plus the wiki tests in `tests/docs/`. On 2026-11-14 it collected 2385 tests, 2274 code tests and 111 wiki tests, and gave `2385 passed` in about 65 seconds on macOS with Python 3.14 and the `agents` extra installed. The wiki tests come to about two per wiki page, so the total grows with the wiki.
- **Step 7.** `build` creates an isolated environment and downloads the build backend (`setuptools`), so this step needs the network. Git ignores `dist/`.

One more check is useful although CI does not run it: `.venv/bin/growbridge simulate` runs one short stage on the simulated AC5 through the assembled runtime and prints a summary. [Tutorial: a simulated research round](Tutorial-Simulated-Round.md) walks through it.

## How the tests are laid out

Tests live in [`tests/`](../../../tests), one folder per area. The folders are not packages, so every test file name is unique and starts with its area, for example `test_control_rights.py`.

| Folder | What it covers |
| --- | --- |
| `tests/foundation/` | The shared models, the SQLite `Database` helper and the simulators themselves. |
| `tests/archive/` | The project archive: append-only store, data snapshots, metadata export, the legacy sample source, storage pressure and backup. |
| `tests/control/` | The control service: write rights, the submit path, the pump interlock, reconciling unknown results. |
| `tests/rules/` | Feedback and protection rule evaluation as pure functions. |
| `tests/executor/` | The executor tick: timed actions, care rules, protection rules, stage events, restarts, an unreadable device state. |
| `tests/workflow/` | The workflow service: rounds, stages, permissions, stage events, recovery check and reconciliation. |
| `tests/tasks/` | The research-task board and the model-call budget. |
| `tests/planning/` | Experimental-design checks, run-sheet validation and evidence checks. |
| `tests/research/` | Statistics, the confirmatory gate, holdout data, report publishing and the code sandbox. |
| `tests/agents/` | The model client adapter, the agent loop, the roles and the tool registry. |
| `tests/dispatch/` | The tool handlers of each model role on real services, including the scoping of ids a model supplies. |
| `tests/compute/` | The compute service: job lifecycle, quotas, races, `FirecrestBackend` against a fake client, the template loading and the workbench balance and budget routes (`tests/workbench/test_workbench_compute.py`). |
| `tests/observer/` | Alerts, notification channels, the outbox, daily metrics and reports, run health and heartbeat. |
| `tests/workbench/` | The workbench routes: operator login and sessions, entry, the request gate, stage and manual actions, and starting and steering a round. |
| `tests/transport/` | `halt` on both BLE transports, and the pid file and folder checks of the native transport. |
| `tests/e2e/` | The assembled runtime: a full research round, interventions, model roles, the CLI commands, and a round driven through the HTTP routes. |
| `tests/web/` | The operator console's scripts, run with `node --test` (see CI step 2): routing, formatting, texts, denials, receipts, the stage page's rules, the chart maths, and the ban on `innerHTML`. Node's own test runner, no npm packages. |
| `tests/docs/` | This wiki: every page exists in `en/` and `zh-CN/`, the page table in [the wiki README](../README.md) lists exactly the pages that exist, relative links point at existing files, and every page links to its translation. The reference tables list what the code has: denial codes, CLI, configuration fields, routes, MCP and model role tools. |
| `tests/test_*.py` | The original bridge: protocol framing, device controls, the HTTP API with MCP, the dashboard. 32 tests. |

Two things apply everywhere:

- Async tests need no decorator, because `asyncio_mode = "auto"` is set in `pyproject.toml`.
- [`tests/conftest.py`](../../../tests/conftest.py) provides `settings` (a temporary data directory and the device name `SIMULATED`) and `bridge` (a started `Bridge` on a `SimulatedTransport`). Most folders add their own `conftest.py` and a helper module named `*_helpers.py` or `*_support.py`.

## Run the console on a simulated device

[`scripts/dev_workbench.py`](../../../scripts/dev_workbench.py) starts the runtime on the simulated AC5, with no radio, no network and no real device, so you can use the operator console in a browser. It seeds one approved safety configuration and one stage waiting for review, polls the simulated device every second so that readings keep arriving, and binds `127.0.0.1` only. The secret of the operator `dev` is read from the environment, never from an argument; it needs at least 12 characters.

```sh
GROWBRIDGE_DEV_SECRET='YOUR_DEV_SECRET' .venv/bin/python scripts/dev_workbench.py
```

| Entry | Address | What it is |
| --- | --- | --- |
| On-site | `http://localhost:8770/workbench` | The LAN entry: everything, irrigation included. |
| Overlay | `http://127.0.0.1:8765/workbench` | The overlay entry: everything except irrigation, which the console shows as disabled. |

The data lives in a fresh temporary directory unless you pass `--data-dir`. Stop the script with Ctrl+C.

### With the model roles

`--roles FILE.toml` also runs the model roles, as `serve` does when `roles` is set. The file has one `[orchestrator]`, `[planner]` or `[researcher]` table per role with the fields of `RoleModel`. The Anthropic SDK reads its endpoint and key from the environment, so a local Anthropic-compatible server is reached with `ANTHROPIC_BASE_URL`.

`--claude-code` runs the roles on the local Claude Code CLI instead (`claude -p`, see [`scripts/claude_code_client.py`](../../../scripts/claude_code_client.py)): no API key, the account Claude Code is signed in with. Each model turn is one headless call with Claude Code's own tools switched off; diagri's loop still validates and runs every tool. Without `--roles`, all three roles run the default model.

`--transcript FILE.jsonl` appends one line per model call. It holds prompts and tool results in clear text, so keep it for development.

`--fast-forward` skips through a running stage: each step moves the clock on by one sampling interval of the run sheet, reads the simulated device and ticks, so a week-long stage ends in a minute or two with complete data. Outside a running stage time is real. The skipped time is kept in `dev_clock_offset` in the data directory, so a restart never sends the clock back. Sessions age with that clock: sign in again after a stage.

The dev workbench moves the simulated readings like a small tent: temperature and humidity follow day and night, the light warms the air, the exhaust cools and dries it, the canopy draws CO2 down under the light, with a little noise. Constant readings would trip the frozen-reading check and pause a long stage. [Example: a complete round](Example-Full-Round-With-Claude.md) is one recorded run with all of this.

```sh
GROWBRIDGE_DEV_SECRET='YOUR_DEV_SECRET' .venv/bin/python scripts/dev_workbench.py --claude-code
```

The project page then shows the project conversation: send a question there, and the orchestrator answers in about 30 seconds. Every tool call of every role is listed under its reply.

## Run part of the suite

```sh
.venv/bin/pytest -q tests/control                               # one area
.venv/bin/pytest -q tests/executor/test_executor_protection.py  # one file
.venv/bin/pytest -q tests/workflow -k recovery                  # tests whose name matches
.venv/bin/pytest -q -rs                                         # everything, with the reason for each skip
```

While other people are still writing wiki pages, `tests/docs/` can fail for pages that are not yours. `.venv/bin/pytest -q --ignore=tests/docs` runs the rest.

The `dev` extra also installs `pytest-cov`. CI does not measure coverage. If you run `.venv/bin/pytest -q --cov=growbridge`, do not commit the `.coverage` file it writes: `.gitignore` does not list it.

## Tests that are skipped

| Tests | Skipped when | Why |
| --- | --- | --- |
| 14 tests in [`tests/research/test_research_sandbox.py`](../../../tests/research/test_research_sandbox.py), 1 in [`tests/e2e/test_e2e_assembly.py`](../../../tests/e2e/test_e2e_assembly.py) and 1 in [`tests/e2e/test_e2e_sandbox_roots.py`](../../../tests/e2e/test_e2e_sandbox_roots.py) | The platform is not macOS, or `/usr/bin/sandbox-exec` is missing. | They run real scripts inside the macOS sandbox (`SeatbeltSandbox`), or check which directories it denies. On other platforms the code uses `RefusingSandbox`, which the other tests in the first file cover. |
| 2 tests in [`tests/agents/test_agents_llm.py`](../../../tests/agents/test_agents_llm.py) | The `anthropic` package is not installed. | They build `AnthropicClient` with a stubbed `messages.create`. No request is sent. |

CI installs only the `dev` extra, so the two `anthropic` tests are skipped in every CI job and the 16 sandbox tests in the Linux jobs. The CI log of 2026-11-13 agrees: 2 skipped in the macOS jobs and 18 in the Linux jobs.

## Rule: no network, no radio, no real credentials

A test never reaches the network, a Bluetooth radio or a real account. Use the simulators in [`src/growbridge/sim/`](../../../src/growbridge/sim):

| Simulator | Stands in for | File |
| --- | --- | --- |
| `SimulatedTransport` | The AC5 behind the `WriteTransport` protocol. A test can change sensor values, edit the device the way its panel would, drop the link, lose replies and set what `halt` reports. | [`sim/device.py`](../../../src/growbridge/sim/device.py) |
| `FakeClock` | The `Clock` protocol. `advance` moves wall and monotonic time together. `jump` steps the wall clock only. | [`sim/clock.py`](../../../src/growbridge/sim/clock.py) |
| `FakeControl` | The `ControlPort` protocol in memory, with settable device facts and a log of the write rights granted and handed over. | [`sim/control.py`](../../../src/growbridge/sim/control.py) |
| `FakeBackend` | The `ComputeBackend` protocol in memory. | [`sim/compute.py`](../../../src/growbridge/sim/compute.py) |
| `ScriptedClient` | The `ModelClient` protocol. It replays replies built with `text_reply` and `tool_reply`. | [`sim/llm.py`](../../../src/growbridge/sim/llm.py) |
| `make_run_sheet`, `make_protocol`, `make_safety`, `humidity_rule` | Valid models that a test overrides field by field. | [`sim/fixtures.py`](../../../src/growbridge/sim/fixtures.py) |

For the rest:

- **HTTP** stays in the process. Outgoing calls get an `httpx.MockTransport`, as in [`tests/observer/test_observer_channels.py`](../../../tests/observer/test_observer_channels.py). The app is called through `httpx.ASGITransport` or FastAPI's `TestClient`.
- **Credentials** are placeholders set with `monkeypatch.setenv`. A test never reads a real key from your environment.
- **Files** go under pytest's `tmp_path` or another temporary directory, never the real data directory.
- **Time** is moved with `FakeClock.advance` wherever a service takes a `Clock`, so a test of a duration or a deadline does not wait for it.

Nothing enforces this rule automatically. Reviewers check it, see [Contributing](Contributing.md).

## See also

- [Code structure and extension points](Code-Structure-and-Extension-Points.md)
- [Contributing](Contributing.md)
- [Tutorial: a simulated research round](Tutorial-Simulated-Round.md)
- [Status and known limitations](Status-and-Known-Limitations.md)
- The "Development and validation" section of the [README](../../../README.md) and [`VALIDATION.md`](../../../VALIDATION.md)
