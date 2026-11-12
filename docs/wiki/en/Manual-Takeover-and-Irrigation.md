# Manual takeover, irrigation and handback

[简体中文](../zh-CN/Manual-Takeover-and-Irrigation.md)

This page is for an operator who needs to take over a live stage, write to the device by hand, irrigate, and hand control back. It gives the request for each step, what comes back, and what to do when a request is refused.

> Tested on the simulated AC5 only. Nothing here has been run against a real pump or a real device. See [Status and known limitations](Status-and-Known-Limitations.md).

## Before you start

- You are logged in to the workbench and know how to send requests to it: see "What the workbench is" in [Run a research round](Run-a-Research-Round.md). The workbench has no web page.
- The stage is `running` or `paused`. Check with `GET /wb/stages/STAGE_ID`.
- For irrigation you are on site and logged in on the LAN entry (`http://YOUR_LAN_HOST:LAN_PORT`). A session from the overlay entry cannot irrigate.
- A manual write can reach only the channels the run sheet marks as host-controlled. To irrigate, `pump` must be one of them.

The reasons behind these rules are on [Control and safety model](Control-and-Safety-Model.md).

## 1. Re-authenticate

Takeover needs a re-authentication within the last 300 seconds. Login counts. If it was longer ago:

```http
POST /wb/reauth

{"secret": "YOUR_OPERATOR_SECRET"}
```

You should get `{"reauth_seconds": 300}`.

## 2. Take over

```http
POST /wb/stages/STAGE_ID/takeover
```

You should get `"state": "manual"`, a `manual_right` number, and `right_number` and `care_right` set to `null`.

What the system has done by then ([`workflow/service.py`](../../../src/growbridge/workflow/service.py), `takeover`):

- It read the device back to settle earlier writes with an unknown result, where that was possible.
- It revoked the stage write right and the care write right. Timed actions, feedback rules and care rules stop. Queued writes under those rights are voided.
- It granted a manual write right bound to your operator name. Another operator's manual writes are refused with `scope`.
- It recorded a `takeover` intervention for the experiment.

Protection rules keep running during a takeover, and sampling continues.

## 3. Write by hand

```http
POST /wb/manual/light

{"stage_id": "STAGE_ID", "request_id": "manual-0001", "level": 40, "note": "dim the lamp"}
```

| Field | Rule |
| --- | --- |
| channel (in the path) | `light`, `exhaust`, `fan` or `pump` |
| `level` | `light` and `exhaust` 0 to 100, `fan` 0 to 10, `pump` 0 only |
| `request_id` | 8 to 100 characters: letters, digits, `_` and `-`. Use a new one for every write. |
| `note` | Optional, up to 200 characters. It is stored as the trigger of the action. |

You should get the action record. Look at `state`:

| `state` | Meaning |
| --- | --- |
| `confirmed` | The device was read back and shows the level. |
| `failed` | The write was not sent, was rejected, or the read-back shows another level. Nothing is pending. You may write again with a new `request_id`. |
| `unknown` | The write may or may not have taken effect. Further manual writes are refused with `unsettled`. See "A write with result unknown" in the [Troubleshooting runbook](Troubleshooting-Runbook.md). |

Sending the same `request_id` with the same body again returns the first record and writes nothing. `GET /wb/receipts/REQUEST_ID` returns the record at any time. Manual writes work on both entries.

## 4. Irrigate

Irrigation is for operators only and is offered on the LAN entry only. It is the only path that switches the pump on: the executor never does, and `POST /wb/manual/pump` accepts level 0 only.

```http
POST /wb/irrigation

{"stage_id": "STAGE_ID", "request_id": "water-0001", "seconds": 2, "note": "tray 3"}
```

Limits, from [`workbench/api.py`](../../../src/growbridge/workbench/api.py) and [`control/service.py`](../../../src/growbridge/control/service.py):

| Limit | Value | When exceeded |
| --- | --- | --- |
| `seconds` in the request | more than 0, at most 60 | `422` |
| `seconds` against the configuration | at most `max_pump_seconds` (default 5) | `scope` |
| Time since the last irrigation started | at least `pump_cooldown_seconds` (default 60) | `cooldown` |
| Irrigations at the same time | one | `cooldown` |

The control service switches the pump on, waits `seconds`, switches it off and reads the off state back, trying twice. The request answers only after that, so it takes about as long as `seconds`. A handback, a stop or a protection write during the wait ends the wait early and the pump is switched off.

