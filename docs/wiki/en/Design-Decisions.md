# Design decisions

[简体中文](../zh-CN/Design-Decisions.md)

This page is for developers and reviewers who ask "why is it built this way?". It records twelve decisions behind DiAGRI. Each record gives the problem, what was decided, what follows from it, and the file where the code holds the decision.

The section numbers refer to the [architecture document](../../diagri-agent-architecture.zh-CN.md), which argues these points at length. Every decision below was checked in the code and its tests. All of them have run on the simulated AC5 only; see [Status and known limitations](Status-and-Known-Limitations.md).

## 1. Model roles get no device or stage control tools

- **Context.** A language model can be wrong, and it can be steered by text it reads on the web. If it could start a stage or switch a channel, one bad answer would reach the plants.
- **Decision.** Each model role has a fixed list of tools (`ROLE_TOOLS`). A second list, `CONTROL_TOOLS`, names the stage and device tools that no role can receive, whatever the configuration says. Configuration can only shorten a role's list. Handlers build the caller's identity themselves as `Actor(kind="model")`, and an input field such as `approved` fails validation. The workflow service refuses a model identity with `model_role`.
- **Consequence.** A model hands in drafts and reports. Only an operator approves, starts, pauses or takes over. With `auto_research` on, the shared API token and the MCP server are read-only as well.
- **Enforced in.** [`agents/tools.py`](../../../src/growbridge/agents/tools.py), [`agents/handlers_common.py`](../../../src/growbridge/agents/handlers_common.py), [`workflow/permissions.py`](../../../src/growbridge/workflow/permissions.py). Sections 4.7, 5.2 and 10.

## 2. One checkpoint for every BLE write

- **Context.** Writes come from timed actions, feedback rules, care rules, protection rules and operators. If each path did its own checks, the checks would drift apart.
- **Decision.** The control service is the only code that writes to the device, through `submit`, `irrigate` and `pump_off`. One lock, the gate, puts hand-overs and writes in a single order, with two priority levels: protection writes, the pump-off that ends an irrigation and hand-overs go before queued ordinary writes, without preempting the write already on its way; `pump_off()` stays outside the gate. A request is checked when it is queued, and again inside the gate just before it is sent.
- **Consequence.** Every ordinary write passes the same list: controls enabled, registered write host, a valid write right, the scope of that right, pump not started, no unsettled action, a live connection with fresh readings. Care and protection writes skip a few of these on purpose, so that they still work while a stage is paused or in recovery check. The BLE connection itself opens only on the registered write host.
- **Enforced in.** [`control/service.py`](../../../src/growbridge/control/service.py) (`_authorize`, `_recheck`), `ControlPort` in [`ports.py`](../../../src/growbridge/ports.py). Sections 7.1 and 7.3.

## 3. The intent is saved before anything is sent

- **Context.** The process can stop between deciding to write and learning the result. Sending the command again blindly could apply it twice.
- **Decision.** An action is stored as `pending` before it is sent, and as `maybe_sent` just before the bytes leave. At startup, every `maybe_sent` action becomes `unknown` and every `pending` action becomes `void`. Nothing is replayed. A `request_id` used again with the same arguments returns the stored record; with other arguments it is refused (`request_id_reused`).
- **Consequence.** After a crash the ledger shows which writes may have reached the device. Ordinary writes stay blocked (`unsettled`) until a read-back or an on-site check settles them.
- **Enforced in.** [`control/service.py`](../../../src/growbridge/control/service.py) (`submit`, `_send`, `_close_unfinished`). Section 7.9.

## 4. Write rights are numbered, and a restore raises the recovery number

- **Context.** After a manual takeover, a command queued by the automatic stage could still go out and overwrite the operator's setting. After a restore from backup, old approvals describe a tent that may have changed.
- **Decision.** Every grant of a write right gets a new number, and every request carries one. A revoked number, or a number from an earlier recovery number, cannot write (`right_invalid`). A hand-over revokes the number, voids its queued actions and waits for the one in flight. While a stage write right is held, no second stage or manual write right is granted (`right_held`). `bump_recovery` adds one to the recovery number and revokes every right.
- **Consequence.** After a restore or a change of write host, someone stops the daemon and runs `growbridge recovery bump --reason ...`. Live stages enter recovery check, approvals are void, and operator sessions bound to the old number are logged out.
- **Enforced in.** [`control/rights.py`](../../../src/growbridge/control/rights.py), [`control/service.py`](../../../src/growbridge/control/service.py) (`handover`, `bump_recovery`), [`workbench/auth.py`](../../../src/growbridge/workbench/auth.py). Sections 4.1, 4.6 and 7.1.

