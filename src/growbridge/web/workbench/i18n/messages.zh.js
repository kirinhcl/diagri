// 服务器以代码加参数发来的消息的文本：msg.<family>.<code> 和 msg.<family>.<code>.action（下一步）。
// 占位符就是 W/messages.js 里有格式规则的参数名。
export default {
  "msg.alert.data_gap": "{sensor}没有可用的数据，它的阈值告警已暂停。",
  "msg.alert.data_gap.action": "检查传感器和连接；数据恢复后告警会自动恢复。",
  "msg.alert.threshold": "{sensor}{op}{value}，已持续{duration_seconds}（规则{rule}）。",
  "msg.alert.threshold.action": "去生长室看看；如果这是预期内的，就确认这条告警。",
  "msg.alert.frozen_watch": "冻结读数检查没能运行。",
  "msg.alert.frozen_watch.action": "请管理员查看服务器日志。",
  "msg.alert.stage_checks": "阶段检查没能运行。",
  "msg.alert.stage_checks.action": "请管理员查看服务器日志。",
  "msg.alert.frozen_reading": "{sensor}一直报告同一个读数{value}，没有变化。",
  "msg.alert.frozen_reading.action": "检查传感器是否卡住或脱落；如果是保护传感器，阶段可能已暂停。",
  "msg.alert.task_missed": "{task_kind}任务应在{due_at}完成，现在已过期，没有记录。",
  "msg.alert.task_missed.action": "把这个任务记为已做或跳过。",
  "msg.alert.measurement_missing":
    "任务记为已做，但在{window_start}到{window_end}之间没有测量记录。",
  "msg.alert.measurement_missing.action": "按实际测量的时间补录这次测量。",
  "msg.alert.measurement_outside_window":
    "{metric}的测量时间（{measured_at}）在阶段的数据窗口之外，不会进入阶段快照。",
  "msg.alert.measurement_outside_window.action": "按正确的时间重新录入，或记一条更正。",
  "msg.alert.pump_unexpected_off": "没有在浇水时水泵却开着；水泵已关闭，插座模式已改回手动。",
  "msg.alert.pump_unexpected_off.action": "查清水泵为什么会在没浇水时开着。",
  "msg.alert.pump_unexpected_interlocked":
    "没有在浇水时水泵却开着；关泵没能确认，水泵已被锁住，系统会继续重试。",
  "msg.alert.pump_unexpected_interlocked.action": "到现场手动关掉水泵。",
  "msg.alert.pump_unexpected_failed":
    "没有在浇水时水泵却开着；关泵失败，水泵没有被锁住。",
  "msg.alert.pump_unexpected_failed.action":
    "到现场确认水泵已关；下一次读到设备状态时系统会再试。",
  "msg.alert.pump_unreadable": "读不到水泵插座的状态，水泵看门狗无法判断水泵是否开着。",
  "msg.alert.pump_unreadable.action": "检查设备连接和水泵插座；看门狗现在看不到水泵。",
  "msg.alert.pump_watchdog_step": "水泵看门狗出错，已经停止检查。",
  "msg.alert.pump_watchdog_step.action": "请自己盯着水泵，并通知管理员。",
  "msg.alert.pump_watchdog_record": "水泵看门狗没能记下这次水泵异常开启的事件。",
  "msg.alert.pump_watchdog_record.action": "请在阶段记录里手动补一条。",
  "msg.alert.backup_unconfigured": "没有指定备份目录，数据库没有备份。",
  "msg.alert.backup_unconfigured.action": "请在服务器设置里指定备份目录，然后重启服务器。",
  "msg.alert.notify_unconfigured": "没有设置邮件或 Telegram，告警发不出去。",
  "msg.alert.notify_unconfigured.action": "请在服务器设置里设置邮件或 Telegram，然后重启服务器。",
  "msg.alert.monitor_unconfigured": "没有设置外部心跳服务。",
  "msg.alert.monitor_unconfigured.action":
    "请设置外部心跳服务；没有它，主机或运行停下时不会有人知道。",
  "msg.alert.not_write_host": "这台电脑不是登记的写入主机，不会控制设备。",
  "msg.alert.not_write_host.action": "请在登记的写入主机上启动服务器。",
  "msg.alert.tick_step": "服务器定时循环里的「{step}」这一步出错了。",
  "msg.alert.tick_step.action":
    "请看服务器日志里这一步的报错；反复失败就重启服务器，并通知管理员。",
  "msg.alert.source_rewound":
    "旧的采样表现在只到第 {top_rowid} 行，比存档记录的第 {cursor} 行还靠前，新的行无法和旧的区分。",
  "msg.alert.source_rewound.action": "请先停下，让管理员检查旧数据，再开始新的运行。",
  "msg.alert.intervention_mirror": "有一次人工干预没能复制到存档。",
  "msg.alert.intervention_mirror.action":
    "请告诉管理员；如果服务器日志显示这次干预丢失了，请重新录入。",
  "msg.alert.stage_waiting": "阶段因为「{event}」自己停下了（{state}）。",
  "msg.alert.stage_waiting.action": "请打开阶段页，按显示的原因处理，然后继续运行这个阶段。",
  "msg.alert.task_deadline": "有一个研究任务过了截止时间，需要处理。",
  "msg.alert.task_deadline.action": "请打开项目里的这个任务，处理完或者关闭它。",
  "msg.alert.run_health": "这次运行的健康检查没有通过：{failures}。",
  "msg.alert.run_health.action": "请修好列出的这几项；修好前，这次运行的数据不可信。",
  "msg.alert.external_monitor": "外部的{signal}心跳没能送出去。",
  "msg.alert.external_monitor.action": "请检查这台电脑的网络和心跳服务。",
  "msg.alert.backup": "最近一次数据库备份失败了。",
  "msg.alert.backup.action": "请检查磁盘空间和备份目录；服务器稍后会自动重试。",
  "msg.alert.agent_task_failed": "{role}的一个任务没能运行。",
  "msg.alert.agent_task_failed.action": "请打开任务，在技术详情里看报错，然后重试或关闭它。",
  "msg.alert.agent_task_attention": "{role}的一个任务停下了，需要处理。",
  "msg.alert.agent_task_attention.action": "请打开任务，回答它或者关闭它。",
  "msg.alert.audit_task_failed": "一次阶段监察没能运行。",
  "msg.alert.audit_task_failed.action": "监察只是提醒；可以重试，也可以忽略。",
  "msg.alert.audit_task_attention": "一次阶段监察停下了，需要处理。",
  "msg.alert.audit_task_attention.action": "监察只是提醒；可以回答、重试，也可以忽略。",
  "msg.alert.audit_schedule": "服务器没能安排监察。",
  "msg.alert.audit_schedule.action": "请管理员处理；修好前不会安排监察。",
  "msg.alert.model_client": "AI 助手没能启动。",
  "msg.alert.model_client.action": "请检查服务器上的模型密钥和软件包；修好前 AI 助手都不工作。",
  "msg.alert.audit_finding": "监察 Agent 对这个阶段有一条备注。",
  "msg.alert.audit_finding.action": "请读备注，决定这个阶段要不要改，再把这条告警标为已读。",
  "msg.finding.device_owned_write":
    "{source_kind}{source}要写{channel}，但这份运行单里{channel}由设备自己控制。",
  "msg.finding.device_owned_write.action":
    "让主机控制{channel}，或者删掉这条动作。",
  "msg.finding.pump_action":
    "{source_kind}{source}会自动开泵，自动步骤不允许这样做。",
  "msg.finding.pump_action.action":
    "删掉自动开泵的步骤，改成写明秒数的人工浇水任务，由现场的人在阶段页启动。",
  "msg.finding.level_range":
    "{source_kind}{source}把{channel}设为{level}，超出设备接受的范围（{min}到{max}）。",
  "msg.finding.level_range.action":
    "改成这个范围内的档位。",
  "msg.finding.pump_device_owned":
    "运行单把水泵留给设备的定时器，或者没写水泵，但水泵必须由主机控制。",
  "msg.finding.pump_device_owned.action":
    "在运行单里把水泵规划为主机控制。",
  "msg.finding.unknown_sensor":
    "规则{rule}用了{sensor}，设备不报告这个传感器。",
  "msg.finding.unknown_sensor.action":
    "选一个设备会报告的传感器。",
  "msg.finding.unit_mismatch":
    "规则{rule}读{sensor}用的单位是{rule_unit}，设备报告的是{device_unit}。",
  "msg.finding.unit_mismatch.action":
    "把规则改成设备的单位。",
  "msg.finding.humidity_exhaust_only":
    "湿度规则{rule}动了排风以外的通道。",
  "msg.finding.humidity_exhaust_only.action":
    "湿度规则只能动排风，请改掉它的通道。",
  "msg.finding.rule_conflict":
    "规则{rule_a}和{rule_b}在同一优先级（{priority}）下把{channel}设成了不同档位。",
  "msg.finding.rule_conflict.action":
    "调整其中一条规则的优先级或档位。",
  "msg.finding.safety_conflict":
    "规则{rule}可能把{channel}设为{level}，而保护规则{protection}会设为{protection_level}。",
  "msg.finding.safety_conflict.action":
    "改档位，让它不和保护规则冲突。",
  "msg.finding.sampling.validity":
    "规则{rule}：读数的有效期是{validity_seconds}，短于采样间隔{interval_seconds}。",
  "msg.finding.sampling.validity.action":
    "让有效期长于采样间隔。",
  "msg.finding.sampling.interval":
    "采样间隔是{interval_seconds}，不大于 0。",
  "msg.finding.sampling.interval.action":
    "把采样间隔设成大于 0。",
  "msg.finding.sampling.max_gap":
    "最长允许的空档（{max_gap_seconds}）短于采样间隔。",
  "msg.finding.sampling.max_gap.action":
    "让最长空档不短于采样间隔。",
  "msg.finding.duration.rule":
    "规则{rule}的持续时长是{duration_seconds}，最短切换间隔是{min_switch_seconds}，这样行不通。",
  "msg.finding.duration.rule.action":
    "持续时长要大于 0，切换间隔不能为负。",
  "msg.finding.duration.protection":
    "保护规则{protection}的持续时长是{duration_seconds}，不大于 0。",
  "msg.finding.duration.protection.action":
    "填一个大于 0 的持续时长。",
  "msg.finding.duration.run":
    "运行时长是{duration_seconds}，不大于 0。",
  "msg.finding.duration.run.action":
    "填一个大于 0 的运行时长。",
  "msg.finding.wait":
    "最长等待是{max_wait_seconds}，不大于 0。",
  "msg.finding.wait.action":
    "填一个大于 0 的最长等待。",
  "msg.finding.missing_tolerance":
    "没有写明{channel}能容忍多久失去主机控制。",
  "msg.finding.missing_tolerance.action":
    "写明{channel}能容忍的缺失时长。",
  "msg.finding.manual_task":
    "每天{at_local}要有人到场，做一次{task_kind}任务。",
  "msg.finding.manual_task.action":
    "确保那个时间有人在场。",
  "msg.finding.manual_task.irrigation":
    "每天{at_local}要有人到场，启动一次{seconds}的浇水。",
  "msg.finding.manual_task.irrigation.action":
    "确保那个时间有人在场，在阶段页启动它。",
  "msg.finding.no_evidence":
    "{source_kind}{source}没有证据卡，也没有用户输入作依据。",
  "msg.finding.no_evidence.action":
    "为这一步附上证据卡。",
  "msg.finding.unverified_source":
    "{source_kind}{source}依据的证据卡还没有核验。",
  "msg.finding.unverified_source.action":
    "先核验这张证据卡。",
  "msg.finding.uncalibrated":
    "{source_kind}{source}依据的证据卡，其测量没有校准。",
  "msg.finding.uncalibrated.action":
    "先校准这张证据卡依据的测量。",
  "msg.finding.superseded_source":
    "{source_kind}{source}引用的证据卡已被新卡取代。",
  "msg.finding.superseded_source.action":
    "改引用现行的证据卡。",
  "msg.finding.retracted_source":
    "{source_kind}{source}引用的证据卡已被撤销：{reason}",
  "msg.finding.retracted_source.action":
    "改引用其他证据卡，或去掉这条引用。",
  "msg.finding.dependency_invalid_source":
    "{source_kind}{source}引用的证据卡所依据的数据已经失效。",
  "msg.finding.dependency_invalid_source.action":
    "改引用其他证据卡，或在有效数据上重做这一轮。",
  "msg.finding.contested_source":
    "{source_kind}{source}引用的证据卡与其他卡相矛盾：{others}。",
  "msg.finding.contested_source.action":
    "先核对相互矛盾的证据卡再采用。",
  "msg.finding.pending_relation":
    "{source_kind}{source}引用的证据卡还有待审核的关系：{relations}。",
  "msg.finding.pending_relation.action":
    "先审核这些关系。",
  "msg.finding.variable_mismatch":
    "{source_kind}{source}读取的是{rule_variable}，而它的证据卡讲的是{card_variable}。",
  "msg.finding.variable_mismatch.action":
    "改引用讲同一变量的证据卡。",
  "msg.finding.evidence_unit_mismatch":
    "{source_kind}{source}用的单位是{rule_unit}，而它的证据卡用{card_unit}。",
  "msg.finding.evidence_unit_mismatch.action":
    "换算其中一个，或改引用同单位的证据卡。",
  "msg.finding.crop_mismatch":
    "{source_kind}{source}引用的证据卡针对作物{card_taxon}，而协议种的是{protocol_taxon}。",
  "msg.finding.crop_mismatch.action":
    "改引用针对协议作物的证据卡。",
  "msg.finding.uncataloged_card":
    "{source_kind}{source}引用的证据卡有数值但没有目录变量，无法核对单位。",
  "msg.finding.uncataloged_card.action":
    "为这张证据卡补上目录变量。",
  "msg.finding.exploratory_finding":
    "{source_kind}{source}引用的证据卡来自{label}轮次，不是确证性的。",
  "msg.finding.exploratory_finding.action":
    "只把它当作线索，不当作已确认的结果。",
  "msg.finding.unknown_treatment":
    "分配里用了协议没有定义的处理：{treatments}。",
  "msg.finding.unknown_treatment.action":
    "只用协议里有的处理。",
  "msg.finding.missing_control.undefined":
    "对照{control}不是协议里定义的处理。",
  "msg.finding.missing_control.undefined.action":
    "在协议里定义对照。",
  "msg.finding.missing_control.unallocated":
    "对照{control}从未被分进任何区组。",
  "msg.finding.missing_control.unallocated.action":
    "把对照分进区组。",
  "msg.finding.no_replication":
    "这些处理的单元不足两个：{treatments}。",
  "msg.finding.no_replication.action":
    "每个处理至少重复两次。",
  "msg.finding.unbalanced_block":
    "区组{block}里各处理出现的次数不一样。",
  "msg.finding.unbalanced_block.action":
    "让这个区组里每个处理各出现一次。",
  "msg.finding.confounded_with_time":
    "每个处理各占一段连续的轮次，处理和时间无法区分。",
  "msg.finding.confounded_with_time.action":
    "每一段轮次里都要混合不同处理。",
  "msg.finding.seed_mismatch.unreproducible":
    "记录的随机种子无法复现分配。",
  "msg.finding.seed_mismatch.unreproducible.action":
    "请重新生成分配。",
  "msg.finding.seed_mismatch.differs":
    "分配和记录的随机种子给出的不同。",
  "msg.finding.seed_mismatch.differs.action":
    "请用种子重新生成分配。",
  "msg.finding.treatment_not_applied":
    "第{round}轮分到的处理是{treatment}，但运行单没有实现它：{problems}。",
  "msg.finding.treatment_not_applied.action":
    "为处理的每个档位加上定时动作。",
  "msg.finding.treatment_not_applied.none":
    "运行单没有实现协议里的任何一个处理（{treatments}）。",
  "msg.finding.treatment_not_applied.none.action":
    "为这一轮需要的处理的每个档位加上定时动作。",
  "msg.receipt.not_sent": "指令没有发出去，设备没有变化。",
  "msg.receipt.not_sent.action": "检查连接后重试。",
  "msg.receipt.device_rejected": "设备拒收了指令，设备没有变化。",
  "msg.receipt.device_rejected.action": "检查设备后重试。",
  "msg.receipt.no_receipt": "没有收到设备的回执，结果不明。",
  "msg.receipt.no_receipt.action": "到现场核对设备，并记一次现场检查。",
  "msg.receipt.link_broke": "发送指令时连接断了，结果不明。",
  "msg.receipt.link_broke.action": "到现场核对设备，并记一次现场检查。",
  "msg.receipt.readback_level": "读回的{channel}档位不是{expected}。",
  "msg.receipt.readback_level.action": "到现场核对设备。",
  "msg.receipt.readback_unavailable": "读不回设备的状态，结果不明。",
  "msg.receipt.readback_unavailable.action": "到现场核对设备。",
  "msg.receipt.readback_mode": "指令发出后，插座的模式是 {mode}，不是手动模式。",
  "msg.receipt.readback_mode.action": "到现场核对设备。",
  "msg.receipt.void_recovery_changed": "恢复编号变了，指令已作废，没有执行。",
  "msg.receipt.void_recovery_changed.action": "需要的话重新提交。",
  "msg.receipt.void_handover": "控制权交接了，指令已作废，没有执行。",
  "msg.receipt.void_handover.action": "需要的话重新提交。",
  "msg.receipt.void_restart": "指令发出前服务器停了，没有执行。",
  "msg.receipt.void_restart.action": "需要的话重新提交。",
  "msg.receipt.void_superseded": "{channel}上的安全保护写入取代了这条指令，它没有执行。",
  "msg.receipt.void_superseded.action": "确认保护写入后{channel}的状态符合需要；需要的话重新提交。",
  "msg.receipt.void_denied": "指令被拒绝，没有执行。",
  "msg.receipt.void_denied.action": "拒绝的原因见技术详情。",
  "msg.receipt.internal_error": "写入时服务器内部出错，结果不明。",
  "msg.receipt.internal_error.action": "到现场核对设备，并通知管理员。",
  "msg.receipt.lost_receipt": "回执存下之前服务器停了，结果不明。",
  "msg.receipt.lost_receipt.action": "到现场核对设备。",
  "msg.receipt.pump_off_unconfirmed": "没有确认水泵已关。",
  "msg.receipt.pump_off_unconfirmed.action": "到现场手动关掉水泵。",
  "msg.receipt.settled_applied": "读回确认{channel}已在{level}，指令已生效。",
  "msg.receipt.settled_not_applied":
    "读回发现{channel}在{level}，模式是 {mode}，指令没有生效。",
  "msg.receipt.settled_not_applied.action": "需要的话重新提交。",
  "msg.task_end.handover": "控制权交接了，浇水提前结束。",
  "msg.task_end.protection_write": "安全保护接管了{channel}，浇水提前结束。",
  "msg.task_end.protection_write.action": "查一下保护为什么动作。",
  "msg.task_end.pump_off_interlock": "联锁关了水泵，浇水提前结束。",
  "msg.task_end.pump_off_interlock.action": "查一下联锁为什么动作。",
  "msg.task_end.pump_off_watchdog": "水泵看门狗关了水泵，浇水提前结束。",
  "msg.task_end.pump_off_watchdog.action": "查一下看门狗为什么动作。",
  "msg.task_end.pump_off_unconfirmed": "没有确认水泵已关，水泵可能还开着；联锁已锁住水泵。",
  "msg.task_end.pump_off_unconfirmed.action": "到现场手动关泵。",
  "msg.task_end.not_confirmed": "浇水没有确认完成（结果：{action_state}）。",
  "msg.task_end.not_confirmed.action": "到现场核对是否浇过水。",
  "msg.task_end.other": "浇水提前结束。",
  "msg.task_end.other.action": "需要的话到现场核对。",
  "msg.compute_stuck.reconcile_wait": "集群还没有确认这次计算是否提交成功，已等了{age_seconds}，仍在核对。",
  "msg.compute_stuck.reconcile_wait.action": "可以再等一等；确定不会有结果时再结算。",
  "msg.compute_stuck.not_refreshed": "这次计算已有{age_seconds}没有刷新。",
  "msg.compute_stuck.not_refreshed.action": "检查集群调度；任务已经不在了就结算。",
  "msg.compute_stuck.error": "这次计算出错了（具体错误见下一行）。",
  "msg.compute_error.submit_rejected": "集群拒绝了提交。",
  "msg.compute_error.submit_rejected.action": "检查任务设置后重试。",
  "msg.compute_error.submit_failed": "提交时出错，集群上可能有、也可能没有这个任务。",
  "msg.compute_error.submit_failed.action": "稍后重试。",
  "msg.compute_error.orphan_not_cancelled": "集群上还有一个没能取消的任务。",
  "msg.compute_error.orphan_not_cancelled.action": "请管理员处理。",
  "msg.compute_error.late_cancelled": "迟到的远端任务已取消。",
  "msg.compute_error.backend_error": "和集群通信出错。",
  "msg.compute_error.backend_error.action": "稍后重试取回。",
  "msg.compute_error.cancelled_no_job": "已取消；集群上没有找到这个任务。",
  "msg.compute_error.cancel_unknown": "已请求取消，但集群上这个任务的状态不明。",
  "msg.compute_error.cancel_unknown.action": "稍后再看。",
  "msg.compute_error.outcome_unknown": "结果不明，已按整笔预留计费。",
  "msg.compute_error.outcome_unknown.action": "需要真实用量的话，到集群上看这个任务。",
  "msg.compute_error.cancel_failed": "取消集群上的任务失败了。",
  "msg.compute_error.cancel_failed.action": "请管理员处理。",
  "msg.compute_error.cleanup_failed": "清理集群上的文件失败了。",
  "msg.compute_error.cleanup_failed.action": "请管理员处理。",
  "msg.compute_error.settled_by_operator": "已由操作员结算。",
  "msg.compute_error.output_limit": "输出超过了上限（{bytes}，上限 {limit}）。",
  "msg.compute_error.output_limit.action": "结算它；按未知用量计费。",
  "msg.compute_error.too_many_files": "输出文件太多（{file_count} 个，上限 {limit_count} 个）。",
  "msg.compute_error.too_many_files.action": "结算它；按未知用量计费。",
  "msg.compute_error.artifact_missing": "输出文件{name}缺失，或不在输出目录里。",
  "msg.compute_error.artifact_missing.action": "结算后重新提交。",
  "msg.compute_error.artifact_mismatch": "输出文件{name}的校验值对不上。",
  "msg.compute_error.artifact_mismatch.action": "结算后重新提交。",
  "msg.compute_error.no_artifacts": "没有取回任何输出文件。",
  "msg.compute_error.no_artifacts.action": "结算后重新提交。",
  "msg.chat_end.denied": "某一步被拒绝了，任务没有做完。",
  "msg.chat_end.denied.action": "原因见技术详情。",
  "msg.chat_end.model_unavailable": "模型连不上，任务没有做完。",
  "msg.chat_end.model_unavailable.action": "检查密钥和预算后再问一次。",
  "msg.chat_end.model_stopped": "模型没做完就停了。",
  "msg.chat_end.model_stopped.action": "把问题说短一点再问一次。",
  "msg.chat_end.undelivered": "{role}没有交出成果。",
  "msg.chat_end.undelivered.action": "再问一次，或者自己做这一步。",
  "msg.chat_end.run_finished": "任务做完了。",
  "msg.estimate.too_few_blocks": "完整区组不足 {min_blocks} 个（目前 {blocks} 个），无法估计处理效应。",
  "msg.estimate.too_few_blocks.action": "再跑几轮，让每个处理至少有 {min_blocks} 个完整区组。",
  "msg.estimate.sampled_p": "p 值是基于 {blocks} 个区组、用 {flips} 次随机翻转符号近似得到的。",
};
