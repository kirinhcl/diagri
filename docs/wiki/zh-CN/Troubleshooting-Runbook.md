# 故障处理手册

[English](../en/Troubleshooting-Runbook.md)

这一页写给遇到“阶段不再按运行单执行”的操作员。每一节讲一种故障：你会看到什么，系统已经自己做了什么，你需要做什么。

> 只在模拟的 AC5 上测试过。涉及真实设备、树莓派或主机时钟的步骤都没有验证。见[状态与已知限制](Status-and-Known-Limitations.md)。

## 先看哪里

| 看什么 | 用什么看 |
| --- | --- |
| 阶段：`state`、`prior_state`、`paused_at` 和三个写入权 | `GET /wb/stages/STAGE_ID` |
| 未解决的告警，其中包括阶段为什么在等待（`stage_waiting`） | `GET /wb/alerts` |
| 某一次写入 | `GET /wb/receipts/REQUEST_ID` |
| 设备 | `.venv/bin/growbridge status` |
| CSC 上的计算作业：余额、预算、进行中和卡住的尝试 | `GET /wb/compute` |
| 守护进程日志 | `serve` 所在的终端或服务日志 |

怎么给工作台发请求，见[运行一轮研究](Run-a-Research-Round.md)。

**暂停的原因写在告警里。** 阶段被系统暂停或被系统送进恢复待核对时，会产生告警 `stage_waiting`，并通过已配置的渠道发出。告警消息写明阶段、状态、事件以及事件携带的内容，例如：

```text
Stage STAGE_ID is paused after external_change: {"differences": [{"actual": 5, "channel": "light", "expected": 60, "field": "level"}]}
```

`recovery_check` 的告警级别是 `critical`，`paused` 是 `warning`。阶段离开这个状态时告警自动解除。操作员自己要求的暂停不产生告警（[`runtime.py`](../../../src/growbridge/runtime.py) 的 `_stage_alerts`）。

工作台仍然既不返回阶段历史，也不返回事件。这两样都在数据目录的 `workflow.sqlite3` 里：`wf_history` 记录每一次状态变化和对应的事件名，事件携带的内容记在 `detail` 列；`wf_events` 记录每一个事件 ID（表结构见 [`workflow/store.py`](../../../src/growbridge/workflow/store.py)）。只读查询可以看到一个阶段的历史。这是产品之外的变通办法，未验证：

```sh
sqlite3 -readonly /absolute/path/to/data_dir/workflow.sqlite3 \
  "SELECT datetime(at,'unixepoch'), from_state, to_state, event, detail FROM wf_history
   WHERE stage_id='STAGE_ID' ORDER BY id DESC LIMIT 5;"
```

事件名就是 [`ports.py`](../../../src/growbridge/ports.py) 里 `StageEventKind` 的取值。处理逻辑在 [`executor/engine.py`](../../../src/growbridge/executor/engine.py) 和 [`workflow/service.py`](../../../src/growbridge/workflow/service.py) 里；这样设计的理由见[控制与安全模型](Control-and-Safety-Model.md)和[工作流与状态机](Workflow-and-State-Machines.md)。

## 所有暂停的共同点

系统把一个 `running` 的阶段暂停时，会撤销阶段写入权，并作废它名下排队的写入。阶段保留养护写入权，所以养护规则继续执行，保护规则也继续执行。阶段不会自己恢复。

要继续，先重新认证，再发 `POST /wb/stages/STAGE_ID/resume`。下列情况下续跑会被拒绝：

