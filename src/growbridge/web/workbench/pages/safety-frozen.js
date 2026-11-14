// The frozen-reading thresholds of an approved safety set, as table rows. Pure: no DOM.

// [sensor, minutes] pairs in sensor-name order; nothing when `frozen` is absent or malformed.
export function frozenRows(frozen) {
  if (frozen === null || typeof frozen !== "object") return [];
  const { minutes } = frozen;
  if (minutes === null || typeof minutes !== "object") return [];
  return Object.entries(minutes).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
}
