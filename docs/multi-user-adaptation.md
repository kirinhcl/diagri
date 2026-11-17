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

### Decisions after the merge review (2026-11-17)

Fixed in the merge (#14): a scoped raise closes the open pre-upgrade row of its kind and key, so the upgrade leaves no duplicate events; other users no longer see when a taken greenhouse was locked; an administrator cannot disable their own account or the last active administrator; a session of a disabled account is refused even if it outlived the disable.

Fixed afterwards (`fix/multi-user-followups`):

- **Analysis by snapshot id.** `snapshot_of` now also requires the snapshot's experiment to belong to the caller's project. Protocols are stored by id and version, so another project may hold other versions of the same id; a snapshot of such a project reached that project's version, frozen script and holdout. It is now refused as `not_this_protocol`, like a snapshot of another protocol.
- **Care after a refused release, and after a refused `abort_round`.** Both hand rights back before their transaction. When the transaction refuses or anything fails after a hand-back (a stage was filed meanwhile, the project changed hands meanwhile, the database failed), a finished stage's dead care right is forgotten (`WorkflowStore.drop_care`, only if it is still that right) and the runtime's `restore_care` issues care again on its next tick, instead of leaving care off until a stage starts or the process restarts. For `abort_round` only finished stages can be affected: an ownership transfer needs every stage of the project finished, and an abort that won the race ends the stages itself.
- **Administrator impersonation.** A secret reset still lets an administrator sign in as that account (that is how a forgotten password is recovered), but it is no longer silent: `operator_events` records every account added, disabled or reset, with who did it and when (`actor` NULL: the command line). `GET /wb/admin/operators` returns it as `events` and the Administration page shows it as the account history, so every administrator sees the others' resets, and the account's owner is signed out by the reset.

Decided to keep:

- **Device alerts go to the next lock holder.** Open device alerts (frozen readings, data gaps, thresholds, the pump watchdog) describe the greenhouse's state now, and the person who holds it is the one who has to act on a latched pump watchdog or frozen readings. Hiding alerts raised before the lock would hide live faults; their message can name a reading from before the lock, which is accepted as the price. Closed alerts are not listed, so nothing of the previous holder's history shows.
- **A start takes over the care it saw.** `start_stage` hands back the care rights held when it began; care that `restore_care` issues during its awaits (after a restart, or within a tick of a refused release) is not taken over. Reaching it needs a stage to be approved and started inside that window, which an operator's review cannot do; handing care back after the start instead would end the new stage's irrigation cycle (`ControlService.handover`, item 7 above).
- **Existence oracles.** Ids are chosen by their callers and are global, so a refused duplicate tells that an id is taken elsewhere, never what it holds. Listed in the Wiki's known limitations; namespacing ids per owner would change every id in the archive.
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

### 合并审查后的决定（2026-11-17）

合并（#14）时已修：带归属的告警会关闭同类同键、升级前留下的无归属旧行，升级不再出现重复事件；别人看不到已占用温室的锁定时间；管理员不能停用自己，也不能停用最后一个在用的管理员；已停用账号的会话即使躲过了停用时的删除，也会被拒绝。

之后修复（`fix/multi-user-followups`）：

- **按快照编号运行分析。** `snapshot_of` 现在还要求快照的实验属于调用者的项目。协议按编号和版本存储，别的项目可能有同一编号的其他版本；这样的快照会走到那个项目的版本、冻结脚本和留出。现在按 `not_this_protocol` 拒绝，和别的协议的快照一样。
- **释放被拒、`abort_round` 被拒之后的养护。** 两者都在事务前交还写入权。交还之后事务拒绝或出现任何失败时（期间有人提交了阶段、期间项目换了所有者、数据库出错），已结束阶段上作废的养护写入权会被清掉（`WorkflowStore.drop_care`，只在它仍是那个写入权时），运行时的 `restore_care` 在下一个周期重新签发，而不是让养护一直停到某个阶段启动或进程重启。`abort_round` 只会影响已结束的阶段：转移项目要求项目的阶段都已结束，抢先完成的中止会自己结束这些阶段。
- **管理员冒充用户。** 重置密码仍然能让管理员以该账号登录（忘记密码就靠它找回），但不再无声无息：`operator_events` 记录每次添加、停用、重置账号，以及谁在何时操作（`actor` 为空表示命令行）。`GET /wb/admin/operators` 以 `events` 返回，「管理」页显示为账号记录，每位管理员都能看到别人的重置；重置也会让账号本人掉线。

决定保留：

- **设备告警交给下一位锁定人。** 未关闭的设备告警（读数冻结、数据缺口、阈值、水泵看门狗）描述的是温室当前的状态，水泵看门狗锁死或读数冻结要由现在持有温室的人处理。隐藏锁定之前发出的告警会把正在发生的故障藏起来；告警消息里可能出现锁定之前的读数，这是可以接受的代价。已关闭的告警不会列出，所以看不到前一位使用者的历史。
- **启动只接管它看到的养护。** `start_stage` 交还它开始时持有的养护写入权；在它等待期间由 `restore_care` 签发的养护（重启之后，或释放被拒后的一个周期内）不会被接管。要碰上它，阶段必须在这个窗口内被审批并启动，操作员审阅做不到；改成启动后再交还则会结束新阶段的灌溉周期（`ControlService.handover`，见上文第 7 条）。
- **存在性探测。** 编号由调用者自定、全局唯一，被拒的重复编号只说明它在别处已被占用，不透露内容。已列入 Wiki 的已知限制；按所有者给编号加命名空间需要改动归档里的每个编号。
- **未合并分支建的开发库**把归属列记成了 `observer_alerts` 第 3–5 步，现在这几步表示 `code`/`params`，需要重建。
