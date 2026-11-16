// State pills: the colour group says what kind of attention a state needs.
import { labelOr } from "../i18n.js";
import { h } from "./dom.js";

// Compute phases are states too: a failed attempt needs a person, a prepared one waits to be sent.
export const STATE_GROUPS = {
  waiting: ["pending_review", "manual", "paused", "needs_attention", "needs_review", "awaiting_choice", "prepared"],
  onsite: ["recovery_check", "failed"],
  active: [
    "running",
    "stage_running",
    "designing",
    "stage_review",
    "data_verification",
    "analysis",
    "in_progress",
    "computing",
    "fetching",
    "remote_queued",
    "reconcile",
    "queued",
  ],
  done: ["ended", "stopped", "delivered", "aborted", "done", "cancelled"],
};

const GROUP_OF = new Map(
  Object.entries(STATE_GROUPS).flatMap(([group, states]) => states.map((state) => [state, group])),
);
const SEVERITY_GROUP = new Map([
  ["critical", "onsite"],
  ["warning", "waiting"],
  ["info", "done"],
]);

export function stateGroup(state) {
  return GROUP_OF.get(String(state)) || "other";
}

// An unknown state or severity says "unknown"; the caller keeps the raw value in its technical details.
export function statePill(t, state) {
  return h("span", { class: ["pill", `pill-${stateGroup(state)}`], text: labelOr(t, "state", state) });
}

export function severityPill(t, severity) {
  const group = SEVERITY_GROUP.get(String(severity)) || "other";
  return h("span", { class: ["pill", `pill-${group}`], text: labelOr(t, "severity", severity) });
}
