# Multi-user: adaptation notes / 多用户：适配说明

Branch `feat/multi-user-locks`. Design: [`docs/superpowers/specs/2026-11-16-multi-user-locks-design.md`](superpowers/specs/2026-11-16-multi-user-locks-design.md); plan: [`docs/superpowers/plans/2026-11-16-multi-user-locks.md`](superpowers/plans/2026-11-16-multi-user-locks.md).

## English

The layer is off unless `auto_research = true` and `multi_user = true`. Off, `WorkflowService.access` is `None` and every check is a no-op, so existing deployments, tests, `growbridge simulate` and `scripts/dev_workbench.py` behave as before. Three defects it fixed are on regardless: a replacement run sheet must keep its stage's project, experiment and device; a measurement correction must stay in its experiment; `get_project_state` names only its own project's active stage. Two more: `TaskBoard.create` refuses a trigger id that belongs to another project, and a stage command no longer hands over a right after its stage changed under it (a late hand-over ended the device's irrigation cycle).


Upgrading an existing installation: create the first administrator with `growbridge operator add --admin`; existing projects have no owner until an administrator hands them over (Administration page or `POST /wb/admin/projects/{project_id}/owner`); alerts open at the upgrade have no owner and show to administrators only.

What new code needs to do:

1. **A new GET route under `/wb`** — add it to `READ_RULES` in `workbench/visibility.py` (the test fails otherwise) and filter it: `project_read` / `stage_read` from `workbench/scope.py`, answering a hidden object exactly as a missing id.
2. **A new write route** — `project_write` / `stage_write` (or the `guard_*` functions in `workflow/access.py` inside `WorkflowService`).
3. **A new alert** — pass `scope=("stage" | "project" | "device", id)` to `raise_alert` / `resolve`. Unscoped alerts are shown to administrators only. Device kinds (`DEVICE_KINDS` in `observer/alerts.py`) default to the local device; with several devices, pass the scope explicitly.
4. **Multi-device** — checks key on `device_id` already (`GreenhouseLocks.holder_of_device`). A run sheet's `device_id` must be held by the project's owner: submission, approval and start check it. Give the planner the owner's greenhouses in `project_context`. The registry is `Settings.greenhouses`.
5. **One round over several greenhouses** — checks are per stage; a set of stages needs the owner to hold every greenhouse in it.
6. **Release with idle settings** — this branch only hands the care right back and leaves the device as it is. Writing idle levels on release needs the executor: suspend and drain the device's care writes, keep protection first, write and confirm, then finish in one transaction, and handle a crash in between (see the second review round in the design, §15).
7. **Hand-over and irrigation** — `ControlService.handover()` ends the current irrigation cycle whatever right it gets. The workflow now re-checks the stage before each hand-over; ending the cycle only when the handed-over right is the irrigation's own would be the deeper fix.
8. **One workbench instance** owns the lock table (it lives in `workflow.sqlite3`).
9. **Twelve AC5s on one Raspberry Pi** — check BlueZ's concurrent connection limit (often about 7 on the built-in controller; not measured) and the radio range; a USB adapter or round-robin connections may be needed.

10. **Alert codes** — since the merge with `main`, a new alert also passes `code=` and `params=` (registered in `codes.py`) besides its scope; see `raise_alert` in `observer/alerts.py`.

### Open points from the merge review (2026-11-17)

Fixed in the merge: a scoped raise closes the open pre-upgrade row of its kind and key, so the upgrade leaves no duplicate events; other users no longer see when a taken greenhouse was locked; an administrator cannot disable their own account or the last active administrator; a session of a disabled account is refused even if it outlived the disable.

Left for the branch's author:

- **Device alerts carry over to the next lock holder.** Open device alerts describe the greenhouse's current state, so the new holder sees them, including readings in their message from before the lock. Hiding them would hide live faults (a latched pump watchdog, frozen readings) from the person now in charge; rewording or re-raising them on a lock change would keep both. Needs a decision.
- **Administrator impersonation.** `POST /admin/operators/secret` lets an administrator take over an account and then approve or start its stages, and nothing records it. An account-event table (who reset or disabled whom, when), shown to administrators and to the account, would make it auditable.
- **Care after a refused release.** When a release finds a newly submitted stage (`greenhouse_busy`), the finished stage's care right stays handed back; if that new stage is then stopped before it starts, nothing reissues care until a restart.
- **`abort_round` hands rights over before its in-transaction owner check.** If that check fails, the rights are already handed back while the stages are unchanged (a narrow window: the owner must change meanwhile).
- **Analysis by snapshot id.** `snapshot_of` accepts any snapshot whose experiment ran under the protocol id at any version, and `owned` checks only the caller's project, so a leaked `snap_` id could run another user's frozen script. Tie the snapshot to the caller's project.
- **Existence oracles.** Experiment ids (the `scope` message), control `request_id` reuse and protocol id squatting tell a user that an id exists elsewhere; list them as known limitations or namespace ids by owner.
- **Development databases from the unmerged branch** recorded the scope columns as `observer_alerts` steps 3–5, which now mean `code`/`params`; recreate them.

## 中文

只有 `auto_research = true` 且 `multi_user = true` 时才启用。关闭时 `WorkflowService.access` 为 `None`，所有检查都不做，现有部署、测试、`growbridge simulate` 和 `scripts/dev_workbench.py` 行为不变。顺手修的几个缺陷不受开关影响：替换运行单不能改变阶段的项目、实验和设备；测量更正只能在本实验内；`get_project_state` 只报本项目的活动阶段；`TaskBoard.create` 拒绝属于别的项目的触发编号；阶段命令在阶段已变化后不再交还写入权（迟到的交还会结束设备的灌溉周期）。


在已有部署上打开：先用 `growbridge operator add --admin` 创建第一个管理员；已有项目没有所有者，要由管理员转出（「管理」页或 `POST /wb/admin/projects/{project_id}/owner`）；升级时开着的告警没有归属，只给管理员看。

新代码要做的事：

1. **新增 `/wb` 读取路由**：登记进 `workbench/visibility.py` 的 `READ_RULES`（否则测试失败），并用 `workbench/scope.py` 的 `project_read` / `stage_read` 过滤，看不到的对象按"不存在的编号"回答。
2. **新增写入路由**：用 `project_write` / `stage_write`（在 `WorkflowService` 里用 `workflow/access.py` 的 `guard_*`）。
3. **新增告警**：`raise_alert` / `resolve` 传 `scope=("stage" | "project" | "device", id)`。没有归属的告警只给管理员看。设备类告警（`observer/alerts.py` 的 `DEVICE_KINDS`）默认归本机设备；多设备时要显式传归属。
4. **多设备接入**：检查已经按 `device_id` 做（`GreenhouseLocks.holder_of_device`）。运行单的 `device_id` 必须由项目所有者锁定，提交、审批、启动都会检查。建议在 `project_context` 里给计划角色列出所有者的温室。温室登记在 `Settings.greenhouses`。
5. **一轮多温室**：检查以阶段为单位；一组阶段要求所有者锁着组内每个温室。
6. **释放时设到空闲状态**：本分支释放只交还养护写入权、设备保持当前设置。要在释放时写空闲状态，需要改执行循环：先暂停并排空该设备的养护写入，保持保护规则优先，写入并确认后在一个事务里收尾，并处理中途崩溃（设计文档 §15、第 2 轮审查）。
7. **交还与灌溉**：`ControlService.handover()` 不论交还哪个写入权都会结束当前灌溉周期。工作流现在交还前复核阶段；更彻底的修法是只在交还的正是灌溉所用写入权时才结束周期。
8. **只有一个工作台实例**持有锁表（在 `workflow.sqlite3` 里）。
9. **一台树莓派连 12 台 AC5**：需要核实 BlueZ 同时连接数上限（板载控制器常见约 7 个，未实测）和覆盖距离，可能要外接 USB 蓝牙适配器或轮流连接。
10. **告警消息码**：与 `main` 合并后，新告警除了归属，还要传 `code=` 和 `params=`（在 `codes.py` 登记），见 `observer/alerts.py` 的 `raise_alert`。

### 合并审查的遗留问题（2026-11-17）

合并时已修：带归属的告警会关闭同类同键、升级前留下的无归属旧行，升级不再出现重复事件；别人看不到已占用温室的锁定时间；管理员不能停用自己，也不能停用最后一个在用的管理员；已停用账号的会话即使躲过了停用时的删除，也会被拒绝。

留给分支作者：

- **设备告警会转给下一位锁定人。** 未关闭的设备告警描述的是温室当前状态，新锁定人能看到，包括消息里锁定之前的读数。隐藏它们会让现在负责温室的人看不到正在发生的故障（水泵看门狗锁死、读数冻结）；换锁时改写或重新发出告警可以两者兼顾。需要决定。
- **管理员冒充用户。** `POST /admin/operators/secret` 让管理员能接管一个账号，再审批或启动它的阶段，而且不留记录。加一张账号事件表（谁在何时重置或停用了谁），给管理员和本人看，就能审计。
- **释放被拒后的养护。** 释放时发现新提交的阶段（`greenhouse_busy`），已结束阶段的养护写入权保持交还状态；如果这个新阶段在启动前被停止，养护要等重启才会重新签发。
- **`abort_round` 先交还写入权，后在事务里查所有者。** 若检查失败，写入权已交还而阶段没变（窗口很窄：期间所有者必须变化）。
- **按快照编号运行分析。** `snapshot_of` 接受该协议编号任何版本下运行过的快照，`owned` 只查调用者的项目；快照编号 `snap_` 一旦泄露，就可能运行别人的冻结脚本。应把快照绑定到调用者的项目。
- **存在性探测。** 实验编号（`scope` 消息）、控制 `request_id` 重复、协议编号抢占，会让用户知道某个编号在别处存在；列为已知限制，或按所有者给编号加命名空间。
- **未合并分支建的开发库**把归属列记成了 `observer_alerts` 第 3–5 步，现在这几步表示 `code`/`params`，需要重建。
