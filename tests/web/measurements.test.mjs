import assert from "node:assert/strict";
import test from "node:test";

import { saveDraft } from "../../src/growbridge/web/workbench/drafts.js";
import { measurementForm, measurementOptions, measurementTable } from "../../src/growbridge/web/workbench/pages/stage-measurements.js";
import { timeText } from "../../src/growbridge/web/workbench/ui/section.js";
import { assertNoLeaks, visibleText, visibleTextIncludingDetails } from "./support/leaks.mjs";
import { FIXTURES, installFakeDom, testCtx } from "./support/render-page.mjs";

installFakeDom();

const settle = () => new Promise((resolve) => setImmediate(resolve));
const RECORDED = FIXTURES["measurements.json"].measurements;
const STAGE = FIXTURES["stage.json"];
const METRIC = RECORDED[0].metric; // an operator-chosen name, shown as recorded

function elements(node, name) {
  const own = node.tagName && node.tagName.toLowerCase() === name ? [node] : [];
  return [...own, ...(node.children || []).flatMap((child) => elements(child, name))];
}

// The buttons a row offers, without the copy buttons of its technical details.
function rowButtons(node) {
  if ((node.getAttribute && node.getAttribute("class")) === "tech-details") return [];
  const own = node.tagName && node.tagName.toLowerCase() === "button" ? [node.textContent] : [];
  return [...own, ...(node.children || []).flatMap(rowButtons)];
}

const input = (node, name) => elements(node, "input").find((element) => element.getAttribute("name") === name);
const rowsOf = (node) => elements(node, "tbody").flatMap((body) => elements(body, "tr"));

// A record and the one that corrects it, an hour later.
const original = { ...RECORDED[0], id: "measurement_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", measured_at: 1796590000 };
const correction = { ...RECORDED[0], id: "measurement_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", measured_at: 1796593600, value: 1.24, corrects: original.id };

test("measurement options are the distinct values already recorded", () => {
  assert.deepEqual(measurementOptions([{ metric: "canopy", unit: "cm2", method: "ruler" }, { metric: "canopy", unit: "cm2", method: "photo" }]), { metric: ["canopy"], unit: ["cm2"], method: ["photo", "ruler"] });
  assert.deepEqual(measurementOptions(undefined), { metric: [], unit: [], method: [] });
  assert.deepEqual(measurementOptions([{ metric: "", unit: null }]), { metric: [], unit: [], method: [] });
});

test("the measurement table shows six columns and folds the rest", () => {
  const ctx = testCtx({ lang: "zh" });
  const view = measurementTable(ctx, RECORDED, { onCorrect: () => {} });
  assert.deepEqual(elements(view, "th").map((th) => th.textContent), ["测量时间", "植株", "指标", "数值", "方法", "录入人"]);
  const text = visibleText(view);
  for (const hidden of [RECORDED[0].id, RECORDED[0].batch, RECORDED[0].layout_version, RECORDED[0].position]) assert.ok(!text.includes(hidden), hidden);
  assert.match(text, /plant-1/);
  assert.match(text, /1\.42 cm2\/day/);
  assertNoLeaks(view, [METRIC]);
  const all = visibleTextIncludingDetails(view);
  for (const kept of [RECORDED[0].id, RECORDED[0].batch, RECORDED[0].layout_version, RECORDED[0].position]) assert.ok(all.includes(kept), kept);
});

test("each row's details tell its corrections by time and keep the ids", () => {
  const ctx = testCtx({ lang: "zh" });
  const view = measurementTable(ctx, [original, correction], { onCorrect: () => {} });
  const [first, second] = rowsOf(view);
  const firstAll = visibleTextIncludingDetails(first);
  assert.ok(firstAll.includes(`已被 ${timeText(ctx, correction.measured_at)} 的记录更正`), firstAll);
  assert.ok(firstAll.includes(correction.id));
  const secondAll = visibleTextIncludingDetails(second);
  assert.ok(secondAll.includes(`更正了 ${timeText(ctx, original.measured_at)} 的记录`), secondAll);
  assert.ok(secondAll.includes(original.id));
  assert.match(visibleText(first), /已被更正/);
  assertNoLeaks(view, [METRIC]);
  const en = testCtx({ lang: "en" });
  const enAll = visibleTextIncludingDetails(measurementTable(en, [original, correction], {}));
  assert.ok(enAll.includes(`Corrected by the record of ${timeText(en, correction.measured_at)}`), enAll);
  assert.ok(enAll.includes(`Corrects the record of ${timeText(en, original.measured_at)}`), enAll);
});

