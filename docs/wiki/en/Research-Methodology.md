# Research methodology

[简体中文](../zh-CN/Research-Methodology.md)

This page is for a plant scientist who wants to know how DiAGRI designs and analyses an experiment in one tent, and how far its conclusions can be trusted. No programming is needed to follow it. The links to code are there so that every rule can be checked.

Read this first: the methods below have been tested on the simulated AC5 and on synthetic numbers only. No real experiment has been run with them, and some steps have no command or button yet (see the last section and [Status and known limitations](Status-and-Known-Limitations.md)). The design background is in sections 4.8, 6.3, 6.5 and 9 of the [architecture document](../../diagri-agent-architecture.zh-CN.md).

## The tent is the experimental unit

The AC5 sets light, exhaust and fan for the whole tent. Every plant in the tent gets the same treatment at the same time. The plants are therefore repeated observations of one unit, not independent replicates. Ten plants under 70 % light tell you about that tent in those weeks. They do not tell you what 70 % light does in general.

DiAGRI builds this into the arithmetic. Before any comparison, `unit_table` in [`research/stats.py`](../../../src/growbridge/research/stats.py) averages all plants and all measurement days of one tent in one round into a single value. Six plants measured on five days give the same unit value, and the same number of replicates, as one plant measured once ([test](../../../tests/research/test_research_stats.py)).

What this means for replication: an independent replicate is another tent, or another round in the same tent. With one tent, replication costs time.

## A single-tent series with blocks

With one tent, treatments have to follow each other in time. A plan of "control first, then treatment" cannot separate the treatment from the season, the seed batch or an ageing lamp. The remedy is a series of rounds grouped into blocks. A block is a set of neighbouring rounds in which every treatment appears once. Treatments are compared inside a block, where conditions are most alike.

The example protocol `make_protocol` in [`sim/fixtures.py`](../../../src/growbridge/sim/fixtures.py) asks whether canopy area grows faster under 70 % light than under 40 % light, the control. It has four rounds in two blocks:

| Round | Block | Tent | Treatment |
| --- | --- | --- | --- |
| 1 | 1 | `tent-1` | `high` (light 70 %) |
| 2 | 1 | `tent-1` | `control` (light 40 %) |
| 3 | 2 | `tent-1` | `control` (light 40 %) |
| 4 | 2 | `tent-1` | `high` (light 70 %) |

The primary endpoint is `canopy_area_growth` and the planned analysis is `paired_block`. An operator starts each round; see [Run a research round](Run-a-Research-Round.md).

## Randomization that can be reproduced

The order of the treatments inside a block is random, so that nobody can give the better weeks to one treatment, even without meaning to. `randomize_series` in [`planning/design.py`](../../../src/growbridge/planning/design.py) shuffles the treatments once per block, using a random generator started from the seed in the protocol (`randomization_seed`). The same seed always gives the same order. The seed `20261118` gives exactly the table above.

Because the seed is recorded, anyone can repeat the draw. `check_experimental_design` does so, and reports `seed_mismatch` when the recorded allocation is not what the seed gives. This finding is advisory. It does not block the design, but it tells a reviewer that the order did not come from the recorded randomization.

For several tents, `randomize_tents` shuffles the treatments over the tents in every round, and the round is the block.

## Design checks

`check_experimental_design` reads a protocol and returns findings. All except the last block the design.

| Finding | Meaning | Example |
| --- | --- | --- |
| `unknown_treatment` | An allocation names a treatment the protocol does not define. | |
| `missing_control` | The control is not one of the treatments, or is never allocated. | |
| `no_replication` | A treatment has fewer than two units. A unit is one tent in one round. | One round of each treatment. |
| `unbalanced_block` | Inside a block the treatments do not appear equally often. | A block with two `high` rounds and no `control`. |
| `confounded_with_time` | In a one-tent series, each treatment occupies one unbroken stretch of rounds. | `control`, `control`, `high`, `high`. |
| `seed_mismatch` | The allocation does not follow from the recorded seed. Advisory. | |

