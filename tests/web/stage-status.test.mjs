import assert from "node:assert/strict";
import test from "node:test";

import { differenceLines, logItem, manualGroup, manualHeading } from "../../src/growbridge/web/workbench/pages/stage-actions.js";
import { statusView } from "../../src/growbridge/web/workbench/pages/stage.js";
import { installFakeDom, FIXTURES, testCtx } from "./support/render-page.mjs";
import { assertNoLeaks, visibleText, visibleTextIncludingDetails } from "./support/leaks.mjs";

installFakeDom();

const stage = { ...FIXTURES["stage.json"], paused_at: null, end_pending: false, right_number: 4, care_right: 2, manual_right: 1 };

test("status hides empty rows and keeps write rights in the details", () => {
  const ctx = testCtx({ lang: "zh" });
  const view = statusView(ctx, stage);
  const text = visibleText(view);
  assert.doesNotMatch(text, /暂停时间|写入权|结束条件/);
  assert.match(text, /Lettuce light series/);
  assert.match(text, /第 1 轮/);
  assert.doesNotMatch(text, new RegExp(stage.experiment_id));
  assertNoLeaks(view);
  const all = visibleTextIncludingDetails(view);
  assert.ok(all.includes(stage.experiment_id));
  assert.ok(all.includes("阶段写入权"));
});

test("a pending end shows a banner and a pause time shows its row", () => {
  const ctx = testCtx({ lang: "zh" });
  const text = visibleText(statusView(ctx, { ...stage, end_pending: true, paused_at: 1000 }));
  assert.match(text, /已到结束条件，正在确认结束动作。/);
  assert.match(text, /暂停时间/);
});

test("a level is written against its full scale", () => {
  const ctx = testCtx({ lang: "zh" });
  assert.equal(manualHeading(ctx, "fan", 3), "风扇调到 3 / 10");
  assert.equal(manualHeading(ctx, "light", 50), "灯光调到 50 %");
  const group = manualGroup({ ctx, stage, log: {}, onChanged() {} });
  assert.ok(group);
});

test("a log item says when it was sent and keeps the request id in the details", () => {
  const ctx = testCtx({ lang: "zh" });
  const item = logItem(ctx, "灯光调到 50 %", { request_id: "wb-abc123", created_at: 1000 });
  assert.doesNotMatch(visibleText(item.element), /wb-/);
  assert.match(visibleText(item.element), /发送于/);
  assert.ok(visibleTextIncludingDetails(item.element).includes("wb-abc123"));
});

test("hand-back differences use labels and units", () => {
  const ctx = testCtx({ lang: "zh" });
  const lines = differenceLines(ctx, [{ channel: "light", field: "level", expected: 50, actual: 0 }]);
  assert.ok(lines.includes("灯光档位：应为 50 %，实际 0 %"));
});
