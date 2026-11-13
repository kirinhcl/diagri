// Device writes whose result is not settled yet. The page may render again, or the form be
// submitted a second time, while an answer is still missing; the write may already have happened,
// so an identical resubmission must carry the same request id and the server can tell it is the
// same write. The map is module level so it outlives any one render. A different body is a new
// write; an entry goes when its receipt settles (applied, failed, or unknown as the final word).
import { newRequestId } from "./receipts.js";

// An intent lives at most INTENT_TTL_MS: an id older than that is never reused, so a genuinely new
// identical write cannot be answered with the stored receipt of an old one.
export const INTENT_TTL_MS = 5 * 60 * 1000;

const unsettled = new Map(); // key -> { signature, id, at }

export const intentKey = (stageId, action) => `${stageId}|${action}`;

// { id, reused }: reused is true when an identical, unexpired, unsettled write already holds an id.
export function claimIntent(key, body, { makeId = newRequestId, now = Date.now } = {}) {
  const signature = JSON.stringify(body);
  const at = now();
  const held = unsettled.get(key);
  if (held && held.signature === signature && at - held.at < INTENT_TTL_MS) return { id: held.id, reused: true };
  const id = makeId();
  unsettled.set(key, { signature, id, at });
  return { id, reused: false };
}

export const idForIntent = (key, body, makeId = newRequestId, now = Date.now) => claimIntent(key, body, { makeId, now }).id;

// Clears the entry, but only for the request id it was made for: a receipt that settles late must
// not drop the entry of a newer, different write.
export function settleIntent(key, id) {
  const held = unsettled.get(key);
  if (held && held.id === id) unsettled.delete(key);
}

// Runs `settle` once the follow-up ends by any path: a final outcome, a timeout, the page being
// left, or a rejection. The promise keeps its own result or error.
export const afterTerminal = (promise, settle) => Promise.resolve(promise).finally(settle);

// A resent request is said so in the action log, so a stored receipt is not taken for a new write.
export const resentHeading = (heading, resentText, reused) => (reused ? `${heading} (${resentText})` : heading);

export const unsettledCount = () => unsettled.size;
export const clearIntents = () => unsettled.clear();
