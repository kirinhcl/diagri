import assert from "node:assert/strict";
import test from "node:test";

import {
  RECEIPT_INTERVAL_MS,
  RECEIPT_LIMIT_MS,
  newRequestId,
  pollReceipt,
  receiptOutcome,
  sleep,
} from "../../src/growbridge/web/workbench/receipts.js";

const record = (state) => ({ request_id: "wb-test-0001", state });

// A fake clock: sleeping moves it forward, fetching takes no time.
function fakeTime() {
  const clock = { at: 1_000_000, slept: [] };
  clock.now = () => clock.at;
  clock.sleep = async (ms, signal) => {
    if (signal && signal.aborted) return;
    clock.slept.push(ms);
    clock.at += ms;
  };
  return clock;
}

function fetcher(states) {
  const calls = { count: 0 };
  calls.fetch = async () => {
    const state = states[Math.min(calls.count, states.length - 1)];
    calls.count += 1;
    if (state instanceof Error) throw state;
    return record(state);
  };
  return calls;
}

test("the poll runs every 2 seconds for at most 60 seconds", () => {
  assert.equal(RECEIPT_INTERVAL_MS, 2000);
  assert.equal(RECEIPT_LIMIT_MS, 60000);
});

test("receiptOutcome maps the action states to applied, unknown and failed", () => {
  assert.equal(receiptOutcome(record("confirmed")), "applied");
  assert.equal(receiptOutcome(record("unknown")), "unknown");
  assert.equal(receiptOutcome(record("failed")), "failed");
  assert.equal(receiptOutcome(record("void")), "failed");
  assert.equal(receiptOutcome(record("pending")), null);
  assert.equal(receiptOutcome(record("maybe_sent")), null);
  assert.equal(receiptOutcome(null), null);
  assert.equal(receiptOutcome({}), null);
});

test("a record that is already settled is not fetched again", async () => {
  const clock = fakeTime();
  const calls = fetcher(["pending"]);
  const result = await pollReceipt({ initial: record("confirmed"), fetchReceipt: calls.fetch, ...clock });
  assert.equal(result.outcome, "applied");
  assert.equal(calls.count, 0);
  assert.deepEqual(clock.slept, []);
});

test("a pending record is fetched every 2 seconds until it settles", async () => {
  const clock = fakeTime();
  const calls = fetcher(["maybe_sent", "pending", "confirmed"]);
  const updates = [];
  const result = await pollReceipt({
    initial: record("pending"),
    fetchReceipt: calls.fetch,
    onUpdate: (update) => updates.push(update.record.state),
    ...clock,
  });
  assert.equal(result.outcome, "applied");
  assert.equal(result.record.state, "confirmed");
  assert.equal(calls.count, 3);
  assert.deepEqual(clock.slept, [2000, 2000, 2000]);
  assert.deepEqual(updates, ["maybe_sent", "pending", "confirmed"]);
});

test("an unknown or failed result ends the poll", async () => {
  for (const [state, outcome] of [
    ["unknown", "unknown"],
    ["failed", "failed"],
  ]) {
    const clock = fakeTime();
    const calls = fetcher([state]);
    const result = await pollReceipt({ initial: record("pending"), fetchReceipt: calls.fetch, ...clock });
    assert.equal(result.outcome, outcome);
    assert.equal(calls.count, 1);
  }
});

test("a result that never settles stops after 60 seconds", async () => {
  const clock = fakeTime();
  const calls = fetcher(["pending"]);
  const result = await pollReceipt({ initial: record("pending"), fetchReceipt: calls.fetch, ...clock });
  assert.equal(result.outcome, "timeout");
  assert.equal(result.record.state, "pending");
  assert.equal(calls.count, 30);
  assert.equal(clock.at - 1_000_000, 60000);
});

test("the last wait is cut short so the limit is never passed", async () => {
  const clock = fakeTime();
  const calls = fetcher(["pending"]);
  await pollReceipt({ initial: record("pending"), fetchReceipt: calls.fetch, ...clock, intervalMs: 7000, limitMs: 20000 });
  assert.deepEqual(clock.slept, [7000, 7000, 6000]);
  assert.equal(calls.count, 3);
});

test("a failed fetch is reported and tried again at the next tick", async () => {
  const clock = fakeTime();
  const calls = fetcher([new Error("offline"), "confirmed"]);
  const errors = [];
  const result = await pollReceipt({
    initial: record("pending"),
    fetchReceipt: calls.fetch,
    onUpdate: (update) => errors.push(update.error ? update.error.message : null),
    ...clock,
  });
  assert.equal(result.outcome, "applied");
  assert.equal(result.error, null);
  assert.deepEqual(errors, ["offline", null]);
});

test("a timeout keeps the last fetch error", async () => {
  const clock = fakeTime();
  const calls = fetcher([new Error("offline")]);
  const result = await pollReceipt({ initial: record("pending"), fetchReceipt: calls.fetch, ...clock });
  assert.equal(result.outcome, "timeout");
  assert.equal(result.error.message, "offline");
  assert.equal(result.record.state, "pending");
});

test("leaving the page stops the poll before the next fetch", async () => {
  const clock = fakeTime();
  const controller = new AbortController();
  const calls = fetcher(["pending"]);
  const result = await pollReceipt({
    initial: record("pending"),
    fetchReceipt: calls.fetch,
    signal: controller.signal,
    onUpdate: () => {
      if (calls.count === 2) controller.abort();
    },
    ...clock,
  });
  assert.equal(result.outcome, "stopped");
  assert.equal(calls.count, 2);
});

test("an inactive page stops the poll too", async () => {
  const clock = fakeTime();
  let active = true;
  const calls = fetcher(["pending"]);
  const result = await pollReceipt({
    initial: record("pending"),
    fetchReceipt: calls.fetch,
    isActive: () => active,
    onUpdate: () => {
      active = false;
    },
    ...clock,
  });
  assert.equal(result.outcome, "stopped");
  assert.equal(calls.count, 1);
});

test("an already aborted signal fetches nothing", async () => {
  const clock = fakeTime();
  const controller = new AbortController();
  controller.abort();
  const calls = fetcher(["confirmed"]);
  const result = await pollReceipt({ initial: record("pending"), fetchReceipt: calls.fetch, signal: controller.signal, ...clock });
  assert.equal(result.outcome, "stopped");
  assert.equal(calls.count, 0);
});

test("sleep ends at once and leaves no timer when the signal aborts", async () => {
  const controller = new AbortController();
  const started = Date.now();
  const waiting = sleep(60000, controller.signal);
  controller.abort();
  await waiting;
  await sleep(60000, controller.signal);
  // A timer left behind would keep this test file running for a minute.
  assert.ok(Date.now() - started < 1000);
});

test("sleep waits the given time without a signal", async () => {
  const started = Date.now();
  await sleep(20);
  assert.ok(Date.now() - started >= 15);
});

test("request ids match the server's pattern and differ each time", () => {
  const pattern = /^[a-zA-Z0-9_-]{8,100}$/;
  const first = newRequestId();
  const second = newRequestId();
  assert.match(first, pattern);
  assert.match(second, pattern);
  assert.notEqual(first, second);
  assert.ok(first.startsWith("wb-"));
});