The example protocol passes with no findings. The planner runs this check with its `check_experimental_design` tool.

## How many blocks: the sample-size estimate

`estimate_sample_size` uses the normal approximation. You give it the effect you want to detect and a standard deviation `sd`. The significance level `alpha` is 0.05 and the power is 0.8 unless you change them.

```text
n = ((z(1 - alpha/2) + z(power)) × sd / effect)²
```

- For `paired_block`, `sd` is the standard deviation of the differences within blocks. The code adds `z(1 - alpha/2)² / 2` as a small-sample correction and rounds up. The result is a number of blocks.
- For `two_group`, the result is `2n` rounded up: the number of units in each group.

Two floors apply. The result is never below 2 (`MIN_SAMPLE_SIZE`). For `paired_block` it is also never below the smallest number of blocks at which the test described below can reach `alpha` at all: 6 blocks for 0.05, 8 blocks for 0.01.

Examples computed by the function: an effect of 0.5 with `sd` 1.0 needs 34 blocks. An effect of 100 with `sd` 0.1 still needs 6 blocks, because of the floor.

The `sd` must describe how much rounds differ from each other. Variation between plants inside one tent is not that number; section 6.3 of the architecture document says a one-tent pilot cannot supply it.

## The estimate and the test, worked by hand

Suppose the four rounds are finished and three plants were measured in each. The numbers are invented for this page.

| Round | Block | Treatment | Plant values | Unit value (mean) |
| --- | --- | --- | --- | --- |
| 1 | 1 | `high` | 2.1, 1.9, 2.0 | 2.0 |
| 2 | 1 | `control` | 1.0, 1.1, 0.9 | 1.0 |
| 3 | 2 | `control` | 1.3, 1.2, 1.1 | 1.2 |
| 4 | 2 | `high` | 2.0, 1.8, 1.9 | 1.9 |

**The estimate.** In each block, `paired_block_estimate` takes treatment minus control: 2.0 − 1.0 = 1.0 in block 1, and 1.9 − 1.2 = 0.7 in block 2. The effect is the mean of the block differences: (1.0 + 0.7) / 2 = 0.85.

**The test.** If light made no difference, it would not matter which round of a block was called `high`, and each block difference could just as well have had the opposite sign. The exact sign-flip permutation test lists every combination of signs and counts how often the sum is at least as far from zero as the observed sum, 1.7.

| Block 1 | Block 2 | Sum | As far from zero as 1.7? |
| --- | --- | --- | --- |
| +1.0 | +0.7 | +1.7 | Yes. This is what was observed. |
| +1.0 | −0.7 | +0.3 | No |
| −1.0 | +0.7 | −0.3 | No |
| −1.0 | −0.7 | −1.7 | Yes |

Two of the four patterns count, so p = 2 / 4 = 0.5. Running `unit_table`, `paired_block_estimate` and `conclusion` on these values gives the same: effect 0.85, 2 blocks, p = 0.5, conclusion `uncertain`.

## Why two blocks are not enough

The observed pattern and its mirror image always count. With n blocks there are 2ⁿ patterns, so the smallest p-value the test can ever give is 2 / 2ⁿ, however large the effect is.

| Blocks | Sign patterns | Smallest possible p |
| --- | --- | --- |
| 2 | 4 | 0.5 |
| 3 | 8 | 0.25 |
| 4 | 16 | 0.125 |
| 5 | 32 | 0.0625 |
| 6 | 64 | 0.03125 |

Two blocks can never give a p-value below 0.5, and five blocks still cannot get below 0.05. Six is the first number that can. For two treatments in one tent, six blocks are twelve rounds.

The floors in the code:

- **Fewer than 2 complete blocks** (`MIN_BLOCKS`): no effect is estimated, and the report says so. A block is complete when it has both the control and the treatment.
- **Fewer than 6 blocks** at the level 0.05: an effect and a p-value are reported, but the conclusion is `uncertain`.
- **More than 20 blocks**: the test is no longer exact. It draws 20,000 sign patterns with a fixed seed, counts the observed pattern as one of them so that p is never 0, and notes that the p-value is approximate.

