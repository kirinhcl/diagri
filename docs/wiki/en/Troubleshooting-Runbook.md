# Troubleshooting runbook

[简体中文](../zh-CN/Troubleshooting-Runbook.md)

This page is for an operator whose stage has stopped doing what the run sheet says. Each section covers one failure: what you see, what the system has already done by itself, and what you must do.

> Tested on the simulated AC5 only. Steps that touch the real device, a Raspberry Pi or the host clock are not verified. See [Status and known limitations](Status-and-Known-Limitations.md).

## Where to look first

| Look at | With |
| --- | --- |
| The stage: `state`, `prior_state`, `paused_at`, the three write rights | `GET /wb/stages/STAGE_ID` |
| Open alerts, among them why a stage waits (`stage_waiting`) | `GET /wb/alerts` |
| One write | `GET /wb/receipts/REQUEST_ID` |
| The device | `.venv/bin/growbridge status` |
| Compute jobs on CSC: balance, budgets, open and stuck attempts | `GET /wb/compute` |
| The daemon log | the terminal or service log of `serve` |

How to send workbench requests is in [Run a research round](Run-a-Research-Round.md).

**The reason for a pause is in an alert.** A stage that is paused or put into the recovery check by the system raises the alert `stage_waiting`, and the alert is sent on the configured channels. Its message names the stage, the state, the event and what the event carried, for example:

```text
Stage STAGE_ID is paused after external_change: {"differences": [{"actual": 5, "channel": "light", "expected": 60, "field": "level"}]}
```

The severity is `critical` for `recovery_check` and `warning` for `paused`. The alert is resolved when the stage leaves that state. A pause that an operator asked for raises none (`_stage_alerts` in [`runtime.py`](../../../src/growbridge/runtime.py)).

The workbench still returns neither the stage history nor the event. Both are in `workflow.sqlite3` in the data directory: `wf_history` holds every state change with the event name and, in `detail`, what the event carried; `wf_events` holds every event id (tables in [`workflow/store.py`](../../../src/growbridge/workflow/store.py)). A read-only query shows the history of a stage. It is a workaround outside the product and not verified:

```sh
sqlite3 -readonly /absolute/path/to/data_dir/workflow.sqlite3 \
  "SELECT datetime(at,'unixepoch'), from_state, to_state, event, detail FROM wf_history
   WHERE stage_id='STAGE_ID' ORDER BY id DESC LIMIT 5;"
```

Event names are the values of `StageEventKind` in [`ports.py`](../../../src/growbridge/ports.py). The handling is in [`executor/engine.py`](../../../src/growbridge/executor/engine.py) and [`workflow/service.py`](../../../src/growbridge/workflow/service.py); the reasons are on [Control and safety model](Control-and-Safety-Model.md) and [Workflow and state machines](Workflow-and-State-Machines.md).

## What every pause has in common

When the system pauses a `running` stage, it revokes the stage write right and voids its queued writes. The stage keeps its care write right, so care rules go on, and protection rules go on. Nothing resumes by itself.

To continue, send `POST /wb/stages/STAGE_ID/resume` after a re-authentication. Resume is refused when:

| Code and message | What to do |
| --- | --- |
| `state`, `actions with unknown results must be settled first` | See "A write with result unknown". |
| `state`, `device differs from the run sheet: ...` | Take over and hand back: `POST .../takeover`, then `POST .../handback`. The answer lists the differences and the executor then brings the channels back to the run sheet. See [Manual takeover, irrigation and handback](Manual-Takeover-and-Irrigation.md). |
| `interlock` | See "Pump-off unconfirmed". |
| `approval_invalid` | The approval no longer fits, for example because the device capabilities changed. A paused stage cannot be approved again, and switching its run sheet has **no route**. The only request left for the stage is `stop`. Then choose `redo` with `POST /wb/rounds/ROUND_ID/choice` and file a new run sheet, or abort the round; see [Run a research round](Run-a-Research-Round.md). |
| `not_connected` | The device state cannot be read. Wait for the link. |

A stage paused longer than the run sheet's `max_wait_seconds` gets the event `max_wait_expired`. With `on_expiry = "stop"` in the run sheet it is then `stopped`; otherwise it stays `paused`.

