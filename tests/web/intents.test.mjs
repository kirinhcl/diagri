import assert from "node:assert/strict";
import test from "node:test";

import {
  settleOnFinal,
  clearIntents,
  clearOnHandOver,
  idForIntent,
  intentKey,
  settleIntent,
  claimIntent,
  INTENT_TTL_MS,
  resentHeading,
  unsettledCount,
} from "../../src/growbridge/web/workbench/intents.js";

const body = { stage_id: "s1", level: 40, note: "" };

function counter() {
  let made = 0;
  return () => `wb-id-${++made}`;
}

test("an identical resubmission reuses the id, also from a fresh render", () => {
  clearIntents();
  const makeId = counter();
  const key = intentKey("s1", "manual:light");
  const first = idForIntent(key, body, makeId);
  // a re-render builds new forms but asks the same module-level map
  assert.equal(idForIntent(key, { ...body }, makeId), first);
  assert.equal(unsettledCount(), 1);
});

test("a different body is a new write with a new id", () => {
  clearIntents();
  const makeId = counter();
  const key = intentKey("s1", "manual:light");
  const first = idForIntent(key, body, makeId);
  const second = idForIntent(key, { ...body, level: 41 }, makeId);
  assert.notEqual(second, first);
  assert.equal(unsettledCount(), 1);
});

test("channels and stages keep their own intents", () => {
  clearIntents();
  const makeId = counter();
  const light = idForIntent(intentKey("s1", "manual:light"), body, makeId);
  const fan = idForIntent(intentKey("s1", "manual:fan"), body, makeId);
  const other = idForIntent(intentKey("s2", "manual:light"), body, makeId);
  assert.equal(new Set([light, fan, other]).size, 3);
  assert.equal(idForIntent(intentKey("s1", "manual:light"), body, makeId), light);
});

test("a settled intent is cleared, so the next write is a new action", () => {
  clearIntents();
  const makeId = counter();
  const key = intentKey("s1", "irrigation");
  const first = idForIntent(key, body, makeId);
  settleIntent(key, first);
  assert.equal(unsettledCount(), 0);
  assert.notEqual(idForIntent(key, body, makeId), first);
});

test("an older receipt settling does not clear a newer intent", () => {
  clearIntents();
  const makeId = counter();
  const key = intentKey("s1", "irrigation");
  const old = idForIntent(key, body, makeId);
  const newer = idForIntent(key, { ...body, seconds: 5 }, makeId);
  settleIntent(key, old);
  assert.equal(idForIntent(key, { ...body, seconds: 5 }, makeId), newer);
});

test("an intent expires after the TTL and an expired id is never reused", () => {
  clearIntents();
  const makeId = counter();
  const key = intentKey("s1", "irrigation");
  assert.equal(INTENT_TTL_MS, 5 * 60 * 1000);
  const first = claimIntent(key, body, { makeId, now: () => 1000 });
  assert.equal(first.reused, false);
  const within = claimIntent(key, body, { makeId, now: () => 1000 + INTENT_TTL_MS - 1 });
  assert.deepEqual(within, { id: first.id, reused: true });
  const after = claimIntent(key, body, { makeId, now: () => 1000 + INTENT_TTL_MS });
  assert.equal(after.reused, false);
  assert.notEqual(after.id, first.id);
});

test("clearing all intents (session lost, operator changed) forgets every id", () => {
  clearIntents();
  const makeId = counter();
  const key = intentKey("s1", "irrigation");
  const first = idForIntent(key, body, makeId);
  clearIntents();
  assert.equal(unsettledCount(), 0);
  assert.notEqual(idForIntent(key, body, makeId), first);
});

test("the log heading says when an earlier request is resent", () => {
  assert.equal(resentHeading("Light 40", "Resent earlier request wb-1", false), "Light 40");
  assert.equal(resentHeading("Light 40", "Resent earlier request wb-1", true), "Light 40 (Resent earlier request wb-1)");
});

test("only a final outcome releases the intent; timeout, stopped and rejection keep it", async () => {
  for (const outcome of ["applied", "failed", "unknown"]) {
    let settled = 0;
    await settleOnFinal(Promise.resolve({ outcome }), () => (settled += 1));
    assert.equal(settled, 1, outcome);
  }
  for (const outcome of ["timeout", "stopped", "unsettled"]) {
    let settled = 0;
    await settleOnFinal(Promise.resolve({ outcome }), () => (settled += 1));
    assert.equal(settled, 0, outcome);
  }
  let settled = 0;
  await settleOnFinal(Promise.reject(new Error("poll broke")), () => (settled += 1)).catch(() => {});
  await settleOnFinal(Promise.resolve(undefined), () => (settled += 1));
  assert.equal(settled, 0);
});

test("a kept intent is reused while young and not once it expired", () => {
  clearIntents();
  const makeId = counter();
  const key = intentKey("s1", "irrigation");
  const first = claimIntent(key, body, { makeId, now: () => 0 });
  assert.equal(claimIntent(key, body, { makeId, now: () => INTENT_TTL_MS - 1 }).id, first.id);
  assert.notEqual(claimIntent(key, body, { makeId, now: () => INTENT_TTL_MS }).id, first.id);
});

test("only an operator change clears the intents, not a lost session", () => {
  clearIntents();
  const key = intentKey("s1", "irrigation");
  const first = idForIntent(key, body, counter());
  assert.equal(clearOnHandOver("alice", "alice"), false); // the same operator signed in again
  assert.equal(unsettledCount(), 1);
  assert.equal(idForIntent(key, body, counter()), first);
  assert.equal(clearOnHandOver("alice", "bob"), true);
  assert.equal(unsettledCount(), 0);
  assert.equal(clearOnHandOver(null, "bob"), false); // the first sign-in clears nothing
});
