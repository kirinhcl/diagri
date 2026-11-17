import assert from "node:assert/strict";
import test from "node:test";

import { ApiError } from "../../src/growbridge/web/workbench/api.js";
import { describeDenial } from "../../src/growbridge/web/workbench/denials.js";
import {
  dropDetachedDraftSavers,
  errorDetail,
  errorLines,
  formControls,
  registerDraftSaver,
  saveAllDrafts,
  simpleForm,
  worthKeeping,
} from "../../src/growbridge/web/workbench/ui/forms.js";
import { visibleText } from "./support/leaks.mjs";
import { installFakeDom, testCtx } from "./support/render-page.mjs";

const t = (key) => `t:${key}`;

test("a known refusal shows its explanation and advice; the server's own words go to the details", () => {
  const error = new ApiError(409, "state", "stage stage-1 is paused; nothing to approve");
  const { text, advice } = describeDenial("state", "en");
  assert.deepEqual(errorLines(error, "en", t), [text, advice]);
  assert.deepEqual(errorDetail(error, t), [
    ["t:tech.httpStatus", 409],
    ["t:tech.code", "state"],
    ["t:tech.serverMessage", "stage stage-1 is paused; nothing to approve"],
  ]);
});

test("the same two lines when the message only repeats the code or is missing", () => {
  const { text, advice } = describeDenial("validation", "zh");
  assert.deepEqual(errorLines(new ApiError(422, "validation", "validation"), "zh", t), [text, advice]);
  assert.deepEqual(errorLines(new ApiError(403, "scope", ""), "zh", t).length, 2);
});

test("an unknown code or a plain error shows only the title; its message is a detail", () => {
  assert.deepEqual(errorLines(new ApiError(409, "brand_new", "changed"), "en", t), ["t:error.title"]);
  assert.deepEqual(errorLines(new Error("boom"), "en", t), ["t:error.title"]);
  assert.deepEqual(errorDetail(new Error("boom"), t), [["t:tech.message", "boom"]]);
  assert.deepEqual(errorDetail("thrown as text", t), [["t:tech.message", "thrown as text"]]);
  assert.deepEqual(errorLines(null, "en", t), ["t:error.title"]);
});

test("the console's own refusal keeps its catalog line as the second line", () => {
  assert.deepEqual(errorLines(new ApiError(0, "not_approved", "changed"), "en", t), ["t:error.title", "changed"]);
});

test("a lost session saves the draft of every form still on the page", () => {
  const saved = [];
  const shown = { isConnected: true };
  const other = { isConnected: true };
  const off = registerDraftSaver(shown, () => saved.push("shown"));
  const offOther = registerDraftSaver(other, () => saved.push("other"));
  assert.equal(saveAllDrafts(), 2);
  assert.deepEqual(saved, ["shown", "other"]);
  off();
  offOther();
});

test("a form that left the document is dropped, not saved", () => {
  const saved = [];
  const gone = { isConnected: true };
  registerDraftSaver(gone, () => saved.push("gone"));
  gone.isConnected = false;
  assert.equal(saveAllDrafts(), 0);
  gone.isConnected = true; // even if put back, it was dropped
  assert.equal(saveAllDrafts(), 0);
  assert.deepEqual(saved, []);
});

test("after a page is shown, the forms of the page before are dropped", () => {
  const saved = [];
  const old = { isConnected: false };
  const current = { isConnected: true };
  registerDraftSaver(old, () => saved.push("old"));
  const off = registerDraftSaver(current, () => saved.push("current"));
  assert.equal(dropDetachedDraftSavers(), 1);
  old.isConnected = true;
  assert.equal(saveAllDrafts(), 1);
  assert.deepEqual(saved, ["current"]);
  off();
});

test("an unregistered form is not saved", () => {
  const saved = [];
  const form = { isConnected: true };
  registerDraftSaver(form, () => saved.push("form"))();
  assert.equal(saveAllDrafts(), 0);
});

test("a form started from a restored draft keeps its values on a lost session", () => {
  assert.equal(worthKeeping(null, { a: "x" }), true);
});

test("a form started fresh keeps its values only when they changed", () => {
  assert.equal(worthKeeping({ a: "x" }, { a: "x" }), false);
  assert.equal(worthKeeping({ a: "x" }, { a: "y" }), true);
});

// --- hidden fields, suggestions and filling a form in ---------------------------------------------
function elements(node, name) {
  const own = node.tagName && node.tagName.toLowerCase() === name ? [node] : [];
  return [...own, ...[...(node.children || [])].flatMap((child) => elements(child, name))];
}

