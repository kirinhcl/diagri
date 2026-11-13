// The change list shown before safety limits are approved: one line per change, "path: old → new".
const SERVER_STAMPED = new Set(["approved_by", "approved_at"]);

// Has the approved set changed since `before` was read? Version and approval time decide; without them the whole config does.
export function baselineChanged(before, after) {
  if (!before || !after) return Boolean(before) !== Boolean(after);
  if (before.version !== undefined || before.approved_at !== undefined) {
    return before.version !== after.version || before.approved_at !== after.approved_at;
  }
  return JSON.stringify(before) !== JSON.stringify(after);
}

export function formatValue(value, t) {
  return value === undefined ? t("safety.absent") : JSON.stringify(value);
}

// Who approved and when are written by the server, so an edit of them changes nothing.
export function visibleChanges(changes) {
  return changes.filter((change) => !SERVER_STAMPED.has(change.path));
}

export function diffLines(changes, t) {
  return changes.map((change) => `${change.path}: ${formatValue(change.before, t)} → ${formatValue(change.after, t)}`);
}
