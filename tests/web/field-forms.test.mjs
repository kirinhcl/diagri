import assert from "node:assert/strict";
import test from "node:test";

import { ApiError } from "../../src/growbridge/web/workbench/api.js";
import { advancedJson, linesField, rowGroup } from "../../src/growbridge/web/workbench/ui/field-forms.js";
import { formControls, saveAllDrafts, simpleForm } from "../../src/growbridge/web/workbench/ui/forms.js";
import { installFakeDom, testCtx } from "./support/render-page.mjs";

const settle = () => new Promise((resolve) => setImmediate(resolve));
const submit = async (form) => {
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  await settle();
};

function find(node, test) {
  const own = test(node) ? [node] : [];
  return [...own, ...[...(node.children || [])].flatMap((child) => find(child, test))];
}
const byTag = (node, tag) => find(node, (el) => el.tagName && el.tagName.toLowerCase() === tag);
const byClass = (node, name) => find(node, (el) => el.classList && el.classList.contains(name));
const inputNamed = (node, name) => find(node, (el) => el.getAttribute && el.getAttribute("name") === name);
const textOf = (node) => node.textContent;

function formWith(fields, onSubmit) {
  const ctx = testCtx({ lang: "en", timezone: "UTC" });
  return simpleForm({ fields, submitLabel: "Save", onSubmit, timeZone: "UTC", ctx });
}

test("a number field refuses a value outside its range beside the field, before anything is sent", async () => {
  installFakeDom();
  const sent = [];
  const form = formWith([{ name: "light", label: "Light", type: "number", min: 0, max: 10 }], async (values) => sent.push(values));
  const [input] = inputNamed(form, "light");
  assert.equal(input.getAttribute("min"), "0");
  assert.equal(input.getAttribute("max"), "10");
  input.value = "11";
  await submit(form);
  assert.deepEqual(sent, []);
  const [error] = byClass(form, "field-error");
  assert.ok(!error.hidden);
  assert.equal(textOf(error), "Enter 10 or less.");
  input.value = "-1";
  await submit(form);
  assert.equal(textOf(error), "Enter 0 or more.");
  assert.deepEqual(sent, []);
  input.value = "7";
  await submit(form);
  assert.deepEqual(sent, [{ light: 7 }]);
  assert.ok(error.hidden);
});

test("a text field refuses more than its maxlength beside the field", async () => {
  installFakeDom();
  const sent = [];
  const form = formWith([{ name: "note", label: "Note", maxlength: 3 }], async (values) => sent.push(values));
  const [input] = inputNamed(form, "note");
  assert.equal(input.getAttribute("maxlength"), "3");
  input.value = "abcd";
  await submit(form);
  assert.deepEqual(sent, []);
  assert.equal(textOf(byClass(form, "field-error")[0]), "Use at most 3 characters.");
});

test("a field shows its hint and unit", () => {
  installFakeDom();
  const form = formWith([{ name: "light", label: "Light", type: "number", hint: "Per day", unit: "h" }], async () => {});
  const [input] = inputNamed(form, "light");
  const [hint] = byClass(form, "field-hint");
  const [unit] = byClass(form, "field-unit");
  assert.equal(textOf(hint), "Per day");
  assert.equal(textOf(unit), "h");
  assert.ok(input.getAttribute("aria-describedby").split(" ").includes(hint.getAttribute("id")));
  const control = byClass(form, "field-control")[0];
  const order = [...control.children];
  assert.ok(order.indexOf(unit) > order.indexOf(input));
});

test("a checkbox gives true or false, and a required one must be ticked", async () => {
  installFakeDom();
  const sent = [];
  const form = formWith(
    [{ name: "on", label: "On", type: "checkbox" }, { name: "agree", label: "Agree", type: "checkbox", required: true }],
    async (values) => sent.push(values),
  );
  const [on] = inputNamed(form, "on");
  const [agree] = inputNamed(form, "agree");
  assert.equal(on.getAttribute("type"), "checkbox");
  await submit(form);
  assert.deepEqual(sent, []);
  assert.match(textOf(byClass(form, "field-error")[1]), /required/i);
  agree.checked = true;
  await submit(form);
  assert.deepEqual(sent, [{ on: false, agree: true }]);
  on.checked = true;
  await submit(form);
  assert.deepEqual(sent[1], { on: true, agree: true });
  assert.equal(formControls(form).get("on"), "true");
});

