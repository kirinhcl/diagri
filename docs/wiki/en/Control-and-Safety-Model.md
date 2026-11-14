# Control and safety model

[简体中文](../zh-CN/Control-and-Safety-Model.md)

This page is for anyone who has to trust, review or change the path from a decision to a BLE write. It explains why every write goes through one checkpoint, and what that checkpoint does at each step.

> **Status.** The behavior on this page is covered by tests against the simulated AC5. None of it has been verified on a real AC5, and a simulator cannot show how a real device or radio fails. See [Status and known limitations](Status-and-Known-Limitations.md).

## The problem

An operator takes over and sets the light to 50%. A command "light to 80%" from the automatic schedule is still queued, and goes out two seconds later. The manual setting is gone, and nobody decided that.

The same kind of accident can come from a restarted process, a restored backup, a second machine, or a command whose reply was lost. The control model removes all of them with one idea: **a write must show a numbered permission that is still valid at the moment the bytes leave, and one service checks it.** That service is `ControlService` in [`control/service.py`](../../../src/growbridge/control/service.py). Model roles cannot call it at all; see [The five agents](The-Five-Agents.md).

## Write rights

A write right is a row in the control service's ledger. It says who may write, to which channels, and for which stage. Every grant gets a new number (`right_number`), and a revoked number can never write again.

| Kind (`RightKind`) | Used for | May write | Granted |
| --- | --- | --- | --- |
| `stage` | automatic control while the stage is `running` | the run sheet's host-controlled channels | at start, resume, handback and run-sheet switch |
| `manual` | one operator during a manual takeover | the same channels, by that operator only | at takeover |
| `care` | care rules | only the channel and level pairs listed in the run sheet's care rules | together with the stage right; kept after the stage ends |
| `protection` | protection rules | only the pairs listed in the approved safety configuration | when an operator approves the safety configuration |

Three rules follow from [`control/rights.py`](../../../src/growbridge/control/rights.py) and `ControlService.grant`:

- **One ordinary controller at a time.** While a stage right is held, a second stage right or a manual right is refused with `right_held`. The workflow service revokes first and grants afterwards.
- **A right is narrow.** A request outside the right's channels, listed values, stage or operator is refused with `scope`. A channel that the run sheet leaves to the AC5's own timer (`Ownership.DEVICE`) is in no right, so nothing in DiAGRI can write it.
- **Numbers, not a switch.** "Automatic control is on" is not a setting that a late command could read at the wrong moment. Each command carries the number it was created under, and that number is checked again when the command is sent.

An example. The stage starts under stage right 7. The operator pauses it, and 7 is revoked. The operator resumes, and the executor now writes under right 8. A command created under 7 is refused with `right_invalid`, however late it arrives.

## One gate for hand-over and dispatch

`ControlService.gate` is a single lock with two priority levels. Three things take it: sending a write, finishing a hand-over, and `reconcile_unsettled`.

- `submit` checks the request, stores it, takes the gate, **checks everything a second time**, and sends.
- `handover` revokes the number, voids the actions still queued under it, and then takes the gate once. Taking it means waiting until a write that is already on its way has its receipt.

**Priority.** Waiters at the urgent level go before waiters at the normal level; within a level it is first come, first served. Urgent are: a write under the protection right, the pump-off that ends an irrigation, and `handover`. Normal are: every other write, the pump-on of an irrigation, and `reconcile_unsettled`. A protection write also voids the ordinary writes still queued on its own channel, so they cannot run after it and undo it (the write already on its way is left alone); the voided action reads `superseded by a protection write on <channel>`. The gate never preempts: an urgent caller waits for the one write already on its way, but not for the ordinary writes queued behind it. `pump_off()` (the interlock path) does not take the gate at all.

Why the same lock: when `handover` returns, no write under the old number is queued and none is in flight. A hand-over and a write cannot interleave, so the workflow service can grant the next right safely.

## What is checked, twice

Each request passes `_authorize` when it is queued and again inside the gate. In order:

1. Controls are enabled in the configuration.
2. This machine is the registered write host.
3. The right exists, is not revoked, and belongs to the current recovery number.
4. The request is inside the right's scope.
5. The request does not switch the pump on.
6. The control service has finished starting, the pump interlock is off, and the old write path is confirmed stopped. For stage and manual rights, no earlier action is unsettled.
7. The BLE link is up. For stage and manual rights, the telemetry is fresh.

A failure is `Denied(code)`. The codes are listed in [Denial codes and stage events](Denial-Codes-and-Events.md). A protection right skips check 6; the reason is in "Protection rules outlive the stage right" below.

## Intent first: the action ledger

Every write is recorded before it is sent, and the record moves through these states:

| State (`ActionState`) | Meaning |
| --- | --- |
| `pending` | The intent is stored. Nothing has been sent. |
| `maybe_sent` | Stored just before the bytes leave. |
| `confirmed` | Read-back shows the planned level. |
| `failed` | The device refused, or read-back shows another level or mode. |
| `unknown` | The write may or may not have taken effect. |
| `void` | Cancelled before sending: a hand-over, a failed second check, a protection write on the same channel, or a restart. |

Why `maybe_sent` exists. Suppose the process dies after the device applied a command but before the receipt was stored. A ledger that only knew `pending` would send the command again after the restart. With `maybe_sent`, start-up marks the action `unknown` and does not replay it (`_close_unfinished`).

A request is idempotent by `request_id`. The same id with the same arguments returns the stored record. The same id with other arguments is refused with `request_id_reused`. The ledger is in [`control/ledger.py`](../../../src/growbridge/control/ledger.py); what each record holds is on [Data, archive and traceability](Data-Archive-and-Traceability.md).

## Read-back and result unknown

A write counts only when the device shows it. After sending, `DeviceIO.write` in [`control/device.py`](../../../src/growbridge/control/device.py) reads the device up to three times (`READBACK_POLLS`) and requires both the planned level and manual mode (`modeType` 0). If the reply is missing, the link breaks, or the read-back cannot be done, the result is `unknown`.

The rule for `unknown` is: **check the device, never resend.**

- Writes under a stage or manual right are refused with `unsettled` while an unknown action is open.
- The executor reports `RESULT_UNKNOWN`, and a running stage is paused.
- `reconcile_unsettled` reads the device and writes "applied" or "not applied" onto the action. It runs when the operator resumes or takes over, and when a stage tries to leave `recovery_check`. It never settles a pump action.
- An operator's on-site check settles every unknown action (`onsite_check`).

Why not resend: for most channels a second identical command is harmless, but the program cannot know that the situation is still the one the command was made for. A person or a fresh read-back decides.

## A state that cannot be read is not a match

The executor compares the device with what it last confirmed. If that read-back itself fails, the answer is "unknown", and the executor never treats it as "the device matches". [`executor/engine.py`](../../../src/growbridge/executor/engine.py) handles three cases:

- **During a running stage.** A short failure is tolerated. If the state stays unreadable for longer than the run sheet's `sampling.max_gap_seconds`, the executor reports `READINGS_STALE` with `detail.reason = "state_unreadable"`, and the stage is paused. A successful read resets the timer.
- **After a link outage.** An unreadable state counts as "the device differs", so the outage is reported as `DISCONNECT_AFFECTS`.
- **While a protection rule holds a level.** See the resend rule below.

An example with `max_gap_seconds = 120`: the link is up and sensor packets keep arriving, but the state query fails. For 120 seconds the stage keeps running. After that it is paused and waits for the operator. The tests are in [`tests/executor/test_executor_unreadable.py`](../../../tests/executor/test_executor_unreadable.py).

## The pump

If the link drops while the pump is running, the program cannot guarantee that it is switched off in time. So no automatic path may start the pump.

