# Tutorial: a simulated research round

[简体中文](../zh-CN/Tutorial-Simulated-Round.md)

This page is for a newcomer who wants to see DiAGRI work before touching any hardware. You will run one short stage on a simulated AC5, read what its result means, and then run the end-to-end tests that take a whole research round from a question to an archived report.

Nothing here uses a radio, the network, a model API key or your configuration file. Everything runs against `SimulatedTransport` in [`sim/device.py`](../../../src/growbridge/sim/device.py), on a fake clock, in a temporary directory that is deleted afterwards.

> The simulation shows that the software parts fit together. It says nothing about a real AC5, a real Bluetooth link or a Raspberry Pi. See [Status and known limitations](Status-and-Known-Limitations.md).

## What you need

A clone of the repository with the package installed in `.venv`: step 1 of [Installation and quick start](Installation-and-Quick-Start.md). You do not need steps 2 to 5 of that page.

## Step 1: run the simulated stage

From the repository root:

```sh
.venv/bin/growbridge simulate
```

It finishes in about a second and prints this:

```json
{
  "stage": "ended",
  "round": "data_verification",
  "beats": 10,
  "samples": 21,
  "writes": 3
}
```

## Step 2: read what happened

The command calls `simulate_stage()` in [`runtime.py`](../../../src/growbridge/runtime.py). In order, that function:

1. Builds a `Runtime` with `auto_research=True`, a simulated device, no notification channels, and a fake clock set to 10:00 on 2027-01-15 in the `Europe/Helsinki` time zone. These are the same services that `growbridge serve` wires together.
2. Registers this machine as the write host and starts the runtime, which connects to the simulated device.
3. Acts as an operator named `simulator` and approves a safety configuration with one protection rule: above 35 °C for 30 seconds, switch the light off.
4. Creates a project, saves a research protocol and creates a round.
5. Submits a run sheet for the stage `stage-sim`, marked as coming from the planner. No model is called: the run sheet is a fixture from [`sim/fixtures.py`](../../../src/growbridge/sim/fixtures.py). The stage lasts 600 seconds. The light is at 60 % from 06:00 to 22:00, the exhaust at 30 % all day, and the light goes off when the stage ends.
6. Checks that validation found nothing blocking, approves the stage as the operator, and starts it.
7. Repeats a "beat" until the stage has ended, at most 40 times. One beat moves the clock forward 60 seconds, asks the device for its status, and calls `runtime.tick()` once. `tick` is the function the daemon calls once per second: it archives new samples, runs the executor, and then runs the observer and the housekeeping steps.

The five fields of the summary:

| Field | Value | What it is | Where it comes from |
| --- | --- | --- | --- |
| `stage` | `ended` | The stage state. `ended` means the planned duration was reached and the end actions ran. | `runtime.workflow.stage("stage-sim").state` |
| `round` | `data_verification` | The round state. The last stage is over and the round waits for its data to be frozen. | `runtime.workflow.round_state(round_id)` |
| `beats` | `10` | How many beats ran: 600 seconds of stage at 60 seconds per beat. | the loop counter |
| `samples` | `21` | The samples the project archive holds for the experiment `experiment-sim`. A sample counts only if it arrived after the stage had started. | `runtime.archive.samples("experiment-sim")` |
| `writes` | `3` | The `setConfigField` commands the simulated AC5 received. That is every write to the device. | `device.commands` |

Three details are worth a closer look.

**Why 21 samples in 10 beats.** The bridge stores every status reply (`getDevSta`) as a sample ([`service.py`](../../../src/growbridge/service.py)). The loop asks for the status once per beat, and each write is followed by a read-back that asks again.

**Which three writes.** The executor made them, through the control service, with the stage write right. The action ledger records each one moving from `pending` to `maybe_sent` to `confirmed`, which means the read-back matched.

| Write | Trigger in the action ledger | Why |
| --- | --- | --- |
| light to 60 | `experiment_action:light-on` | The stage starts at 10:00, and the timed action `light-on` has been in force since 06:00. |
| exhaust to 30 | `experiment_action:exhaust-base` | The timed action `exhaust-base` is in force from 00:00. |
| light to 0 | `end:light` | The end action of the run sheet. |

**Why the round stops at `data_verification`.** `simulate` runs one stage and stops. The stage went from `pending_review` to `running` when it was started, and to `ended` after the end actions. The remaining steps of a round, freezing a data snapshot (`analysis`) and publishing the report (`delivered`), are in the test you run next.

## Step 3: run a whole round as a test

The end-to-end tests in [`tests/e2e/`](../../../tests/e2e/) are runnable examples. Each one builds the real services on one simulated device and one fake clock ([`e2e_support.py`](../../../tests/e2e/e2e_support.py)) and then plays the operator, the device and the passing of time.

