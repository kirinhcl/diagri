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
};
