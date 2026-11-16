# FAQ

[简体中文](../zh-CN/FAQ.md)

This page is for new users and new contributors. It answers the questions that come up first, in a few sentences each, and points to the page that has the detail.

## Safety and control

### Can a model switch the pump on, or change any other device setting?

No. The tools for stage and device control, `run_pump` and `set_light` among them, are listed in `CONTROL_TOOLS` and are removed from every model role's tool set ([`agents/tools.py`](../../../src/growbridge/agents/tools.py)). The pump has further guards: validation blocks a run sheet that would start it, and the executor refuses to switch it on. The pump starts only when an operator calls `/wb/irrigation` from the LAN entry during a manual takeover, for at most `max_pump_seconds`.

Detail: [Control and safety model](Control-and-Safety-Model.md), [Manual takeover, irrigation and handback](Manual-Takeover-and-Irrigation.md).

### What happens when the model API is down?

Device control goes on. The tick that runs the executor, the protection rules and the observer never calls a model, so an approved stage keeps running to its end ([`runtime.py`](../../../src/growbridge/runtime.py)). A research task whose model call fails moves to `needs_attention` with the reason and raises an alert; it does not run again by itself ([`agents/dispatch.py`](../../../src/growbridge/agents/dispatch.py)). If the model client cannot be built when the daemon starts, the daemon raises an alert and serves without model roles.

Detail: [The agents](The-Five-Agents.md), [Troubleshooting runbook](Troubleshooting-Runbook.md).

### Why do `set_light` and the dashboard controls stop working once DiAGRI is on?

That is intended. With `auto_research = true` the three bridge write endpoints answer 403 with `Device writes go through the workbench` ([`api.py`](../../../src/growbridge/api.py)), and the MCP server registers only its three read tools ([`mcp_server.py`](../../../src/growbridge/mcp_server.py)). A write by hand goes through `/wb/manual/{channel}` and needs a stage that is under manual takeover.

Detail: [Manual takeover, irrigation and handback](Manual-Takeover-and-Irrigation.md), [HTTP, workbench and MCP interfaces](API-Reference.md).

## Running it

### How do I turn DiAGRI off?

Set `auto_research = false` in `config.toml`, or remove the line, then restart `growbridge serve` and any MCP client. The daemon starts as the bridge-only mode: no runtime is built, the `/wb` routes are not mounted, and the bridge write endpoints and MCP write tools work again if `controls_enabled` is true ([`cli.py`](../../../src/growbridge/cli.py)). The DiAGRI databases stay in the data directory. Stop a running stage first, because in bridge-only mode nothing executes its run sheet, its care rules or its protection rules.

Detail: [Enable DiAGRI](Enable-DiAGRI.md), [Configuration reference](Configuration-Reference.md).

### Do I need a model API key?

Not for the bridge-only mode, for `growbridge simulate` or for the tests. In DiAGRI mode the model roles are optional: the daemon builds a model client only when `roles` is set in the configuration ([`cli.py`](../../../src/growbridge/cli.py)). The client needs the `agents` extra, installed with `pip install '.[agents]'`, and takes its credentials from the environment, never from `config.toml` ([`config.py`](../../../src/growbridge/config.py)).

Detail: [Enable DiAGRI](Enable-DiAGRI.md).

### Can I give it a research question today?

Yes, through the workbench routes: with the console page at `/workbench` or by hand. There is no command. An operator creates the project, the research protocol and the round, sets the model call budget and states the question with `POST /wb/goals`. [Run a research round](Run-a-Research-Round.md) lists the requests. The workbench is a set of HTTP routes under `/wb`, and the operator console at `/workbench` is its page. This path has run only in the tests in [`tests/e2e/`](../../../tests/e2e/), with a scripted model on the simulated AC5. What a real model does with the question has not been verified.

Detail: [Status and known limitations](Status-and-Known-Limitations.md).

### Has DiAGRI controlled a real tent? Can I try it without one?