The tests need the development extras:

```sh
.venv/bin/python -m pip install -c constraints-tested.txt -e '.[dev]'
```

Run the test that takes one question through a whole round:

```sh
.venv/bin/pytest tests/e2e/test_e2e_round.py -v
```

The output ends like this (the time varies):

```text
tests/e2e/test_e2e_round.py::test_open_question_goes_through_a_whole_round PASSED [100%]

============================== 1 passed in 1.07s ===============================
```

Open [`test_e2e_round.py`](../../../tests/e2e/test_e2e_round.py) and read it next to this list. The test:

1. approves the safety configuration, creates the project, saves the protocol and creates the round, which is now `designing`;
2. submits the run sheet (`stage_review`), then approves and starts the stage (`stage_running`);
3. lets the executor bring the light to 60, then takes over as the operator (the stage is `manual`), sets the exhaust to 55 by hand, and hands back, accepting the difference as a recorded intervention;
4. runs the stage to its end (`data_verification`);
5. freezes a data snapshot and verifies it (`analysis`);
6. computes the paired-block estimate from four manual measurements, classifies the analysis as `confirmatory`, and arrives at the conclusion `uncertain`, because two blocks are too few to reach significance;
7. publishes the report, which makes the round `delivered`.

## Step 4: look at a takeover and a restart

Each file in `tests/e2e/` demonstrates one part of the system.

| File | What it demonstrates |
| --- | --- |
| [`test_e2e_round.py`](../../../tests/e2e/test_e2e_round.py) | One question through a whole round, with a takeover in the middle |
| [`test_e2e_agents.py`](../../../tests/e2e/test_e2e_agents.py) | The three model roles driven by a scripted client, with no network and no key: a delegation, a planner draft that waits for review, a researcher that freezes data and publishes. Also a stage that runs to its end while every model call fails, and a planner that cannot approve or start anything. |
| [`test_e2e_interventions.py`](../../../tests/e2e/test_e2e_interventions.py) | A takeover is recorded in the project archive and in the frozen snapshot, exactly once |
| [`test_e2e_runtime.py`](../../../tests/e2e/test_e2e_runtime.py) | A stage that runs with no model client; a restart; a host that is not the registered write host; a failing tick step that becomes an alert |
| [`test_e2e_reviewed.py`](../../../tests/e2e/test_e2e_reviewed.py) | Failure paths: stale capture, backups, failed heartbeats, a lost write reply that pauses the stage, a recovery number bump that voids approvals and sessions |
| [`test_e2e_assembly.py`](../../../tests/e2e/test_e2e_assembly.py) | What `build_runtime` assembles: one database file per service, the host id, the sandbox, the order of the tick steps, one daily report per day |
| [`test_e2e_cli.py`](../../../tests/e2e/test_e2e_cli.py) | The DiAGRI subcommands: `operator add`, `host register`, `recovery bump`, `simulate` |

Two tests to run and read next:

```sh
.venv/bin/pytest "tests/e2e/test_e2e_interventions.py::test_takeover_is_in_the_archive_and_in_the_frozen_snapshot" -v
.venv/bin/pytest "tests/e2e/test_e2e_runtime.py::test_restart_enters_recovery_check_then_the_operator_resumes" -v
```

The first takes over a running stage, hands back, and finds the takeover in the archive and in the snapshot file `interventions.jsonl`. The second stops the runtime in the middle of a stage and builds a new one on the same data. The stage comes back in `recovery_check` with no write right. After one beat it is `paused`, and it runs again only when the operator resumes it.

To run the whole folder, which takes a few seconds:

```sh
.venv/bin/pytest tests/e2e -q
```

## What you have not seen

- A real device. Timing, Bluetooth interruptions and power loss are not simulated here.
- A real model. The model roles in the tests answer from a script ([`sim/llm.py`](../../../src/growbridge/sim/llm.py)).
- Notifications. `simulate` runs with no channels, and the tests use fake ones.
- The daemon itself. `growbridge serve` and its background loops are not started by anything on this page.

## Where to go next

- [Workflow and state machines](Workflow-and-State-Machines.md) for the states you saw: `designing`, `stage_review`, `stage_running`, `data_verification`, `analysis`, `delivered`.
- [Manual takeover, irrigation and handback](Manual-Takeover-and-Irrigation.md) for what the takeover test did.
- [Enable DiAGRI](Enable-DiAGRI.md) to switch the mode on for a real tent.

## See also

- [Overview](Overview.md)
- [Research methodology](Research-Methodology.md): why the conclusion in the test is `uncertain`.
- [Development setup, testing and CI](Development-Setup-Testing-and-CI.md)
- [Glossary](Glossary.md)
