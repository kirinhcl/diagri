# Contributing

[简体中文](../zh-CN/Contributing.md)

This page is for anyone about to send a change. It describes how changes are made in this repository today, step by step, and ends with the checklist reviewers use.

What follows is current practice, not a formal policy. The root [`CONTRIBUTING.md`](../../../CONTRIBUTING.md) is a short entry point to this page; there is no pull-request template and no git hooks of its own. Where the history does not yet show a habit, the page says so.

## Before you start

1. Set up the environment and get a green test run: [Development setup, testing and CI](Development-Setup-Testing-and-CI.md).
2. Find the code you are about to change, and the contract it has to keep: [Code structure and extension points](Code-Structure-and-Extension-Points.md).

## Make a change

### 1. Work on a branch

```sh
git switch -c feat/<short-name>
```

Changes are made on a branch and not on `main`. The one feature branch so far is `feat/auto-research-agents`, where the agent system was added. Beyond that example there is no rule for branch names.

### 2. Write the test first where hardware moves

For anything in [`control/`](../../../src/growbridge/control), [`executor/`](../../../src/growbridge/executor) or [`workflow/`](../../../src/growbridge/workflow), write the failing test before the code. These three packages decide what is written to a real device and when, so a mistake there switches a light, a fan or a pump.

- For a bug, start with a test that fails because of the bug.
- Use the simulators. A test never needs an AC5. See the rule on [Development setup, testing and CI](Development-Setup-Testing-and-CI.md).
- Put the test in the folder of its area, for example `tests/control/`, and start the file name with the area.

Current practice sets no order for the other packages.

### 3. Run the checks CI runs

```sh
.venv/bin/ruff check src tests scripts
.venv/bin/ruff format --check src tests scripts
.venv/bin/pytest -q
```

The full list, in CI's order, is on [Development setup, testing and CI](Development-Setup-Testing-and-CI.md).

### 4. Commit

Write the subject line as `<type>: <description>`.

| Type | Use it for |
| --- | --- |
| `feat` | new behavior |
| `fix` | a bug fix |
| `refactor` | a change of structure that keeps behavior |
| `docs` | documentation only |
| `test` | tests only |
| `chore` | maintenance that fits nowhere else |
| `perf` | a performance change |
| `ci` | the CI workflow |

In the history of `main`, the first seven commits are plain sentences that start with a verb, such as "Add local dashboard with live controls, history charts and CSV export". Every later commit uses this format, apart from two that use `style:`, a type outside the table.

### 5. Push and wait for CI

CI runs on every push and on every pull request. A change is ready for review when all four jobs pass: Linux and macOS, each with Python 3.11 and 3.13. Passing on one operating system is not enough, because the BLE transport, the sandbox and 14 tests differ between the two.

## Rules that hold today

### No secrets in the repository

Credentials come from two places, and neither is a tracked file.

| Where | What | Read by |
| --- | --- | --- |
| Environment variables | The model API key, `GROWBRIDGE_TELEGRAM_TOKEN`, `GROWBRIDGE_ROLE_TOKEN_<ROLE>`, the `FIRECREST_*` variables | [`agents/llm.py`](../../../src/growbridge/agents/llm.py), [`observer/channels.py`](../../../src/growbridge/observer/channels.py), [`cli.py`](../../../src/growbridge/cli.py), [`compute/firecrest.py`](../../../src/growbridge/compute/firecrest.py) |
| The private configuration file | The installation token | [`config.py`](../../../src/growbridge/config.py). By default `growbridge init` creates the file outside the repository, readable by its owner only. |

[`.gitignore`](../../../.gitignore) keeps the usual carriers out: `.env`, `config.toml`, `*.sqlite*`, `*.backup`, `*.jsonl` and `.local/`. In tests, every credential is a placeholder. Real device addresses, account names and raw protocol captures do not belong in the repository either.

### Files stay under 800 lines

Every Python file under `src/`, `tests/` and `scripts/` is under 800 lines today. When a file approaches the limit, split it by responsibility: the tool handlers are split into `agents/handlers_*.py`, and when the workflow service passed 800 lines its recovery check moved to [`workflow/recovery.py`](../../../src/growbridge/workflow/recovery.py). The dashboard's `web/app.js` and `web/style.css` are longer; they belong to the bridge and are older than the rest of DiAGRI.

