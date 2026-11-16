import assert from "node:assert/strict";
import test from "node:test";

import { differenceText } from "../../src/growbridge/web/workbench/pages/stage-diff.js";
import { detailLines, HISTORY_SHOWN, historyView, timeline } from "../../src/growbridge/web/workbench/pages/stage-history.js";
import { assertNoLeaks, countPills, visibleText } from "./support/leaks.mjs";
import { FIXTURES, installFakeDom, testCtx } from "./support/render-page.mjs";

installFakeDom();

test("events read as sentences and same-state moves show no pills", () => {
  const ctx = testCtx({ lang: "zh" });
  const view = historyView(ctx, { history: [{ at: 10, from: "running", to: "running", event: "end_condition_met", detail: { confirmed: true, right_number: 3 } }], interventions: [] });
  assert.match(visibleText(view), /结束条件已满足/);
  assert.equal(countPills(view), 0);
  assertNoLeaks(view);
});

test("a move between two states shows both pills", () => {
  const view = historyView(testCtx({ lang: "en" }), { history: [{ at: 10, from: "running", to: "paused", event: "pause", detail: {} }] });
  assert.equal(countPills(view), 2);
});

test("durations, times and reasons are written for people; raw values go to the details", () => {
  const { lines, raw } = detailLines(testCtx({ lang: "zh" }), { type: "transition", event: "disconnect_affects", detail: { reasons: ["due_action", "gap_too_long"], seconds: 412.6, state_unreadable: false } });
  assert.ok(lines.some((l) => l.includes("7 分钟")));
  assert.ok(!lines.join(" ").includes("due_action"));
  assert.ok(raw.length >= 1);
});

test("unexpected watering shows labelled times, not epoch seconds", () => {
  const ctx = testCtx({ lang: "zh" });
  const [entry] = timeline([], [{ stage_id: "s", at: 1796594500, kind: "unexpected_watering", operator: null, status_at: 1796594400.2, off_confirmed: true, request_id: "req-77" }]);
  const { lines, raw } = detailLines(ctx, entry);
  assert.ok(lines.length >= 2);
  assert.ok(!lines.join(" ").includes("1796594400"));
  assert.ok(raw.some(([, value]) => value === "req-77"));
});

test("an unknown event says unknown and keeps the code in the details", () => {
  const ctx = testCtx({ lang: "zh" });
  const view = historyView(ctx, { history: [{ at: 10, from: "running", to: "running", event: "brand_new", detail: {} }] });
  assert.match(visibleText(view), /未知（技术详情）/);
  assert.ok(detailLines(ctx, { type: "transition", event: "brand_new", detail: {} }).raw.some(([, value]) => value === "brand_new"));
  assertNoLeaks(view);
});

test("free-text reasons and unknown keys stay in the details", () => {
  const { lines, raw } = detailLines(testCtx({ lang: "en" }), { type: "transition", event: "start", detail: { reason: "next stage starts", novel_key: 1, on_expiry: "stay_paused" } });
  assert.deepEqual(lines, ["When the wait ran out: the stage stays paused"]);
  assert.ok(raw.some(([, value]) => value === "next stage starts"));
  assert.ok(raw.some(([label]) => label === "novel_key"));
});

test("newest first; a transition and an intervention of the same second keep a fixed order", () => {
  const rows = timeline([{ at: 5, from: "a", to: "b", event: "start" }], [{ at: 5, kind: "takeover" }, { at: 9, kind: "accepted" }]);
  assert.deepEqual(rows.map((r) => r.type + r.at), ["intervention9", "intervention5", "transition5"]);
});

test("beyond twenty entries the newest stay on top and the rest fold away", () => {
  const history = Array.from({ length: HISTORY_SHOWN + 5 }, (_, i) => ({ at: 100 + i, from: "running", to: "running", event: "start", detail: {} }));
  const view = historyView(testCtx({ lang: "zh" }), { history });
  const [shown, fold] = view.childNodes;
  assert.equal(shown.childNodes.length, HISTORY_SHOWN);
  assert.match(visibleText(fold), /更早的 5 条/);
  assert.equal(shown.childNodes[0].childNodes[0].getAttribute("datetime"), new Date((100 + HISTORY_SHOWN + 4) * 1000).toISOString());
});

test("differences read as sentences", () => {
  const t = testCtx({ lang: "zh" }).t;
  assert.equal(differenceText(t, { channel: "light", field: "level", expected: 50, actual: 0 }), "灯光档位：应为 50 %，实际 0 %");
  assert.match(differenceText(t, { channel: "fan", field: "level", expected: 3, actual: null }), /实际 —/);
});

test("the history fixture renders without leaks", () => {
  assertNoLeaks(historyView(testCtx({ lang: "en" }), FIXTURES["history.json"]));
  assertNoLeaks(historyView(testCtx({ lang: "zh" }), FIXTURES["history-pending.json"]));
});

test("server-shaped pause and unknown-result details keep ids out of the body", () => {
  const details = [
    ["alert_pause", { rule: "Soil too dry", alert: "alert_9d38ffa4ca3049948194e0b60315c650" }],
    ["rule_pause", { rule: "frozen:soil_moisture", alert: "alert_9d38ffa4ca3049948194e0b60315c650", period: "frozen_9d38ffa4ca3049948194e0b60315c650" }],
    ["result_unknown", { request_ids: ["write_9d38ffa4ca3049948194e0b60315c650", "write_abc"], right_number: 3 }],
  ];
  for (const lang of ["zh", "en"]) {
    const ctx = testCtx({ lang });
    const history = details.map(([event, detail], i) => ({ at: 10 + i, from: "running", to: "paused", event, detail }));
    assertNoLeaks(historyView(ctx, { history }));
    const { lines, raw } = detailLines(ctx, { type: "transition", event: "rule_pause", detail: details[1][1] });
    assert.equal(lines.length, 1);
    assert.ok(raw.some(([, value]) => value === details[1][1].period));
  }
});

test("a level is written against its scale", () => {
  const ctx = testCtx({ lang: "zh" });
  const { lines } = detailLines(ctx, { type: "transition", event: "end_actions", detail: { channel: "light", level: 50 } });
  assert.ok(lines.some((l) => l.includes("50 %")));
});