| `state` in the answer | Meaning |
| --- | --- |
| `confirmed` | The pump ran and pump-off was confirmed. |
| `failed` | The start failed: it was not sent, was rejected, or the read-back did not show the pump on. Pump-off was still sent and confirmed. |
| `unknown` | Either the start could not be confirmed, or pump-off could not: then `error` says `pump off unconfirmed; interlock set`. Go to the device and see "Pump-off unconfirmed" in the [Troubleshooting runbook](Troubleshooting-Runbook.md). |

## 5. Hand back

```http
POST /wb/stages/STAGE_ID/handback

{"accept_as_intervention": false}
```

The body is optional; the default is `false`. Handback needs no re-authentication.

You should get `{"stage": {...}, "differences": [...]}` with the stage in `running`. Each difference has `channel`, `field` (`level` or `mode`), `expected` and `actual`: it compares the device now with what the run sheet wants at this moment.

What the system does ([`workflow/service.py`](../../../src/growbridge/workflow/service.py), `handback`):

1. It reads the device first. If the device cannot be read, the request is refused with `not_connected` and the stage keeps its manual right.
2. It revokes the manual right and grants a new stage write right and care write right.
3. With `accept_as_intervention` set to `true` and at least one difference, it records the differences as an `accepted` intervention. With `false` nothing more is recorded.
4. The stage goes to `running`, also when it was `paused` before the takeover.

In both cases the executor brings every host-controlled channel back to the run sheet's level on its next tick. `accept_as_intervention` decides what is recorded, not what the device does next.

Any operator may hand a stage back, not only the one who took over.

## If the daemon restarts during a takeover

The stage goes to `recovery_check` and the manual right is void. Once the checks pass, the stage returns to `manual` with a new manual right for the same operator. See "Process restart" in the [Troubleshooting runbook](Troubleshooting-Runbook.md).

## Refusals and what to do

A refusal has the body `{"detail": {"code": "...", "message": "..."}}`.

| Code | Why | What to do |
| --- | --- | --- |
| `entry` | Irrigation was sent on the overlay entry, the session belongs to the other entry, or the `Origin` or `x-growbridge-ui` header is missing. | Go on site and log in on the LAN address. |
| `reauth_required` | Takeover without a recent re-authentication. | Step 1, then repeat. |
| `state` | The stage is not `running` or `paused` (takeover) or not `manual` (write, irrigation, handback), or it changed while the request ran. | Read the stage, then repeat or take over first. |
| `pump_on_forbidden` | `POST /wb/manual/pump` with a level other than 0. | Use `POST /wb/irrigation`. |
| `cooldown` | The last irrigation started less than `pump_cooldown_seconds` ago, or one is running. | Wait and send it again with a new `request_id`. |
| `scope` | `seconds` is above `max_pump_seconds`, the channel is not host-controlled in the run sheet, or another operator holds the manual right. | Shorten the run, or have the operator who took over send the request. |
| `interlock` | Pump-off is unconfirmed. Ordinary writes are blocked. | Check the pump on site. See the runbook. |
| `unsettled` | An earlier write has an unknown result, the old write path is not confirmed stopped, or the control service is still starting. | See "A write with result unknown" in the runbook. |
| `stale` | No fresh device telemetry within `stale_seconds` (default 20). | Wait for telemetry. If it does not return, treat it as a BLE outage. |
| `not_connected` | No live BLE connection, or the device state could not be read. | Wait for the reconnect, then repeat. |
| `right_invalid` | The manual right was revoked: the stage left `manual`, or the daemon restarted. | Read the stage. Take over again if it is not `manual`. |
| `right_held` | A stage write right is still active on the device. Takeover revokes the stage's own right first, so this is not expected through the workbench. | Read the stage and repeat once. If it stays, report it. |
| `request_id_reused` | The `request_id` was used before with other arguments. | Use a new `request_id`. |
| `controls_disabled` | `controls_enabled` is `false`. | Set it to `true` and restart `serve`. |
| `host_unregistered` | This machine is not the registered write host. | See [Enable DiAGRI](Enable-DiAGRI.md), step 3. |
| `session` | The session expired or the recovery number changed. | Log in again. |

A `422` means the body is malformed: an unknown channel, a level outside the range, `seconds` outside 0 to 60, or a `request_id` in the wrong form. All codes are listed in [Denial codes and stage events](Denial-Codes-and-Events.md).

## See also

- [Run a research round](Run-a-Research-Round.md)
- [Troubleshooting runbook](Troubleshooting-Runbook.md)
- [Control and safety model](Control-and-Safety-Model.md)
- [Denial codes and stage events](Denial-Codes-and-Events.md)
- [HTTP, workbench and MCP interfaces](API-Reference.md)
