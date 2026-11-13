import assert from "node:assert/strict";
import test from "node:test";

import { approveBody, availableActions, heldByEntry, sheetCheck } from "../../src/growbridge/web/workbench/stage-rules.js";

test("approval goes ahead only for the run sheet digest the operator reviewed", () => {
  assert.equal(sheetCheck("sha-a", "sha-a"), "same");
  assert.equal(sheetCheck("sha-a", "sha-b"), "changed");
  assert.equal(sheetCheck("sha-a", undefined), "changed"); // an answer without a digest proves nothing
  assert.equal(sheetCheck(null, "sha-a"), "unread");
  assert.equal(sheetCheck("", "sha-a"), "unread");
});

test("each stage state offers the actions of the plan's table", () => {
  assert.deepEqual(availableActions("pending_review", "lan"), ["approve", "start", "draft"]);
  assert.deepEqual(availableActions("running", "lan"), ["pause", "stop", "takeover"]);
  assert.deepEqual(availableActions("paused", "lan"), ["resume", "stop", "takeover"]);
  assert.deepEqual(availableActions("manual", "lan"), ["manual", "irrigation", "handback", "stop"]);
  assert.deepEqual(availableActions("recovery_check", "lan"), ["onsite_check"]);
});

test("irrigation is offered on the on-site entry only", () => {
  assert.deepEqual(availableActions("manual", "overlay"), ["manual", "handback", "stop"]);
  assert.deepEqual(availableActions("manual", null), ["manual", "handback", "stop"]);
  assert.deepEqual(availableActions("manual", undefined), ["manual", "handback", "stop"]);
});

test("the remote entry changes nothing but irrigation", () => {
  for (const state of ["pending_review", "running", "paused", "recovery_check"]) {
    assert.deepEqual(availableActions(state, "overlay"), availableActions(state, "lan"), state);
  }
});

test("finished and unknown states offer nothing", () => {
  for (const state of ["ended", "stopped", "no_such_state", "", null, undefined, "__proto__", "constructor"]) {
    assert.deepEqual(availableActions(state, "lan"), [], String(state));
  }
});

test("heldByEntry names what the entry holds back, so it can be shown disabled", () => {
  assert.deepEqual(heldByEntry("manual", "overlay"), ["irrigation"]);
  assert.deepEqual(heldByEntry("manual", null), ["irrigation"]);
  assert.deepEqual(heldByEntry("manual", "lan"), []);
  assert.deepEqual(heldByEntry("running", "overlay"), []);
  assert.deepEqual(heldByEntry("constructor", "overlay"), []);
});

test("the returned lists are fresh copies", () => {
  const first = availableActions("running", "lan");
  first.push("irrigation");
  first.length = 0;
  assert.deepEqual(availableActions("running", "lan"), ["pause", "stop", "takeover"]);
  const held = heldByEntry("manual", "overlay");
  held.pop();
  assert.deepEqual(heldByEntry("manual", "overlay"), ["irrigation"]);
});

test("the approve request carries the reviewed digest for the server to hold it to", () => {
  assert.deepEqual(approveBody("sha-a"), { expected_digest: "sha-a" });
});
