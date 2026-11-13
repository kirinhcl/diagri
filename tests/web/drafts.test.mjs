import test from "node:test";
import assert from "node:assert/strict";
import {
  clearDrafts,
  handOver,
  saveDraft,
  stripSecrets,
  takeDraft,
} from "../../src/growbridge/web/workbench/drafts.js";

test("takeDraft returns a draft once", () => {
  saveDraft("k", { a: 1 });
  assert.deepEqual(takeDraft("k"), { a: 1 });
  assert.equal(takeDraft("k"), null);
});

test("saved drafts are copies", () => {
  const v = { a: 1 };
  saveDraft("c", v);
  v.a = 2;
  assert.deepEqual(takeDraft("c"), { a: 1 });
});

test("clearDrafts drops every draft", () => {
  saveDraft("one", { a: 1 });
  saveDraft("two", { b: 2 });
  clearDrafts();
  assert.equal(takeDraft("one"), null);
  assert.equal(takeDraft("two"), null);
});

test("a different operator signing in drops the drafts, the same one keeps them", () => {
  saveDraft("form", { a: 1 });
  assert.equal(handOver("ann", "ann"), false);
  assert.equal(handOver(null, "bob"), false);
  assert.deepEqual(takeDraft("form"), { a: 1 });
  saveDraft("form", { a: 2 });
  assert.equal(handOver("ann", "bob"), true);
  assert.equal(takeDraft("form"), null);
});

test("stripSecrets removes password fields", () => {
  const input = { name: "x", password: "p", secret: "s" };
  assert.deepEqual(stripSecrets(input, ["password", "secret"]), { name: "x" });
  assert.deepEqual(input, { name: "x", password: "p", secret: "s" });
});
