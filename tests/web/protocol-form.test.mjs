// The research protocol and holdout forms of the project page: what they build, what they refuse, and what they never invent.
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { clearDrafts } from "../../src/growbridge/web/workbench/drafts.js";
import en from "../../src/growbridge/web/workbench/i18n/en.js";
import { protocolForm } from "../../src/growbridge/web/workbench/pages/protocol-form.js";
import { holdoutEditor } from "../../src/growbridge/web/workbench/pages/project-forms.js";
import { bindFormContext, formControls } from "../../src/growbridge/web/workbench/ui/forms.js";
import { assertNoPendingDialogAnswers, resetDialogs } from "./support/dialogs.mjs";
import { visibleText } from "./support/leaks.mjs";
import { FIXTURES, testCtx } from "./support/render-page.mjs";

afterEach(() => {
  assertNoPendingDialogAnswers();
  resetDialogs();
  clearDrafts();
});

const PROJECT = FIXTURES["project.json"];
const TAIL = PROJECT.project_id.slice(-6);
const settle = () => new Promise((resolve) => setImmediate(resolve));
const find = (node, match) => [...(match(node) ? [node] : []), ...[...(node.children || [])].flatMap((child) => find(child, match))];
const byTag = (node, tag) => find(node, (el) => el.localName === tag);
const byClass = (node, name) => find(node, (el) => el.classList && el.classList.contains(name));
const named = (node, name) => find(node, (el) => el.getAttribute && el.getAttribute("name") === name);
const change = (input, value) => {
  input.value = value;
  input.dispatchEvent(new Event("input"));
  input.dispatchEvent(new Event("change"));
};
const errorsIn = (node) => byClass(node, "field-error").map((error) => error.textContent).filter(Boolean);
const groups = (form) => byClass(form, "row-group");
const rowsOf = (group) => byClass(group, "row-group-row");
const addRow = (group) => [...group.children].at(-1).dispatchEvent(new Event("click"));
const optionsOf = (select) => byTag(select, "option").map((option) => option.getAttribute("value"));

async function open({ project = PROJECT, protocolId, ctxOptions = {} } = {}) {
  const ctx = testCtx({ lang: "en", ...ctxOptions });
  bindFormContext(ctx);
  const sent = [];
  const element = protocolForm(ctx, { project, protocolId, onSubmit: async (value) => void sent.push(value) });
  return { ctx, element, form: byTag(element, "form")[0], sent };
}

const submit = async (form) => {
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  await settle();
  await settle();
};

// A complete protocol: two treatments, two allocations. Everything typed here, nothing offered by the form.
function fill(form, { question = "Does more light speed up growth?" } = {}) {
  formControls(form).set({ question, crop: "lettuce", batch: "batch-1", randomization_seed: "20261118", stages: ["vegetative"], rounds: 2, blocks: 1 });
  const [treatments, allocations] = groups(form);
  const [first, second] = rowsOf(treatments);
  change(named(first, "id")[0], "control");
  change(named(first, "name")[0], "light 40 %");
  change(named(first, "factors")[0], "light=40");
  change(named(second, "id")[0], "high");
  change(named(second, "name")[0], "light 70 %");
  change(named(second, "factors")[0], "light=70\nmode=steady");
  change(named(form, "control_treatment_id")[0], "control");
  for (const [round, treatment] of [["1", "high"], ["2", "control"]]) {
    addRow(allocations);
    const row = rowsOf(allocations).at(-1);
    change(named(row, "round")[0], round);
    change(named(row, "block")[0], "1");
    change(named(row, "unit")[0], "tent-1");
    change(named(row, "treatment_id")[0], treatment);
  }
  change(named(form, "primary_endpoint")[0], "canopy_area_growth");
  change(named(form, "target_effect")[0], "0.15");
  change(named(form, "method")[0], "paired_block");
}

