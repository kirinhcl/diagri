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
};
