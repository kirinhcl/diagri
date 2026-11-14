# Notifications, daily reports and backup

[简体中文](../zh-CN/Notifications-Reports-and-Backup.md)

This page is for an operator who sets up what the daemon sends out and what it saves: the daily report time, the notification channels and their credentials, the heartbeat to an outside monitor, and the database backups, including how to restore one.

> **Not verified.** Delivery through Telegram and email, and the heartbeat to an outside service, have been tested with fake transports only. No message has been sent to a real service. See [Status and known limitations](Status-and-Known-Limitations.md).

## What exists today

| Feature | Configured with | State |
| --- | --- | --- |
| Daily report | `report_time`, `report_timezone` in the configuration file | Made by `serve` while a stage governs the device. |
| Telegram channel | Environment variables | Built by `serve` when its variables are set. |
| Email channel | Environment variables | Built by `serve` when its variables are set. |
| Heartbeat to an outside monitor | Environment variables | Built by `serve` when both URLs are set; one alone stops the start. |
| Database backups | `backup_dir`, `backup_interval_seconds` | Run by `serve` when `backup_dir` is set. |

Every change on this page takes effect when `serve` starts. Configuration fields are described in the [Configuration reference](Configuration-Reference.md).

## Set the daily report time

1. Stop the daemon.
2. Set the two fields in the configuration file:

   ```toml
   report_time = "08:00"
   report_timezone = "Europe/Helsinki"
   ```

   `report_time` is `HH:MM` in 24-hour form. `report_timezone` is an IANA zone name. The defaults are `08:00` and `UTC`.
3. Start `serve`.

What happens then ([`runtime.py`](../../../src/growbridge/runtime.py), `_daily_report`, and [`observer/report.py`](../../../src/growbridge/observer/report.py)):

- Once the local time has passed `report_time`, the report for yesterday's local date is made. It is made only while a stage governs the device: from the first stage start of a round until that round is delivered or aborted.
- After downtime, every missed day is reported, oldest first, up to the seven most recent days.
- The report has the time-weighted mean of each reading, the data coverage with its gaps, the protective actions and the manual interventions of that day, and a "Frozen readings" section that lists each period of that day in which a sensor kept reporting the same value (for example `temp stuck at 24 from 08:00 to 10:05`, or `(still frozen)` if it has not ended; `(no longer checked)` is added when the period ended because the sensor was taken off the check, not because the reading moved; `(close reason unrecorded)` marks a period closed before the reason was kept, which must not be read as a recovery), so you know which stretches of data are suspect. At most five periods are listed, periods that are still frozen first and then by start time; a last line `and N more (temp, co2)` names the sensors of the periods left out. Times are in the report timezone; a time outside that day also shows its date, and a time that cannot be shown reads "unknown time". No model writes any part of it. The runtime passes no ranges, crop observations or to-do items, so those parts are empty.
- It is saved once per project and date in the table `observer_reports` of `observer.sqlite3`, and queued on every notification channel.

An unknown zone name is not caught when the file is loaded. It shows up later as an alert of kind `tick_step` with the key `report`.

There is **no route** to read a saved report. You see it only through a notification channel.

## Set up a notification channel

The channels are in [`observer/channels.py`](../../../src/growbridge/observer/channels.py). Their settings come only from the environment of `serve`, never from the configuration file. [`runtime.py`](../../../src/growbridge/runtime.py) (`default_channels`) builds a channel only when both of its required variables are set at start.

| Channel | Required | Optional |
| --- | --- | --- |
| Telegram | `GROWBRIDGE_TELEGRAM_TOKEN` (the bot token), `GROWBRIDGE_TELEGRAM_CHAT_IDS` (chat ids, separated by commas) | none |
| Email | `GROWBRIDGE_SMTP_HOST`, `GROWBRIDGE_EMAIL_TO` (addresses, separated by commas) | `GROWBRIDGE_SMTP_PORT` (default 587), `GROWBRIDGE_SMTP_USER`, `GROWBRIDGE_SMTP_PASSWORD`, `GROWBRIDGE_SMTP_FROM` |