test("a lines field gives the non-empty trimmed lines and refuses too many or too long", async () => {
  installFakeDom();
  const sent = [];
  const spec = linesField({ name: "tags", label: "Tags", hint: "One per line", maxItems: 3, maxItemLength: 5, required: true });
  const form = formWith([spec], async (values) => sent.push(values));
  const [area] = inputNamed(form, "tags");
  area.value = "  a \n\n b\r\n   \nc";
  await submit(form);
  assert.deepEqual(sent, [{ tags: ["a", "b", "c"] }]);
  area.value = "a\nb\nc\nd";
  await submit(form);
  assert.equal(sent.length, 1);
  assert.equal(textOf(byClass(form, "field-error")[0]), "Use at most 3 lines.");
  area.value = "abcdef";
  await submit(form);
  assert.equal(textOf(byClass(form, "field-error")[0]), "Each line may have at most 5 characters.");
  area.value = " \n ";
  await submit(form);
  assert.match(textOf(byClass(form, "field-error")[0]), /required/i);
  assert.equal(sent.length, 1);
});

test("a lines field starts from an array, one item per line", () => {
  installFakeDom();
  const form = formWith([linesField({ name: "tags", label: "Tags", value: ["x", "y"] })], async () => {});
  assert.equal(formControls(form).get("tags"), "x\ny");
});

function group(extra = {}) {
  const ctx = testCtx({ lang: "en", timezone: "UTC" });
  const fields = [{ name: "name", label: "Name", required: true }, { name: "dose", label: "Dose", type: "number", min: 0 }];
  return rowGroup({ ctx, name: "treatments", label: "Treatments", fields, addLabel: "Add a row", removeLabel: "Remove this row", ...extra });
}
const buttons = (g, label) => byTag(g.element, "button").filter((button) => textOf(button) === label);
const fill = (g, index, name, value) => {
  inputNamed(g.element, name)[index].value = value;
};

test("a row group adds and removes rows and gives one object per row", () => {
  installFakeDom();
  const g = group({ rows: [{ name: "control", dose: 0 }], minRows: 1, maxRows: 3 });
  assert.deepEqual(g.rows(), [{ name: "control", dose: 0 }]);
  assert.ok(buttons(g, "Remove this row")[0].hasAttribute("disabled"));
  buttons(g, "Add a row")[0].dispatchEvent(new Event("click"));
  fill(g, 1, "name", "high");
  fill(g, 1, "dose", "5");
  assert.deepEqual(g.rows(), [{ name: "control", dose: 0 }, { name: "high", dose: 5 }]);
  buttons(g, "Add a row")[0].dispatchEvent(new Event("click"));
  assert.ok(buttons(g, "Add a row")[0].hasAttribute("disabled"));
  buttons(g, "Remove this row")[0].dispatchEvent(new Event("click"));
  assert.equal(inputNamed(g.element, "name").length, 2);
  assert.equal(inputNamed(g.element, "name")[0].value, "high");
  g.setRows([{ name: "x" }]);
  assert.deepEqual(g.values(), { treatments: [{ name: "x" }] });
});

test("a row group shows a row's own mistakes beside its field and gives no values", () => {
  installFakeDom();
  const g = group({ rows: [{ name: "a" }, { name: "" }] });
  assert.equal(g.values(), null);
  const errors = byClass(g.element, "field-error");
  assert.ok(errors[0].hidden && errors[1].hidden);
  assert.ok(!errors[2].hidden);
  fill(g, 0, "dose", "-2");
  assert.equal(g.values(), null);
  assert.ok(!errors[1].hidden);
});

test("a server error at protocol.treatments.1.name lands beside the second row's name field", () => {
  installFakeDom();
  const ctx = testCtx({ lang: "en" });
  const g = group({ ctx, rows: [{ name: "a" }, { name: "b" }] });
  const other = { loc: ["body", "title"], msg: "bad", type: "missing", limits: {} };
  const problem = { loc: ["body", "protocol", "treatments", 1, "name"], msg: "bad", type: "missing", limits: {} };
  const left = g.placeErrors([problem, other]);
  assert.deepEqual(left, [other]);
  const errors = byClass(g.element, "field-error");
  assert.equal(errors.length, 4);
  assert.ok(errors[0].hidden && errors[1].hidden && errors[2].hidden === false && errors[3].hidden);
  assert.equal(inputNamed(g.element, "name")[1].getAttribute("aria-invalid"), "true");
  const stray = { loc: ["body", "treatments", 9, "name"], msg: "x", type: "missing", limits: {} };
  assert.deepEqual(g.placeErrors([stray]), [stray]);
});

