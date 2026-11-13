import test from "node:test";
import assert from "node:assert/strict";
import { saveDraft, stripSecrets, takeDraft } from "../../src/growbridge/web/workbench/drafts.js";

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

test("stripSecrets removes password fields", () => {
  const input = { name: "x", password: "p", secret: "s" };
  assert.deepEqual(stripSecrets(input, ["password", "secret"]), { name: "x" });
  assert.deepEqual(input, { name: "x", password: "p", secret: "s" });
});