1. Stop the daemon.
2. Set the variables in the environment that `serve` starts in:

   ```sh
   export GROWBRIDGE_TELEGRAM_TOKEN='YOUR_BOT_TOKEN'
   export GROWBRIDGE_TELEGRAM_CHAT_IDS='YOUR_CHAT_ID'
   ```

   The installers in `scripts/` write no environment into the background service, so for a service you have to add the variables to the service definition yourself. Not verified.
3. Start `serve`.

What the channels do:

- Telegram posts to the registered chat ids and has no code that reads incoming messages. Email uses STARTTLS and logs in only when `GROWBRIDGE_SMTP_USER` is set. The sender address is `GROWBRIDGE_SMTP_FROM`, or the user, or `growbridge@localhost`.
- Two kinds of message are sent: each alert, once, as `[severity] message`, and each daily report as its full text. Resolving an alert sends nothing.
- A channel reports `accepted`, `unknown` or `failed`. Anything not accepted is tried again after 30 seconds, then with a doubling delay up to 30 minutes, for at most 20 attempts in all ([`observer/outbox.py`](../../../src/growbridge/observer/outbox.py)). These numbers are constants in the code, not configuration. An `unknown` result can therefore give you the same message twice.

There is no command that sends a test message. To check delivery, read `GET /wb/alerts`: the alert `run_health` names `oldest_undelivered_alert` when a notification on a configured channel has stayed undelivered for 900 seconds. Alerts themselves can always be read there, with or without a channel.

### With no channel set

This is what `serve` does when neither channel is configured, checked on the simulated device:

1. No alert and no daily report is queued for sending. Alerts are still recorded, and daily reports are still saved.
2. The warning alert `notify_unconfigured` is raised at start. It is resolved the next time `serve` starts with a channel.
3. The run health is not affected: `oldest_undelivered_alert` counts only notifications queued for a channel that has a sender.
4. When you configure a channel later and restart, every alert that is still open is queued and sent on it. Alerts that were resolved in the meantime, and daily reports made in the meantime, are not sent.

The same holds when you remove a channel: a notification already queued for it stays `pending` and no longer counts for the run health, and the alerts that are still open are queued on the channels that remain.

There is no command that clears the queue. A notification that used up its 20 attempts on a configured channel keeps `oldest_undelivered_alert` failing.

## The heartbeat to an outside monitor

What is implemented, in [`observer/health.py`](../../../src/growbridge/observer/health.py) and [`observer/channels.py`](../../../src/growbridge/observer/channels.py):

- Two signals: a host heartbeat sent with every beat, and a run heartbeat sent only while the run health is good. When the run health is bad, a failure signal is sent instead and the run heartbeat stops.
- The runtime beats once every 60 seconds (`HEARTBEAT_SECONDS` in [`runtime.py`](../../../src/growbridge/runtime.py)), and at once when the run health turns good or bad. An outside monitor needs a grace period longer than 60 seconds.
- `HeartbeatChannel` requests a URL read from an environment variable for a heartbeat, and the same URL followed by `/fail` for a failure.
- A signal that cannot be delivered raises the alert `external_monitor` with the key `host` or `run`.

### How to configure it

`serve` reads two environment variables ([`runtime_heartbeat.py`](../../../src/growbridge/runtime_heartbeat.py), called from `_serve_auto_research` in [`cli.py`](../../../src/growbridge/cli.py)). Both hold a URL from your monitoring service, for example a Healthchecks.io ping URL:

| Variable | Signal |
| --- | --- |
| `GROWBRIDGE_HEARTBEAT_HOST_URL` | The host heartbeat. |
| `GROWBRIDGE_HEARTBEAT_RUN_URL` | The run heartbeat. A failure goes to the same URL followed by `/fail`. |

- **Both or neither.** With both set, `serve` sends the heartbeats. With only one set, `serve` refuses to start and says which variable is missing: watching half of the failures would look like monitoring while it is not. A blank value counts as not set.
- **Neither set.** No request is made. The runtime raises the standing warning alert `monitor_unconfigured` with the key `heartbeats`, and resolves it the next time `serve` starts with both variables.
- **The URLs are secrets.** They are read only from the environment, when a signal is sent. They appear in no log line, alert text, error message or `repr`. Request URLs are never logged: `serve` runs at INFO, and the HTTP library would log every request URL at that level, so [`logging_setup.py`](../../../src/growbridge/logging_setup.py) holds the `httpx` and `httpcore` loggers at WARNING. This also protects the Telegram bot token, which is part of the Bot API request path.
- Give the monitor a grace period of more than 60 seconds; the monitor's own phone alert is what tells you when a heartbeat stops.

