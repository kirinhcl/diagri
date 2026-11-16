// Texts for the messages the server sends as a code plus params: msg.<family>.<code> and
// msg.<family>.<code>.action (the next step). Placeholders are the params named in W/messages.js.
export default {
  "msg.alert.data_gap": "There is no usable {sensor} data, so its threshold alerts are paused.",
  "msg.alert.data_gap.action":
    "Check the sensor and its connection; the alerts resume once data returns.",
  "msg.alert.threshold": "{sensor} {op} {value} for {duration_seconds} (rule {rule}).",
  "msg.alert.threshold.action":
    "Go and look at the chamber; if this is expected, acknowledge the alert.",
  "msg.alert.frozen_watch": "The frozen-reading check could not run.",
  "msg.alert.frozen_watch.action": "Ask an administrator to look at the server log.",
  "msg.alert.stage_checks": "The stage checks could not run.",
  "msg.alert.stage_checks.action": "Ask an administrator to look at the server log.",
  "msg.alert.frozen_reading": "{sensor} has reported the same reading, {value}, without change.",
  "msg.alert.frozen_reading.action":
    "Check whether the sensor is stuck or has come loose; if it is a protection sensor, the stage may be paused.",
  "msg.alert.task_missed": "The {task_kind} task was due at {due_at} and has no record.",
  "msg.alert.task_missed.action": "Record the task as done or skipped.",
  "msg.alert.measurement_missing":
    "The task was recorded done, but no measurement is dated between {window_start} and {window_end}.",
  "msg.alert.measurement_missing.action":
    "Enter the measurement with the time it was actually taken.",
  "msg.alert.measurement_outside_window":
    "The {metric} measurement ({measured_at}) is outside the stage's data window and will not be in its snapshot.",
  "msg.alert.measurement_outside_window.action":
    "Enter it again with the right time, or record a correction.",
  "msg.alert.pump_unexpected_off":
    "The pump was on while no watering was running; it was switched off and the outlet mode set back to manual.",
  "msg.alert.pump_unexpected_off.action":
    "Find out why the pump was on when nothing was watering.",
  "msg.alert.pump_unexpected_interlocked":
    "The pump was on while no watering was running; the switch-off is unconfirmed, the pump is locked and the system keeps retrying.",
  "msg.alert.pump_unexpected_interlocked.action": "Go there and switch the pump off by hand.",
  "msg.alert.pump_unexpected_failed":
    "The pump was on while no watering was running; the switch-off failed and the pump is not locked.",
  "msg.alert.pump_unexpected_failed.action":
    "Go there and check the pump is off; the system tries again on the next device status.",
  "msg.alert.pump_unreadable":
    "The pump outlet cannot be read, so the pump watchdog cannot tell whether the pump is on.",
  "msg.alert.pump_unreadable.action":
    "Check the device connection and the pump outlet; the watchdog cannot see the pump now.",
  "msg.alert.pump_watchdog_step": "The pump watchdog failed and has stopped checking.",
  "msg.alert.pump_watchdog_step.action":
    "Watch the pump yourself and tell an administrator.",
  "msg.alert.pump_watchdog_record":
    "The pump watchdog could not record the unexpected pump event.",
  "msg.alert.pump_watchdog_record.action": "Add a note to the stage record by hand.",
  "msg.alert.backup_unconfigured":
    "No backup folder is set, so the databases are not being backed up.",
  "msg.alert.backup_unconfigured.action":
    "Set the backup folder in the server settings and restart the server.",
  "msg.alert.notify_unconfigured":
    "No email or Telegram channel is set up, so alerts are not sent anywhere.",
  "msg.alert.notify_unconfigured.action":
    "Set up email or Telegram in the server settings, then restart the server.",
  "msg.alert.monitor_unconfigured": "No external heartbeat service is set up.",
  "msg.alert.monitor_unconfigured.action":
    "Set up an external heartbeat service; without one nobody is told when the host or the run stops.",
  "msg.alert.not_write_host":
    "This computer is not the registered write host, so it does not control the device.",
  "msg.alert.not_write_host.action": "Start the server on the registered write host.",
  "msg.alert.tick_step": "The “{step}” step of the server's regular cycle failed.",
  "msg.alert.tick_step.action":
    "Look in the server log for this step's error; if it keeps failing, restart the server and tell an administrator.",
  "msg.alert.source_rewound":
    "The older sample table now ends at row {top_rowid}, before the archive's position at row {cursor}, so new rows cannot be told from old ones.",
  "msg.alert.source_rewound.action":
    "Stop, ask an administrator to check the old data, and only then start a new run.",
  "msg.alert.intervention_mirror":
    "A manual intervention could not be copied to the archive.",
  "msg.alert.intervention_mirror.action":
    "Tell an administrator; if the server log shows the intervention was lost, enter it again.",
  "msg.alert.stage_waiting": "A stage stopped by itself ({state}) after {event}.",
  "msg.alert.stage_waiting.action":
    "Open the stage page, deal with the reason shown, then continue the stage.",
  "msg.alert.task_deadline": "A research task is past its deadline and needs attention.",
  "msg.alert.task_deadline.action": "Open this task in its project; finish it or close it.",
  "msg.alert.run_health": "The run's health checks are failing: {failures}.",
  "msg.alert.run_health.action":
    "Fix the items listed; until then the data of this run cannot be trusted.",
  "msg.alert.external_monitor": "The external {signal} heartbeat could not be delivered.",
  "msg.alert.external_monitor.action":
    "Check this computer's network connection and the heartbeat service.",
  "msg.alert.backup": "The latest database backup failed.",
  "msg.alert.backup.action":
    "Check the disk space and the backup folder; the server tries again later by itself.",
  "msg.alert.agent_task_failed": "A task for the {role} failed to run.",
  "msg.alert.agent_task_failed.action":
    "Open the task and read the error in the technical details, then retry it or close it.",
  "msg.alert.agent_task_attention": "A task for the {role} stopped and needs attention.",
  "msg.alert.agent_task_attention.action": "Open the task, then answer it or close it.",
  "msg.alert.audit_task_failed": "An audit of a stage failed to run.",
  "msg.alert.audit_task_failed.action":
    "An audit is only a reminder; you can retry it or ignore it.",
  "msg.alert.audit_task_attention": "An audit of a stage stopped and needs attention.",
  "msg.alert.audit_task_attention.action":
    "An audit is only a reminder; you can answer it, retry it or ignore it.",
  "msg.alert.audit_schedule": "The server could not schedule audits.",
  "msg.alert.audit_schedule.action":
    "Ask an administrator to look at it; no audit is scheduled until it is fixed.",
  "msg.alert.model_client": "The AI assistants could not start.",
  "msg.alert.model_client.action":
    "Check the model key and the software packages on the server; the AI assistants do not work until then.",
  "msg.alert.audit_finding": "The audit assistant left a note about this stage.",
  "msg.alert.audit_finding.action":
    "Read the note, decide whether the stage needs a change, then mark the alert as read.",
  "msg.finding.device_owned_write":
    "{source_kind} {source} writes {channel}, which the device runs itself in this run sheet.",
  "msg.finding.device_owned_write.action":
    "Let the host control {channel} in the run sheet, or delete this step.",
  "msg.finding.pump_action":
    "{source_kind} {source} would start the pump automatically; no automatic step may.",
  "msg.finding.pump_action.action":
    "Delete the automatic pump step and add a manual watering task that states the seconds; someone on site starts it from the stage page.",
  "msg.finding.level_range":
    "{source_kind} {source} sets {channel} to {level}, outside the range the device accepts ({min} to {max}).",
  "msg.finding.level_range.action":
    "Change it to a level inside that range.",
  "msg.finding.pump_device_owned":
    "The run sheet leaves the pump to the device timer or leaves it out, but the pump must be host-controlled.",
  "msg.finding.pump_device_owned.action":
    "Plan the pump as host-controlled in the run sheet.",
  "msg.finding.unknown_sensor":
    "Rule {rule} uses {sensor}, which the device does not report.",
  "msg.finding.unknown_sensor.action":
    "Pick a sensor the device reports.",
  "msg.finding.unit_mismatch":
    "Rule {rule} reads {sensor} in {rule_unit}, but the device reports it in {device_unit}.",
  "msg.finding.unit_mismatch.action":
    "Change the rule to the device's unit.",
  "msg.finding.humidity_exhaust_only":
    "Humidity rule {rule} moves a channel other than the exhaust.",
  "msg.finding.humidity_exhaust_only.action":
    "A humidity rule may only move the exhaust; change its channel.",
  "msg.finding.rule_conflict":
    "Rules {rule_a} and {rule_b} set {channel} to different levels at the same priority ({priority}).",
  "msg.finding.rule_conflict.action":
    "Change the priority or level of one of the two rules.",
  "msg.finding.safety_conflict":
    "Rule {rule} can set {channel} to {level} while protection {protection} sets it to {protection_level}.",
  "msg.finding.safety_conflict.action":
    "Change the level so it no longer conflicts with the protection.",
  "msg.finding.sampling.validity":
    "Rule {rule}: a reading stays valid for {validity_seconds}, less than the sampling interval of {interval_seconds}.",
  "msg.finding.sampling.validity.action":
    "Make the validity period longer than the sampling interval.",
  "msg.finding.sampling.interval":
    "The sampling interval is {interval_seconds}, which is not above zero.",
  "msg.finding.sampling.interval.action":
    "Set a sampling interval above zero.",
  "msg.finding.sampling.max_gap":
    "The longest allowed gap ({max_gap_seconds}) is shorter than the sampling interval.",
  "msg.finding.sampling.max_gap.action":
    "Make the longest gap at least as long as the sampling interval.",
  "msg.finding.duration.rule":
    "Rule {rule} has a duration of {duration_seconds} and a minimum switch interval of {min_switch_seconds}, which cannot work.",
  "msg.finding.duration.rule.action":
    "Give the rule a duration above zero and a switch interval of zero or more.",
  "msg.finding.duration.protection":
    "Protection {protection} has a duration of {duration_seconds}, which is not above zero.",
  "msg.finding.duration.protection.action":
    "Enter a duration above zero.",
  "msg.finding.duration.run":
    "The run duration is {duration_seconds}, which is not above zero.",
  "msg.finding.duration.run.action":
    "Enter a run duration above zero.",
  "msg.finding.wait":
    "The longest wait is {max_wait_seconds}, which is not above zero.",
  "msg.finding.wait.action":
    "Enter a longest wait above zero.",
  "msg.finding.missing_tolerance":
    "No longest tolerated outage is given for {channel}.",
  "msg.finding.missing_tolerance.action":
    "State how long {channel} may be out of host control.",
  "msg.finding.manual_task":
    "Someone must be on site every day at {at_local} for a {task_kind} task.",
  "msg.finding.manual_task.action":
    "Make sure someone is there at that time.",
  "msg.finding.manual_task.irrigation":
    "Someone must be on site every day at {at_local} to start a {seconds} watering run.",
  "msg.finding.manual_task.irrigation.action":
    "Make sure someone is there at that time to start it from the stage page.",
  "msg.finding.no_evidence":
    "{source_kind} {source} has no evidence card or user input behind it.",
  "msg.finding.no_evidence.action":
    "Attach an evidence card to this step.",
  "msg.finding.unverified_source":
    "{source_kind} {source} rests on an evidence card that has not been verified.",
  "msg.finding.unverified_source.action":
    "Verify the card first.",
  "msg.finding.uncalibrated":
    "{source_kind} {source} rests on an evidence card whose measurement is not calibrated.",
  "msg.finding.uncalibrated.action":
    "Calibrate the measurement the card relies on first.",
  "msg.finding.unknown_treatment":
    "The allocations use treatments the protocol does not define: {treatments}.",
  "msg.finding.unknown_treatment.action":
    "Use only treatments the protocol defines.",
  "msg.finding.missing_control.undefined":
    "The control {control} is not a treatment the protocol defines.",
  "msg.finding.missing_control.undefined.action":
    "Define the control in the protocol.",
  "msg.finding.missing_control.unallocated":
    "The control {control} is never allocated to a block.",
  "msg.finding.missing_control.unallocated.action":
    "Allocate the control to the blocks.",
  "msg.finding.no_replication":
    "These treatments have fewer than two units: {treatments}.",
  "msg.finding.no_replication.action":
    "Repeat every treatment at least twice.",
  "msg.finding.unbalanced_block":
    "Block {block} does not hold every treatment equally often.",
  "msg.finding.unbalanced_block.action":
    "Make each treatment appear once in this block.",
  "msg.finding.confounded_with_time":
    "Each treatment occupies one unbroken stretch of rounds, so treatment and time cannot be told apart.",
  "msg.finding.confounded_with_time.action":
    "Mix different treatments within each stretch of rounds.",
  "msg.finding.seed_mismatch.unreproducible":
    "The recorded random seed cannot reproduce the allocations.",
  "msg.finding.seed_mismatch.unreproducible.action":
    "Generate the allocations again.",
  "msg.finding.seed_mismatch.differs":
    "The allocations differ from what the recorded random seed gives.",
  "msg.finding.seed_mismatch.differs.action":
    "Generate the allocations again from the seed.",
  "msg.finding.treatment_not_applied":
    "Round {round} is allocated treatment {treatment}, but the run sheet does not apply it: {problems}.",
  "msg.finding.treatment_not_applied.action":
    "Add a timed action for each level the treatment sets.",
  "msg.finding.treatment_not_applied.none":
    "The run sheet applies none of the protocol's treatments ({treatments}).",
  "msg.finding.treatment_not_applied.none.action":
    "Add timed actions for the levels of the treatment this round needs.",
};
