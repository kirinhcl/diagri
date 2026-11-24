// Texts for the messages the server sends as a code plus params: msg.<family>.<code> and
// msg.<family>.<code>.action (the next step). Placeholders are the params named in W/messages.js.
export default {
  "msg.alert.data_gap": "{sensor}: there is no usable data, so its threshold alerts are paused.",
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
  "msg.alert.task_missed": "{task_kind} task: it was due at {due_at} and has no record.",
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
  "msg.alert.stage_waiting": "A stage stopped by itself. Cause: {event}. State now: {state}.",
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
  "msg.alert.agent_task_failed": "{role}: a task failed to run.",
  "msg.alert.agent_task_failed.action":
    "Open the task and read the error in the technical details, then retry it or close it.",
  "msg.alert.agent_task_attention": "{role}: a task stopped and needs attention.",
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
    "{source_kind} {source} writes a channel the device runs itself in this run sheet: {channel}.",
  "msg.finding.device_owned_write.action":
    "{channel}: let the host control it in the run sheet, or delete this step.",
  "msg.finding.pump_action":
    "{source_kind} {source} would start the pump automatically; no automatic step may.",
  "msg.finding.pump_action.action":
    "Delete the automatic pump step and add a manual watering task that states the seconds; someone on site starts it from the stage page.",
  "msg.finding.level_range":
    "{source_kind} {source} sets a level the device does not accept. {channel}: {level}, outside the range {min} to {max}.",
  "msg.finding.level_range.action":
    "Change it to a level inside that range.",
  "msg.finding.pump_device_owned":
    "The run sheet leaves the pump to the device timer or leaves it out, but the pump must be host-controlled.",
  "msg.finding.pump_device_owned.action":
    "Plan the pump as host-controlled in the run sheet.",
  "msg.finding.unknown_sensor":
    "Rule {rule} uses a sensor the device does not report: {sensor}.",
  "msg.finding.unknown_sensor.action":
    "Pick a sensor the device reports.",
  "msg.finding.unit_mismatch":
    "Rule {rule} uses another unit than the device. {sensor}: the rule reads {rule_unit}, the device reports {device_unit}.",
  "msg.finding.unit_mismatch.action":
    "Change the rule to the device's unit.",
  "msg.finding.humidity_exhaust_only":
    "Humidity rule {rule} moves a channel other than the exhaust.",
  "msg.finding.humidity_exhaust_only.action":
    "A humidity rule may only move the exhaust; change its channel.",
  "msg.finding.rule_conflict":
    "Rules {rule_a} and {rule_b} have the same priority ({priority}) but set different levels on one channel: {channel}.",
  "msg.finding.rule_conflict.action":
    "Change the priority or level of one of the two rules.",
  "msg.finding.safety_conflict":
    "Rule {rule} and protection {protection} disagree. {channel}: the rule can set {level}, the protection sets {protection_level}.",
  "msg.finding.safety_conflict.action":
    "Change the level so it no longer conflicts with the protection.",
  "msg.finding.safety_conflict.release":
    "Rule {rule} can release while protection {protection} still holds. {channel}: the release sets {level}, the protection holds {protection_level}.",
  "msg.finding.safety_conflict.release.action":
    "Change the release level or the recovery condition so the two cannot meet.",
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
    "{channel}: no longest tolerated outage is given.",
  "msg.finding.missing_tolerance.action":
    "{channel}: state how long it may be out of host control.",
  "msg.finding.manual_task":
    "{task_kind} task: someone must be on site every day at {at_local}.",
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
  "msg.finding.superseded_source":
    "{source_kind} {source} cites an evidence card that a newer card has replaced.",
  "msg.finding.superseded_source.action":
    "{replacement_validity}",
  "msg.finding.retracted_source":
    "{source_kind} {source} cites an evidence card that has been retracted: {reason}",
  "msg.finding.retracted_source.action":
    "Cite another card or remove the citation.",
  "msg.finding.dependency_invalid_source":
    "{source_kind} {source} cites an evidence card built on data that has since been invalidated.",
  "msg.finding.dependency_invalid_source.action":
    "Cite another card, or redo the round on valid data.",
  "msg.finding.contested_source":
    "{source_kind} {source} cites an evidence card that other cards contradict.",
  "msg.finding.contested_source.action":
    "Check the conflicting cards before relying on it.",
  "msg.finding.pending_relation":
    "{source_kind} {source} cites an evidence card with relations still awaiting review.",
  "msg.finding.pending_relation.action":
    "Review those relations first.",
  "msg.finding.variable_mismatch":
    "{source_kind} {source} reads {rule_variable}, but its evidence card is about {card_variable}.",
  "msg.finding.variable_mismatch.action":
    "Cite a card about the variable the rule reads.",
  "msg.finding.evidence_unit_mismatch":
    "{source_kind} {source} uses unit {rule_unit}, but its evidence card is in {card_unit}.",
  "msg.finding.evidence_unit_mismatch.action":
    "Convert one of them, or cite a card in the same unit.",
  "msg.finding.crop_mismatch":
    "{source_kind} {source} cites an evidence card for crop {card_taxon}, but the protocol grows {protocol_taxon}.",
  "msg.finding.crop_mismatch.action":
    "Cite a card for the protocol's crop.",
  "msg.finding.uncataloged_card":
    "{source_kind} {source} cites an evidence card with a value but no catalog variable, so its unit cannot be checked.",
  "msg.finding.uncataloged_card.action":
    "Cards are never edited: enter a new card that names the catalog variable, and record that it supersedes this one.",
  "msg.finding.exploratory_finding":
    "{source_kind} {source} cites an evidence card from a round labelled {label}, not a confirmatory one.",
  "msg.finding.exploratory_finding.action":
    "Treat it as a lead, not a confirmed result.",
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
  "msg.receipt.not_sent": "The command was never sent, so the device is unchanged.",
  "msg.receipt.not_sent.action": "Check the connection, then try again.",
  "msg.receipt.device_rejected": "The device refused the command, so it is unchanged.",
  "msg.receipt.device_rejected.action": "Check the device, then try again.",
  "msg.receipt.no_receipt": "The device sent no receipt, so the result is not known.",
  "msg.receipt.no_receipt.action":
    "Check the device on site, then record an on-site check.",
  "msg.receipt.link_broke": "The connection broke while the command was being sent, so the result is not known.",
  "msg.receipt.link_broke.action":
    "Check the device on site, then record an on-site check.",
  "msg.receipt.readback_level":
    "{channel}: the device did not read back {expected}.",
  "msg.receipt.readback_level.action": "Check the device on site.",
  "msg.receipt.readback_unavailable":
    "The device state could not be read back, so the result is not known.",
  "msg.receipt.readback_unavailable.action": "Check the device on site.",
  "msg.receipt.readback_mode":
    "The outlet is in mode {mode}, not manual, after the command.",
  "msg.receipt.readback_mode.action": "Check the device on site.",
  "msg.receipt.void_recovery_changed":
    "The recovery number changed, so the command was cancelled and did not run.",
  "msg.receipt.void_recovery_changed.action": "Submit it again if it is still needed.",
  "msg.receipt.void_handover":
    "Control was handed over, so the command was cancelled and did not run.",
  "msg.receipt.void_handover.action": "Submit it again if it is still needed.",
  "msg.receipt.void_restart":
    "The server stopped before the command was sent, so it did not run.",
  "msg.receipt.void_restart.action": "Submit it again if it is still needed.",
  "msg.receipt.void_superseded":
    "{channel}: a safety write took its place, so the command did not run.",
  "msg.receipt.void_superseded.action": "{channel}: check that the safety write left it as you need it; submit again if needed.",
  "msg.receipt.void_denied": "The command was refused, so it did not run.",
  "msg.receipt.void_denied.action": "The reason is in the technical details.",
  "msg.receipt.internal_error":
    "The server hit an internal error while writing, so the result is not known.",
  "msg.receipt.internal_error.action":
    "Check the device on site and tell an administrator.",
  "msg.receipt.lost_receipt":
    "The server stopped before the receipt was stored, so the result is not known.",
  "msg.receipt.lost_receipt.action": "Check the device on site.",
  "msg.receipt.pump_off_unconfirmed": "The pump was not confirmed off.",
  "msg.receipt.pump_off_unconfirmed.action": "Switch the pump off by hand on site.",
  "msg.receipt.settled_applied":
    "{channel}: a read-back confirmed it is at {level}, so the command took effect.",
  "msg.receipt.settled_not_applied":
    "{channel}: a read-back found it at {level} in mode {mode}, so the command did not take effect.",
  "msg.receipt.settled_not_applied.action": "Submit it again if it is still needed.",
  "msg.task_end.handover": "Control was handed over, so the irrigation ended early.",
  "msg.task_end.protection_write":
    "{channel}: a safety protection took over, so the irrigation ended early.",
  "msg.task_end.protection_write.action": "Find out why the protection acted.",
  "msg.task_end.pump_off_interlock": "The interlock switched the pump off, so the irrigation ended early.",
  "msg.task_end.pump_off_interlock.action": "Find out why the interlock acted.",
  "msg.task_end.pump_off_watchdog": "The pump watchdog switched the pump off, so the irrigation ended early.",
  "msg.task_end.pump_off_watchdog.action": "Find out why the watchdog acted.",
  "msg.task_end.pump_off_unconfirmed":
    "The pump was not confirmed off, so it may still be on; the interlock keeps the pump locked.",
  "msg.task_end.pump_off_unconfirmed.action": "Switch the pump off by hand on site.",
  "msg.task_end.not_confirmed":
    "The irrigation was not confirmed complete (result: {action_state}).",
  "msg.task_end.not_confirmed.action": "Check on site that the watering happened.",
  "msg.task_end.other": "The irrigation ended early.",
  "msg.task_end.other.action": "Check on site if it matters.",
  "msg.compute_stuck.reconcile_wait":
    "The cluster has not confirmed whether this computation was submitted; it has waited {age_seconds} for reconciliation.",
  "msg.compute_stuck.reconcile_wait.action":
    "You can wait a little longer, or settle it if you are sure nothing will come back.",
  "msg.compute_stuck.not_refreshed": "This computation has not been refreshed for {age_seconds}.",
  "msg.compute_stuck.not_refreshed.action":
    "Check the cluster scheduler; if the job is no longer there, settle it.",
  "msg.compute_stuck.error": "This computation hit an error (the specific error is on the next line).",
  "msg.compute_error.submit_rejected": "The cluster refused the submission.",
  "msg.compute_error.submit_rejected.action": "Check the job settings, then try again.",
  "msg.compute_error.submit_failed": "Something went wrong while submitting, so the cluster may or may not have the job.",
  "msg.compute_error.submit_failed.action": "Try again in a while.",
  "msg.compute_error.orphan_not_cancelled": "A job is still on the cluster and could not be cancelled.",
  "msg.compute_error.orphan_not_cancelled.action": "Ask an administrator to deal with it.",
  "msg.compute_error.late_cancelled": "A job that arrived late on the cluster was cancelled.",
  "msg.compute_error.backend_error": "Talking to the cluster failed.",
  "msg.compute_error.backend_error.action": "Try fetching again in a while.",
  "msg.compute_error.cancelled_no_job": "Cancelled; the cluster has no such job.",
  "msg.compute_error.cancel_unknown": "Cancelling was requested, but the job's state on the cluster is not known.",
  "msg.compute_error.cancel_unknown.action": "Look again in a while.",
  "msg.compute_error.outcome_unknown": "The outcome is not known, so the whole reservation was charged.",
  "msg.compute_error.outcome_unknown.action": "If you need the real usage, look at the job on the cluster.",
  "msg.compute_error.cancel_failed": "Cancelling the job on the cluster failed.",
  "msg.compute_error.cancel_failed.action": "Ask an administrator to deal with it.",
  "msg.compute_error.cleanup_failed": "Cleaning up on the cluster failed.",
  "msg.compute_error.cleanup_failed.action": "Ask an administrator to deal with it.",
  "msg.compute_error.settled_by_operator": "An operator settled this attempt.",
  "msg.compute_error.output_limit": "The outputs go over the limit ({bytes} against {limit}).",
  "msg.compute_error.output_limit.action": "Settle it; it is charged as unknown use.",
  "msg.compute_error.too_many_files": "There are too many output files ({file_count} against a limit of {limit_count}).",
  "msg.compute_error.too_many_files.action": "Settle it; it is charged as unknown use.",
  "msg.compute_error.artifact_missing": "The output file {name} is missing or is not in the output folder.",
  "msg.compute_error.artifact_missing.action": "Settle it, then submit again.",
  "msg.compute_error.artifact_mismatch": "The output file {name} does not match its checksum.",
  "msg.compute_error.artifact_mismatch.action": "Settle it, then submit again.",
  "msg.compute_error.no_artifacts": "No output files came back.",
  "msg.compute_error.no_artifacts.action": "Settle it, then submit again.",
  "msg.chat_end.denied": "A step was refused, so the task did not finish.",
  "msg.chat_end.denied.action": "The reason is in the technical details.",
  "msg.chat_end.model_unavailable": "The model could not be reached, so the task did not finish.",
  "msg.chat_end.model_unavailable.action": "Check the key and the budget, then ask again.",
  "msg.chat_end.model_stopped": "The model stopped before it finished.",
  "msg.chat_end.model_stopped.action": "Ask again with a shorter question.",
  "msg.chat_end.undelivered": "{role} did not hand in a result.",
  "msg.chat_end.undelivered.action": "Ask again, or do this step yourself.",
  "msg.chat_end.run_finished": "The task finished.",
  "msg.estimate.too_few_blocks":
    "Fewer than {min_blocks} complete blocks ({blocks} so far), so no treatment effect can be estimated.",
  "msg.estimate.too_few_blocks.action":
    "Run more rounds until every treatment has at least {min_blocks} complete blocks.",
  "msg.estimate.sampled_p":
    "The p value is approximated from {flips} random sign flips over {blocks} blocks.",
};
