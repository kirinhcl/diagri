# CLI reference

[简体中文](../zh-CN/CLI-Reference.md)

This page is for anyone who runs the `growbridge` command. It lists every subcommand and option, what each one does and prints, and how it exits.

The parser is `main()` in [`cli.py`](../../../src/growbridge/cli.py). The tables were checked against `growbridge --help` and the `--help` of every subcommand, version `0.2.0`. On this page "bridge-only mode" means `auto_research = false`.

## Synopsis

```text
growbridge [-h] [--version] [--config CONFIG]
           {init,scan,serve,mcp,status,dashboard,operator,host,recovery,simulate} ...
```

## Global options

Global options go before the subcommand, for example `growbridge --config /absolute/path/to/config.toml status`.

| Option | Argument | Default | What it does |
| --- | --- | --- | --- |
| `-h`, `--help` | none | | Prints the help text and exits 0. Every subcommand accepts it too. |
| `--version` | none | | Prints the version and exits 0. |
| `--config` | `CONFIG`, a path | `~/.config/spiderfarmer-growbridge/config.toml` | The configuration file to read. For `init`, the file to create. |

## Subcommands

There are 10 subcommands. `operator`, `host` and `recovery` each take one nested subcommand, which is required.

| Command | Arguments and options | Reads the configuration file | Needs a running daemon | DiAGRI mode |
| --- | --- | --- | --- | --- |
| `init` | `--device DEVICE` (required), `--enable-controls` | no, it creates it | no | not needed |
| `scan` | none | no | no | not needed |
| `serve` | none | yes | it is the daemon | works in both modes |
| `mcp` | none | yes | yes, every tool calls it | works in both modes; the tools differ |
| `status` | none | yes | yes | works in both modes |
| `dashboard` | `--no-open` | yes | yes | works in both modes; the dashboard cannot write in DiAGRI mode |
| `operator add` | `name` (positional, required), `--admin` (make the operator an administrator; multi-user) | yes | no | meant for it; the command does not check `auto_research` |
| `host register` | none | yes | no | meant for it; the command does not check `auto_research` |
| `recovery bump` | `--reason REASON` (required) | yes | no, it must be stopped | meant for it; the command does not check `auto_research` |
| `simulate` | none | no | no | builds its own DiAGRI runtime in a temporary directory |

No command creates a project, a research protocol or a research round, sets a project's call budget, or creates the first task of the orchestrator. An operator does these through the workbench routes; see [Run a research round](Run-a-Research-Round.md). Among the commands only `simulate` makes those calls, inside `_design_and_start` in [`runtime.py`](../../../src/growbridge/runtime.py).

## What each command does

