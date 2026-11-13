import assert from "node:assert/strict";
import test from "node:test";

import { enterFields } from "../../src/growbridge/web/workbench/pages/evidence.js";
import { versionMismatch } from "../../src/growbridge/web/workbench/pages/round-analysis.js";

const ctx = { t: (key) => `t:${key}` };

test("entering evidence makes the operator choose whether it was calibrated: no default", () => {
  const calibrated = enterFields(ctx).find((field) => field.name === "calibrated");
  assert.equal(calibrated.required, true);
  assert.equal(calibrated.value, undefined);
  assert.deepEqual(
    calibrated.options.map((option) => option.value),
    ["", "yes", "no"],
  );
});

test("the analysis block says when the protocol's latest version is not the round's", () => {
  assert.equal(versionMismatch({ version: 2 }, { protocol_version: 2 }), null);
  assert.deepEqual(versionMismatch({ version: 3 }, { protocol_version: 2 }), { latest: 3, round: 2 });
});