test("the protocol form builds a protocol the server accepts, with version 1 for a new id and the next version for a saved one", async () => {
  const fresh = await open();
  fill(fresh.form);
  await submit(fresh.form);
  assert.equal(fresh.sent.length, 1);
  assert.deepEqual(fresh.sent[0], {
    protocol: {
      id: `protocol-2-${TAIL}`,
      project_id: PROJECT.project_id,
      version: 1,
      question: "Does more light speed up growth?",
      hypothesis: "",
      crop: "lettuce",
      batch: "batch-1",
      treatments: [
        { id: "control", name: "light 40 %", description: "", factors: { light: 40 } },
        { id: "high", name: "light 70 %", description: "", factors: { light: 70, mode: "steady" } },
      ],
      control_treatment_id: "control",
      allocations: [
        { round: 1, block: 1, unit: "tent-1", treatment_id: "high" },
        { round: 2, block: 1, unit: "tent-1", treatment_id: "control" },
      ],
      randomization_seed: 20261118,
      analysis: { primary_endpoint: "canopy_area_growth", target_effect: 0.15, method: "paired_block", exclusion_rules: [], max_missing_fraction: 0.2, max_deviation_fraction: 0.1 },
      stages: ["vegetative"],
      rounds: 2,
      blocks: 1,
      experimental_unit: "tent",
    },
  });
  const saved = await open({ protocolId: "protocol-lettuce-light" });
  fill(saved.form);
  await submit(saved.form);
  assert.equal(saved.sent[0].protocol.id, "protocol-lettuce-light");
  assert.equal(saved.sent[0].protocol.version, 2);
});

test("the version is worked out when the form is sent, from the newest read of the project", async () => {
  const { ctx, form, sent } = await open({ protocolId: "protocol-lettuce-light" });
  const reads = [];
  const newer = { ...PROJECT, protocols: [...PROJECT.protocols, { protocol_id: "protocol-lettuce-light", version: 2 }, { protocol_id: "protocol-lettuce-light", version: 3 }] };
  ctx.api.get = async (path) => {
    reads.push(path);
    return structuredClone(newer);
  };
  fill(form);
  await submit(form);
  assert.equal(sent[0].protocol.version, 4);
  assert.ok(reads.some((path) => path.includes(PROJECT.project_id)), reads.join(","));
  await submit(form);
  assert.equal(sent[1].protocol.version, 4, "a second send reads again, it does not reuse the first number");
});

test("the question is required, the hypothesis is not", async () => {
  const { form, sent } = await open();
  fill(form, { question: "" });
  await submit(form);
  assert.equal(sent.length, 0);
  assert.deepEqual(errorsIn(form), [en["form.required"]]);
  formControls(form).set({ question: "Why?" });
  await submit(form);
  assert.equal(sent.length, 1);
  assert.equal(sent[0].protocol.hypothesis, "");
  formControls(form).set({ hypothesis: "More light grows more." });
  await submit(form);
  assert.equal(sent[1].protocol.hypothesis, "More light grows more.");
});

test("the control treatment is chosen from the treatment rows and follows renames", async () => {
  const { form } = await open();
  const [treatments] = groups(form);
  const select = named(form, "control_treatment_id")[0];
  assert.deepEqual(optionsOf(select), [""]);
  const [first, second] = rowsOf(treatments);
  change(named(first, "id")[0], "control");
  change(named(second, "id")[0], "high");
  assert.deepEqual(optionsOf(select), ["", "control", "high"]);
  assert.equal(byTag(select, "option")[0].textContent, en["form.choose"]);
  change(select, "control");
  change(named(first, "id")[0], "baseline");
  assert.deepEqual(optionsOf(select), ["", "baseline", "high"]);
  assert.equal(select.value, "baseline");
  const removers = byTag(rowsOf(treatments)[0], "button");
  removers.at(-1).dispatchEvent(new Event("click"));
  assert.deepEqual(optionsOf(select), ["", "high"]);
  assert.equal(select.value, "", "a removed treatment clears the choice");
  addRow(treatments);
  change(named(rowsOf(treatments).at(-1), "id")[0], "extra");
  assert.deepEqual(optionsOf(select), ["", "high", "extra"]);
});

test("allocations start empty; nothing is randomised for the user", async () => {
  const { form, sent } = await open();
  const [, allocations] = groups(form);
  assert.equal(rowsOf(allocations).length, 0);
  fill(form);
  for (const row of rowsOf(allocations)) for (const select of named(row, "treatment_id")) assert.deepEqual(optionsOf(select), ["", "control", "high"]);
  assert.equal(named(rowsOf(allocations)[0], "treatment_id")[0].value, "high");
  const blank = await open();
  fill(blank.form);
  const [, blankAllocations] = groups(blank.form);
  addRow(blankAllocations);
  assert.equal(named(rowsOf(blankAllocations).at(-1), "treatment_id")[0].value, "", "a new allocation row chooses no treatment");
  assert.equal(sent.length, 0);
});