It has not. DiAGRI has only run on the simulated AC5; the bridge-only mode is the part that has read and controlled a real AC5 ([VALIDATION.md](../../../VALIDATION.md)). To see DiAGRI work without hardware, run `growbridge simulate`, which needs no configuration, radio or network.

Detail: [Tutorial: a simulated research round](Tutorial-Simulated-Round.md), [Status and known limitations](Status-and-Known-Limitations.md).

### Does it run on Linux or a Raspberry Pi?

The code is written for both, but it has not been verified on a physical Raspberry Pi. On Linux the Bluetooth backend is Bleak on BlueZ ([`transport.py`](../../../src/growbridge/transport.py)), [`scripts/install_linux.py`](../../../scripts/install_linux.py) installs a systemd user service, and CI runs the test suite on `ubuntu-latest` against the simulated device. DiAGRI has one more limit outside macOS: there is no sandbox, so local analysis and the confirmatory analysis are refused with `sandbox_unavailable`.

Detail: [Status and known limitations](Status-and-Known-Limitations.md), and "Deploy on Raspberry Pi" in the [README](../../../README.md).

## Data and results

### Where is my data stored?

On the machine that runs the daemon, in two private places. The configuration, with the access token, is `~/.config/spiderfarmer-growbridge/config.toml`. Everything else is under `data_dir` from that file, which `init` sets to `~/.local/share/spiderfarmer-growbridge`: the bridge history `growbridge.sqlite3` and, in DiAGRI mode, one SQLite file per service (`control`, `workflow`, `archive`, `observer`, `compute`, `agents`) and the `archive/` folder with the snapshots ([`runtime.py`](../../../src/growbridge/runtime.py)). Copies of the six databases go to `backup_dir` when it is set.

Two features that you configure send data elsewhere: a model role sends what it reads to the model provider, and a notification channel sends alert and report text to Telegram or to your mail server.

Detail: [Data, archive and traceability](Data-Archive-and-Traceability.md), [Notifications, daily reports and backup](Notifications-Reports-and-Backup.md).

### What does a conclusion of `uncertain` mean?

It means the experiment could not decide the question. It does not mean the treatment has no effect. `conclusion()` in [`research/analysis.py`](../../../src/growbridge/research/analysis.py) returns `uncertain` when the round stopped early or reached fewer samples than planned, when the effect cannot be estimated, or when there are too few blocks for the test to reach the significance level at all. With the default level of 0.05 the last case means fewer than six blocks. In every other case the result is `supported` or `not_supported`.

Detail: [Research methodology](Research-Methodology.md).

## The project

### Why are the package and the command called `growbridge` when the project is DiAGRI?

DiAGRI is the project, and the repository is named after it. GrowBridge is one part of it: the device bridge that talks to the Spider Farmer AC5. The bridge was written first, so the Python package (`spiderfarmer-growbridge` in [`pyproject.toml`](../../../pyproject.toml)), the import name and the command (`growbridge`), and the configuration directory (`~/.config/spiderfarmer-growbridge`) carry its name, and the rest of DiAGRI lives in sub-packages of `growbridge`. So you clone `diagri` and `cd diagri`, and from then on every command is `growbridge`.

Detail: [Installation and quick start](Installation-and-Quick-Start.md).

### What should I run before I send a change?

The same checks as CI ([`ci.yml`](../../../.github/workflows/ci.yml)):

```sh
.venv/bin/ruff check src tests scripts
.venv/bin/ruff format --check src tests scripts
.venv/bin/pytest -q
```

They need the `dev` extra. Every test uses the simulated device, so the suite never touches a radio or a real AC5.

Detail: [Development setup, testing and CI](Development-Setup-Testing-and-CI.md), [Contributing](Contributing.md).

## See also

- [Overview](Overview.md)
- [Glossary](Glossary.md)
- [Status and known limitations](Status-and-Known-Limitations.md)
- [Troubleshooting runbook](Troubleshooting-Runbook.md)
