// State pills: the colour group says what kind of attention a state needs.
import { hasLabel, labelOr } from "../i18n.js";
import { h } from "./dom.js";
import { techDetails } from "./section.js";

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

const isMissing = (value) => value === null || value === undefined || value === "";

// The [label, code] entry for the technical details of a code the catalog has no label for; none for
// a known or missing one.
export function unknownCode(t, prefix, value) {
  return isMissing(value) || hasLabel(t, prefix, value) ? [] : [[t("tech.code"), value]];
}

// The shown text, followed by a fold with the raw code when the text says "unknown (technical details)".
function withCode(t, prefix, value, shown) {
  const fold = techDetails(t, unknownCode(t, prefix, value));
  return fold ? h("span", { class: "cell-stack" }, shown, fold) : shown;
}

// A label for a code (an alert kind, say): the text alone when the catalog knows it, else "unknown"
// with the code folded beside it.
export function codeLabel(t, prefix, value) {
  return withCode(t, prefix, value, labelOr(t, prefix, value));
}

// An unknown state or severity says "unknown" and keeps its code in a fold beside the pill.
// `{ fold: false }` leaves the code to a caller that holds it in a fold of its own (a row that is a
// link cannot hold a fold).
export function statePill(t, state, { fold = true } = {}) {
  const pill = h("span", { class: ["pill", `pill-${stateGroup(state)}`], text: labelOr(t, "state", state) });
  return fold ? withCode(t, "state", state, pill) : pill;
}

// A state pill that stays the same element while the state does, for a part its page draws again on
// every poll: a fold the reader opened beside it stays open until the state changes.
export function statePillKeeper(t) {
  let shown;
  let kept = null;
  return (state) => {
    if (kept === null || state !== shown) {
      shown = state;
      kept = statePill(t, state);
    }
    return kept;
  };
}

export function severityPill(t, severity, { fold = true } = {}) {
  const group = SEVERITY_GROUP.get(String(severity)) || "other";
  const pill = h("span", { class: ["pill", `pill-${group}`], text: labelOr(t, "severity", severity) });
  return fold ? withCode(t, "severity", severity, pill) : pill;
}
