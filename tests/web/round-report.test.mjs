import assert from "node:assert/strict";
import test from "node:test";

import en from "../../src/growbridge/web/workbench/i18n/en.js";
import { makeT } from "../../src/growbridge/web/workbench/i18n.js";
import { estimateText } from "../../src/growbridge/web/workbench/pages/round.js";

const ctx = { t: makeT("en") };

test("an estimate reads as effect, p value and blocks, or says why there is none", () => {
  assert.equal(estimateText(ctx, { estimable: true, effect: 0.42, p_value: 0.0312, blocks: 2 }), "Effect 0.42, p = 0.031, over 2 complete blocks");
  const none = { estimable: false, note: "fewer than 2 complete blocks; no treatment effect can be estimated" };
  assert.equal(estimateText(ctx, none), none.note);
  assert.equal(estimateText(ctx, { estimable: false }), en["report.notEstimable"]);
  assert.equal(estimateText(ctx, null), "—");
});

test("every label and conclusion the server writes has a text", () => {
  for (const label of ["confirmatory", "exploratory", "descriptive"]) assert.ok(en[`report.labels.${label}`], label);
  for (const c of ["supported", "not_supported", "uncertain"]) assert.ok(en[`report.conclusions.${c}`], c);
});
