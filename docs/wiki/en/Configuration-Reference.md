# Configuration reference

[简体中文](../zh-CN/Configuration-Reference.md)

This page is for anyone who installs or operates DiAGRI. It lists every field of the configuration file, the checks made when the file is loaded, and the values that come from the environment and are never in the file.

The fields are `Settings` and `RoleModel` in [`config.py`](../../../src/growbridge/config.py). On this page "bridge-only mode" means `auto_research = false`, which is the default.

## The file

| Item | Value |
| --- | --- |
| Format | TOML |
| Default path | `~/.config/spiderfarmer-growbridge/config.toml`, from `default_config()` |
| Another path | `growbridge --config /absolute/path/to/config.toml <command>` |
| Read by | every command except `init`, `scan` and `simulate` (see [CLI reference](CLI-Reference.md)) |
| Unknown keys | refused: `Settings` and `RoleModel` both set `extra="forbid"` |

## `Settings` fields

There are 25 fields. "Required" means the field has no default. The last column says whether the field has an effect only in DiAGRI mode.

| Field | Type | Default | Allowed values | What it does | DiAGRI only |
| --- | --- | --- | --- | --- | --- |
| `device` | string | required | any string | Address or UUID of the AC5, as `growbridge scan` printed it on this machine. | no |
| `token` | string | required | at least 24 characters | Bearer token of the bridge HTTP API. The CLI and the MCP server read it from this file. In DiAGRI mode it can read and cannot write. | no |
| `data_dir` | path | required | any path; `~` is expanded | Directory for the databases, `daemon.lock` and `host_id`. | no |
| `port` | integer | `8766` | 1024 to 65535 | Port of the listener on `127.0.0.1`. In DiAGRI mode a request is on the overlay entry only if it arrived on this port. | no |
| `controls_enabled` | boolean | `false` | `true`, `false` | Allows writes to the device. While `false`, the bridge API answers 409 and the control service refuses with `controls_disabled`. | no |
| `stale_seconds` | number | `20` | 5 to 120 | Age in seconds after which the latest sample counts as stale (`health.stale`). Ordinary writes need fresh data. | no |
| `max_pump_seconds` | number | `5` | more than 0, at most 60 | Longest pump run in seconds, for `POST /pump` in bridge-only mode and `POST /wb/irrigation` in DiAGRI mode. | no |
| `pump_cooldown_seconds` | number | `60` | 0 or more | Shortest time in seconds between two pump runs. | no |
| `pump_outlet` | integer | `4` | 1 to 5 | Outlet the pump is plugged into. | no |
| `light_outlet` | integer | `1` | 1 to 5 | Outlet of the light. | no |
| `exhaust_outlet` | integer | `2` | 1 to 5 | Outlet of the exhaust fan. | no |
| `fan_outlet` | integer | `3` | 1 to 5 | Outlet of the circulation fan. | no |
| `retention_days` | integer | `30` | 1 to 365 | Days of samples the daemon's sample store keeps. In DiAGRI mode only samples already copied to the project archive are deleted. | no |
| `auto_research` | boolean | `false` | `true`, `false` | Switches the daemon to DiAGRI mode: the runtime and the workbench routes start, the three bridge write routes answer 403, and the MCP server offers its read tools only. | it is the switch |
| `lan_hosts` | list of strings | `[]` | host names or addresses; a port is ignored | Addresses of the LAN entry. They join the trusted hosts and the allowed browser origins. | yes |
| `overlay_hosts` | list of strings | `[]` | host names or addresses; a port is ignored | Addresses of the overlay entry. They join the trusted hosts and the allowed browser origins (as `https://`). | yes |
| `lan_bind` | string | `""` | an address of this machine | Address the LAN listener binds to. The listener starts only when `lan_bind` and `lan_port` are both set. | yes |
| `lan_port` | integer or unset | unset | 1024 to 65535 | Port of the LAN listener. A request is on the LAN entry only if it arrived on this port with a `Host` in `lan_hosts`. Unset means there is no LAN entry. | yes |
| `report_time` | string | `"08:00"` | 24-hour `HH:MM`, `00:00` to `23:59` | Local time from which the daily report of the day before is produced. A report is produced only while a stage is active. | yes |
| `report_timezone` | string | `"UTC"` | an IANA time zone name known to the host | Time zone of `report_time` and of the report dates. It is also the zone in which the operator console shows and takes times (served as `timezone` by `GET /wb/me`). An unknown name is refused on load. | yes |
| `roles` | table of `RoleModel` | `{}` | keys are role names | Model configuration of each model role. While it is empty, `serve` builds no model client and no model role runs. | yes |
| `backup_dir` | path or unset | unset | any path; `~` is expanded | Directory for the SQLite online backups. While unset there are no backups and the runtime raises a `backup_unconfigured` warning alert at start. | yes |
| `backup_interval_seconds` | number | `21600` | 60 or more | Seconds between two backups. | yes |
| `compute_templates_dir` | path or unset | unset | a directory holding `*.json` files; `~` is expanded | One reviewed job template (`JobTemplate`) per JSON file. With `compute_member` and the seven `FIRECREST_*` variables it turns the compute service on. Every file is validated at start; a bad one stops `serve` and the message names the file. | yes |
| `compute_member` | string or unset | unset | at least 1 character | The CSC account name under which the researcher role's jobs are submitted. | yes |

