# 安装与快速开始

[English](../en/Installation-and-Quick-Start.md)

这一页写给手边有 AC5 的新用户，给出从克隆仓库到在仅桥接模式下读到实时数据的最短路径。手边没有硬件的话，请直接看[教程：在模拟器上跑通一轮研究](Tutorial-Simulated-Round.md)。

[README](../../../README.zh-CN.md) 对同样的内容讲得更细，包括控制台、MCP 客户端、后台运行和树莓派部署。本页不重复这些内容。下面用到的每个命令都定义在 [`cli.py`](../../../src/growbridge/cli.py) 里。

> **树莓派上未验证。** 这些步骤在 macOS 上对一台 AC5（广播名称 SF-GGS-PS5、固件 3.2、明文协议 v1）实际走通过。Linux 这条路径在代码和 README 里都有，但还没有在树莓派上连过真实的 AC5。见[状态与已知限制](Status-and-Known-Limitations.md)。

## 开始之前

- Python 3.11 或更高版本（[`pyproject.toml`](../../../pyproject.toml) 里的 `requires-python`）。
- macOS：需要 Xcode 命令行工具。第一次扫描时会用 `xcrun swiftc` 编译一个很小的 Swift 辅助程序并签名（见 [`transport.py`](../../../src/growbridge/transport.py)）。
- Linux：需要 BlueZ 和系统 D-Bus。Linux 后端使用 Bleak。
- AC5 已通电，并且在这台机器的蓝牙范围内。

## 1. 安装

```sh
git clone https://github.com/kirinhcl/diagri.git
cd diagri
python3 -m venv .venv
.venv/bin/python -m pip install -c constraints-tested.txt .
.venv/bin/growbridge --version
```

最后一条命令会打印已安装的版本号，说明 `growbridge` 命令已经可用。仓库名是 `diagri`，软件包和命令却叫 `growbridge`，原因见[常见问题](FAQ.md)。

## 2. 找到 AC5

```sh
.venv/bin/growbridge scan
```

命令以 JSON 列表的形式打印它能扫到的 Spider Farmer 设备。在 macOS 上，第一次运行会构建 `GrowBridge BLE` 辅助程序，系统会询问是否允许它使用蓝牙，请选择允许。从输出里记下你那台 AC5 的地址。

地址只在扫描它的那台机器上有效。macOS 上得到的设备 UUID 不能拿到 Linux 上用，换一台机器就要重新扫描。

## 3. 创建配置

```sh
.venv/bin/growbridge init --device YOUR_SCANNED_ADDRESS
```

`init` 会写入一份私有配置文件，默认位置是 `~/.config/spiderfarmer-growbridge/config.toml`，里面带一个新生成的访问令牌，并打印文件路径。已有的配置文件不会被覆盖。

`init` 之后控制功能是关闭的，程序只读不写。想一开始就允许写入，加上 `--enable-controls`；也可以之后在配置文件里设置 `controls_enabled = true` 再重启程序。无论哪种做法，先对照 [README](../../../README.zh-CN.md) 里的插座对应表核对接线。

如果想把配置文件放在别处，在子命令**之前**加上 `--config /absolute/path/to/config.toml`，这条命令和之后的每条命令都要带上。

## 4. 启动常驻服务

```sh
.venv/bin/growbridge serve
```

让它一直运行。它会连接 AC5，并在 `127.0.0.1` 上提供本地接口，默认端口是 8766。一个数据目录只能由一个常驻服务占用：再启动一个 `serve` 会报 `A daemon already owns this data directory` 并退出。

## 5. 读取帐篷状态

另开一个终端：

```sh
.venv/bin/growbridge status
```

输出是 JSON，有三个键（见 [`service.py`](../../../src/growbridge/service.py)）：

| 键 | 内容 |
| --- | --- |
| `health` | `connected`、`stale`、`age_seconds`、`last_sample_at`、`protocol_version`、`controls_enabled`、`pump_off_unconfirmed`、`last_error`、`outlet_mapping` |
| `data` | 最新的传感器读数，以及各插座和设备的状态 |
| `system` | 控制器上报的系统信息 |

`health.connected` 为 `true` 且 `health.stale` 为 `false`，就说明安装已经可用。

接着打开控制台：

```sh
.venv/bin/growbridge dashboard
```

它会用一个一次性链接打开浏览器，链接 60 秒后失效。加上 `--no-open` 则只打印链接，不打开浏览器。

## 某一步不成功时

| 现象 | 含义 |
| --- | --- |
| `init` 因文件已存在而失败 | 配置已经存在，`init` 不会覆盖它。直接编辑这个文件，或用 `--config` 指定另一个路径。 |
| `serve` 报 `A daemon already owns this data directory` 后退出 | 同一个数据目录上已经有一个常驻服务在运行。直接用它，或先把它停掉。 |
| `status` 连不上 | 常驻服务没有运行，或者它用的配置文件和 `status` 读取的不是同一份。 |
| `health.stale` 为 `true` | 在 `stale_seconds`（默认 20 秒）内没有收到新读数，或者蓝牙没有连上。看 `health.last_error`。 |

## 接下来做什么

| 如果你想 | 请看 |
| --- | --- |
| 让 MCP 客户端读取和控制帐篷 | [README](../../../README.zh-CN.md) 的「接入 Codex / MCP 客户端」一节。命令是 `growbridge mcp`。 |
| 让服务在后台一直运行 | [README](../../../README.zh-CN.md) 的「Mac 后台运行」和「树莓派部署」两节 |
| 查看全部配置项 | [配置参考](Configuration-Reference.md) |
| 查看全部命令 | [CLI 参考](CLI-Reference.md) |
| 不接硬件试用 DiAGRI | [教程：在模拟器上跑通一轮研究](Tutorial-Simulated-Round.md) |
| 在这顶帐篷上启用 DiAGRI | [启用 DiAGRI](Enable-DiAGRI.md) |

## 另见

- [项目概览](Overview.md)
- [README](../../../README.zh-CN.md) 和 [VALIDATION.md](../../../VALIDATION.md)
- [状态与已知限制](Status-and-Known-Limitations.md)
- [常见问题](FAQ.md)
