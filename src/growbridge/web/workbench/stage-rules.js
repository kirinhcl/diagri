// Which stage controls the page offers in which state. The server stays the judge: this only
// decides what is shown, and a refused action still shows the server's reason.

// Irrigation needs the on-site entry; the server refuses it elsewhere with code "entry".
const LAN_ONLY = new Set(["irrigation"]);

const ACTIONS_BY_STATE = new Map([
  ["pending_review", ["approve", "start", "draft"]],
  ["running", ["pause", "stop", "takeover"]],
  ["paused", ["resume", "stop", "takeover"]],
  ["manual", ["manual", "irrigation", "handback", "stop"]],
  ["recovery_check", ["onsite_check"]],
]);

function actionsOf(stageState) {
  return ACTIONS_BY_STATE.get(String(stageState)) || [];
}

// The actions to offer for this state on this entry, in display order (a fresh array).
export function availableActions(stageState, entry) {
  return actionsOf(stageState).filter((action) => entry === "lan" || !LAN_ONLY.has(action));
}

// The actions this state would offer but the entry holds back; shown disabled with the reason.
export function heldByEntry(stageState, entry) {
  if (entry === "lan") return [];
  return actionsOf(stageState).filter((action) => LAN_ONLY.has(action));
}
