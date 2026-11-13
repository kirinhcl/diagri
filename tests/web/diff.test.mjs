import assert from "node:assert/strict";
import test from "node:test";

import { configDiff } from "../../src/growbridge/web/workbench/diff.js";

test("configDiff lists changed, added and removed paths", () => {
  assert.deepEqual(configDiff({ a: 1, b: { c: [1, 2] } }, { a: 1, b: { c: [1, 3] }, d: 4 }), [
    { path: "b.c[1]", before: 2, after: 3 },
    { path: "d", before: undefined, after: 4 },
  ]);
  assert.deepEqual(configDiff({ a: 1, b: 2 }, { a: 1 }), [{ path: "b", before: 2, after: undefined }]);
});

test("configDiff of equal values is empty", () =>
  assert.deepEqual(configDiff({ a: [{ b: 1 }] }, { a: [{ b: 1 }] }), []));

test("configDiff reports array length changes and nested paths", () => {
  assert.deepEqual(configDiff({ a: [{ c: 1 }] }, { a: [{ c: 1 }, { c: 2 }] }), [
    { path: "a[1]", before: undefined, after: { c: 2 } },
  ]);
  assert.deepEqual(configDiff({ a: [{ c: 1 }] }, { a: [{ c: 5 }] }), [{ path: "a[0].c", before: 1, after: 5 }]);
});

test("configDiff reports a type change as one entry", () =>
  assert.deepEqual(configDiff({ a: { b: 1 } }, { a: 3 }), [{ path: "a", before: { b: 1 }, after: 3 }]));
