# Installation and quick start

[简体中文](../zh-CN/Installation-and-Quick-Start.md)

This page is for a new user who has an AC5 nearby. It gives the shortest path from a fresh clone to live readings in the bridge-only mode. If you have no hardware, go to [Tutorial: a simulated research round](Tutorial-Simulated-Round.md) instead.

The [README](../../../README.md) covers the same ground in more detail: the dashboard, MCP clients, running in the background and Raspberry Pi deployment. This page does not repeat it. Every command below is defined in [`cli.py`](../../../src/growbridge/cli.py).

> **Not verified on a Raspberry Pi.** These steps have been carried out on macOS with one AC5 (advertised as SF-GGS-PS5, firmware 3.2, plaintext protocol v1). The Linux path is in the code and in the README, but it has not been run against a real AC5 from a Raspberry Pi. See [Status and known limitations](Status-and-Known-Limitations.md).

## Before you start

- Python 3.11 or newer (`requires-python` in [`pyproject.toml`](../../../pyproject.toml)).
- On macOS: Xcode Command Line Tools. The first scan compiles a small Swift helper with `xcrun swiftc` and signs it ([`transport.py`](../../../src/growbridge/transport.py)).
- On Linux: BlueZ and the system D-Bus. The Linux backend uses Bleak.
- The AC5 switched on and within Bluetooth range of the machine.

## 1. Install

```sh
git clone https://github.com/kirinhcl/diagri.git
cd diagri
python3 -m venv .venv
.venv/bin/python -m pip install -c constraints-tested.txt .
.venv/bin/growbridge --version
```

The last command prints the installed version, which shows that the `growbridge` command is in place. The repository is named `diagri`, while the package and the command are `growbridge`; the [FAQ](FAQ.md) says why.

## 2. Find the AC5

```sh
.venv/bin/growbridge scan
```

The command prints a JSON list of the Spider Farmer devices it can see. On macOS the first run builds the `GrowBridge BLE` helper, and the system asks whether it may use Bluetooth: allow it. Copy the address of your AC5 from the output.

An address is valid only on the machine that scanned it. A device UUID found on macOS cannot be used on Linux, so scan again on each machine.

## 3. Create the configuration

```sh
.venv/bin/growbridge init --device YOUR_SCANNED_ADDRESS
```

`init` writes a private configuration file, by default `~/.config/spiderfarmer-growbridge/config.toml`, with a newly generated access token, and prints the path. It does not overwrite an existing file.

Controls are off after `init`: the daemon only reads. To allow writes from the start, add `--enable-controls`. You can also set `controls_enabled = true` in the file later and restart the daemon. Check your wiring against the outlet table in the [README](../../../README.md) before you do either.

To keep the file somewhere else, put `--config /absolute/path/to/config.toml` before the subcommand, on this command and on every later one.

## 4. Start the daemon

```sh
.venv/bin/growbridge serve
```

Leave it running. It connects to the AC5 and serves the local API on `127.0.0.1`, port 8766 by default. Only one daemon can own a data directory: a second `serve` stops with `A daemon already owns this data directory`.

## 5. Read the tent

In another terminal:

```sh
.venv/bin/growbridge status
```

The output is JSON with three keys ([`service.py`](../../../src/growbridge/service.py)):

| Key | Content |
| --- | --- |
| `health` | `connected`, `stale`, `age_seconds`, `last_sample_at`, `protocol_version`, `controls_enabled`, `pump_off_unconfirmed`, `last_error`, `outlet_mapping` |
| `data` | The latest sensor readings and the states of the outlets and devices |
| `system` | System information reported by the controller |

The installation works when `health.connected` is `true` and `health.stale` is `false`.

Then open the dashboard:

```sh
.venv/bin/growbridge dashboard
```

It opens the browser with a one-use link that expires after 60 seconds. With `--no-open` it prints the link instead of opening a browser.

## If a step fails

| What you see | What it means |
| --- | --- |
| `init` fails because the file exists | A configuration is already there. `init` never overwrites it. Edit the file, or pass another path with `--config`. |
| `serve` stops with `A daemon already owns this data directory` | Another daemon is running on the same data directory. Use that one, or stop it first. |
| `status` cannot connect | The daemon is not running, or it uses another configuration file than the one `status` reads. |
| `health.stale` is `true` | No fresh reading arrived within `stale_seconds` (20 by default), or Bluetooth is not connected. Look at `health.last_error`. |

## What to do next

| If you want to | Go to |
| --- | --- |
| let an MCP client read and control the tent | "Connect Codex or another MCP client" in the [README](../../../README.md). The command is `growbridge mcp`. |
| keep the daemon running in the background | "Run in the background on macOS" and "Deploy on Raspberry Pi" in the [README](../../../README.md) |
| see every setting | [Configuration reference](Configuration-Reference.md) |
| see every command | [CLI reference](CLI-Reference.md) |
| try DiAGRI without hardware | [Tutorial: a simulated research round](Tutorial-Simulated-Round.md) |
| switch DiAGRI on for this tent | [Enable DiAGRI](Enable-DiAGRI.md) |

## See also

- [Overview](Overview.md)
- [README](../../../README.md) and [VALIDATION.md](../../../VALIDATION.md)
- [Status and known limitations](Status-and-Known-Limitations.md)
- [FAQ](FAQ.md)
