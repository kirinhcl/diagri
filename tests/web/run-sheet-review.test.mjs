import assert from "node:assert/strict";
import test from "node:test";

import { groupFindings, findingsList } from "../../src/growbridge/web/workbench/pages/stage-actions.js";
import { reviewView, sectionOrder } from "../../src/growbridge/web/workbench/pages/stage.js";
import { installFakeDom, FIXTURES, renderPage, testCtx } from "./support/render-page.mjs";
import { assertNoLeaks, exemptStrings, visibleText, visibleTextIncludingDetails } from "./support/leaks.mjs";

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
    assert.ok(text.includes(lang === "zh" ? "协议「protocol-lettuce-light」，第 1 版" : "Protocol “protocol-lettuce-light”, version 1"), text);
    assertNoLeaks(view, exemptStrings("stage", FIXTURES));
  }
});

test("the review calls a protocol the console saved by its number, and keeps its id beside the fingerprint", () => {
  const id = "protocol-2-9abf5a";
  const base = FIXTURES["run-sheet.json"];
  const review = { ...base, run_sheet: { ...base.run_sheet, protocol_id: id } };
  for (const [lang, name] of [["zh", "协议 2，第 1 版"], ["en", "Protocol 2, version 1"]]) {
    const ctx = testCtx({ lang });
    const view = reviewView(ctx, review);
    assert.ok(visibleText(view).includes(name), visibleText(view));
    assert.ok(!visibleText(view).includes(id));
    const ids = [...view.children].at(-1);
    assert.ok(ids.textContent.includes(ctx.t("tech.id.protocol_id")) && ids.textContent.includes(id), "the id fold names the protocol id");
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

// --- final review: the run sheet's hash has one name, fingerprint (F10) -------------------------
import { makeT } from "../../src/growbridge/web/workbench/i18n.js";

test("every label of the run sheet's hash calls it a fingerprint, never a digest", () => {
  const keys = ["stage.review.fingerprint", "stage.review.digest", "stage.approve.digestApproved", "stage.approve.digestReviewed", "history.field.digest"];
  const zh = makeT("zh");
  const en = makeT("en");
  for (const key of keys) {
    assert.match(zh(key), /指纹/, key);
    assert.doesNotMatch(zh(key), /摘要/, key);
    assert.match(en(key), /fingerprint/i, key);
    assert.doesNotMatch(en(key), /digest/i, key);
  }
});

const SENTENCE_FINDINGS = [
  { code: "manual_task", blocking: false, message: "manual irrigation irrigate-daily needs the user at 09:00", variant: "irrigation", params: { task_id: "irrigate-daily", at_local: "09:00", seconds: 20 } },
  { code: "manual_task", blocking: false, message: "manual photo canopy-photo needs the user at 10:00", variant: "", params: { task_kind: "photo", task_id: "canopy-photo", at_local: "10:00" } },
];

test("each finding reads as a sentence and its group says how to fix it once", () => {
  const ctx = testCtx({ lang: "en" });
  const node = findingsList(ctx, SENTENCE_FINDINGS);
  const text = visibleText(node);
  assert.match(text, /Someone must be on site every day at 09:00 to start a/);
  assert.match(text, /Photo task: someone must be on site every day at 10:00\./);
  assert.ok(!text.includes("irrigate-daily") && !text.includes("manual irrigation"));
  assert.equal(text.split(ctx.t("stage.review.howToFix")).length - 1, 1);
  assert.match(text, /How to fix:/);
  const all = visibleTextIncludingDetails(node);
  assert.ok(all.includes("irrigate-daily") && all.includes("manual photo canopy-photo needs the user at 10:00"));
  assert.ok(all.includes("manual_task.irrigation"));
});

test("a finding the catalog lacks says unknown and keeps the server's words in the details", () => {
  const ctx = testCtx({ lang: "en" });
  const node = findingsList(ctx, [{ code: "brand_new", blocking: true, message: "server words here", variant: "", params: {} }]);
  assert.ok(visibleText(node).includes(ctx.t("common.unknown")));
  assert.ok(!visibleText(node).includes("server words here"));
  assert.ok(visibleTextIncludingDetails(node).includes("server words here"));
});

test("a finding without params or variant still reads (old data)", () => {
  const ctx = testCtx({ lang: "en" });
  const node = findingsList(ctx, [{ code: "no_evidence", blocking: true, message: "old" }]);
  assert.ok(!visibleText(node).includes("old"));
});

test("a name a planner chose is shown in quotes", () => {
  const ctx = testCtx({ lang: "en" });
  const fx = FIXTURES["run-sheet.json"].findings;
  const text = visibleText(findingsList(ctx, fx));
  assert.ok(text.includes("\u201clight-on\u201d") || text.includes('"light-on"'), text);
  assertNoLeaks(findingsList(ctx, fx), exemptStrings("stage"));
});

const walk = (node, match) => [...(match(node) ? [node] : []), ...[...(node.children || [])].flatMap((child) => walk(child, match))];
const settleAll = async () => {
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
};

test("the stage page changes a run sheet with a form, the full JSON stays in a closed fold, and an unchanged form posts the sheet as read", async () => {
  const { element, ctx } = await renderPage("stage", { stageId: FIXTURES["stage-pending.json"].stage_id }, { lang: "en" });
  const group = walk(element, (el) => el.localName === "div" && el.getAttribute("data-action") === "draft")[0];
  const forms = walk(group, (el) => el.localName === "form");
  assert.equal(forms.length, 2, "the form and the JSON editor");
  const fold = walk(group, (el) => el.localName === "details")[0];
  assert.equal(fold.hasAttribute("open"), false, "the JSON fold starts closed");
  assert.ok(walk(fold, (el) => el.localName === "form").length === 1 && walk(fold, (el) => el.localName === "summary")[0].textContent === ctx.t("forms.advanced"));
  forms[0].dispatchEvent(new Event("submit", { cancelable: true }));
  await settleAll();
  const post = ctx.api.calls.find((call) => call.method === "POST" && call.path === "/drafts/run-sheet");
  assert.ok(post, "the form posts the draft");
  const review = FIXTURES["run-sheet-pending.json"];
  assert.equal(JSON.stringify(post.body), JSON.stringify({ round_id: FIXTURES["stage-pending.json"].round_id, run_sheet: review.run_sheet }));
});

test("the run-sheet form and its JSON fold have different submit buttons, in both languages", async () => {
  for (const lang of ["en", "zh"]) {
    const { element, ctx } = await renderPage("stage", { stageId: FIXTURES["stage-pending.json"].stage_id }, { lang });
    const group = walk(element, (el) => el.localName === "div" && el.getAttribute("data-action") === "draft")[0];
    const [formButton, jsonButton] = walk(group, (el) => el.localName === "form").map((form) => walk(form, (el) => el.localName === "button" && el.getAttribute("type") === "submit")[0].textContent);
    assert.notEqual(formButton, jsonButton, lang);
    assert.equal(formButton, ctx.t("stage.draft.submit"));
    assert.equal(jsonButton, ctx.t("stage.draft.submitJson"));
  }
});
