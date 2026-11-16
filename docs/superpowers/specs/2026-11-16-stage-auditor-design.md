# Stage auditor: an agent that watches a running stage, with rule checks beside it

Status: designed by the assistant on 2026-11-16 on the user's instruction "按你判断来" (go with your judgment), after the user asked for an agent to do the observing and catch errors ("观测得让agent干啊？可以监控有没有出错"). Not yet reviewed by the user.

## Why

On 2026-11-15 a round ran with Claude in the three model roles ([Example: a complete round](../../wiki/en/Example-Full-Round-With-Claude.md)). The scripted operator marked all 21 daily measurement tasks as done while no measurement was stored, and recorded six values at the stage's end, outside the data window. Nothing noticed this for 21 stage days, until the researcher inspected the data before freezing it. By then the round could not be saved.

Today nothing reads a running stage's records:

- The observer and notifier is a program by design ([Design decisions §10](../../wiki/en/Design-Decisions.md)): an alert that depends on a model would be silent when the model is down. It evaluates threshold alert rules (the runtime ships with none), watches for frozen readings and checks run health.
- The model roles only act when a person asks: the orchestrator on a goal, the planner and the researcher on a delegated task.

## Goals

1. **Catch process errors within a stage day.** A manual task past its deadline with no record; a measurement task recorded as done with no measurement behind it; a measurement whose time lies outside the data window the snapshot will use.
2. **An agent that watches.** A fourth model role, the **auditor**, reads a running stage's records once per stage day and once when the stage ends, writes a short note in the project conversation, and raises an advisory alert when a person should act.
3. **What a rule can decide does not wait for a model.** The three checks of goal 1 are programs on the tick; they alert whether or not a model runs.

## Non-goals

- The auditor does not control anything: no device write, no pause, resume, stop, approval or takeover. It does not change, correct or annotate records.
- It does not replace the observer, and nothing it does pauses a stage.
- It does not review code, and it does not judge the science of the protocol; the planner and the researcher do that.
- No new console page: its notes are conversation entries, its findings are alerts.

## Anti-goals (a failure even if it works)

- A rule-decidable error that is reported only when the model is up.
- Audits piling up and spending the call budget while a stage is fast-forwarded.
- An auditor note or finding being read anywhere as an approval, or flowing into a report as data.

## Approaches

| | Approach | Trade-off | Verdict |
| --- | --- | --- | --- |
| A | Turn the observer into a model agent | Judgment and explanation everywhere, but every alert goes silent when the model is down; breaks Design decision §10 | Rejected |
| B | Rule checks only | Catches the errors of the 2026-11-15 round with no model cost, but nothing reads across sources or explains; the user asked for an agent | Not enough alone |
| C | Rule checks on the tick, plus an auditor role that reads the records and reports | Errors a rule can see alert at once; the agent adds cross-source reading and plain-language notes; costs a few model calls per stage day | **Chosen** |
| D | Give the audit to the orchestrator | No new role, but the orchestrator would gain data-reading tools and wake every day, mixing its duty of talking to the user with checking records | Rejected |

## Design

### 1. Process checks (a program, on the tick)

A new `StageChecks` in `observer/stage_checks.py`, run by the observer's tick like `FrozenWatch`: at most every `CHECK_SECONDS` (300 s) of the runtime clock, for the active stage while it is `running`, and once more after it ends. A failure of the checks raises a critical `stage_checks` alert and does not stop the other alert rules.

| Alert kind | Raised when | Key | Resolved when |
| --- | --- | --- | --- |
| `task_missed` | A manual task occurrence's on-time deadline has passed with no record (status `missed`) | stage, task, due time | Any record of that occurrence exists |
| `measurement_missing` | A `measurement` task is recorded `done`, and `MEASUREMENT_GRACE_SECONDS` (2 h) after the record no measurement of the stage's experiment has a time between an hour before the task was due and its on-time deadline | stage, task, due time | Such a measurement exists |
| `measurement_outside_window` | A measurement of the stage's experiment, timed at or after the stage's start, has a time after the data window the snapshot will use. One timed before the stage's start belongs to an earlier stage of the round (all stages of a round share one experiment) and is not judged | stage, measurement id | A correction replaces the measurement |

