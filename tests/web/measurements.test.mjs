import assert from "node:assert/strict";
import test from "node:test";

import { ApiError } from "../../src/growbridge/web/workbench/api.js";
import { saveDraft } from "../../src/growbridge/web/workbench/drafts.js";
import { measurementBody, measurementForm, measurementOptions, measurementTable, variableOptions } from "../../src/growbridge/web/workbench/pages/stage-measurements.js";
import { timeText } from "../../src/growbridge/web/workbench/ui/section.js";
import { assertNoLeaks, visibleText, visibleTextIncludingDetails } from "./support/leaks.mjs";
import { FIXTURES, installFakeDom, renderPage, testCtx } from "./support/render-page.mjs";

installFakeDom();

const settle = () => new Promise((resolve) => setImmediate(resolve));
const RECORDED = FIXTURES["measurements.json"].measurements;
const STAGE = FIXTURES["stage.json"];
const METRIC = RECORDED[0].metric; // an operator-chosen name, shown as recorded
const VARIABLES = FIXTURES["variables.json"].variables; // what the stage's experiment declares
// Two declared variables, to choose between.
const TWO = [
  { id: "canopy_area_growth", label_en: "Canopy area growth", label_zh: "冠层面积增长", unit: "cm2/d", method: "top-view images", min: null, max: null, deprecated: false },
  { id: "height", label_en: "Plant height", label_zh: "株高", unit: "cm", method: "ruler, soil to apex", min: null, max: null, deprecated: false },
];

function elements(node, name) {
  const own = node.tagName && node.tagName.toLowerCase() === name ? [node] : [];
  return [...own, ...[...(node.children || [])].flatMap((child) => elements(child, name))];
}

// The buttons a row offers, without the copy buttons of its technical details.
function rowButtons(node) {
  if ((node.getAttribute && node.getAttribute("class")) === "tech-details") return [];
  const own = node.tagName && node.tagName.toLowerCase() === "button" ? [node.textContent] : [];
  return [...own, ...[...(node.children || [])].flatMap(rowButtons)];
}

const input = (node, name) => elements(node, "input").find((element) => element.getAttribute("name") === name);
const select = (node, name) => elements(node, "select").find((element) => element.getAttribute("name") === name);
const rowsOf = (node) => elements(node, "tbody").flatMap((body) => elements(body, "tr"));

// A record and the one that corrects it, an hour later.
const original = { ...RECORDED[0], id: "measurement_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", measured_at: 1796590000 };
const correction = { ...RECORDED[0], id: "measurement_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", measured_at: 1796593600, value: 1.24, corrects: original.id };

test("measurement options are the distinct methods already recorded", () => {
  assert.deepEqual(measurementOptions([{ metric: "canopy", unit: "cm2", method: "ruler" }, { metric: "canopy", unit: "cm2", method: "photo" }]), { method: ["photo", "ruler"] });
  assert.deepEqual(measurementOptions(undefined), { method: [] });
  assert.deepEqual(measurementOptions([{ metric: "", unit: null, method: "" }]), { method: [] });
});

test("variable options are labelled in the page's language, with the unit", () => {
  assert.deepEqual(variableOptions(TWO, "zh"), [
    { value: "canopy_area_growth", label: "冠层面积增长 (cm2/d)" },
    { value: "height", label: "株高 (cm)" },
  ]);
  assert.deepEqual(variableOptions(TWO, "en"), [
    { value: "canopy_area_growth", label: "Canopy area growth (cm2/d)" },
    { value: "height", label: "Plant height (cm)" },
  ]);
  assert.deepEqual(variableOptions(undefined, "en"), []);
});