### Wiki pages change in both languages, in the same commit

Every page exists in `en/` and `zh-CN/` under the same file name. Change both in one commit, and follow the ten conventions in [the wiki README](../README.md). The test [`tests/docs/test_docs_wiki.py`](../../../tests/docs/test_docs_wiki.py) checks the parts a program can check:

- every page exists in both languages;
- the page table in the wiki README lists exactly the pages that exist;
- every relative link points at an existing file;
- every page links to its translation.

Two more tests hold the reference pages to the code, in both languages. [`test_docs_reference.py`](../../../tests/docs/test_docs_reference.py) compares the denial codes, the CLI commands and options, the `Settings` and `RoleModel` fields, the MCP tools (in the READMEs too) and the model role tools, with the counts the pages state, and checks that [`CITATION.cff`](../../../CITATION.cff) names the package version. [`test_docs_routes.py`](../../../tests/docs/test_docs_routes.py) compares the bridge and workbench routes. A failure names what the page misses and what it lists that the code does not have: change the page in both languages.

Beyond those tables, no test checks that the two versions say the same thing. That is for the reviewer.

### Do not bypass git hooks

Do not commit or push with `--no-verify`. The repository ships no hooks, so this concerns hooks installed on your machine or by your organization. If a hook stops a commit, fix what it reports.

## Review checklist

Each item is a kind of defect that reviews of this code have found. Check your own change against the list before asking for review.

| Look for | The question to ask | Where the code shows the right way |
| --- | --- | --- |
| A check that fails open when a read fails | What does this branch do when the read raises or returns nothing? "Could not read" must never count as "matches", "safe" or "no difference". | The executor treats an unreadable device state as a difference: [`tests/executor/test_executor_unreadable.py`](../../../tests/executor/test_executor_unreadable.py). |
| An id supplied by a model that is not scoped to its task | Is every snapshot, round or stage id checked against the project of the caller's task before anything is read or created? | `scoped_snapshot` and `require_round` in [`agents/handlers_common.py`](../../../src/growbridge/agents/handlers_common.py), and [`tests/dispatch/test_dispatch_snapshot_scope.py`](../../../tests/dispatch/test_dispatch_snapshot_scope.py). |
| A write path that does not go through the control service | Does every device write go through `submit`, `irrigate` or `pump_off` of `ControlPort`? | Within the DiAGRI packages, only `control/` imports `Bridge`. [`ports.py`](../../../src/growbridge/ports.py) has the contract. |
| A wall-clock comparison where the monotonic clock is needed | Is this a duration, a timeout or a minimum interval? Then it uses `Clock.monotonic()`. `Clock.now()` is for calendar triggers and for the timestamps on records. | [`executor/rules.py`](../../../src/growbridge/executor/rules.py) and [`archive/clock.py`](../../../src/growbridge/archive/clock.py). In a test, `FakeClock.jump` steps the wall clock without letting time pass. |
| A test that reaches the network | Does the test open a real connection, resolve a real host or read a real key? | `httpx.MockTransport` in [`tests/observer/test_observer_channels.py`](../../../tests/observer/test_observer_channels.py), and the simulators in [`sim/`](../../../src/growbridge/sim). |

Two more questions apply to every change:

- Does a new tool, route or command give a model role control of a stage or of the device? It must not. See [Control and safety model](Control-and-Safety-Model.md).
- Does the change describe behavior on real hardware, a Raspberry Pi, a real notification service or CSC? Then it says what was tested and what was not, and links to [Status and known limitations](Status-and-Known-Limitations.md), as convention 6 of the wiki README requires.

## See also

- [Development setup, testing and CI](Development-Setup-Testing-and-CI.md)
- [Code structure and extension points](Code-Structure-and-Extension-Points.md)
- [Control and safety model](Control-and-Safety-Model.md)
- [Status and known limitations](Status-and-Known-Limitations.md)
- [How this wiki is edited](../README.md)
