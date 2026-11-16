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
};
