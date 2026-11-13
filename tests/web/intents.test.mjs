import assert from "node:assert/strict";
import test from "node:test";

import {
  clearIntents,
  idForIntent,
  intentKey,
  settleIntent,
  settlesIntent,
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

test("only a final receipt outcome settles an intent", () => {
  for (const outcome of ["applied", "failed", "unknown"]) assert.equal(settlesIntent(outcome), true);
  for (const outcome of ["timeout", "stopped", "unsettled", undefined]) assert.equal(settlesIntent(outcome), false);
});