## BLE disconnect during a running stage

**You see.** While the link is down the stage is still `running`. `GET /wb/alerts` shows `run_health` naming `growbridge_response` and `capture` once the data is old enough. After the link is back the stage is either still `running` or `paused` with the event `disconnect_affects`.

**The system has.** Reconnected by itself, without replaying any command. Written nothing for the stage while offline. On the first tick with the link back, checked four things: a level change in the run sheet fell inside the outage (`due_action`), the device differs from what was applied or cannot be read (`device_differs`), a write has an unknown result (`unknown_result`), the outage was longer than the run sheet's `sampling.max_gap_seconds` (`gap_too_long`). Any one of them pauses the stage. None: the gap is recorded and the stage continues.

**You do.** Nothing if the stage is `running`. If it is `paused`, check the device and resume. If the link does not come back, check the AC5 and the distance to it on site. The device is told nothing while the link is down, so it keeps its last settings.

## Readings stale

**You see.** The stage is `paused` with the event `readings_stale`. The link is up.

**The system has.** Found no valid reading for longer than the run sheet's `sampling.max_gap_seconds`, and paused the stage.

**You do.** Check that `growbridge status` shows current sensor values, and check the sensor on site. Resume only once readings are fresh: otherwise the stage is paused again on the next tick.

## Device state unreadable while connected

**You see.** The stage is `paused` with the event `readings_stale`. The `stage_waiting` alert and the `wf_history` row carry `"reason": "state_unreadable"`; in `wf_events` the event id contains `state-unreadable`.

**The system has.** Kept the link and fresh readings, but failed to read the device state (levels and modes) back. A failure shorter than `sampling.max_gap_seconds` is tolerated and the schedule continues; any successful read restarts the count. Once the failure outlasted the limit, the executor reported it and the stage was paused. A protection level that cannot be read back is sent again, at most every 30 seconds. After an outage, an unreadable state counts as a difference and gives `disconnect_affects` instead.

**You do.** Look for read errors in the log. Then send resume: it reads the device itself, and `not_connected` means the state is still unreadable.

## A write with result unknown

**You see.** An action record with `"state": "unknown"`. A `running` stage is `paused` with the event `result_unknown`. Manual writes are refused with `unsettled`.

**The system has.** Sent the write and received no receipt, lost the link while sending, or could not read back. It does not send the write again. On resume, on takeover and during a recovery check it reads the device and settles each unknown action as applied or not applied. That needs a live link, fresh readings and a confirmed stop of the old write path. Pump actions are never settled this way.

**You do.** Wait for fresh readings and resume. If resume is still refused, or the stage is `manual`, look at the device and record what you saw:

```http
POST /wb/stages/STAGE_ID/onsite-check

{"note": "light at 40 %, pump off"}
```

The request is accepted in `paused`, `manual` and `recovery_check`. It stores your name and note, marks every unknown action as settled, clears the pump interlock and marks the old write path as stopped. It trusts you, on either entry: send it only after you have looked at the device.

## Pump-off unconfirmed (interlock)

**You see.** An irrigation answers `"state": "unknown"` with `pump off unconfirmed; interlock set`. Writes, start and resume are refused with `interlock`. A live stage may move to `recovery_check` with the event `pump_off_unconfirmed`.

**The system has.** Tried pump-off twice at the end of the irrigation and set the interlock. On every tick with a live link the executor sends pump-off again and reads it back. When that is confirmed, and the old write path is confirmed stopped, it clears the interlock by itself. When it is not, it reports the event and the stage loses all write rights. Protection rules still act.

**You do.** Go to the pump. If it runs, switch it off at the AC5 or cut its power. Then read the stage. Once the interlock has cleared, a stage in `recovery_check` leaves it by itself when the other checks pass. If it stays there, send the on-site check above; the stage returns to `paused`, or to `manual` if it was taken over. Then resume. With no live stage there is **no route** to clear the interlock by hand; the executor keeps trying pump-off.

## A change made on the device panel

**You see.** The stage is `paused` with the event `external_change`.

**The system has.** Compared, on every tick, the level and mode of each channel with what it last applied. Someone changed a channel at the AC5 panel, in the app or with a device timer, and the executor paused instead of overwriting it. The same event is reported when writes to one channel fail three times in a row.

