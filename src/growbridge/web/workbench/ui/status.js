// State pills: the colour group says what kind of attention a state needs.
import { h } from "./dom.js";

export const STATE_GROUPS = {
  waiting: ["pending_review", "manual", "paused", "needs_attention", "needs_review", "awaiting_choice"],
  onsite: ["recovery_check"],
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
  ],
  done: ["ended", "stopped", "delivered", "aborted", "done"],
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

// The translated label, or the raw value when no text exists for it.
function label(t, prefix, value) {
  const key = `${prefix}.${value}`;
  const text = t(key);
  return text === key ? String(value) : text;
}

export function statePill(t, state) {
  return h("span", { class: ["pill", `pill-${stateGroup(state)}`], text: label(t, "state", state) });
}

export function severityPill(t, severity) {
  const group = SEVERITY_GROUP.get(String(severity)) || "other";
  return h("span", { class: ["pill", `pill-${group}`], text: label(t, "severity", severity) });
}