## 5. Rules run on the monotonic clock, and a data gap breaks continuity

- **Context.** A rule such as "humidity above 70 % for 60 seconds" must not be satisfied, or reset, by a jump of the wall clock. It must not count a minute in which no reading arrived.
- **Decision.** Durations and minimum switch intervals use the monotonic time carried by each reading. A reading drives a rule only if it has a value, quality `ok`, the rule's unit, and is no older than the rule's `validity_seconds`. If two valid readings are further apart than the run sheet's `max_gap_seconds`, the timer starts again.
- **Consequence.** A clock correction cannot trigger or release a rule. After a gap, the condition has to hold for the full duration again. With no valid reading, a feedback rule does nothing or pauses the stage, as its `on_missing` says (`hold` or `pause`), and a protection rule does not act.
- **Enforced in.** [`executor/rules.py`](../../../src/growbridge/executor/rules.py), [`archive/clock.py`](../../../src/growbridge/archive/clock.py). Section 7.4.

## 6. The entry comes from the listener that accepted the connection

- **Context.** Pump operations must be possible on site only. The daemon sits behind a proxy on its main port, and a client can write any name into the `Host` header.
- **Decision.** A request is on the LAN entry only if it was accepted on `lan_port` and names a host in `lan_hosts`. It is on the overlay entry only if it was accepted on `port` and names a host in `overlay_hosts`. A `Host` header alone proves nothing. Everything else has no entry, including an address that is on both lists. With `lan_port` unset there is no LAN entry at all. A session works only on the entry it was created on, and an entry claimed in a request body is ignored.
- **Consequence.** A remote user cannot reach LAN-only actions by forging a header. A deployment without `lan_port` cannot irrigate from the workbench.
- **Enforced in.** `entry_for` in [`workbench/auth.py`](../../../src/growbridge/workbench/auth.py), `find_entry` and `on_site` in [`workbench/api.py`](../../../src/growbridge/workbench/api.py), [tests](../../../tests/workbench/test_workbench_entry.py). Section 10.

## 7. One database file per owner; services share only protocols and models

- **Context.** Stage state, the action ledger and the records each have rules that one service must guard. If any service could write any table, no service could keep its rules.
- **Decision.** `build_runtime` creates one SQLite file per owner: `control`, `workflow`, `archive`, `observer`, `compute` and `agents`. A service imports the contracts in `ports.py` and the models in `archive/models.py`, not another service's classes. The runtime and the tool handlers of the model roles are the glue that connects them.
- **Consequence.** The workflow service is the only owner of stage state, the control service the only BLE writer, the archive the owner of records. Each file is backed up on its own. All services still run in one process under one system account; the separate system accounts of section 10 are a deployment step that the code does not perform. The runtime, which assembles everything, reads two tables directly for the daily report.
- **Enforced in.** [`runtime.py`](../../../src/growbridge/runtime.py) (`DATABASES`, `build_runtime`), [`ports.py`](../../../src/growbridge/ports.py), [`archive/db.py`](../../../src/growbridge/archive/db.py). Sections 10 and 12.1.

## 8. Raw data is append-only, derived data can be recomputed

- **Context.** A result has to be checkable months later. That fails if the rows it was computed from can change.
- **Decision.** The archive only inserts. A correction is a new record that points at the old one, and the snapshots and artifacts that used the old value are flagged as invalid. An analysis reads a frozen data snapshot whose files are fingerprinted, and freezing again makes a new version.
- **Consequence.** Storage only grows. A correction means freezing again and publishing again. The rule is kept by the `Archive` class, not by the database, so it does not cover a program that opens the file directly.
- **Enforced in.** [`archive/store.py`](../../../src/growbridge/archive/store.py), [`archive/snapshot.py`](../../../src/growbridge/archive/snapshot.py). Sections 11.2 and 11.3. Details in [Data, archive and traceability](Data-Archive-and-Traceability.md).

## 9. A confirmatory gate, and honest downgrade