| 拒绝码与提示 | 怎么办 |
| --- | --- |
| `state`，`actions with unknown results must be settled first` | 见“写入结果未知”。 |
| `state`，`device differs from the run sheet: ...` | 先接管再交还：`POST .../takeover`，然后 `POST .../handback`。响应会列出差异，之后执行 Agent 把各通道调回运行单的设定。见[人工接管、灌溉与交还](Manual-Takeover-and-Irrigation.md)。 |
| `interlock` | 见“关泵未确认”。 |
| `approval_invalid` | 审批已经对不上了，例如设备能力变了。暂停中的阶段不能重新审批，切换运行单又**无路由**。能对这个阶段发的请求只剩 `stop`。之后用 `POST /wb/rounds/ROUND_ID/choice` 选 `redo` 并提交新的运行单，或者中止轮次，见[运行一轮研究](Run-a-Research-Round.md)。 |
| `not_connected` | 读不到设备状态。等连接恢复。 |

阶段暂停的时间超过运行单的 `max_wait_seconds`，会收到事件 `max_wait_expired`。运行单里 `on_expiry = "stop"` 时阶段变成 `stopped`，否则保持 `paused`。

## 阶段执行中 BLE 断连

**你会看到。** 连接断开期间，阶段仍然是 `running`。数据足够旧之后，`GET /wb/alerts` 里出现 `run_health`，消息里点名 `growbridge_response` 和 `capture`。连接恢复后，阶段要么仍是 `running`，要么是 `paused`，事件为 `disconnect_affects`。

**系统已经做了。** 自己重连，不重放任何指令。离线期间没有为这个阶段写入任何东西。连接恢复后的第一次评估检查四件事：中断期间运行单里有档位变化到期（`due_action`）；设备状态和已写入的不一致，或者读不到（`device_differs`）；有写入结果未知（`unknown_result`）；中断时间超过运行单的 `sampling.max_gap_seconds`（`gap_too_long`）。任何一条成立，阶段就被暂停。都不成立，记下这段缺口，阶段继续。

**你要做的。** 阶段是 `running` 就什么都不用做。是 `paused` 就检查设备，然后续跑。连接一直不恢复，到现场检查 AC5 和主机到它的距离。断连期间设备收不到任何指令，所以保持最后一次的设置。

## 读数过期

**你会看到。** 阶段是 `paused`，事件为 `readings_stale`。连接是通的。

**系统已经做了。** 发现超过运行单 `sampling.max_gap_seconds` 的时间里没有一条有效读数，于是暂停了阶段。

**你要做的。** 确认 `growbridge status` 显示的是当前的传感器数值，并到现场检查传感器。读数恢复之后再续跑，否则下一次评估阶段又会被暂停。

## 连接正常但读不到设备状态

**你会看到。** 阶段是 `paused`，事件为 `readings_stale`。`stage_waiting` 告警和 `wf_history` 的记录里带有 `"reason": "state_unreadable"`；在 `wf_events` 里，它的事件 ID 包含 `state-unreadable`。

**系统已经做了。** 连接和读数都正常，但回读设备状态（档位和模式）失败。失败时间短于 `sampling.max_gap_seconds` 时予以容忍，日程照常执行；只要有一次读取成功，计时就重新开始。失败超过这个上限后，执行 Agent 上报事件，阶段被暂停。保护规则要写的档位如果回读不到，会重发，最多每 30 秒一次。断连恢复后读不到状态，按“有差异”处理，上报的是 `disconnect_affects`。

**你要做的。** 在日志里找读取错误。然后发续跑请求：续跑本身会读设备，返回 `not_connected` 说明状态还是读不到。

## 写入结果未知

**你会看到。** 某条动作记录的 `"state"` 是 `"unknown"`。`running` 的阶段变成 `paused`，事件为 `result_unknown`。人工写入被拒绝，拒绝码 `unsettled`。

**系统已经做了。** 写入发出后没有收到回执，或者发送途中连接断了，或者无法回读。它不会重发这次写入。续跑时、接管时和待核对期间，它会读设备，把每个结果未知的动作核定为“已生效”或“未生效”。这需要连接有效、读数新鲜，并且旧的写入通路已确认停止。水泵动作不会用这种方式核定。

**你要做的。** 等读数恢复后续跑。如果续跑仍被拒绝，或者阶段处于 `manual`，就去看设备，然后把看到的情况记录下来：