- **`submit` never switches the pump on.** A pump request with a level other than 0 is refused with `pump_on_forbidden`, under every kind of right. The executor refuses even earlier and leaves pump entries out of the end actions.
- **Only `irrigate` starts it.** It is reached from `POST /wb/irrigation` and needs all of this: an operator session on the LAN entry; a stage in `manual` whose manual right that operator holds; a duration above 0 and at most `max_pump_seconds`; and the cooldown `pump_cooldown_seconds` since the last run, with no other run in progress.
- **Off always runs.** The pump is switched on under the gate, the wait happens outside the gate, and the switch-off happens under the gate again, with two attempts (`PUMP_OFF_TRIES`). A hand-over, a protection write or a `pump_off` call ends the run early.

**The pump-off interlock.** If the switch-off cannot be confirmed, the control service sets the interlock flag in its ledger. While it is set:

- writes under a stage or manual right are refused with `interlock`, and a stage cannot be started or resumed;
- the executor calls `pump_off` first in every tick. This path can only write "pump off" and read it back;
- if pump-off is still unconfirmed, the executor reports `PUMP_OFF_UNCONFIRMED` and a live stage goes to `recovery_check`;
- protection writes still pass. The gate also lets a care write on a channel other than the pump through, once the old write path is confirmed stopped.

The interlock clears when pump-off is confirmed and the old write path is confirmed stopped, or when an operator records an on-site check. A restart with an unsettled pump action sets it again. The operator's side of this is on [Manual takeover, irrigation and handback](Manual-Takeover-and-Irrigation.md).

## Old-write-stop confirmation

Revoking a number stops this process from writing. It does not prove that an older writer has stopped: a helper process or a BLE session may still hold queued commands. So the control service asks the transport, which is the part that actually holds the BLE connection.

`WriteTransport.halt()` returns true only when the transport can vouch for it: the macOS helper process is confirmed gone, or the BLE session is confirmed disconnected ([`transport.py`](../../../src/growbridge/transport.py)). A timeout or an error is "not confirmed". The control service asks at start-up and after a recovery number change, and stores the answer.

While the answer is "not confirmed", every write except protection is refused with `unsettled`, and the executor reports `TRANSPORT_UNCONFIRMED`, which sends a live stage to `recovery_check`. The other way out is an operator's on-site check.

## Protection rules outlive the stage right

The stage right is revoked on every pause, takeover, stop and restart. If overheating protection used it, protection would disappear exactly when something had gone wrong. So protection has its own right:

- It is issued by `approve_safety`, a separate approval, and is reissued at start-up. No stage hand-over revokes it.
- The gate does not apply check 6 to it. A protection write passes during a pause, a takeover, `recovery_check` and the interlock.
- The executor evaluates the protection rules in every tick while the link is up, before it looks at the stage. It does so in any stage state, and also when there is no stage.

It is still bound by the other checks: enabled controls, the registered host, the current recovery number, a live link, a listed value, and never the pump on.

**Holding a level.** While a rule's trigger holds, the executor verifies in every tick that the device shows the protective level. If the device shows another level, it writes again at once. If the level cannot be read back, that is not a confirmation, so the executor sends the level again, but at most once per `PROTECTION_RESEND_SECONDS` (30 seconds) per channel. The limit keeps a one-second tick from filling the ledger with a record per second.

**Limits.** After a recovery number change there is no protection until the safety configuration is approved again. Without a BLE link nothing can be written, so a risk that must be covered while offline needs the AC5's own limits or separate hardware. A protection rule on a channel that the run sheet leaves to the device is a conflict, and the stage cannot start (`safety_conflict`). The code restricts a protection right to its listed values; that those values lower the risk is what the operator confirms when approving the configuration.

## Frozen readings

A sensor that keeps reporting exactly the same value is not a reading, it is a stuck sensor. The observer records a frozen period and raises an alert, but it pauses a stage only when that stage depends on the sensor: a feedback rule of the run sheet uses it, or a protection rule does (a rule on `vpd` counts as using `temp` and `humi`). A frozen sensor nothing depends on only produces an alert. A protection rule on the sensor raises the alert to critical. Only a `running` stage is paused, once per period and stage, and no second pause once the first has paused the stage: when two periods open in the same check, the second one pauses the stage on a later check, after the operator has resumed it. Periods a protection rule depends on are handled first. Raw samples are never changed; the period is a separate, append-only record.