test("a factor line without = is refused beside the field, and numbers become numbers", async () => {
  const { form, sent } = await open();
  fill(form);
  const [treatments] = groups(form);
  const factors = named(rowsOf(treatments)[0], "factors")[0];
  change(factors, "light 40");
  await submit(form);
  assert.equal(sent.length, 0);
  assert.equal(errorsIn(rowsOf(treatments)[0]).length, 1);
  change(factors, "light=40\nspectrum=blue 1e");
  await submit(form);
  assert.deepEqual(sent[0].protocol.treatments[0].factors, { light: 40, spectrum: "blue 1e" });
});

test("endpoint and method suggest what saved protocols used", async () => {
  const { form } = await open();
  const suggestions = (name) => byTag(named(form, name)[0].parentNode, "option").map((option) => option.getAttribute("value"));
  const endpoint = suggestions("primary_endpoint");
  assert.ok(endpoint.includes("canopy_area_growth"), endpoint.join(","));
  assert.ok(endpoint.includes("temp"), "the sensor metrics are suggested too");
  const method = suggestions("method");
  assert.deepEqual(method.slice(0, 2), ["paired_block", "two_group"]);
  const other = { ...PROJECT, protocols: [{ protocol_id: "p-x", version: 1, primary_endpoint: "fresh_mass", method: "mixed_model" }] };
  const again = await open({ project: other });
  const added = (name) => byTag(named(again.form, name)[0].parentNode, "option").map((option) => option.getAttribute("value"));
  assert.ok(added("primary_endpoint").includes("fresh_mass"));
  assert.ok(added("method").includes("mixed_model"));
  assert.equal(added("method").filter((value) => value === "paired_block").length, 1, "no suggestion twice");
  change(named(again.form, "method")[0], "my_own_method");
  assert.equal(named(again.form, "method")[0].value, "my_own_method", "free text stays possible");
});

test("analysis limits default to 0.2 and 0.1 and stay between 0 and 1", async () => {
  const { form, sent } = await open();
  assert.equal(named(form, "max_missing_fraction")[0].value, "0.2");
  assert.equal(named(form, "max_deviation_fraction")[0].value, "0.1");
  fill(form);
  change(named(form, "max_missing_fraction")[0], "1.5");
  await submit(form);
  assert.equal(sent.length, 0);
  assert.ok(errorsIn(form).length >= 1);
});

test("the protocol form shows no ids or field names", async () => {
  const { element } = await open();
  const text = visibleText(element);
  assert.ok(!text.includes(PROJECT.project_id), text);
  assert.ok(!/[a-z]+_[a-z_]+/.test(text.replace(/https?:\S+/g, "")), text);
});

// --- holdouts ----------------------------------------------------------------------------------

function holdoutForm() {
  const ctx = testCtx({ lang: "en" });
  bindFormContext(ctx);
  const fold = holdoutEditor(ctx, PROJECT);
  return { ctx, fold, form: byTag(fold, "form")[0] };
}

test("the holdout form takes one batch per line and explains hold-out and development", async () => {
  const { ctx, fold, form } = holdoutForm();
  const text = visibleText(fold);
  assert.ok(text.includes(en["holdout.form.hint"]), text);
  assert.match(en["holdout.form.hint"], /held-out/i);
  assert.match(en["holdout.form.hint"], /development/i);
  formControls(form).set({ batch_ids: ["b-1", "b-2"], development_batch_ids: ["d-1"], outcome_fields: ["fresh_mass"] });
  await submit(form);
  const post = ctx.api.calls.find((call) => call.method === "POST");
  assert.equal(post.path, "/holdouts");
  assert.deepEqual(post.body, { project_id: PROJECT.project_id, batch_ids: ["b-1", "b-2"], development_batch_ids: ["d-1"], outcome_fields: ["fresh_mass"] });
});

test("each holdout list needs 1 to 50 items of at most 100 characters", async () => {
  const { ctx, form } = holdoutForm();
  formControls(form).set({ batch_ids: [], development_batch_ids: ["d"], outcome_fields: ["f"] });
  await submit(form);
  assert.equal(ctx.api.calls.filter((call) => call.method === "POST").length, 0);
  formControls(form).set({ batch_ids: Array.from({ length: 51 }, (_, i) => `b${i}`) });
  await submit(form);
  assert.equal(ctx.api.calls.filter((call) => call.method === "POST").length, 0);
  formControls(form).set({ batch_ids: ["x".repeat(101)] });
  await submit(form);
  assert.equal(ctx.api.calls.filter((call) => call.method === "POST").length, 0);
  assert.equal(errorsIn(form).length, 1);
  formControls(form).set({ batch_ids: ["ok"] });
  await submit(form);
  assert.equal(ctx.api.calls.filter((call) => call.method === "POST").length, 1);
});