```http
POST /wb/stages/STAGE_ID/onsite-check

{"note": "light at 40 %, pump off"}
```

这个请求在 `paused`、`manual` 和 `recovery_check` 状态下都接受。它保存你的名字和备注，把所有结果未知的动作标为已核定，解除关泵联锁，并把旧的写入通路标为已停止。两个入口都能发，系统完全相信你的话：一定要看过设备再发。

## 关泵未确认（联锁）

**你会看到。** 灌溉请求返回 `"state": "unknown"`，并带有 `pump off unconfirmed; interlock set`。写入、启动和续跑都被拒绝，拒绝码 `interlock`。正在进行的阶段可能进入 `recovery_check`，事件为 `pump_off_unconfirmed`。

**系统已经做了。** 灌溉结束时尝试关泵两次，然后设置联锁。之后只要连接有效，执行 Agent 每次评估都会再发一次关泵并回读。关泵得到确认、并且旧的写入通路已确认停止时，它自己解除联锁。得不到确认时，它上报事件，阶段失去全部写入权。保护规则仍然执行。

**你要做的。** 到水泵跟前去。如果还在转，在 AC5 上关掉，或者直接断电。然后读一下阶段。联锁解除后，处于 `recovery_check` 的阶段在其他核对项通过时会自己退出。如果它一直不退出，发上面的现场核查请求；阶段回到 `paused`，接管中的阶段回到 `manual`。然后续跑。没有进行中的阶段时，手动解除联锁**无路由**；执行 Agent 会一直尝试关泵。

## 有人在设备面板上改了设置

**你会看到。** 阶段是 `paused`，事件为 `external_change`。

**系统已经做了。** 每次评估都把各通道的档位和模式与自己上一次写入的值比较。有人在 AC5 面板、App 或设备定时里改了某个通道，执行 Agent 没有覆盖回去，而是暂停。对同一个通道的写入连续失败三次时，上报的也是这个事件。

**你要做的。** 先决定这次改动要不要保留。要回到运行单的设定，就接管再交还；交还的响应会列出差异，带上 `{"accept_as_intervention": true}` 会把差异记录下来。执行 Agent 之后的写入也会把设备上的这个通道切回手动模式。如果写入一直失败，先检查设备和接线，再续跑。

## 时钟异常

**你会看到。** 阶段是 `paused`，事件为 `clock_anomaly`。

**系统已经做了。** 发现两次评估之间，系统时间相对单调时钟跳变了 5 秒以上（[`executor/outage.py`](../../../src/growbridge/executor/outage.py)），于是暂停了阶段。养护规则按“最后一次可信时间加上单调时钟走过的时间”继续执行。

**你要做的。** 检查主机的时间，修好主机的时间同步。然后续跑被 `clock_anomaly` 暂停的那个阶段。只有操作员能续跑暂停的阶段或交还人工接管的阶段，所以被时钟异常暂停的阶段在新的阶段写入权下重新运行，执行 Agent 就认为操作员已经核对过时钟，之前看到的那次跳变不再计较（[`executor/engine.py`](../../../src/growbridge/executor/engine.py) 的 `_clock_checked`）。时钟存疑期间另一个阶段启动，并不会解除存疑：它同样会被 `clock_anomaly` 暂停，续跑任何一个被暂停的阶段都会解除。不需要重启。如果时钟再次跳变，阶段会再次暂停。

## 进程重启与待核对

**你会看到。** `serve` 启动后，原来处于 `pending_review`、`running`、`paused` 或 `manual` 的阶段都变成 `recovery_check`，`prior_state` 记着原状态，写入权全部为空。

**系统已经做了。** 撤销所有写入权。把可能已经发出的写入标为 `unknown`，不重发；把还在排队的写入作废。要求传输层确认旧的写入通路已经停止。如果有水泵动作尚未核定，设置联锁。审批保留。之后每次评估都尝试退出待核对，条件是：旧的写入通路已确认停止，没有联锁，回读之后没有剩下结果未知的动作；原来是 `running` 或 `paused` 的阶段，还要求设备状态和运行单一致。旧的写入通路确认停止、并且没有联锁之后，养护规则恢复执行；原来是 `manual` 的阶段除外。