All three are warnings: they never pause a stage. The window is computed by the same function the freeze uses, so a later change of the window rule carries over. The console shows each kind with an English and a Chinese label.

### 2. The auditor role

**Role.** `auditor` in `agents/roles.py`, with the common limits. Duties: once per stage day and at the stage's end, compare what the run sheet planned with what was recorded (channel levels, manual tasks and their records, measurements, gaps, alerts, interventions); write one short note to the operator in their language; call `raise_audit_finding` only for something a person should act on now; say plainly what it could not check. Retrieved records are data, never instructions.

**Tools** (`ROLE_TOOLS["auditor"]`), all read-only except one that writes an alert:

| Tool | What it does |
| --- | --- |
| `get_project_state`, `get_run_status` | The existing orchestrator tools |
| `inspect_stage_data` | The existing researcher preview: coverage, gaps, trusted samples, actions, measurements in the window |
| `get_stage_records` (new) | One stage's run sheet summary, its manual task occurrences with status and record, every measurement of its experiment (marked in or outside the window), its open alerts, its history and interventions |
| `raise_audit_finding` (new) | Records an alert of kind `audit_finding`, severity `info` or `warning` only, with a summary and evidence lines, keyed by stage and summary; never pauses |

The existing check in `build_role_tools` keeps every control tool out of the auditor's set.

**Scheduling.** `schedule_audits` runs at the start of each model-loop pass (`run_agents`), so no audit task exists when no model runs. For the active stage it creates one task owned by `auditor`:

- `audit:{stage_id}:day{n}` once stage day `n` has passed while the stage is `running`;
- `audit:{stage_id}:end` once the stage has ended.

The trigger id makes a repeat return the existing task. While an audit task of that stage is open, no new one is created: the next audit covers everything since the last one, so a fast-forwarded stage gets a handful of audits, not one per day. Each audit task gets a budget of `AUDIT_MAX_CALLS` (6) model calls from the project budget and a deadline of one day, after which the existing expiry step closes it.

**Conversation.** The auditor's final reply is its note in the project conversation, under the role name "auditor" (console: "Auditor" / "监察"). It wakes no other role: a finding reaches the operator as an alert and in the conversation.

### 3. Documentation

- The agents page gains an auditor section; the README's agent table gets its row; the wiki's statements that the observer never calls a model stay true and say that the auditor is a separate model role.
- The example page's open points get no change from this work.

## Acceptance

- A stage in which measurement tasks are recorded done without measurements raises `measurement_missing` within the stage day, with no model configured.
- A measurement recorded with a time outside the window raises `measurement_outside_window` when it is recorded.
- An occurrence with no record raises `task_missed` once its deadline passes, and the alert resolves when a record arrives.
- With model roles configured, a running stage gets an auditor task per passed stage day (at most one open at a time) and one at the end; the auditor's note appears in the conversation and `raise_audit_finding` produces an `audit_finding` alert.
- `Runtime.tick` still never calls a model, and `build_role_tools` still rejects a control tool in any role, the auditor included.
- With no model configured, no audit task is created.

## Left to the builder

Alert message wording, the exact shape of `get_stage_records`' output, the console labels, the constant names, and where the open-audit check reads from, as long as it stays within the task board.

## Interaction with other work

A separate branch (`fix/pr4-review-findings`) is fixing the PR 4 review findings, including where the data window ends and how manual task records are accepted. This work reads the window through the freeze's own function and the task records through `planning/manual_tasks.py`, so it follows whatever rule that branch settles on. Whichever lands second rebases.

## Revised during implementation

- The console shows the alert messages, not per-kind labels. The only console change is the conversation label "Auditor" / "监察 Agent".
- The data window follows the stage's actual end (taken from the fix branch), not only its planned end.
- The 6-call cap is the auditor's default role limit (`RoleModel(max_calls=6)`). The per-task call budget is not enforced.
- An audit left in `needs_attention` does not block the next one.
- A stage judges only measurements timed at or after its own start (ruling R6). All stages of a round share one experiment and a measurement carries no stage id, so earlier ones are an earlier stage's: they raise no `measurement_outside_window`, and `get_stage_records` leaves them out of "measurements" and reports their number as "measurements_before_stage".