test("the body takes its unit from the chosen variable, never from the values", () => {
  const values = { metric: "height", value: 12.5, unit: "mm", plant_id: "plant-1" };
  const body = measurementBody(values, TWO, "experiment-1");
  assert.equal(body.unit, "cm");
  assert.equal(body.metric, "height");
  assert.equal(body.experiment_id, "experiment-1");
  assert.equal(body.position, "", "an empty position is sent as such");
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

function formView(lang = "zh", variables = VARIABLES) {
  const ctx = testCtx({ lang });
  const recorded = [];
  const form = measurementForm(ctx, STAGE, async (message) => recorded.push(message), variables);
  return { ctx, form, recorded };
}

test("the metric is a choice of the declared variables, and only the method suggests", () => {
  const { form } = formView("zh", TWO);
  form.update(RECORDED);
  const metric = select(form.element, "metric");
  assert.deepEqual(elements(metric, "option").map((o) => [o.getAttribute("value"), o.textContent]), [
    ["canopy_area_growth", "冠层面积增长 (cm2/d)"],
    ["height", "株高 (cm)"],
  ]);
  assert.equal(input(form.element, "metric"), undefined, "no free-text metric");
  assert.equal(input(form.element, "unit"), undefined, "the unit comes with the variable");
  assert.equal(select(form.element, "unit"), undefined);
  const list = input(form.element, "method").getAttribute("list");
  const datalist = elements(form.element, "datalist").find((item) => item.getAttribute("id") === list);
  assert.deepEqual(elements(datalist, "option").map((o) => o.getAttribute("value")), ["image"]);
  assert.equal(elements(form.element, "datalist").length, 1);
  assertNoLeaks(form.element);
});

test("the method is filled in from the chosen variable when the form opens and on each choice", () => {
  const { form } = formView("en", TWO);
  assert.equal(input(form.element, "method").value, "top-view images");
  const metric = select(form.element, "metric");
  metric.value = "height";
  metric.dispatchEvent(new Event("change"));
  assert.equal(input(form.element, "method").value, "ruler, soil to apex");
});

test("with no declared variables there is no form, only a note saying why", () => {
  for (const lang of ["zh", "en"]) {
    const { ctx, form } = formView(lang, []);
    assert.equal(elements(form.element, "form").length, 0);
    assert.equal(elements(form.element, "button").length, 0, "no submit button");
    assert.ok(visibleText(form.element).includes(ctx.t("measure.noVariables")), visibleText(form.element));
    form.update(RECORDED);
    const view = measurementTable(ctx, RECORDED, { onCorrect: form.correct });
    assert.deepEqual(rowsOf(view).flatMap(rowButtons), [], "nothing to correct with");
  }
  assert.equal(elements(measurementForm(testCtx(), STAGE, async () => {}).element, "form").length, 0, "variables left out count as none");
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
  assert.equal(select(form.element, "metric").value, target.metric);
  assert.ok(input(form.element, "measured_at").value.startsWith("2026-12-07T"), input(form.element, "measured_at").value);
  assert.ok(visibleText(form.element).includes(`正在更正 ${timeText(ctx, target.measured_at)} 的 ${METRIC} 记录`));
  elements(form.element, "form")[0].dispatchEvent(new Event("submit"));
  await settle();
  await settle();
  const sent = ctx.api.calls.find((call) => call.method === "POST");
  assert.equal(sent.path, "/measurements");
  assert.equal(sent.body.corrects, target.id);
  assert.equal(sent.body.experiment_id, STAGE.experiment_id);
  assert.equal(sent.body.metric, target.metric);
  assert.equal(sent.body.unit, VARIABLES[0].unit, "the declared unit, not the one the record carried");
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

test("a refused correction names the corrected record, not the field", async () => {
  const { ctx, form } = formView();
  ctx.api.post = async () => {
    throw new ApiError(422, "validation", "invalid", [{ loc: ["body", "corrects"], msg: "no such measurement" }]);
  };
  form.update(RECORDED);
  form.correct(RECORDED[0]);
  elements(form.element, "form")[0].dispatchEvent(new Event("submit"));
  await settle();
  await settle();
  const text = visibleText(form.element);
  assert.match(text, /被更正的记录: no such measurement/);
  assert.ok(!text.includes("corrects:"), text);
});

// --- final review: a correction keeps the seconds of the time it copied (F6) ----------------------
async function submitCorrection(form, record, editTime) {
  form.update([record]);
  form.correct(record);
  if (editTime) input(form.element, "measured_at").value = editTime;
  elements(form.element, "form")[0].dispatchEvent(new Event("submit"));
  await settle();
  await settle();
}

test("a correction whose time was not touched sends the original epoch, seconds and all", async () => {
  const { ctx, form } = formView();
  const record = { ...RECORDED[0], measured_at: 1796594755 };
  assert.equal(record.measured_at % 60, 55, "the record has seconds");
  await submitCorrection(form, record);
  const sent = ctx.api.calls.find((call) => call.method === "POST");
  assert.equal(sent.body.measured_at, 1796594755);
  assert.equal(sent.body.corrects, record.id);
});

test("a correction whose time was changed sends the new minute", async () => {
  const { ctx, form } = formView();
  const record = { ...RECORDED[0], measured_at: 1796594755 };
  const shown = input(form.element, "measured_at");
  form.update([record]);
  form.correct(record);
  const [day, time] = shown.value.split("T");
  const [hour, minute] = time.split(":").map(Number);
  const edited = `${day}T${String(hour).padStart(2, "0")}:${String((minute + 1) % 60).padStart(2, "0")}`;
  await submitCorrection(form, record, edited);
  const sent = ctx.api.calls.find((call) => call.method === "POST");
  assert.notEqual(sent.body.measured_at, 1796594755);
  assert.equal(sent.body.measured_at % 60, 0);
});

// --- variable catalog: the stage page reads what its experiment declares -------------------------
test("the stage page reads its experiment's variables and offers them in the form", async () => {
  const { element, ctx } = await renderPage("stage", { stageId: STAGE.stage_id }, { lang: "en" });
  const asked = ctx.api.calls.filter((call) => call.method === "GET" && call.path.includes("/variables"));
  assert.deepEqual(asked.map((call) => [call.path, call.fixture]), [[`/experiments/${encodeURIComponent(STAGE.experiment_id)}/variables`, "variables.json"]]);
  assert.deepEqual(elements(select(element, "metric"), "option").map((o) => o.textContent), ["Canopy area growth (cm2/d)"]);
});

test("variables that cannot be read leave a refusal where the form was, and no Correct", async () => {
  const { element, ctx } = await renderPage("stage", { stageId: STAGE.stage_id }, { lang: "en", fixtures: { "variables.json": null } });
  assert.equal(select(element, "metric"), undefined);
  assert.ok(!visibleText(element).includes(ctx.t("measure.noVariables")), "not read is not none declared");
  assert.ok(visibleText(element).includes(ctx.t("error.notFound")), visibleText(element));
  assert.ok(!elements(element, "button").some((b) => b.textContent === ctx.t("measure.correct")));
});