- **Context.** If an analysis can be rerun and adjusted until something looks good, the word "confirmed" means little. With one tent, most designs cannot support a strong claim at all.
- **Decision.** The server computes the label of a report from the protocol and the frozen data. A confirmatory label needs a script frozen by hash, a complete and verified snapshot, and exactly one run. Five rules lower the label to descriptive or exploratory. What the model declares can only make the result stricter. An experiment that is too small ends as `uncertain`, never as "no effect".
- **Consequence.** Reports from one tent will often be exploratory or descriptive, and they say why. In the current code no command or tool starts the confirmatory run, so a report published through the tools is at most exploratory.
- **Enforced in.** [`research/analysis.py`](../../../src/growbridge/research/analysis.py), [`agents/handlers_report.py`](../../../src/growbridge/agents/handlers_report.py), [`research/report.py`](../../../src/growbridge/research/report.py). Sections 4.8, 6.5 and 9.3. Details in [Research methodology](Research-Methodology.md).

## 10. The executor and the observer are deterministic programs

- **Context.** A model API can be down, slow or expensive, and it does not answer the same way twice. The plants need their light schedule regardless.
- **Decision.** `Runtime.tick` never calls a model. The executor, the observer and the control service import no model client. Models run in a separate loop, and a model failure becomes a task that needs attention and an alert.
- **Consequence.** An approved stage runs to its end with no model client at all. The price is that the plan cannot adapt by itself: a change needs a new run sheet version and a new approval.
- **Enforced in.** [`runtime.py`](../../../src/growbridge/runtime.py), [`runtime_agents.py`](../../../src/growbridge/runtime_agents.py), [`executor/engine.py`](../../../src/growbridge/executor/engine.py). Tests: [`test_e2e_runtime.py`](../../../tests/e2e/test_e2e_runtime.py), [`test_e2e_agents.py`](../../../tests/e2e/test_e2e_agents.py). Sections 2, 7 and 8.

## 11. Fail closed when the device state cannot be read

- **Context.** A read-back can fail while the connection still looks alive. Treating "could not read" as "nothing differs" would let a stage continue on a state nobody has seen.
- **Decision.** The executor keeps "no difference" and "unreadable" apart. After an outage, an unreadable state counts as a difference and the stage pauses. During a running stage, an unreadable state is tolerated for `max_gap_seconds`; after that it is reported like stale readings and the stage pauses. A protection level that cannot be read back is sent again, at most every 30 seconds per channel, instead of being assumed in place.
- **Consequence.** More pauses that need an operator, in exchange for never acting on a guess. The same rule appears elsewhere: no entry when the listener is unknown (record 6), and no ordinary write while an earlier result is unknown (record 3).
- **Enforced in.** [`executor/engine.py`](../../../src/growbridge/executor/engine.py) (`_differences`, `_state_unreadable`, `_verified`), [tests](../../../tests/executor/test_executor_unreadable.py). Sections 4.4 and 7.7.

## 12. The pump is started only by an operator on the LAN entry

- **Context.** If the BLE connection drops while the pump runs, the program cannot be sure to stop it.
- **Decision.** Run sheet validation blocks any action that would start the pump (`pump_action`). `submit` never switches the pump on (`pump_on_forbidden`). The only path that does is `irrigate`: it needs a manual write right, a duration within `max_pump_seconds` and the cooldown `pump_cooldown_seconds`. The workbench offers it only to an operator on the LAN entry. Switching the pump off has its own path, and while pump-off is unconfirmed the pump interlock blocks ordinary writes.
- **Consequence.** This version has no automatic irrigation. Watering needs a person on site, or is done by hand as a manual task.
- **Enforced in.** [`planning/validate.py`](../../../src/growbridge/planning/validate.py), [`control/rights.py`](../../../src/growbridge/control/rights.py), [`control/service.py`](../../../src/growbridge/control/service.py), [`workbench/api.py`](../../../src/growbridge/workbench/api.py). Sections 4.5, 7.6 and 7.8. Steps in [Manual takeover, irrigation and handback](Manual-Takeover-and-Irrigation.md).

## See also

- [Architecture overview](Architecture.md)
- [Control and safety model](Control-and-Safety-Model.md)
- [Workflow and state machines](Workflow-and-State-Machines.md)
- [Data, archive and traceability](Data-Archive-and-Traceability.md)
- [Research methodology](Research-Methodology.md)
- [Denial codes and stage events](Denial-Codes-and-Events.md)