**你要做的。** 读一下阶段。原来是 `running` 或 `paused` 的阶段退出后是 `paused`：续跑即可。原来是 `manual` 的退出后还是 `manual`，带一个新的人工写入权。原来是 `pending_review` 的退出后还是 `pending_review`：照常审批、启动。如果阶段一直停在 `recovery_check`，说明有一个条件不满足：到设备跟前检查，然后发现场核查请求。重启不会让你的会话失效。

## 从备份恢复或更换写入主机

两种情况最后都要把恢复编号加一，此前所有的写入权、审批和会话随之作废。

1. 停掉守护进程。换主机时，先确保旧主机再也不能写入：卸掉它的服务，删掉它的配置（[架构设计文档](../../diagri-agent-architecture.zh-CN.md) 12.2 节）。代码不会替你做这件事，也不检查。
2. 把数据库放回去。目前没有恢复命令。先把数据目录里旧的 `*.sqlite3` 文件，以及它们旁边的 `-wal` 和 `-shm` 文件移走，再把六个备份文件复制进来。文件清单和完整性校验见[通知、日报与备份](Notifications-Reports-and-Backup.md)。未验证。
3. 提高恢复编号：

   ```sh
   .venv/bin/growbridge recovery bump --reason "restored from backup"
   ```

   应该看到 `Recovery number is now N; confirm the safety config and review live stages`。如果提示 `a daemon is running on this data directory; stop it first`，说明第 1 步没做。
4. 仅换主机时：`.venv/bin/growbridge host register`。恢复回来的控制数据库里登记的如果是旧主机，命令会被拒绝，提示 `another host is registered for this device`。目前**没有命令**可以替换已登记的主机。代码比较的是数据目录里的 `host_id` 文件和控制数据库里的记录，所以把这个文件连同数据库一起搬过来，登记也就跟着过来了。未验证。
5. 启动 `serve`，重新登录。旧的 Cookie 会被拒绝，拒绝码 `session`。
6. 重新批准安全配置：见[启用 DiAGRI](Enable-DiAGRI.md)第 8 步。旧编号下批准的那一份已经无效。
7. 所有没结束的阶段都在 `recovery_check`。设备状态和运行单不一致时，它会一直停在那里，直到你发现场核查请求。之后它回到 `pending_review`，原有审批作废。重新批准、重新启动。启动会记一个新的开始时间，阶段的时长从这里重新算起。

## 卡住的计算尝试

**你会看到。** `GET /wb/compute` 在 `stuck` 里列出这次尝试，并给出 `reason`：在等对账（提交的结果未知）、上一次轮询的错误，或者一个小时没有刷新。它的额度仍被预留着。

**系统已做的。** 每分钟，tick 会再看一遍没有人回应的尝试：超过 5 分钟没有回执的提交，按作业名去查，绝不会再提交一次；排队或运行中的作业会被轮询，结束时结算。查不到作业时，这次尝试按全额预留计账（它可能已经跑过），并清理远端目录。CSC 不再列出的作业，或代码不认识的 Slurm 状态，无法轮询：tick 记下错误，继续重试。

**你要做的。** 先到 CSC 上（MyCSC，或 `squeue`/`sacct`）查清名为 `gb-<尝试编号>` 的作业怎么了。如果它已不在或无法恢复，就结算这次尝试：

```http
POST /wb/compute/attempts/ATTEMPT_ID/settle

{"reason": "作业 123456 已在 CSC 上结束但不再被列出，产物丢失"}
```

需要近期重新认证。尝试变成 `failed`；如果它的用量还没计账，就按全额预留计账（真实用量未知），记下你的名字和原因，服务还会尽力取消作业并删除它的目录（失败的步骤写进这次尝试的 `error`）。重复结算会被以 `state` 拒绝。之后研究 Agent 可以重试这次失败的尝试。如果作业的产物还在 CSC 上，也可以不动这次尝试，先排除原因（凭据、网络），tick 会自己恢复。

