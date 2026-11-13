// Device writes whose result is not settled yet. The page may render again, or the form be
// submitted a second time, while an answer is still missing; the write may already have happened,
// so an identical resubmission must carry the same request id and the server can tell it is the
// same write. The map is module level so it outlives any one render. A different body is a new
// write; an entry goes when its receipt settles (applied, failed, or unknown as the final word).
import { newRequestId } from "./receipts.js";

const unsettled = new Map(); // key -> { signature, id }

export const intentKey = (stageId, action) => `${stageId}|${action}`;

export function idForIntent(key, body, makeId = newRequestId) {
  const signature = JSON.stringify(body);
  const held = unsettled.get(key);
  if (held && held.signature === signature) return held.id;
  const id = makeId();
  unsettled.set(key, { signature, id });
  return id;
}

// Clears the entry, but only for the request id it was made for: a receipt that settles late must
// not drop the entry of a newer, different write.
export function settleIntent(key, id) {
  const held = unsettled.get(key);
  if (held && held.id === id) unsettled.delete(key);
}

export const settlesIntent = (outcome) => outcome === "applied" || outcome === "failed" || outcome === "unknown";

export const unsettledCount = () => unsettled.size;
export const clearIntents = () => unsettled.clear();