function sampleForm(sent) {
  const fields = [
    { name: "when", label: "When", type: "datetime", required: true },
    { name: "metric", label: "Metric", required: true, suggestions: ["height"] },
    { name: "link", type: "hidden" },
  ];
  return simpleForm({ fields, submitLabel: "Save", onSubmit: async (values) => sent.push(values), timeZone: "UTC", ctx: testCtx({ lang: "en", timezone: "UTC" }) });
}

const settle = () => new Promise((resolve) => setImmediate(resolve));

test("a hidden field has no label, is sent when set and left out when empty", async () => {
  installFakeDom();
  const sent = [];
  const form = sampleForm(sent);
  const hidden = elements(form, "input").find((input) => input.getAttribute("name") === "link");
  assert.equal(hidden.getAttribute("type"), "hidden");
  assert.deepEqual(elements(form, "label").map((label) => label.textContent), ["When", "Metric"]);
  const controls = formControls(form);
  controls.set({ when: 1796594755, metric: "height", link: "m-1" });
  assert.equal(controls.get("when"), "2026-12-06T22:05");
  form.dispatchEvent(new Event("submit"));
  await settle();
  controls.set({ link: null });
  form.dispatchEvent(new Event("submit"));
  await settle();
  assert.deepEqual(sent, [
    { when: 1796594700, metric: "height", link: "m-1" },
    { when: 1796594700, metric: "height" },
  ]);
});

test("suggestions make a datalist the page can refill", () => {
  installFakeDom();
  const form = sampleForm([]);
  const input = elements(form, "input").find((element) => element.getAttribute("name") === "metric");
  const list = elements(form, "datalist")[0];
  assert.equal(input.getAttribute("list"), list.getAttribute("id"));
  const values = () => elements(list, "option").map((option) => option.getAttribute("value"));
  assert.deepEqual(values(), ["height"]);
  formControls(form).suggest("metric", ["area", "height"]);
  assert.deepEqual(values(), ["area", "height"]);
  assert.ok(!visibleText(form).includes("area"), "suggestions are not page text");
  assert.throws(() => formControls(form).suggest("when", ["x"]), /no suggestions/);
  assert.throws(() => formControls(form).get("nope"), /no field/);
});

test("onChange tells the page each value a field is changed to, and only that field", () => {
  installFakeDom();
  const form = sampleForm([]);
  const seen = [];
  formControls(form).onChange("metric", (value) => seen.push(value));
  const field = (name) => elements(form, "input").find((element) => element.getAttribute("name") === name);
  field("metric").value = "area";
  field("metric").dispatchEvent(new Event("change"));
  field("when").dispatchEvent(new Event("change"));
  assert.deepEqual(seen, ["area"]);
  assert.throws(() => formControls(form).onChange("nope", () => {}), /no field/);
});

test("a refusal of a hidden field is written with the field's label, not its name", async () => {
  installFakeDom();
  const fields = [
    { name: "metric", label: "Metric", required: true },
    { name: "link", type: "hidden", label: "Corrected record" },
  ];
  const refusal = new ApiError(422, "validation", "invalid", [{ loc: ["body", "link"], msg: "no such record", type: "missing", limits: {} }]);
  const onSubmit = async () => {
    throw refusal;
  };
  const form = simpleForm({ fields, submitLabel: "Save", onSubmit, ctx: testCtx({ lang: "en" }) });
  formControls(form).set({ metric: "height", link: "m-1" });
  form.dispatchEvent(new Event("submit"));
  await settle();
  const text = visibleText(form);
  assert.match(text, /Corrected record: This is required\./);
  assert.ok(!/\blink\b/.test(text), text);
});

test("a datetime or select field keeps working next to a hint, a unit and a check box", async () => {
  installFakeDom();
  const sent = [];
  const fields = [
    { name: "when", label: "When", type: "datetime", hint: "Local time", required: true },
    { name: "kind", label: "Kind", type: "select", options: ["a", "b"] },
    { name: "ok", label: "OK", type: "checkbox", value: true },
  ];
  const form = simpleForm({ fields, submitLabel: "Save", onSubmit: async (values) => sent.push(values), timeZone: "UTC", ctx: testCtx({ lang: "en", timezone: "UTC" }) });
  formControls(form).set({ when: 1796594755 });
  form.dispatchEvent(new Event("submit"));
  await settle();
  assert.deepEqual(sent, [{ when: 1796594700, kind: "a", ok: true }]);
  const when = elements(form, "input").find((input) => input.getAttribute("name") === "when");
  assert.match(when.getAttribute("aria-describedby"), /zone.* .*hint.* .*error/);
});
