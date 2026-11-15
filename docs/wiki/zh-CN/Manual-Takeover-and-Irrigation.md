# 人工接管、灌溉与交还

[English](../en/Manual-Takeover-and-Irrigation.md)

这一页写给需要接管一个进行中的阶段、手动写设备、灌溉，再把控制权交还的操作员。每一步都给出请求、返回内容，以及请求被拒绝时怎么办。

> 只在模拟的 AC5 上测试过。这里的内容没有在真实水泵或真实设备上跑过。见[状态与已知限制](Status-and-Known-Limitations.md)。

## 开始之前

- 已经登录工作台，并且知道怎么给它发请求：见[运行一轮研究](Run-a-Research-Round.md)里的“工作台是什么”。`/workbench` 的控制台用按钮完成同样的步骤。
- 阶段处于 `running` 或 `paused`。用 `GET /wb/stages/STAGE_ID` 确认。
- 要灌溉的话，人在现场，并且是从局域网入口（`http://YOUR_LAN_HOST:LAN_PORT`）登录的。覆盖网络入口的会话不能灌溉。
- 人工写入只能动运行单里标为主机控制的通道。要灌溉，`pump` 必须是其中之一。

这些规则背后的理由见[控制与安全模型](Control-and-Safety-Model.md)。

## 1. 重新认证

接管要求最近 300 秒内重新认证过。登录本身算一次。超过了就先发：

```http
POST /wb/reauth

{"secret": "YOUR_OPERATOR_SECRET"}
```

应该得到 `{"reauth_seconds": 300}`。

## 2. 接管

```http
POST /wb/stages/STAGE_ID/takeover
```

应该得到 `"state": "manual"` 和一个 `manual_right` 编号，`right_number` 和 `care_right` 都是 `null`。

到这时系统已经做了这些事（[`workflow/service.py`](../../../src/growbridge/workflow/service.py) 的 `takeover`）：

- 回读设备，把之前结果未知的写入尽量核对清楚。
- 撤销阶段写入权和养护写入权。定时动作、反馈规则和养护规则停止，这两个写入权下排队的写入作废。
- 授予一个绑定到你这个操作员名字的人工写入权。别的操作员发的人工写入会被拒绝，拒绝码 `scope`。
- 为这个实验记录一条 `takeover` 人工干预。

接管期间保护规则照常执行，采样也继续。

## 3. 手动写入

```http
POST /wb/manual/light

{"stage_id": "STAGE_ID", "request_id": "manual-0001", "level": 40, "note": "dim the lamp"}
```

| 字段 | 规则 |
| --- | --- |
| 通道（写在路径里） | `light`、`exhaust`、`fan` 或 `pump` |
| `level` | `light` 和 `exhaust` 为 0 到 100，`fan` 为 0 到 10，`pump` 只能是 0 |
| `request_id` | 8 到 100 个字符，只能用字母、数字、`_` 和 `-`。每次写入用一个新的。 |
| `note` | 可选，最多 200 个字符。它会作为这次动作的触发依据保存下来。 |

返回的是动作记录，看其中的 `state`：

| `state` | 含义 |
| --- | --- |
| `confirmed` | 已回读设备，档位和写入的一致。 |
| `failed` | 写入没有发出、被设备拒绝，或者回读到的是别的档位。没有遗留问题，可以换一个 `request_id` 再写。 |
| `unknown` | 写入可能生效了，也可能没有。之后的人工写入会被拒绝，拒绝码 `unsettled`。见[故障处理手册](Troubleshooting-Runbook.md)里的“写入结果未知”。 |

用同一个 `request_id` 和同样的请求体再发一次，返回的是第一次的记录，不会再写设备。`GET /wb/receipts/REQUEST_ID` 随时可以取回这条记录。人工写入在两个入口都能用。

## 4. 灌溉

灌溉只有操作员能做，而且只在局域网入口提供。它是唯一能开泵的途径：执行 Agent 从不开泵，`POST /wb/manual/pump` 也只接受 0。

> **运行单计划好的浇水不需要接管。** 运行单里有带 `seconds` 的浇水任务时，在阶段页的**人工任务**里启动（`POST /wb/stages/STAGE_ID/manual-tasks/irrigate`，同样只在局域网入口），阶段继续运行。接管会被记为干预，在报告里算作方案偏离；计划内浇水则记为该任务已完成（被截断或没有得到确认时记为部分完成）。见[运行一轮研究](Run-a-Research-Round.md)。

```http
POST /wb/irrigation

{"stage_id": "STAGE_ID", "request_id": "water-0001", "seconds": 2, "note": "tray 3"}
```

限制来自 [`workbench/api.py`](../../../src/growbridge/workbench/api.py) 和 [`control/service.py`](../../../src/growbridge/control/service.py)：

| 限制 | 取值 | 超出时 |
| --- | --- | --- |
| 请求里的 `seconds` | 大于 0，不超过 60 | `422` |
| `seconds` 对照配置 | 不超过 `max_pump_seconds`（默认 5） | `scope` |
| 距离上一次灌溉开始的时间 | 不少于 `pump_cooldown_seconds`（默认 60） | `cooldown` |
| 同时进行的灌溉 | 一次 | `cooldown` |

控制服务开泵，等待 `seconds` 秒，关泵，再回读关闭状态，最多尝试两次。这些都做完请求才返回，所以请求耗时大致等于 `seconds`。等待期间如果发生交还、停止或保护规则写入，等待会提前结束，水泵随即关闭。