test("the advanced fold is closed and holds a JSON editor with the same submit", async () => {
  installFakeDom();
  const ctx = testCtx({ lang: "en" });
  const sent = [];
  const fold = advancedJson({ ctx, label: "JSON", value: { a: 1 }, onSubmit: async (v) => sent.push(v), draftKey: "adv:1" });
  assert.equal(fold.tagName.toLowerCase(), "details");
  assert.ok(fold.classList.contains("edit-fold"));
  assert.ok(!fold.hasAttribute("open"));
  assert.equal(textOf(byTag(fold, "summary")[0]), "Advanced (JSON)");
  const [area] = byTag(fold, "textarea");
  assert.equal(JSON.parse(area.value).a, 1);
  area.value = '{"a": 2}';
  await submit(byTag(fold, "form")[0]);
  assert.deepEqual(sent, [{ a: 2 }]);
  void ApiError;
});

test("the new texts exist in both languages", async () => {
  const en = (await import("../../src/growbridge/web/workbench/i18n/forms.en.js")).default;
  const zh = (await import("../../src/growbridge/web/workbench/i18n/forms.zh.js")).default;
  assert.deepEqual(Object.keys(en).sort(), Object.keys(zh).sort());
});

function composed(onSubmit, rows) {
  const ctx = testCtx({ lang: "en", timezone: "UTC" });
  const fields = [{ name: "name", label: "Protocol name", required: true }];
  const group = rowGroup({ ctx, name: "treatments", label: "Treatments", fields: [{ name: "name", label: "Row name", required: true }], rows, addLabel: "Add", removeLabel: "Remove" });
  const form = simpleForm({ fields, submitLabel: "Save", onSubmit, ctx, parts: [group] });
  return { form, group };
}

test("a form with a row group sends the rows with the fields", async () => {
  installFakeDom();
  const sent = [];
  const { form, group } = composed(async (values) => sent.push(values), [{ name: "a" }, { name: "b" }]);
  assert.ok(form.contains ? form.contains(group.element) : byTag(form, "fieldset").length === 1);
  inputNamed(form, "name")[0].value = "P";
  await submit(form);
  assert.deepEqual(sent, [{ name: "P", treatments: [{ name: "a" }, { name: "b" }] }]);
});

test("an invalid row blocks the send and shows its error beside the row", async () => {
  installFakeDom();
  const sent = [];
  const { form } = composed(async (values) => sent.push(values), [{ name: "a" }, { name: "" }]);
  inputNamed(form, "name")[0].value = "P";
  await submit(form);
  assert.deepEqual(sent, []);
  const errors = byClass(form, "field-error");
  assert.ok(errors[0].hidden && errors[1].hidden && !errors[2].hidden);
});

test("a server error under a row lands on that row, not on a top-level field of the same name", async () => {
  installFakeDom();
  const problem = { loc: ["body", "protocol", "treatments", 1, "name"], msg: "bad", type: "missing", limits: {} };
  const refusal = new ApiError(422, "validation", "invalid", [problem]);
  const { form } = composed(async () => {
    throw refusal;
  }, [{ name: "a" }, { name: "b" }]);
  inputNamed(form, "name")[0].value = "P";
  await submit(form);
  const errors = byClass(form, "field-error");
  assert.ok(errors[0].hidden, "top-level name stays clean");
  assert.ok(errors[1].hidden && !errors[2].hidden);
  assert.equal(inputNamed(form, "name")[2].getAttribute("aria-invalid"), "true");
});

function draftForm(rows) {
  const ctx = testCtx({ lang: "en", timezone: "UTC" });
  const group = rowGroup({ ctx, name: "treatments", label: "Treatments", fields: [{ name: "name", label: "Row name" }], rows, addLabel: "Add", removeLabel: "Remove" });
  const form = simpleForm({ fields: [{ name: "title", label: "Title" }], submitLabel: "Save", onSubmit: async () => {}, ctx, draftKey: "rows-draft", parts: [group] });
  return { form, group };
}

test("rows edited in a row group are restored after a draft is kept", () => {
  installFakeDom();
  const first = draftForm([{ name: "a" }]);
  inputNamed(first.form, "name")[0].value = "edited";
  const add = byTag(first.group.element, "button").at(-1);
  add.dispatchEvent(new Event("click"));
  inputNamed(first.form, "name")[1].value = "second";
  document.body.append(first.form);
  assert.ok(saveAllDrafts() >= 1);
  const second = draftForm([{ name: "a" }]);
  assert.deepEqual(inputNamed(second.form, "name").map((input) => input.value), ["edited", "second"]);
  assert.deepEqual(second.group.rows(), [{ name: "edited" }, { name: "second" }]);
});

test("a draft saved before parts existed (fields only) still restores", async () => {
  installFakeDom();
  const { saveDraft } = await import("../../src/growbridge/web/workbench/drafts.js");
  saveDraft("rows-draft", { title: "old" });
  const { form, group } = draftForm([{ name: "a" }]);
  assert.equal(inputNamed(form, "title")[0].value, "old");
  assert.deepEqual(group.rows(), [{ name: "a" }]);
});
