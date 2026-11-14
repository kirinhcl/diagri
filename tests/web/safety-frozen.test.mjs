import assert from "node:assert/strict";
import test from "node:test";

import { frozenRows } from "../../src/growbridge/web/workbench/pages/safety-frozen.js";

test("frozenRows lists the sensors in name order", () => {
  assert.deepEqual(frozenRows({ minutes: { temp: 120, co2: 60 } }), [
    ["co2", 60],
    ["temp", 120],
  ]);
});

test("frozenRows is empty when there is nothing to show", () => {
  assert.deepEqual(frozenRows(undefined), []);
  assert.deepEqual(frozenRows(null), []);
  assert.deepEqual(frozenRows("x"), []);
  assert.deepEqual(frozenRows({}), []);
  assert.deepEqual(frozenRows({ minutes: {} }), []);
});
