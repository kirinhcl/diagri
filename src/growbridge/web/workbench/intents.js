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

// Releases the intent only when the follow-up ends in a final outcome (applied, failed, unknown).
// A timeout, the page being left or a rejection says nothing about whether the write reached the
// device, so the intent stays (until it expires) and a resubmission carries the same id.
const FINAL = new Set(["applied", "failed", "unknown"]);
export const settleOnFinal = (promise, settle) =>
  Promise.resolve(promise).then((result) => {
    if (result && FINAL.has(result.outcome)) settle();
    return result;
  });

// A session lost and signed in again does not say what happened to a write; another operator
// taking over does start afresh. True when the intents were cleared.
export function clearOnHandOver(previousOperator, operator) {
  const changed = Boolean(previousOperator) && previousOperator !== operator;
  if (changed) unsettled.clear();
  return changed;
}

// A resent request is said so in the action log, so a stored receipt is not taken for a new write.
export const resentHeading = (heading, resentText, reused) => (reused ? `${heading} (${resentText})` : heading);

export const unsettledCount = () => unsettled.size;
export const clearIntents = () => unsettled.clear();