**You do.** Decide whether the change should stay. To return to the run sheet, take over and hand back; the handback answer lists the differences, and `{"accept_as_intervention": true}` records them. The executor's next writes also put the channel back into manual mode on the device. If writes keep failing, check the device and its wiring before you resume.

## Clock anomaly

**You see.** The stage is `paused` with the event `clock_anomaly`.

**The system has.** Seen the wall clock step by more than 5 seconds against the monotonic clock between two ticks ([`executor/outage.py`](../../../src/growbridge/executor/outage.py)). It paused the stage. Care rules continue from the last trusted time plus elapsed monotonic time.

**You do.** Check the time of the host and fix its time synchronization. Then resume the stage that the `clock_anomaly` paused. Only an operator can resume a paused stage or hand a manual one back, so a stage that the anomaly paused and that runs again under a new write right tells the executor that an operator has checked the clock, and the step seen earlier is forgotten (`_clock_checked` in [`executor/engine.py`](../../../src/growbridge/executor/engine.py)). A different stage that starts while the suspicion stands does not clear it: it is paused with `clock_anomaly` too, and resuming either of the paused stages clears it. No restart is needed. If the clock steps again, the stage is paused again.

## Process restart and the recovery check

**You see.** After `serve` starts, every stage that was `pending_review`, `running`, `paused` or `manual` is in `recovery_check`, with `prior_state` set and no write rights.

**The system has.** Revoked every write right. Marked writes that may have been sent as `unknown`, without sending them again, and voided queued ones. Asked the transport to confirm that the old write path is stopped. Set the interlock if a pump action is unsettled. Kept the approvals. On every tick it tries to leave the recovery check, which needs: the old write path confirmed stopped, no interlock, no unknown action left after a read-back and, for a stage that was `running` or `paused`, a device that matches the run sheet. Care rules run again once the old write path is confirmed stopped and no interlock is set, except for a stage that was `manual`.

**You do.** Read the stage. A stage that was `running` or `paused` comes out as `paused`: resume it. One that was `manual` comes out as `manual` with a new manual right. One that was `pending_review` comes out as `pending_review`: approve and start it as usual. If the stage stays in `recovery_check`, one condition fails: go to the device, check it, and send the on-site check. Your session survives a restart.

## Restore from backup or a new write host

Both end with a higher recovery number, which voids every earlier write right, approval and session.

1. Stop the daemon. For a new host, first make sure the old host can no longer write: remove its service and its configuration ([architecture document](../../diagri-agent-architecture.zh-CN.md), section 12.2). The code does not do or check this.
2. Put the databases back. There is no restore command. Move the old `*.sqlite3` files and the `-wal` and `-shm` files next to them out of the data directory, then copy the six backup files in. See [Notifications, daily reports and backup](Notifications-Reports-and-Backup.md) for the file list and the integrity check. Not verified.
3. Raise the recovery number:

   ```sh
   .venv/bin/growbridge recovery bump --reason "restored from backup"
   ```

   You should see `Recovery number is now N; confirm the safety config and review live stages`. `a daemon is running on this data directory; stop it first` means step 1 is not done.
4. New host only: `.venv/bin/growbridge host register`. It is refused with `another host is registered for this device` when the restored control database names the old host. There is **no command** to replace the registered host. The check compares the `host_id` file in the data directory with the control database, so moving that file along with the databases moves the registration. Not verified.
5. Start `serve` and log in again. The old cookie is refused with `session`.
6. Approve the safety configuration again: [Enable DiAGRI](Enable-DiAGRI.md), step 8. The one approved under the old number is not valid.
7. Every unfinished stage is in `recovery_check`. If the device differs from the run sheet it stays there until you send the on-site check. It then returns to `pending_review` with its approvals void. Approve and start it again. Starting sets a new start time, so the stage's duration counts from there.

## A stuck compute attempt

**You see.** `GET /wb/compute` lists the attempt under `stuck` with a `reason`: waiting for reconciliation (the outcome of a submit is unknown), an error from the last poll, or no refresh for an hour. Its quota stays reserved.