## 计算产物过大

**你会看到。** `GET /wb/compute` 在 `stuck` 里列出这次尝试，阶段是 `needs_review`，原因以 `output limit:` 开头，并指明超了哪一项：文件数量、列表中的总大小对比模板的 `max_storage_gb`，或实际下载到的字节数。研究 Agent 的 `fetch_compute_artifacts` 会被 `state` 拒绝，也不会再重试。

**系统已做的。** 列表本身就超限、或某个文件单独就放不进剩余额度时，在下载之前拒绝。每次下载都有看门：每 0.25 秒检查一次磁盘上这个文件的大小，一超限就取消传输，然后删除这次取回已下载的所有文件，这样运行守护进程的机器（它同时存放归档）的磁盘不会被写满。远端文件仍留在 CSC 上。看门反应之前，磁盘上可能短暂地多出一点：最多是链路在 0.25 秒内传送的量（1 Gbit/s 时约 31 MB）加一个数据块，随后立刻被删除。

**你要做的。** 到 CSC 上查看这个作业的输出目录（`FIRECREST_WORKDIR/gb-<尝试编号>/out`）。如果是模板或参数的问题导致体积过大，先修正，结算后让研究 Agent 重试。如果确实需要这些产物，自己取回需要的部分，然后再结算。结算这次尝试：

```http
POST /wb/compute/attempts/ATTEMPT_ID/settle

{"reason": "产物 80 GB，预留只有 5 GB；模板已修正"}
```

结算会把这次尝试标为 `failed`，并删除它的远端目录。要更大的上限，需要发布一个 `max_storage_gb` 更高的新模板版本。

## 模型运行出了问题：看它的轨迹

**你会看到。** 某个模型任务（编排、规划、研究、审计）以 `needs_attention` 结束、给出了错误的答案，或者以你没想到的方式调用了工具，而日志里看不出原因。

**系统已经做了。** 除非 `model_trace` 开着，否则什么也没记。配置里写 `model_trace = true` 后，每次模型角色运行写一个 JSONL 文件：`<data_dir>/model_traces/<YYYY-MM-DD>/<task_id>-<HHMMSS>-<4 位十六进制>.jsonl`（目录权限 0700，文件权限 0600）。文件第一行记下这次运行的设置，`token` 除外。轨迹写不进去时，运行不受影响。轨迹不是档案记录，见[数据、档案与可追溯性](Data-Archive-and-Traceability.md)。

**你要做的。**

1. 打开 `model_trace` 并重启 `serve`。从这时起才会记录，已经发生的那次不会补记。轨迹里是明文的提示词、用户消息、网页内容、思考和完整的工具结果，DiAGRI 从不删除它们。
2. 把任务再跑一次，然后找到文件：先找日期目录，再按工作台任务列表里的任务 id 找。
3. 用 `growbridge trace show FILE` 列出内容（长内容加 `--full`）。它不需要配置文件，逐步打印这次运行。文件被截断时，它打印能读到的部分并以退出码 2 结束。
4. 用 `growbridge trace replay FILE` 在当前代码上把它重跑一遍。模型回复取自文件，所以不调用模型，也不花钱。命令在数据的临时副本上、按轨迹记下的设置工作，从不启动设备连接。只有退回到配置里的数据目录时（或者轨迹是没有记下设置的旧轨迹时），它才读配置文件。它每个工具调用打印一行，`ok` 或 `DIFFERENT`，在第一处不一致时停下，并给出工具名、输入和差异。录下的模型回复在重放里没有用完，也算不一致。退出码 0 表示每一步都一致，1 表示有不一致，2 表示无法重放。`--keep-going` 在不一致之后继续；`--keep-copy` 保留副本供查看。
5. 查完把 `model_trace` 关掉，不再需要的轨迹手动删除。

