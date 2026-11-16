import assert from "node:assert/strict";
import test from "node:test";

import { groupFindings, findingsList } from "../../src/growbridge/web/workbench/pages/stage-actions.js";
import { reviewView, sectionOrder } from "../../src/growbridge/web/workbench/pages/stage.js";
import { installFakeDom, FIXTURES, renderPage, testCtx } from "./support/render-page.mjs";
import { assertNoLeaks, exemptStrings, visibleText } from "./support/leaks.mjs";

installFakeDom();

const FINDINGS = [
  { code: "manual_task", blocking: false, message: "a" },
  { code: "no_evidence", blocking: true, message: "b" },
  { code: "manual_task", blocking: false, message: "c" },
];

test("blocking findings come first, grouped by code with counts", () => {
  const groups = groupFindings(FINDINGS);
  assert.deepEqual(groups.map((g) => [g.blocking, g.code, g.items.length]), [[true, "no_evidence", 1], [false, "manual_task", 2]]);
});

test("a code seen first as a hint and later as blocking is grouped by both", () => {
  const groups = groupFindings([{ code: "x", blocking: false, message: "1" }, { code: "x", blocking: true, message: "2" }]);
  assert.deepEqual(groups.map((g) => [g.blocking, g.items.length]), [[true, 1], [false, 1]]);
});

test("finding codes are shown as labels with counts, never as code", () => {
  const ctx = testCtx({ lang: "en" });
  const text = visibleText(findingsList(ctx, FINDINGS));
  assert.ok(!text.includes("manual_task") && !text.includes("no_evidence"));
  assert.match(text, /Manual task \(2\)/);
  assert.match(text, /No evidence \(1\)/);
  assert.ok(text.includes("a") && text.includes("c"));
});

test("the review shows days, a short fingerprint, a version and a simulated device", () => {
  for (const lang of ["zh", "en"]) {
    const ctx = testCtx({ lang });
    const review = FIXTURES["run-sheet.json"];
    const view = reviewView(ctx, review);
    const text = visibleText(view);
    assert.match(text, lang === "zh" ? /21 天/ : /21 days/);
    assert.match(text, /[0-9a-f]{8}…/);
    assert.ok(text.includes(ctx.t("stage.review.simulated")));
    assert.ok(text.includes(ctx.t("stage.review.versionValue", { n: review.run_sheet_version })));
    assert.ok(text.includes(ctx.t("stage.review.protocolValue", { id: review.run_sheet.protocol_id, v: review.run_sheet.protocol_version })));
    assertNoLeaks(view, exemptStrings("stage", FIXTURES));
  }
});

test("pending review puts the run sheet before the controls; running puts readings first", () => {
  const pending = sectionOrder("pending_review");
  assert.ok(pending.indexOf("runSheet") < pending.indexOf("controls"));
  const running = sectionOrder("running");
  assert.ok(running.indexOf("readings") < running.indexOf("controls"));
  assert.ok(running.indexOf("controls") < running.indexOf("runSheet"));
  assert.deepEqual(sectionOrder("paused"), running);
  assert.deepEqual(sectionOrder("ended"), ["status", "controls", "readings", "runSheet", "tasks", "measurements", "history"]);
});

const headings = (node) => [...(node.localName === "h2" ? [node.textContent] : []), ...[...(node.children || [])].flatMap(headings)];

test("the pending stage page lists the run sheet before the controls", async () => {
  for (const lang of ["zh", "en"]) {
    const { element } = await renderPage("stage", { stageId: FIXTURES["stage-pending.json"].stage_id }, { lang });
    const t = testCtx({ lang }).t;
    const order = headings(element);
    assert.ok(order.indexOf(t("stage.runSheet")) >= 0);
    assert.ok(order.indexOf(t("stage.runSheet")) < order.indexOf(t("stage.controls")), order.join("|"));
  }
});

test("the run sheet has its own fold, before the findings, and the id fold does not hold it", () => {
  const ctx = testCtx({ lang: "zh" });
  const view = reviewView(ctx, FIXTURES["run-sheet-pending.json"]);
  const folds = [];
  const walk = (node) => {
    if (node.localName === "details") folds.push(node);
    [...(node.children || [])].forEach(walk);
  };
  walk(view);
  const summary = (fold) => fold.children[0].textContent;
  assert.equal(summary(folds[0]), "运行单全文（JSON）");
  assert.ok(folds[0].textContent.includes("protocol_id"));
  const idFold = folds.find((fold) => summary(fold) === ctx.t("tech.title") && fold.textContent.includes(FIXTURES["run-sheet-pending.json"].run_sheet_digest));
  assert.ok(idFold && !idFold.textContent.includes("protocol_id"));
  const text = visibleText(view);
  assert.ok(visibleText(view).indexOf(ctx.t("stage.review.findings")) > text.indexOf(ctx.t("stage.review.fingerprint")));
  const all = [];
  const order = (node) => {
    all.push(node);
    [...(node.children || [])].forEach(order);
  };
  order(view);
  assert.ok(all.indexOf(folds[0]) < all.findIndex((n) => (n.getAttribute && n.getAttribute("class")) === "finding-group"));
});

test("a page refreshed with a running stage rearranges its regions", async () => {
  const { element, ctx, refresh } = await renderPage("stage", { stageId: FIXTURES["stage-pending.json"].stage_id }, { lang: "en" });
  const get = ctx.api.get;
  ctx.api.get = async (path, ...rest) => {
    const answer = await get(path, ...rest);
    return /\/stages\/[^/]+$/.test(path.split("?")[0]) ? { ...answer, state: "running" } : answer;
  };
  await refresh();
  const order = headings(element);
  const t = ctx.t;
  assert.ok(order.indexOf(t("stage.readings")) < order.indexOf(t("stage.controls")), order.join("|"));
});