test("a record already corrected offers no second correction", () => {
  const ctx = testCtx({ lang: "zh" });
  const [first, second] = rowsOf(measurementTable(ctx, [original, correction], { onCorrect: () => {} }));
  assert.deepEqual(rowButtons(first), []);
  assert.deepEqual(rowButtons(second), ["更正"]);
});

function formView(lang = "zh") {
  const ctx = testCtx({ lang });
  const recorded = [];
  const form = measurementForm(ctx, STAGE, async (message) => recorded.push(message));
  return { ctx, form, recorded };
}

test("the metric, unit and method fields suggest what this stage already recorded", () => {
  const { form } = formView();
  form.update(RECORDED);
  const lists = ["metric", "unit", "method"].map((name) => input(form.element, name).getAttribute("list"));
  assert.equal(new Set(lists).size, 3);
  const datalists = elements(form.element, "datalist");
  const options = (id) => elements(datalists.find((list) => list.getAttribute("id") === id), "option").map((o) => o.getAttribute("value"));
  assert.deepEqual(options(lists[0]), [METRIC]);
  assert.deepEqual(options(lists[1]), ["cm2/day"]);
  assert.deepEqual(options(lists[2]), ["image"]);
  const other = formView().form;
  assert.ok(!lists.includes(input(other.element, "metric").getAttribute("list")), "ids are unique per form");
});

test("the form's lead names no experiment id and corrects stays hidden", () => {
  const { form } = formView();
  const text = visibleText(form.element);
  assert.ok(!text.includes(STAGE.experiment_id), text);
  assertNoLeaks(form.element);
  assert.equal(input(form.element, "corrects").getAttribute("type"), "hidden");
  assert.ok(!text.includes("更正的测量"), "the free-text corrects field is gone");
});

test("Correct fills the form from the row and says which record it corrects", async () => {
  const { ctx, form, recorded } = formView();
  form.update(RECORDED);
  const view = measurementTable(ctx, RECORDED, { onCorrect: form.correct });
  const target = RECORDED[1];
  const button = elements(rowsOf(view)[1], "button").find((b) => b.textContent === "更正");
  button.dispatchEvent(new Event("click"));
  assert.equal(input(form.element, "corrects").value, target.id);
  assert.equal(input(form.element, "plant_id").value, target.plant_id);
  assert.equal(input(form.element, "value").value, String(target.value));
  assert.equal(input(form.element, "metric").value, target.metric);
  assert.ok(input(form.element, "measured_at").value.startsWith("2026-12-07T"), input(form.element, "measured_at").value);
  assert.ok(visibleText(form.element).includes(`正在更正 ${timeText(ctx, target.measured_at)} 的 ${METRIC} 记录`));
  elements(form.element, "form")[0].dispatchEvent(new Event("submit"));
  await settle();
  await settle();
  const sent = ctx.api.calls.find((call) => call.method === "POST");
  assert.equal(sent.path, "/measurements");
  assert.equal(sent.body.corrects, target.id);
  assert.equal(sent.body.experiment_id, STAGE.experiment_id);
  assert.equal(recorded.length, 1);
  assert.ok(!recorded[0].includes("measurement_"), recorded[0]);
  assert.equal(input(form.element, "corrects").value, "", "the next record is a new one");
  assert.ok(!visibleText(form.element).includes("正在更正"));
});

test("a correction can be called off before it is saved", () => {
  const { form } = formView();
  form.update(RECORDED);
  form.correct(RECORDED[0]);
  const cancel = elements(form.element, "button").find((b) => b.textContent === "取消更正");
  cancel.dispatchEvent(new Event("click"));
  assert.equal(input(form.element, "corrects").value, "");
  assert.ok(!visibleText(form.element).includes("正在更正"));
});

test("a draft restored after a lost session still says it corrects a record", () => {
  saveDraft(`measurement:${STAGE.experiment_id}`, { plant_id: "plant-3", corrects: RECORDED[2].id });
  const { ctx, form } = formView();
  assert.equal(input(form.element, "corrects").value, RECORDED[2].id);
  assert.ok(visibleText(form.element).includes("正在更正一条已有记录"), visibleText(form.element));
  form.update(RECORDED);
  assert.ok(visibleText(form.element).includes(`正在更正 ${timeText(ctx, RECORDED[2].measured_at)} 的 ${METRIC} 记录`));
  assertNoLeaks(form.element, [METRIC]);
});