**重放从哪份数据开始。** 依次是：`--data-dir DIR`、轨迹旁边的运行前副本（`<轨迹名>.pre/`）、配置里的数据目录。只有运行前副本能给出可靠的重放。用其他来源时，输出里会写 `results are for reference only`：数据在运行之后变过，读状态的步骤即使代码没变也可能不一致。

**为什么 `serve` 的轨迹只能作参考。** `serve` 不做运行前副本，它的轨迹通常没有。拿当前数据目录去重放，常常从第一个读状态的步骤起就不一致，比如任务在这之后已经结束。开发工作台带 `--trace` 会在每次运行之前做一份运行前副本（见[环境搭建、测试与 CI](Development-Setup-Testing-and-CI.md)）。要在正式主机上得到可靠的重放，请在再次运行任务之前复制数据目录，并用 `--data-dir` 传给重放命令。

**已知限制。**

- 会访问本机以外的工具直接返回当时记录的结果，处理函数不会运行（`lookup_crop_conditions`、`search_and_verify_sources`、`submit_compute_job`、`get_compute_job`、`fetch_compute_artifacts`）。`submit_compute_job` 和 `fetch_compute_artifacts` 写下的内容在重放里不会发生，所以之后读取这些内容的本地步骤可能显示不一致，而这并不是代码变了。
- 恢复出来的备份不是受支持的来源：它没有 `archive/` 和 `agent_work/` 下的文件。
- 重放不会改动来源数据库的内容，但 SQLite 读取一个正在使用的数据库时，可能在它旁边创建 `-wal` 和 `-shm` 附属文件。运行前副本保持逐字节不变。

## 其他告警

