// The change list shown before safety limits are approved: one line per change, "path: old → new".
const SERVER_STAMPED = new Set(["approved_by", "approved_at"]);

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