## The confirmatory gate

A confirmatory analysis is one whose method was fixed before the data were seen. A result may be called confirmatory only if all of the following hold. The code is `ConfirmatoryRunner` in [`research/analysis.py`](../../../src/growbridge/research/analysis.py).

1. **The script is frozen by its hash, before any stage has started.** The operator freezes it with `POST /wb/protocols/PROTOCOL_ID/analysis`, which calls `freeze_analysis`. It records the SHA-256, the text of the script and who froze it, for one version of the protocol. A version has one script. A script that differs from the recorded hash, or from the hash written in the protocol, is refused (`script_hash`). The script is compiled when it is frozen, never run, and a script that does not compile is refused (`param`): a frozen script cannot be corrected, so a typo must not burn the only attempt. Freezing is refused (`state`) once any stage of a round that runs the protocol version has started, because the analysis must be fixed before the outcome data can be seen (section 6.5 of the architecture document).
2. **The data are a frozen, complete and verified snapshot.** Before the run, the manifest and every file of the data snapshot are hashed again and compared, and the snapshot must be complete (coverage of at least 0.9). Otherwise the run is refused (`snapshot_incomplete`). See [Data, archive and traceability](Data-Archive-and-Traceability.md).
3. **One run.** The operator starts it with `POST /wb/analysis/runs`, which runs the stored script. A protocol version can run its script on a given snapshot once. A second attempt is refused (`already_run`). A run that fails or exceeds 600 seconds still uses up the attempt, and it is recorded as exploratory.
4. **The script runs in a sandbox**, with no network and a read-only view of the snapshot ([`research/sandbox.py`](../../../src/growbridge/research/sandbox.py)). The sandbox exists on macOS only. On any other system, a Raspberry Pi included, it refuses to run anything (`sandbox_unavailable`).

When a report is published, the server checks that such a run succeeded for every snapshot the report uses. If not, the label is at most exploratory. While a script is frozen for the protocol version, publishing is refused (`state`) until the run of every snapshot the report cites has ended, so that a round is not delivered with an exploratory conclusion before the operator has run the analysis. A run that ended in failure lets the report through, as exploratory. The whole path, from the freeze to a confirmatory report, is exercised by [`test_e2e_confirmatory.py`](../../../tests/e2e/test_e2e_confirmatory.py) with a fake sandbox.

## Honest downgrade

The label of a report is computed by the server from the protocol and the frozen data. The researcher cannot set it. `classify` applies five rules:

| Rule | Threshold in the code | Label | Where the fact comes from |
| --- | --- | --- | --- |
| Too few independent replicates | The control or the treatment has fewer than 2 units (`MIN_REPLICATES`) | descriptive | The allocations of the rounds that have data |
| Treatment cannot be told from time | `confounded_with_time` | descriptive | The design check, applied to the rounds that have data |
| Too much is missing | Above `max_missing_fraction` in the protocol, 0.2 by default | exploratory | The larger of two numbers: the share of planned units with no measurement of the primary endpoint, and 1 minus the lowest snapshot coverage |
| The plan changed after outcomes were seen | The flag `changed_after_outcomes` | exploratory | Declared by the researcher; the server cannot see it |
| The treatment deviated from the approved plan | Above `max_deviation_fraction`, 0.1 by default | exploratory | The larger of two numbers: the share of experiments with a recorded intervention, and the fraction the researcher declares |

Descriptive outranks exploratory, and every reason is written into the report. Three more caps lower a confirmatory label to exploratory on the way out ([`agents/handlers_report.py`](../../../src/growbridge/agents/handlers_report.py), [`research/report.py`](../../../src/growbridge/research/report.py)): no successful confirmatory run for every snapshot, an incomplete snapshot, and a holdout that was already read once.

The researcher can pass three flags: `changed_after_outcomes`, `early_terminated` and `deviation_fraction`. Each can only make the result stricter. A report that would be confirmatory but has unresolved questions, or lost the label because of an incomplete snapshot, goes to review (`needs_review`) and the round is not delivered.