| Command | What it does | What it prints |
| --- | --- | --- |
| `init` | Creates the configuration file with `initialize`: parent directory mode `0700`, file mode `0600`, 11 keys. See [Configuration reference](Configuration-Reference.md#what-initialize-writes). | `Configuration created: <path>` |
| `scan` | Scans for 8 seconds for Bluetooth devices whose name starts with `SF-`. It first creates `~/.local/share/spiderfarmer-growbridge` with mode `0700`. On macOS it builds and runs a native helper; elsewhere it uses `BleakScanner`. | A JSON list of objects with `name`, `address` and `rssi` |
| `serve` | Creates `data_dir` with mode `0700`, takes an exclusive lock on `daemon.lock` in it, sets logging to `INFO` and serves until stopped. Bridge-only mode: the bridge HTTP API on `127.0.0.1:<port>`. DiAGRI mode: see the next table. | Log lines |
| `mcp` | Runs the MCP server over stdio until the client closes it. Each tool calls the daemon on `127.0.0.1:<port>` with the token from the file. Bridge-only mode has 8 tools, DiAGRI mode 3. See [API reference](API-Reference.md#mcp-tools). | MCP protocol messages on standard output |
| `status` | Sends `GET /status` to the daemon. | The JSON reply, with the keys `health`, `data` and `system` |
| `dashboard` | Sends `POST /ui/session` to the daemon and builds the link `http://127.0.0.1:<port>/#session=<code>`. The code works once and expires after 60 seconds. Without `--no-open` it opens the link in a browser. | Without `--no-open`: `Dashboard opened. Connection link expires in 60 seconds.` With `--no-open`: the link |
| `operator add` | Asks twice for the secret without echo (`Operator secret: `, `Repeat secret: `) and stores the operator in `workflow.sqlite3` in `data_dir`. The secret is stored as a salted scrypt hash. The name is 1 to 64 characters, the secret 12 to 256. | `Operator added: <name>` |
| `host register` | Reads or creates `host_id` in `data_dir` (mode `0600`) and registers this machine as the write host of `device` in `control.sqlite3`. It opens no Bluetooth connection. Running it again on the registered host succeeds. | `Write host registered: <host id>` |
| `recovery bump` | Takes the daemon lock, builds the runtime without starting it, raises the recovery number by one, revokes every write right, voids queued actions, moves every stage that is not finished to `recovery_check` and voids its approvals. `REASON` is stored with the event. | `Recovery number is now <n>; confirm the safety config and review live stages` |
| `simulate` | Runs one short stage on the simulated AC5 with a simulated clock, in a temporary directory: approve the safety configuration, create project, protocol and round, submit and approve a run sheet, start the stage, tick until it ends. No radio and no network. | A JSON object with `stage`, `round`, `beats`, `samples` and `writes` |

### `serve` in DiAGRI mode

The steps are in `_serve_auto_research` and `_serve_listeners`.

| Order | Step |
| --- | --- |
| 1 | Reads `GROWBRIDGE_HEARTBEAT_HOST_URL` and `GROWBRIDGE_HEARTBEAT_RUN_URL`: one without the other stops the command here; neither means no heartbeat and a standing warning. Then builds the runtime with `build_runtime(settings, heartbeats=...)`. Also reads the compute settings (`compute_templates_dir`, `compute_member` and the seven `FIRECREST_*` variables) and passes the compute service only when all of them are present; a partial setup logs what is missing, a bad template stops the command here. |
| 2 | Reads the model-role tokens from `GROWBRIDGE_ROLE_TOKEN_<ROLE>` and builds the workbench routes. A token shorter than 32 characters stops the command here. |
| 3 | Starts the runtime. If this machine is not the registered write host, the Bluetooth connection stays closed and an alert is raised. |
| 4 | Starts the tick loop: `Runtime.tick()` once a second (`TICK_SECONDS`). |
| 5 | If `roles` is not empty and the model client can be built, starts the model roles: `Runtime.run_agents()` every 30 seconds (`AGENT_SECONDS`). Otherwise no model role runs. |
| 6 | Serves the bridge routes and the workbench routes on `127.0.0.1:<port>`, and also on `<lan_bind>:<lan_port>` when `lan_bind` and `lan_port` are both set. |

## Exit behavior

| Situation | Commands | Message | Exit code |
| --- | --- | --- | --- |
| Success | all | see the table above | 0 |
| Missing subcommand, unknown option, missing required argument | all | usage text and `growbridge: error: ...` | 2 |
| The configuration file is missing or does not pass `load` | all that read it | Python traceback (`FileNotFoundError`, `ValidationError`, `ValueError`, ...) | 1 |
| The configuration file already exists | `init` | traceback ending in `FileExistsError` | 1 |
| Another daemon holds the lock on `data_dir` | `serve` | `A daemon already owns this data directory` | 2 |
| A model-role token is shorter than 32 characters | `serve` in DiAGRI mode | `growbridge: the token of role '<role>' is shorter than 32 characters` | 1 |
| The daemon does not answer, or answers with an error | `status`, `dashboard` | traceback; for an error reply, `RuntimeError` with the daemon's `detail` | 1 |
| The secret is shorter than 12 characters | `operator add` | `the secret needs at least 12 characters` | 2 |
| The two entries of the secret differ | `operator add` | `the two entries differ` | 2 |
| The name is empty or too long, the secret is too long, or the operator exists | `operator add` | the `ValueError` text from `Operators.add` | 2 |
| Another host is registered for the device | `host register` | `another host is registered for this device` | 2 |
| A daemon is running on `data_dir` | `recovery bump` | `a daemon is running on this data directory; stop it first` | 2 |

Every command sets the process umask to `0o077` after parsing its arguments, so files it creates are private to the user.

`scan`, and `serve` against a real AC5, were not run for this page. Behavior on real hardware is not verified; see [Status and known limitations](Status-and-Known-Limitations.md).

## See also

- [Configuration reference](Configuration-Reference.md)
- [HTTP, workbench and MCP interfaces](API-Reference.md)
- [Installation and quick start](Installation-and-Quick-Start.md)
- [Enable DiAGRI](Enable-DiAGRI.md)
- [Troubleshooting runbook](Troubleshooting-Runbook.md)