The exact pattern of `report_time` is:

```text
^([01]\d|2[0-3]):[0-5]\d$
```

A host that appears in both `lan_hosts` and `overlay_hosts` belongs to neither entry (`entry_for` in [`workbench/auth.py`](../../../src/growbridge/workbench/auth.py)).

## `RoleModel` fields

There are 9 fields. Each key of `roles` holds one `RoleModel`, written as a `[roles.<role>]` table. All of them matter in DiAGRI mode only.

| Field | Type | Default | Allowed values | What it does |
| --- | --- | --- | --- | --- |
| `provider` | string | `"anthropic"` | `"anthropic"` | Model provider. `AnthropicClient` is the only client in the code. |
| `model` | string | `"claude-opus-5-5"` | any string | Model name sent with every request of the role. Only the default model has a built-in price (`DEFAULT_PRICE` in [`agents/llm.py`](../../../src/growbridge/agents/llm.py)); any other model is refused on load unless `input_per_mtok` and `output_per_mtok` are set. |
| `effort` | string | `"medium"` | `low`, `medium`, `high`, `xhigh`, `max` | Sent with every request as `output_config.effort`. |
| `max_tokens` | integer | `16000` | 256 to 64000 | `max_tokens` of every request. |
| `max_calls` | integer | `20` | 1 or more | Most model calls in one run of the role (`max_turns` of `run_agent` in [`agents/loop.py`](../../../src/growbridge/agents/loop.py)). A run that reaches it stops with `max_turns` and its task moves to `needs_attention`. The project call budget ([`agents/budget.py`](../../../src/growbridge/agents/budget.py)) applies as well. |
| `tools` | list of strings | `[]` | tool names of the role (see [API reference](API-Reference.md#model-role-tools)) | Narrows the tools of the role. Empty means every tool the role may use. A control tool or a tool of another role is refused with `model_role` when the role runs, and the task moves to `needs_attention`. |
| `data` | list of strings | `[]` | any strings | Checked on load. No code reads it: it does not restrict what a role can read. |
| `input_per_mtok` | number or unset | unset | 0 or more | Price of `model` in USD per million input tokens, used for the cost budget. Set it together with `output_per_mtok`. Required when `model` is not the default model. |
| `output_per_mtok` | number or unset | unset | 0 or more | Price of `model` in USD per million output tokens. Set it together with `input_per_mtok`. |

Role names that are read are `orchestrator`, `planner` and `researcher` (`ROLE_TOOLS` in [`agents/tools.py`](../../../src/growbridge/agents/tools.py)). Other keys pass validation and are ignored. When `roles` has at least one key, a role that is not listed runs with the defaults above (`make_dispatcher` in [`runtime_agents.py`](../../../src/growbridge/runtime_agents.py)).

## Job template files

Each `*.json` file in `compute_templates_dir` is one `JobTemplate` ([`compute/backend.py`](../../../src/growbridge/compute/backend.py)). Every file is validated when `serve` starts, and the first bad one stops it with the file name. The rules:

| Field | Rule |
| --- | --- |
| `id`, `version` | A pair must be unique across the files. The newest version of an `id` is the one that runs; a retry of an attempt whose version has been replaced is refused. |
| `script` | A Slurm batch script. It must start with `#!`, must set a time limit (`#SBATCH --time=...` or `-t`) so that a job is bounded, and must not set its own job name (the service adds `gb-<attempt id>`). Parameters arrive only as `DIAGRI_PARAM_<NAME>`, inputs as `DIAGRI_INPUT_<NAME>`; results go to `DIAGRI_OUTPUT_DIR`. |
| `parameters` | A name must be usable in an environment variable name. `kind` is `int`, `float`, `str` or `bool`. A number may have `minimum` and `maximum`, and a float must be finite. A `str` must either list `choices` or declare a `pattern`: a regular expression that the whole value has to match. `max_length` shortens the allowed length; no text is longer than 1000 characters, and a value with a control character is always refused. A `default` must itself pass these rules. A parameter without a `default` is required. |
| `max_cpu_hours`, `max_storage_gb` | Finite numbers, 0 or more. They are what one attempt reserves and, when the API reports no usage, what it is charged. `max_storage_gb` (decimal gigabytes) is also the most that a fetch brings home: the outputs of a job may total at most that many bytes and at most 1000 files, or the fetch is refused before anything is downloaded; a download is watched and cancelled as soon as its file passes what is left of the limit, and what was downloaded is deleted (a little more than the limit can be on disk for a moment, at most what the link carries in 0.25 seconds). Every output must show its size in the FirecREST listing, or the fetch is refused. |
| `result_changing` | Names of parameters; each must exist. Changing one in a retry starts a new analysis version. |
| `max_retries` | Default 2. |

## What `load` checks

`load` runs for every command that reads the file. The CLI does not catch these errors, so the command ends with a traceback.

| Order | Check | Error when it fails |
| --- | --- | --- |
| 1 | The file exists at the given or default path (`~` expanded). | `FileNotFoundError` |
| 2 | The file is valid TOML. | `tomllib.TOMLDecodeError` |
| 3 | `data_dir` is present. | `KeyError` |
| 4 | Every field has the type, range and pattern in the tables above, and there is no unknown key. `report_timezone` is a known zone. A role on a model other than the default states both prices. | `pydantic.ValidationError` |
| 5 | `pump_outlet`, `light_outlet`, `exhaust_outlet` and `fan_outlet` are four different numbers. | `ValueError: Each device must have a separate outlet` |

Template files are not read by `load`; `serve` checks them at start. `load` does not check these: that `data_dir`, `backup_dir` or `compute_templates_dir` exist, that `lan_bind` and `lan_port` are set together, the role names in `roles`, and the tool names in `tools`.

## What `initialize` writes

`growbridge init --device DEVICE` calls `initialize`. It creates the parent directory with mode `0700` and the file with mode `0600`. It never overwrites: if the file exists it fails. It writes these 11 keys and no DiAGRI field.

| Key | Value written |
| --- | --- |
| `device` | the `--device` argument |
| `token` | a new random value from `secrets.token_urlsafe(32)` |
| `data_dir` | `~/.local/share/spiderfarmer-growbridge`, written as an absolute path |
| `controls_enabled` | `false`, or `true` with `--enable-controls` |
| `port` | `8766` |
| `max_pump_seconds` | `5` |
| `pump_cooldown_seconds` | `60` |
| `light_outlet` | `1` |
| `exhaust_outlet` | `2` |
| `fan_outlet` | `3` |
| `pump_outlet` | `4` |

## Values that are never in the file

Credentials are read from the environment of the `growbridge serve` process. All of them matter in DiAGRI mode only. Delivery to real Telegram and SMTP services has not been verified; see [Status and known limitations](Status-and-Known-Limitations.md).

| Variable | Read in | What it is | Rules |
| --- | --- | --- | --- |
| none named in the code | `AnthropicClient` in [`agents/llm.py`](../../../src/growbridge/agents/llm.py) | Model credentials | The client is built as `anthropic.AsyncAnthropic()` with no arguments, so the SDK resolves the credentials from its own environment variables. The tests set `ANTHROPIC_API_KEY`. The SDK is the optional extra `agents`. If the client cannot be built, `serve` logs a warning, raises a `model_client` alert and runs without model roles. |
| `GROWBRIDGE_ROLE_TOKEN_<ROLE>` | `role_tokens_from_env` in [`cli.py`](../../../src/growbridge/cli.py) | Bearer token with which a model role calls the workbench routes. The role id is the suffix in lower case. | At least 32 characters, or `serve` exits before it starts anything. An empty value is ignored. |
| `GROWBRIDGE_TELEGRAM_TOKEN` | `default_channels` in [`runtime.py`](../../../src/growbridge/runtime.py), `TelegramChannel` in [`observer/channels.py`](../../../src/growbridge/observer/channels.py) | Telegram bot token | The `telegram` channel exists only when this and `GROWBRIDGE_TELEGRAM_CHAT_IDS` are both set. |
| `GROWBRIDGE_TELEGRAM_CHAT_IDS` | `default_channels` | Chat ids that receive notifications | Comma-separated. |
| `GROWBRIDGE_EMAIL_TO` | `default_channels` | Recipients of e-mail notifications | Comma-separated. The `email` channel exists only when this and `GROWBRIDGE_SMTP_HOST` are both set. |
| `GROWBRIDGE_SMTP_HOST` | `default_channels`, `_smtp_send` in `observer/channels.py` | SMTP server | The connection always uses STARTTLS. |
| `GROWBRIDGE_SMTP_PORT` | `_smtp_send` | SMTP port | Default `587`. |
| `GROWBRIDGE_SMTP_USER` | `_smtp_send` | SMTP login name | No login when unset. |
| `GROWBRIDGE_SMTP_PASSWORD` | `_smtp_send` | SMTP password | Default empty. |
| `GROWBRIDGE_SMTP_FROM` | `_smtp_send` | `From` address | Default: the SMTP user, or `growbridge@localhost`. |
| `FIRECREST_URL` | `FirecrestBackend` in [`compute/firecrest.py`](../../../src/growbridge/compute/firecrest.py) | Base address of the FirecREST API, e.g. `https://api.roihu.csc.fi/v1` (FirecREST v2). | Part of the all-or-nothing compute setting: with any of the nine names missing (these seven, `compute_templates_dir`, `compute_member`) the compute service does not start and the log names what is missing, never a value. |
| `FIRECREST_TOKEN_URL` | `FirecrestBackend` in [`compute/firecrest.py`](../../../src/growbridge/compute/firecrest.py) | OAuth token endpoint of the robot account, e.g. `https://user-auth.csc.fi/idp/profile/oidc/token`. | Part of the all-or-nothing compute setting: with any of the nine names missing (these seven, `compute_templates_dir`, `compute_member`) the compute service does not start and the log names what is missing, never a value. |
| `FIRECREST_CLIENT_ID` | `FirecrestBackend` in [`compute/firecrest.py`](../../../src/growbridge/compute/firecrest.py) | Client id of the CSC robot account (the account name). | Part of the all-or-nothing compute setting: with any of the nine names missing (these seven, `compute_templates_dir`, `compute_member`) the compute service does not start and the log names what is missing, never a value. |
| `FIRECREST_CLIENT_SECRET` | `FirecrestBackend` in [`compute/firecrest.py`](../../../src/growbridge/compute/firecrest.py) | Client secret of the robot account (its password). Never logged, never in an error, not in `repr`. | Part of the all-or-nothing compute setting: with any of the nine names missing (these seven, `compute_templates_dir`, `compute_member`) the compute service does not start and the log names what is missing, never a value. |
| `FIRECREST_SYSTEM` | `FirecrestBackend` in [`compute/firecrest.py`](../../../src/growbridge/compute/firecrest.py) | The Roihu subsystem: only `cpu` or `gpu`. | Part of the all-or-nothing compute setting: with any of the nine names missing (these seven, `compute_templates_dir`, `compute_member`) the compute service does not start and the log names what is missing, never a value. |
| `FIRECREST_ACCOUNT` | `FirecrestBackend` in [`compute/firecrest.py`](../../../src/growbridge/compute/firecrest.py) | The CSC project the jobs are charged to, e.g. `project_2001234`. Letters, digits and `_` only. | Part of the all-or-nothing compute setting: with any of the nine names missing (these seven, `compute_templates_dir`, `compute_member`) the compute service does not start and the log names what is missing, never a value. |
| `FIRECREST_WORKDIR` | `FirecrestBackend` in [`compute/firecrest.py`](../../../src/growbridge/compute/firecrest.py) | Absolute remote directory under which each job gets its own `gb-<attempt id>` directory, e.g. `/scratch/project_2001234/diagri`. No `..`. | Part of the all-or-nothing compute setting: with any of the nine names missing (these seven, `compute_templates_dir`, `compute_member`) the compute service does not start and the log names what is missing, never a value. |

When neither channel is configured, no notification is queued. Alerts are still recorded and shown by `GET /wb/alerts`, and the runtime raises a `notify_unconfigured` warning alert at start (`build_runtime` and `Runtime.start` in [`runtime.py`](../../../src/growbridge/runtime.py)).

## Frozen-reading thresholds (`SafetyConfig.frozen`)

Not part of the settings file: the thresholds are a field of the approved safety configuration, `SafetyConfig.frozen`, a `FrozenCheck` in [`archive/models.py`](../../../src/growbridge/archive/models.py). A person approves them with the rest of the safety limits (`POST /wb/safety/approve`) and the workbench safety page shows them. The observer flags a sensor whose value stays exactly the same for longer than its threshold.

| Field | Type | Default | Validation | What it does |
| --- | --- | --- | --- | --- |
| `minutes` | dict of sensor name to number | `{"temp": 120, "humi": 60, "co2": 60, "tempSoil": 240}` (`DEFAULT_FROZEN_MINUTES`; every config gets its own copy) | Each value must be greater than 0 and at most 1440 (`0`, negative, NaN, infinity and anything above 1440 are refused). An empty dict is allowed and means no sensor is checked. At approval, a name the device does not have is refused (`approval_invalid`); the AC5 has `temp`, `humi`, `vpd`, `co2`, `ppfd` and `tempSoil`. A misspelt name therefore cannot switch a check off unnoticed. | Minutes a sensor may keep the same value before it counts as frozen. A sensor with no entry is not checked. |
| `max_gap_seconds` | number | `600` | Greater than 0 and at most 3600 (NaN, infinity and larger values are refused). | Longest gap between two readings that still counts as one unbroken run of the same value. |

When no safety configuration has been approved, the thresholds are the defaults above. A safety configuration stored before this field existed has no `frozen` key and loads with the defaults.

## What has no setting

| Feature | State in the code |
| --- | --- |
| External heartbeat (`ExternalMonitor`, `HeartbeatChannel`) | No `Settings` field; it is set by the environment variables `GROWBRIDGE_HEARTBEAT_HOST_URL` and `GROWBRIDGE_HEARTBEAT_RUN_URL`. Both or neither: one alone stops `serve`, neither raises the warning alert `monitor_unconfigured`. The URLs are secrets and are never logged. See [Notifications, daily reports and backup](Notifications-Reports-and-Backup.md). |
| Compute service (`ComputeService`) | Set by `compute_templates_dir`, `compute_member` and the seven `FIRECREST_*` environment variables, all or none. All set: `serve` builds the compute service over `FirecrestBackend`. None set: no compute service. Some set: no compute service and a warning in the log that names what is missing. A bad template, a missing `pyfirecrest` or an invalid `FIRECREST_SYSTEM`, `FIRECREST_ACCOUNT` or `FIRECREST_WORKDIR` stops `serve`. Not verified against the real CSC service; see [Status and known limitations](Status-and-Known-Limitations.md). |
| Alert rules | No `Settings` field. `DEFAULT_ALERT_RULES` in `runtime.py` is empty. |
| Operator accounts | Stored in `data_dir` by `growbridge operator add`, not in the file. |

## Examples

Minimal bridge-only configuration. Controls stay off.

```toml
device = "YOUR_SCANNED_ADDRESS"
token = "REPLACE_WITH_AT_LEAST_24_CHARACTERS"
data_dir = "/absolute/path/to/data"
```

Minimal DiAGRI configuration with both entries, backups and the three model roles on their defaults.

```toml
device = "YOUR_SCANNED_ADDRESS"
token = "REPLACE_WITH_AT_LEAST_24_CHARACTERS"
data_dir = "/absolute/path/to/data"
controls_enabled = true
auto_research = true
lan_hosts = ["YOUR_PI_LAN_ADDRESS"]
lan_bind = "YOUR_PI_LAN_ADDRESS"
lan_port = 8767
overlay_hosts = ["YOUR_PI_OVERLAY_NAME"]
backup_dir = "/absolute/path/to/backup"

[roles.orchestrator]

[roles.planner]

[roles.researcher]
```

## See also

- [CLI reference](CLI-Reference.md)
- [HTTP, workbench and MCP interfaces](API-Reference.md)
- [Enable DiAGRI](Enable-DiAGRI.md)
- [Notifications, daily reports and backup](Notifications-Reports-and-Backup.md)
- [Glossary](Glossary.md)
