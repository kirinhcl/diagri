# Enable DiAGRI

[简体中文](../zh-CN/Enable-DiAGRI.md)

This page is for an operator who already runs the bridge-only daemon and wants to switch DiAGRI on: the configuration fields, the write host, the first operator, where credentials come from, how to start `serve` and how to check it. It also shows how to switch the mode off again.

> **What enabling gives you today.** With `auto_research = true`, `serve` starts the runtime, runs the executor about once a second, mounts the workbench routes under `/wb` and, when `roles` is set, runs open model tasks every 30 seconds. An operator starts a round through those routes: project, research protocol, round, model call budget and goal; see [Run a research round](Run-a-Research-Round.md). There is no web page and no CLI command for it. What a real model does with a goal has not been run: the tests use a scripted model. `serve` also sends no external heartbeat and starts no compute service. All of it has been tested on the simulated AC5 only. See [Status and known limitations](Status-and-Known-Limitations.md).

## Before you start

- The bridge-only install works: `.venv/bin/growbridge status` prints the device state. If it does not, go to [Installation and quick start](Installation-and-Quick-Start.md).
- You know which configuration file the daemon uses. The default is `~/.config/spiderfarmer-growbridge/config.toml`. For another file, put `--config /absolute/path/to/config.toml` before the subcommand in every command below.
- To see the mode work without a device, run `.venv/bin/growbridge simulate` first. It needs no configuration and prints a summary with `"stage": "ended"`. See [Tutorial: a simulated research round](Tutorial-Simulated-Round.md).

## 1. Stop the daemon

Stop `serve` with Ctrl-C. If it runs as a background service, remove the service for now:

```sh
.venv/bin/python scripts/install_macos.py --uninstall   # macOS
.venv/bin/python scripts/install_linux.py --uninstall   # Linux
```

The configuration file is read once, when `serve` starts.

## 2. Set the configuration fields

Add the top-level fields before any `[roles.*]` table, because TOML assigns every key after a table header to that table.

```toml
auto_research = true
controls_enabled = true

lan_bind = "YOUR_LAN_ADDRESS"
lan_port = 9443
lan_hosts = ["YOUR_LAN_HOST"]
overlay_hosts = ["YOUR_OVERLAY_HOST"]

report_time = "08:00"
report_timezone = "Europe/Helsinki"

backup_dir = "/absolute/path/to/backup"
backup_interval_seconds = 21600

[roles.planner]
model = "claude-opus-5-5"
effort = "medium"
max_tokens = 16000
```

| Field | Set it to | If you leave it out |
| --- | --- | --- |
| `auto_research` | `true` | The daemon runs in bridge-only mode. |
| `controls_enabled` | `true` | Every write is refused with `controls_disabled`, so the executor cannot act. |
| `lan_bind`, `lan_port` | The address and port of the on-site listener. Give it a port of its own, not `port`. | Both are needed to start the listener. Without them there is no LAN entry and irrigation is refused with `entry`. |
| `lan_hosts` | The host names or addresses an on-site client puts in its `Host` header. | No request can be a LAN entry request. |
| `overlay_hosts` | The host name of the overlay address. | There is no overlay entry. |
| `report_time`, `report_timezone` | `HH:MM` and an IANA zone name. | `08:00` and `UTC`. |
| `backup_dir`, `backup_interval_seconds` | A directory on independent media, and seconds between backups (60 or more). | No backups and a standing `backup_unconfigured` warning. The interval defaults to 21600. |
| `[roles.<name>]` | One table per model role: `orchestrator`, `planner`, `researcher`. | With no table at all, model roles are off. With at least one, a role without a table uses the defaults. |

Things the loader in [`config.py`](../../../src/growbridge/config.py) and the entry check in [`workbench/auth.py`](../../../src/growbridge/workbench/auth.py) do with these fields:

- An unknown field name makes `serve` fail at start, at top level and inside a role table.
- A host listed in both `lan_hosts` and `overlay_hosts` is no entry at all.
- The overlay entry is the loopback listener `127.0.0.1:<port>`. A request counts as overlay when it arrives there with a `Host` header listed in `overlay_hosts`. The repository ships no proxy and no overlay network setup: you need your own HTTPS reverse proxy that forwards to that listener and keeps the `Host` header. Not verified.
- Of the role fields, the code reads `model`, `effort`, `max_tokens` and `tools`. `provider`, `max_calls` and `data` are checked when the file is loaded and are not read anywhere yet.

The full list of fields is in the [Configuration reference](Configuration-Reference.md). Report and backup behavior is in [Notifications, daily reports and backup](Notifications-Reports-and-Backup.md).

## 3. Register the write host

```sh
.venv/bin/growbridge host register
```

You should see `Write host registered: <host id>`. The id is kept in `host_id` in the data directory. Running the command twice is harmless.

If it is refused with `another host is registered for this device`, the control database already names another machine. See "Restore from backup or a new write host" in the [Troubleshooting runbook](Troubleshooting-Runbook.md).

Do this before starting `serve`. A daemon that starts unregistered keeps the BLE connection closed, raises the alert `runtime` / `write_host` and refuses writes until it is registered and restarted.

## 4. Add an operator

```sh
.venv/bin/growbridge operator add YOUR_OPERATOR
```

The command asks for the secret twice and never takes it as an argument. The secret needs 12 to 256 characters. You should see `Operator added: YOUR_OPERATOR`. Only a salted hash is stored.

| Message | What to do |
| --- | --- |
| `the secret needs at least 12 characters` | Choose a longer secret. |
| `the two entries differ` | Run the command again. |
| `operator 'YOUR_OPERATOR' already exists` | Use another name. There is no command to remove an operator or change a secret. |

## 5. Put credentials in the environment

No credential goes into the configuration file. `serve` reads them from its own environment.

| Purpose | Where it comes from |
| --- | --- |
| Model calls | The Anthropic SDK reads its own variables; the tests set `ANTHROPIC_API_KEY` ([`tests/agents/test_agents_llm.py`](../../../tests/agents/test_agents_llm.py)). The SDK is the optional extra `agents` in [`pyproject.toml`](../../../pyproject.toml): `.venv/bin/python -m pip install '.[agents]'`. Its version is not pinned in `constraints-tested.txt`. |
| A model role calling `/wb` over HTTP | `GROWBRIDGE_ROLE_TOKEN_<ROLE>`, for example `GROWBRIDGE_ROLE_TOKEN_PLANNER`, sent as `Authorization: Bearer ...`. At least 32 characters; a shorter one stops `serve` at start. The model tasks that `serve` runs itself do not use these tokens. |
| Notifications | `GROWBRIDGE_TELEGRAM_*`, `GROWBRIDGE_EMAIL_TO`, `GROWBRIDGE_SMTP_*`. See [Notifications, daily reports and backup](Notifications-Reports-and-Backup.md). |

The installers in `scripts/` write no environment into the launchd or systemd service. To use these variables in a background service you have to add them to the service definition yourself. Not verified. A real model call has not been made in any test either: the tests stub it.

## 6. Start the daemon

```sh
.venv/bin/growbridge serve
```

`serve` listens on `127.0.0.1:<port>` and, when `lan_bind` and `lan_port` are set, on that address as well. Lines to look for in the log:

| Log line | Meaning |
| --- | --- |
| `not the registered write host: the BLE connection stays closed` | Step 3 was skipped. Stop, register, start again. |
| `the device did not identify itself within 20.0 s` | The AC5 did not answer. The daemon keeps running and keeps trying. |
| `model roles are off: ...` | `roles` is set but the SDK or its credentials are missing. Everything else still runs. |
| `growbridge: the token of role '...' is shorter than 32 characters` | `serve` stopped. Fix the role token. |

The two real listeners are not covered by a test; the tests reach the same application in process.

## 7. Check that it is up

1. `.venv/bin/growbridge status` still prints the device state.
2. The workbench is mounted. A request without a session is answered `401` with code `session`; `404` means the daemon is in bridge-only mode.

   ```sh
   curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8766/wb/me
   ```