| 返回的 `state` | 含义 |
| --- | --- |
| `confirmed` | 水泵运行过，并且关泵已确认。 |
| `failed` | 开泵失败：指令没有发出、被拒绝，或者回读没有显示水泵已开。关泵指令仍然发出并得到确认。 |
| `unknown` | 要么开泵无法确认，要么关泵无法确认；后一种情况下 `error` 是 `pump off unconfirmed; interlock set`。到设备跟前去，并查看[故障处理手册](Troubleshooting-Runbook.md)里的“关泵未确认”。 |

## 5. 交还

```http
POST /wb/stages/STAGE_ID/handback

{"accept_as_intervention": false}
```

请求体可以不带，默认是 `false`。交还不需要重新认证。

应该得到 `{"stage": {...}, "differences": [...]}`，阶段处于 `running`。每条差异包含 `channel`、`field`（`level` 或 `mode`）、`expected` 和 `actual`：比较的是设备此刻的状态和运行单在当前时点的目标。

系统做的事（[`workflow/service.py`](../../../src/growbridge/workflow/service.py) 的 `handback`）：

1. 先读设备。读不到时请求被拒绝，拒绝码 `not_connected`，阶段保留人工写入权。
2. 撤销人工写入权，授予新的阶段写入权和养护写入权。
3. `accept_as_intervention` 为 `true` 并且至少有一条差异时，把这些差异记成一条 `accepted` 人工干预。为 `false` 时不再多记什么。
4. 阶段进入 `running`。接管之前是 `paused` 的阶段也一样。

两种情况下，执行 Agent 都会在下一次评估时把每个主机控制的通道调回运行单规定的档位。`accept_as_intervention` 决定的是记录什么，不是设备接下来怎么动。

任何操作员都可以交还，不限于发起接管的那一位。

## 接管期间守护进程重启了

阶段进入 `recovery_check`，人工写入权作废。各项核对通过后，阶段回到 `manual`，并给原来那位操作员发一个新的人工写入权。见[故障处理手册](Troubleshooting-Runbook.md)里的“进程重启”。

## 拒绝码与处理办法

被拒绝时响应体是 `{"detail": {"code": "...", "message": "..."}}`。

| 拒绝码 | 原因 | 怎么办 |
| --- | --- | --- |
| `entry` | 灌溉请求是从覆盖网络入口发的，会话属于另一个入口，或者缺少 `Origin` 或 `x-growbridge-ui` 请求头。 | 到现场，从局域网地址登录。 |
| `reauth_required` | 接管前没有近期的重新认证。 | 做第 1 步，再重发。 |
| `state` | 阶段不是 `running` 或 `paused`（接管时），或者不是 `manual`（写入、灌溉、交还时），或者请求处理期间阶段变了。 | 读一下阶段，再重发，或者先接管。 |
| `pump_on_forbidden` | `POST /wb/manual/pump` 的档位不是 0。 | 改用 `POST /wb/irrigation`。 |
| `cooldown` | 上一次灌溉开始还不到 `pump_cooldown_seconds` 秒，或者有一次灌溉正在进行。 | 等一等，换一个 `request_id` 再发。 |
| `scope` | `seconds` 超过了 `max_pump_seconds`，通道在运行单里不是主机控制的，或者人工写入权在另一位操作员手里。 | 缩短时长，或者让发起接管的操作员来发请求。 |
| `interlock` | 关泵未确认，普通写入被阻止。 | 到现场检查水泵。见手册。 |
| `unsettled` | 之前有一次写入结果未知，旧的写入通路还没确认停止，或者控制服务还没启动完。 | 见手册里的“写入结果未知”。 |
| `stale` | `stale_seconds`（默认 20）秒内没有新的设备遥测。 | 等遥测恢复。一直不恢复就按 BLE 中断处理。 |
| `not_connected` | BLE 没连上，或者读不到设备状态。 | 等重连，然后重发。 |
| `right_invalid` | 人工写入权已被撤销：阶段已经离开 `manual`，或者守护进程重启过。 | 读一下阶段。不是 `manual` 就重新接管。 |
| `right_held` | 设备上还有一个有效的阶段写入权。接管会先撤销本阶段自己的阶段写入权，所以经工作台操作时不应该遇到。 | 读一下阶段，重发一次。还是这样就上报。 |
| `request_id_reused` | 这个 `request_id` 以前用过，参数不一样。 | 换一个 `request_id`。 |
| `controls_disabled` | `controls_enabled` 是 `false`。 | 改成 `true`，重启 `serve`。 |
| `host_unregistered` | 这台机器不是登记的写入主机。 | 见[启用 DiAGRI](Enable-DiAGRI.md)第 3 步。 |
| `session` | 会话过期，或者恢复编号变了。 | 重新登录。 |

`422` 表示请求体不合格：通道不存在、档位超出范围、`seconds` 不在 0 到 60 之间，或者 `request_id` 格式不对。全部拒绝码见[拒绝码与事件类型](Denial-Codes-and-Events.md)。

## 另见

- [运行一轮研究](Run-a-Research-Round.md)
- [故障处理手册](Troubleshooting-Runbook.md)
- [控制与安全模型](Control-and-Safety-Model.md)
- [拒绝码与事件类型](Denial-Codes-and-Events.md)
- [HTTP、工作台与 MCP 接口](API-Reference.md)