Not verified: the heartbeat has only been tested against a fake HTTP client. No signal has been sent to a real monitoring service.

The run health itself is computed on every tick and is visible as the alert `run_health`. Its probes and limits:

| Probe | Fails when |
| --- | --- |
| `growbridge_response` | No packet from the device for 60 seconds. |
| `executor_evaluation` | No executor tick for 30 seconds. |
| `capture` | No sample for `stale_seconds`, or for the run sheet's `sampling.max_gap_seconds` while a stage governs the device. |
| `archive_write` | No write to the project archive for 600 seconds. |
| `oldest_undelivered_alert` | A notification on a configured channel has been undelivered for 900 seconds. |
| `offsite_backup` | The last backup is older than two backup intervals. Checked only when `backup_dir` is set. |

## Set up backups

1. Stop the daemon.
2. Set the fields:

   ```toml
   backup_dir = "/absolute/path/to/backup"
   backup_interval_seconds = 21600
   ```

   Use a directory on other media than the data directory. The code does not check that. The interval is at least 60 seconds; the default is 21600 (6 hours).
3. Start `serve`. The first backup starts on the first tick. After it, the directory holds twelve files: `control`, `workflow`, `archive`, `observer`, `compute` and `agents`, each as `<name>.sqlite3` and `<name>.sqlite3.manifest.json`.

How it works ([`runtime_backup.py`](../../../src/growbridge/runtime_backup.py), [`archive/backup.py`](../../../src/growbridge/archive/backup.py)):

- **How often.** A backup starts when the oldest of the six last-success times is older than the interval. It runs in the background and does not hold up the executor.
- **Consistency.** Each database is copied through a separate read-only connection inside one read transaction, so the copy is one consistent state and writers are not blocked.
- **Integrity.** The copy is checked with `PRAGMA integrity_check` before it replaces the previous backup. A failed copy or check leaves the previous backup in place. The manifest holds `sha256`, `size` and `created_at` (UTC seconds) of the file.
- **One generation.** Each backup replaces the one before. Keeping older copies is up to you.
- **Failure.** The alert `backup` is raised with the error, and the next attempt waits 300 seconds. With no `backup_dir`, the warning `backup_unconfigured` stays open.

**Not in the backup:** the bridge sample history `growbridge.sqlite3`, the files under `archive/` in the data directory (data snapshot files), the files under `agent_work/` (research report files), the `host_id` file and the configuration file. The databases keep the records and digests of those files, not the files.

To check a backup by hand, compare the file with its manifest, for example with `shasum -a 256 /absolute/path/to/backup/control.sqlite3`. This uses a tool outside the product.

## Restore a backup

There is no restore command. The steps below are not covered by a test, apart from one that opens a backup file and finds the same records ([`tests/archive/test_archive_storage_backup.py`](../../../tests/archive/test_archive_storage_backup.py)).

1. Stop the daemon.
2. Check each backup file against its manifest.
3. Move the old `*.sqlite3` files of the six databases, and the `-wal` and `-shm` files next to them, out of the data directory. Copy the six backup files in.
4. Raise the recovery number:

   ```sh
   .venv/bin/growbridge recovery bump --reason "restored from backup"
   ```

5. Start `serve` and continue with "Restore from backup or a new write host" in the [Troubleshooting runbook](Troubleshooting-Runbook.md).

**What a restore does to the recovery number.** Copying files back changes nothing: the restored control database carries the recovery number it had when the backup was made, and nothing detects that a restore happened. Step 4 is what makes the restore safe. The bump raises the number by one, revokes every write right, voids queued writes and every approval, moves each unfinished stage to `recovery_check`, and makes every earlier session and the earlier safety approval invalid. Why this is required is on [Control and safety model](Control-and-Safety-Model.md).

## See also

- [Enable DiAGRI](Enable-DiAGRI.md)
- [Troubleshooting runbook](Troubleshooting-Runbook.md)
- [Configuration reference](Configuration-Reference.md)
- [Data, archive and traceability](Data-Archive-and-Traceability.md)
- [Status and known limitations](Status-and-Known-Limitations.md)