| 告警类型 | 含义 | 怎么办 |
| --- | --- | --- |
| `runtime`，键 `write_host` | 这台机器不是登记的写入主机，BLE 不会打开。 | 见[启用 DiAGRI](Enable-DiAGRI.md)第 3 步，然后重启。 |
| `run_health` | 消息里列出没通过的探测项：`growbridge_response`、`executor_evaluation`、`capture`、`archive_write`、`oldest_undelivered_alert`、`offsite_backup`。 | 按探测项去查：设备连接、守护进程、通知或备份。 |
| `tick_step` | 每秒评估里的某一步报错，键就是那一步的名字。其他步骤照常执行。 | 看日志。这一步恢复正常后告警自动解除。 |
| `pump_unexpected`（键 `pump`） | DiAGRI 没有灌溉时，水泵读回为开。正文写明关泵是否已确认。 | 严重。查水泵和面板：有人或者面板定时器把它打开了。正文若写“未确认”，联锁已设置，需要做现场检查。 |
| `pump_unreadable`（键 `pump`） | 设备状态里读不出水泵插座，看门狗无法判断泵是否开着。警告。 | 查设备连接，以及状态里有没有插座这一块（可能是固件或格式不同）。能再读到状态时自动解决。锁存告警，见表格下方。 |
| `pump_watchdog`（键 `step` 或 `intervention`） | `step`：看门狗自己出错。`intervention`：`unexpected_watering` 干预没能记下来（泵仍然被关掉了）。严重。 | 看日志。`step` 在一次读过水泵的步骤完成后解决；`intervention` 在之后有干预记录成功后解决。锁存告警，见表格下方。 |
| `frozen_reading`（键为传感器名） | 某个传感器的读数在超过门槛的时间里完全不变。保护规则用到它时为严重，否则为警告。规则依赖它的阶段会被暂停（事件 `alert_pause`，`rule` 为 `frozen:<传感器>`）。 | 检查探头和线缆。读数变化或传感器移出检查后告警解决。传感器恢复或改了规则后，再恢复阶段。 |
| `frozen_watch`（键 `check`） | 冻结读数检查本身出错。严重。 | 看日志。一次检查完整结束后解决。 |
| `task_missed`（键 `stage:task:due`） | 某次人工任务已过准时截止时间，却没有记录。警告。 | 还来得及就去做，并在控制台里录入记录。有记录后告警自动解决。 |
| `measurement_missing`（键 `stage:task:due`） | 测量任务已记为完成，但记录 2 小时后，该实验没有任何一条有效测量的时间落在「任务应做时间前一小时」到截止时间之间。警告。 | 按真实时间录入测量；如果其实没有测，就更正任务记录。窗口内有了测量后告警解决。 |
| `measurement_outside_window`（键 `stage:measurement`） | 有一条有效测量的时间在窗口之外，快照会把它排除。警告。 | 检查录入的时间，用更正后的测量替换它；被替换后告警解决。 |
| `stage_checks`（键 `check`） | 阶段检查本身出错。严重。 | 看日志。一次检查完整结束后解决。其他告警规则照常运行。 |
| `audit_finding` | 监察 Agent 发现了需要人处理的事。信息或警告级，不会暂停任何东西，消息里写明内容。 | 读这条发现，以及项目对话里监察 Agent 的说明，必要时自己处理阶段。 |
| `audit_schedule`（键 `schedule`） | 安排监察时出错。其他模型任务照常运行。 | 看日志。调度恢复后监察继续。 |
| `audit_task`（键 `audit:stage`） | 一次监察运行失败，或者结束时需要处理。警告，每个阶段一条：同一阶段之后再失败的监察只累加次数。不会暂停任何东西，阶段执行不受影响。 | 看日志和消息里点名的任务，检查 SDK 和凭据。该阶段有一次监察以 `done` 结束，或者该阶段不再是当前阶段时，告警解决。 |
| `stage_waiting` | 系统暂停了某个阶段，或把它送进了恢复待核对。消息里写明事件和事件携带的内容。 | 按事件名到上面对应的小节处理。阶段离开这个状态时告警自动解除。 |
| `backup`、`backup_unconfigured` | 备份失败，或者没有配置 `backup_dir`。 | 见[通知、日报与备份](Notifications-Reports-and-Backup.md)。 |
| `notify_unconfigured` | 没有配置任何通知渠道。告警会记录，但不会发出。 | 见[通知、日报与备份](Notifications-Reports-and-Backup.md)。 |
| `monitor_unconfigured` | 两个心跳 URL 都没有设，主机或运行停了也没有人会被通知。 | 设置 `GROWBRIDGE_HEARTBEAT_HOST_URL` 和 `GROWBRIDGE_HEARTBEAT_RUN_URL`；见[通知、日报与备份](Notifications-Reports-and-Backup.md)。 |
| `external_monitor`（键为 `host` 或 `run`） | 心跳或失败信号没有送达。 | 检查监控 URL 和网络；见同一页。 |
| `model_client`、`agent_task`、`task_deadline` | 模型角色没启用，或者某个模型任务失败、超期（监察失败是上面的 `audit_task`）。阶段执行不受影响。 | 检查 SDK 和凭据。处理任务**无路由**。 |

**锁存的看门狗告警。** 只要原因还在，`pump_unreadable` 和 `pump_watchdog` 就每 5 分钟重新写入一次。已读标记会保留；但原因还在时手动关掉（在数据库里解决）的告警，会在 5 分钟内作为一条新告警回来，并再发一次通知。应当消除原因，告警随后会自行解决。见[控制与安全模型](Control-and-Safety-Model.md)。

如果工作台完全连不上，[架构设计文档](../../diagri-agent-architecture.zh-CN.md)第 10 节给出的最后手段是：停掉守护进程，然后用 AC5 面板操作，或者断电。

## 另见

- [人工接管、灌溉与交还](Manual-Takeover-and-Irrigation.md)
- [拒绝码与事件类型](Denial-Codes-and-Events.md)
- [控制与安全模型](Control-and-Safety-Model.md)
- [工作流与状态机](Workflow-and-State-Machines.md)
- [通知、日报与备份](Notifications-Reports-and-Backup.md)