## Recovery number

A backup holds rights and approvals that were issued in the past, for a device that may have changed since. `growbridge recovery bump` raises the recovery number, and everything issued under the old number stops working:

- every write right is revoked and every queued action is voided (`bump_recovery`);
- every stage that is not finished goes to `recovery_check`, and its approvals are voided;
- operator sessions bound to the old number are refused;
- the safety configuration no longer counts until an operator approves it again, and only then can a stage leave `recovery_check`, back to `pending_review`.

The command runs only while the daemon is stopped.

## Write host

One machine is registered per device (`growbridge host register`). The first machine to register holds the device, and any other is refused with `host_unregistered`. On a machine that is not registered, the BLE connection is not even opened, and granting, writing, approving the safety configuration and `pump_off` are all refused. The reason: two daemons writing to one AC5 would each pass their own checks.

## Entries: where a request came in

Some operations are only safe when the operator is standing next to the tent. The server therefore decides which entry (`Entry`) a request used, in `entry_for` in [`workbench/auth.py`](../../../src/growbridge/workbench/auth.py):

- **LAN entry**: the connection was accepted by the listener on `lan_port`, and its `Host` is one of `lan_hosts`.
- **Overlay entry**: the connection was accepted by the main listener on `port`, and its `Host` is one of `overlay_hosts`.
- Anything else has no entry, and an operator can neither log in nor act from there. If `lan_port` is not set, there is no LAN entry at all.

The listener is what decides; a `Host` header alone selects nothing. A remote client that reaches the main port through the overlay proxy can send any `Host` it likes, but it cannot change which listener accepted it. An operator session also stays bound to the entry it logged in on. Irrigation is offered on the LAN entry only.

## What this model does not cover

The control service owns the GrowBridge side of the BLE link. The AC5 panel and the Spider Farmer app can still change the device. DiAGRI only notices afterwards, through read-back, as `EXTERNAL_CHANGE`.

The pump is the exception. Nobody switches the pump on by hand during an experiment and the pump is never left to the AC5 timer, so a pump outlet that reads back as on while DiAGRI is not irrigating is always unexpected. The executor's pump watchdog checks this on every tick: it switches the pump off through the dedicated `pump_off` path (trigger `watchdog`), raises a critical `pump_unexpected` alert and records an `unexpected_watering` intervention against the active stage (with no active stage the watchdog still runs, but then only the ledger record and the alert exist and no intervention is recorded). `pump_off` also resets the outlet mode to manual, which clears a timer set on the AC5 panel. If the outlet cannot be read it only raises a `pump_unreadable` warning and does nothing else. The watchdog acts only while connected and with no unconfirmed pump-off; an unconfirmed switch-off is handed to the pump-off interlock.

The watchdog's `pump_unreadable` and `pump_watchdog` alerts are latched. While the condition holds, the watchdog stores the alert again every 5 minutes (a changed message at most once a minute), and it resolves the alert once a step shows the condition is over. Storing an alert that is still open only raises its count: a read mark stays and no second notification is sent. An alert closed by hand while the condition still holds (the console only marks alerts as read, so this means resolving it in the database) therefore comes back within 5 minutes as a new alert, with a new notification. To silence it, remove the cause. If the alert cannot be stored, the watchdog tries again on its next step rather than 5 minutes later, and a resolve that could not be stored is likewise tried again on the next step. The latch lives in memory: after a restart the first step stores the alert again, which only raises the count of the alert still open.

## See also

- [Workflow and state machines](Workflow-and-State-Machines.md)
- [The five agents](The-Five-Agents.md)
- [Manual takeover, irrigation and handback](Manual-Takeover-and-Irrigation.md)
- [Troubleshooting runbook](Troubleshooting-Runbook.md)
- [Denial codes and stage events](Denial-Codes-and-Events.md)
- [Glossary](Glossary.md)
- [Architecture document](../../diagri-agent-architecture.zh-CN.md), sections 4.1 to 4.6, 7 and 10
- Tests: [`tests/control/`](../../../tests/control/), [`tests/executor/`](../../../tests/executor/)