**The system has.** Every minute the tick looks again at attempts nobody has answered for: an unanswered submit older than 5 minutes is looked up by its job name and never submitted twice; a queued or running job is polled and settled when it ends. If no job is found, the attempt is charged its whole reservation (it may have run) and its remote directory is cleaned up. A job that CSC no longer lists, or a Slurm state the code does not know, cannot be polled: the tick records the error and keeps trying.

**You do.** First check on CSC (MyCSC or `squeue`/`sacct`) what became of the job named `gb-<attempt id>`. If it is gone or cannot be recovered, settle the attempt:

```http
POST /wb/compute/attempts/ATTEMPT_ID/settle

{"reason": "job 123456 finished on CSC but is no longer listed; outputs lost"}
```

It needs a recent re-authentication. The attempt becomes `failed`; if its usage was not charged yet, the whole reservation is charged (the real use is unknown), your name and the reason are stored, and the service tries to cancel the job and remove its directory (what fails is written into the attempt's `error`). Settling twice is refused with `state`. A failed attempt can then be retried by the researcher. If the job's outputs are still on CSC you can instead leave the attempt alone and fix the cause (credentials, network); the tick resumes by itself.

## Compute outputs too large

**You see.** `GET /wb/compute` lists the attempt under `stuck` in the phase `needs_review` with a reason that starts with `output limit:`. It names which limit was hit: the number of files, the total listed size against the template's `max_storage_gb`, or the bytes that actually arrived. The researcher's `fetch_compute_artifacts` is refused with `state` and is not retried.

**The system has.** Refused before any download when the listing already breaks a limit, or when one file alone does not fit in what is left. Each download is watched: a quarter of a second at a time the size of the file on disk is checked, and the transfer is cancelled as soon as it passes the limit; then everything that fetch had downloaded is deleted, so the disk of the daemon's machine (which also holds the archive) is not filled. The remote files stay on CSC. Expect the disk to briefly hold somewhat more than the limit before the watchdog reacts: at most what the link carries in 0.25 seconds (about 31 MB at 1 Gbit/s) plus a chunk, and it is deleted again at once.

**You do.** Look at the job's output directory on CSC (`FIRECREST_WORKDIR/gb-<attempt id>/out`). If the size is a mistake in the template or a parameter, fix that and let the researcher retry after you settle. If the outputs are really needed, fetch what you need by hand and then settle. To close the attempt:

```http
POST /wb/compute/attempts/ATTEMPT_ID/settle

{"reason": "outputs 80 GB against a 5 GB reservation; template fixed"}
```

Settling marks the attempt `failed` and removes its remote directory. A larger limit needs a new template version with a higher `max_storage_gb`.

## Other alerts

| Alert kind | Meaning | What to do |
| --- | --- | --- |
| `runtime`, key `write_host` | This machine is not the registered write host. BLE stays closed. | [Enable DiAGRI](Enable-DiAGRI.md), step 3, then restart. |
| `run_health` | The message names the failing probes: `growbridge_response`, `executor_evaluation`, `capture`, `archive_write`, `oldest_undelivered_alert`, `offsite_backup`. | Follow the probe: device link, daemon, notifications or backups. |
| `tick_step` | One step of the tick raised an error; the key is the step. The other steps still run. | Read the log. The alert resolves when the step succeeds again. |
| `pump_unexpected` (key `pump`) | The pump read back as on while DiAGRI was not irrigating. The text says whether the switch-off was confirmed. | Critical. Check the pump and the panel: someone or a panel timer switched it on. If the text says unconfirmed, the interlock is set; do an on-site check. |
| `pump_unreadable` (key `pump`) | The pump outlet cannot be read from the device status, so the watchdog cannot tell whether the pump is on. Warning. | Check the device link and that the status contains the outlet block (a firmware or format difference). It resolves when a status can be read again. Latched: see below the table. |
| `pump_watchdog` (key `step` or `intervention`) | `step`: the watchdog itself failed. `intervention`: the `unexpected_watering` intervention could not be recorded (the pump was still switched off). Critical. | Read the log. `step` resolves after a step that read the pump; `intervention` after a later intervention is recorded. Latched: see below the table. |
| `frozen_reading` (key = sensor) | A sensor has reported exactly the same value for longer than its threshold. Critical when a protection rule uses it, otherwise warning. A stage whose rules depend on it is paused (event `alert_pause`, `rule` `frozen:<sensor>`). | Check the probe and its cable. The alert resolves when the value changes or the sensor leaves the check. Resume the stage once the sensor works or the rule is changed. |
| `frozen_watch` (key `check`) | The frozen-reading check itself is failing. Critical. | Read the log. It resolves after a completed check. |
| `task_missed` (key `stage:task:due`) | A manual task occurrence is past its on-time deadline and has no record. Warning. | Do the task if it can still be done and enter its record in the console; the alert resolves when a record arrives. |
| `measurement_missing` (key `stage:task:due`) | A measurement task is recorded done, but 2 hours after the record no current measurement of the experiment is timed between an hour before the task was due and its deadline. Warning. | Enter the measurement with its true time, or correct the task record if nothing was measured. The alert resolves when a measurement in the window exists. |
| `measurement_outside_window` (key `stage:measurement`) | A current measurement is timed outside the window, so the snapshot will leave it out. Warning. | Check the time entered. Replace the measurement with a corrected one; the alert resolves when it is replaced. |
| `stage_checks` (key `check`) | The stage checks themselves are failing. Critical. | Read the log. It resolves after a completed check. The other alert rules still run. |
| `audit_finding` | The auditor found something a person should act on. Info or warning; it pauses nothing. The message says what. | Read the finding and the auditor's note in the project conversation, then act on the stage yourself if needed. |
| `audit_schedule` (key `schedule`) | Scheduling the audits raised an error. The other model tasks still ran. | Read the log. Audits resume when scheduling works. |
| `audit_task` (key `audit:stage`) | An auditor run failed or ended needing attention. Warning, one per stage: later failed audits of the same stage add to its count. It pauses nothing; stage execution is not affected. | Read the log and the task the message names, and check the SDK and credentials. It resolves when an audit of that stage ends `done`, or once the stage is no longer the active one. |
| `stage_waiting` | The system paused a stage or put it into the recovery check. The message names the event and its detail. | Find the event in the sections above. The alert resolves when the stage leaves that state. |
| `backup`, `backup_unconfigured` | A backup failed, or no `backup_dir` is set. | [Notifications, daily reports and backup](Notifications-Reports-and-Backup.md). |
| `notify_unconfigured` | No notification channel is configured. Alerts are recorded but not sent. | [Notifications, daily reports and backup](Notifications-Reports-and-Backup.md). |
| `monitor_unconfigured` | Neither heartbeat URL is set, so nobody is told if the host or the run stops. | Set `GROWBRIDGE_HEARTBEAT_HOST_URL` and `GROWBRIDGE_HEARTBEAT_RUN_URL`; see [Notifications, daily reports and backup](Notifications-Reports-and-Backup.md). |
| `external_monitor` (key `host` or `run`) | A heartbeat or failure signal was not delivered. | Check the monitor URL and the network; see the same page. |
| `model_client`, `agent_task`, `task_deadline` | Model roles are off, or a model task failed or is overdue (a failed audit is `audit_task`, above). Stage execution is not affected. | Check the SDK and credentials. There is **no route** to settle a task. |

**Latched watchdog alerts.** `pump_unreadable` and `pump_watchdog` are stored again every 5 minutes for as long as their cause is there. A read mark is kept, but an alert closed by hand (resolved in the database) while the cause is still there comes back within 5 minutes as a new alert, with a new notification. Fix the cause instead; the alert then resolves by itself. See [Control and safety model](Control-and-Safety-Model.md).

If the workbench cannot be reached at all, the [architecture document](../../diagri-agent-architecture.zh-CN.md) (section 10) gives the last resort: stop the daemon, then use the AC5 panel or cut the power.

## See also

- [Manual takeover, irrigation and handback](Manual-Takeover-and-Irrigation.md)
- [Denial codes and stage events](Denial-Codes-and-Events.md)
- [Control and safety model](Control-and-Safety-Model.md)
- [Workflow and state machines](Workflow-and-State-Machines.md)
- [Notifications, daily reports and backup](Notifications-Reports-and-Backup.md)