## "Uncertain", never "no effect"

A small experiment that finds no difference has not shown that there is none. `conclusion` therefore has three outcomes: `supported` (支持), `not_supported` (未获支持) and `uncertain` (不确定). There is no outcome called "no effect".

The conclusion is `uncertain` when any of these is true:

- the experiment was stopped early (the flag `early_terminated`);
- fewer complete blocks were achieved than the protocol planned;
- no effect could be estimated (fewer than 2 complete blocks);
- there are too few blocks for the test to reach 0.05 (fewer than 6).

Only otherwise does the p-value decide: `supported` below 0.05, `not_supported` from 0.05 upwards.

The code does not compute a confidence interval. It does not judge how wide an interval is; it applies the four rules above. The example protocol, with its two blocks, always ends as `uncertain`. It has the size of a pilot.

## Holdout data for prediction models

A prediction model must be judged on data it has never touched. `HoldoutRegistry` in [`research/holdout.py`](../../../src/growbridge/research/holdout.py) keeps the books:

- A holdout is registered by batch before development starts. It needs at least 2 development batches (`MIN_DEVELOPMENT_BATCHES`).
- From then on, outcome measurements of the held-out batches are left out when a dataset is frozen. An outcome with no batch is treated as held out. The snapshot manifest records how many were left out.
- Before an evaluation, the model, its features and its preprocessing are registered by hash. An unregistered model is refused (`model_unregistered`).
- The first evaluation on a holdout may be confirmatory. Every later one is exploratory. Every read is logged with its time and reader.
- `late_features` lists features that were received only after the time of the prediction.

## What the researcher can reach

The researcher is a language model, so its tools are fenced in ([`agents/handlers_common.py`](../../../src/growbridge/agents/handlers_common.py), [`agents/handlers_researcher.py`](../../../src/growbridge/agents/handlers_researcher.py)):

- **Scoped to the task's project.** `freeze_dataset`, `run_local_analysis` and `publish_research_report` each name a research task, and the name must be the task the dispatcher is running: the server binds the task for the run, and an id from the model is only compared with it, never trusted. A task of another role or project, a second task of the same project, and a call outside a dispatched run are all refused. A stage, a round or a snapshot can be used only if it belongs to the same project as that task. Anything else is refused with `scope`, and a snapshot of another project looks the same as one that does not exist.
- **One owner per experiment.** A snapshot's project is the project of the stage that runs its experiment. The workflow refuses a run sheet that reuses another project's `experiment_id`, and an experiment claimed by stages of two projects has no owner, so every scope check on it refuses.
- **No holdout rows.** A snapshot whose measurement file contains outcomes of a held-out batch is refused before anything is read or mounted. This catches snapshots that were frozen before the holdout was registered.
- **Limits from the run sheet.** When data are frozen, the time window and the sampling limits come from the run sheet, not from the model.
- **Own analyses are exploratory.** Anything the researcher runs with `run_local_analysis` is labelled exploratory.

## What is not there yet

- No model tool and no CLI command freezes or runs the analysis script; the operator does both through the workbench. `HoldoutRegistry.register` and `register_model` have no route or tool: only tests call them.
- `randomize_series`, `randomize_tents` and the make-up rule for a failed round (`make_up_allocation`) are functions without a tool. The design check only compares an allocation with its seed.
- The effect and the p-value in a report are computed by the server with `paired_block_estimate`. The output of the frozen script stays in the run folder and is not copied into the report.
- One confirmatory run covers one snapshot. Section 6.5 of the architecture document describes a single run over all rounds of a series; the code has no such run.
- No confidence interval and no detectable-difference calculation exist.

## See also

- [Data, archive and traceability](Data-Archive-and-Traceability.md)
- [Design decisions](Design-Decisions.md)
- [The five agents](The-Five-Agents.md)
- [Run a research round](Run-a-Research-Round.md)
- [Denial codes and stage events](Denial-Codes-and-Events.md)
- [Glossary](Glossary.md)