3. Log in on the LAN entry. The workbench has no web page, so send the request with any HTTP client that keeps cookies. [Run a research round](Run-a-Research-Round.md) lists the headers every request needs.

   ```http
   POST /wb/login
   Host: YOUR_LAN_HOST:9443
   Origin: http://YOUR_LAN_HOST:9443
   x-growbridge-ui: 1
   Content-Type: application/json

   {"name": "YOUR_OPERATOR", "secret": "YOUR_OPERATOR_SECRET"}
   ```

   You should get `{"operator": "YOUR_OPERATOR", "entry": "lan", "reauth_seconds": 300}` and the cookie `growbridge_operator`, valid for 8 hours on paths under `/wb`.
4. `GET /wb/alerts` with that cookie returns `{"alerts": [...]}`. On a new setup expect `backup_unconfigured` when `backup_dir` is unset, and `model_client` when model roles could not start. `runtime` with key `write_host` means the host is not registered. With no notification channel configured, expect the standing warning `notify_unconfigured`: alerts are recorded but not sent; see [Notifications, daily reports and backup](Notifications-Reports-and-Backup.md).
5. The bridge write endpoints `POST /control/{device}`, `POST /outlet` and `POST /pump` now answer `403` with `Device writes go through the workbench`. The dashboard controls and the MCP write tools call those endpoints, so they stop working; reading still works.

## 8. Approve the safety configuration

Protection rules exist only after an operator approves a safety configuration. Within 300 seconds of logging in or re-authenticating, send:

```http
POST /wb/safety/approve

{"config": {"version": 1, "rules": [{"id": "overheat-light-off", "sensor": "temp", "unit": "C",
  "validity_seconds": 20, "trigger": {"op": ">", "value": 35}, "duration_seconds": 30,
  "action": {"channel": "light", "level": 0}}]}}
```

You should get `{"protection_right": <number>}`. A configuration with a NaN or an infinite number is rejected with `422`, and the configuration approved before stays in force. The rule above is the one in the simulator fixture ([`sim/fixtures.py`](../../../src/growbridge/sim/fixtures.py)); it is an example of the shape, not a recommended setting. What protection rules may do is explained in the [Control and safety model](Control-and-Safety-Model.md).

## When a step is refused

| You see | What to do |
| --- | --- |
| `400 Invalid host header` | The `Host` you used is not in `lan_hosts` or `overlay_hosts`. Add it and restart. |
| `403`, code `entry`, on login | The host and the listener do not match: a LAN host must arrive on `lan_port`, an overlay host on `port`. `127.0.0.1` is not an entry. The same code is returned when the `Origin` or `x-growbridge-ui` header is missing. |
| `401`, code `session` | Wrong name or secret, or the session expired. Log in again. |
| `429`, code `locked` | Five failed attempts for this name from this address inside 15 minutes. Wait. |
| `403`, code `reauth_required` | Send `POST /wb/reauth` with `{"secret": "..."}` and repeat the request. |
| `A daemon already owns this data directory` | Another `serve` is running on the same `data_dir`. |

All codes are listed in [Denial codes and stage events](Denial-Codes-and-Events.md).

## Switch it off again

1. Stop every live stage first: `POST /wb/stages/STAGE_ID/stop`. Once the mode is off nothing follows a run sheet, and care rules and protection rules no longer run.
2. Stop the daemon, set `auto_research = false` and start `serve` again. The other fields may stay; bridge-only mode ignores them.
3. Check: the `curl` command in step 7 now prints `404`, and the bridge write endpoints accept writes again when `controls_enabled` is `true`.

The databases, the operators and the write-host registration stay in the data directory. When you switch the mode on again, the start is handled like any restart: every stage that is not `ended` or `stopped` goes to `recovery_check`. See [Troubleshooting runbook](Troubleshooting-Runbook.md).

## See also

- [Run a research round](Run-a-Research-Round.md)
- [Configuration reference](Configuration-Reference.md)
- [CLI reference](CLI-Reference.md)
- [Control and safety model](Control-and-Safety-Model.md)
- [Status and known limitations](Status-and-Known-Limitations.md)
