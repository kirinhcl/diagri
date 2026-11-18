// The research protocol and holdout forms of the project page: what they build, what they refuse, and what they never invent.
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { clearDrafts } from "../../src/growbridge/web/workbench/drafts.js";
import en from "../../src/growbridge/web/workbench/i18n/en.js";
import zh from "../../src/growbridge/web/workbench/i18n/zh.js";
import { protocolForm } from "../../src/growbridge/web/workbench/pages/protocol-form.js";
import { holdoutEditor } from "../../src/growbridge/web/workbench/pages/project-forms.js";
import { bindFormContext, formControls, saveAllDrafts } from "../../src/growbridge/web/workbench/ui/forms.js";
import { assertNoPendingDialogAnswers, resetDialogs } from "./support/dialogs.mjs";
import { visibleText } from "./support/leaks.mjs";
import { FIXTURES, renderPage, testCtx } from "./support/render-page.mjs";

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
  formControls(form).set({ question, crop: "lettuce", crop_taxon: "NCBITaxon:4236", cultivar: "Grand Rapids", batch: "batch-1", randomization_seed: "20261118", stages: ["vegetative"], rounds: 2, blocks: 1 });
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
  change(named(form, "variables")[0], "canopy_area_growth");
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
      crop_taxon: "NCBITaxon:4236",
      cultivar: "Grand Rapids",
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
      variables: ["canopy_area_growth"],
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

test("the crop species is required, the cultivar is not", async () => {
  const { form, sent } = await open();
  fill(form);
  formControls(form).set({ crop_taxon: "", cultivar: "" });
  await submit(form);
  assert.equal(sent.length, 0);
  assert.deepEqual(errorsIn(form), [en["form.required"]]);
  formControls(form).set({ crop_taxon: "NCBITaxon:4236" });
  await submit(form);
  assert.equal(sent.length, 1);
  assert.deepEqual([sent[0].protocol.crop_taxon, sent[0].protocol.cultivar], ["NCBITaxon:4236", ""]);
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
  for (const code of ["temp", "light", "exhaust", "fan", "humi", "co2"]) assert.ok(!endpoint.includes(code), `${code} is a sensor or device channel, not a plant endpoint`);
  assert.deepEqual(endpoint, [...new Set(PROJECT.protocols.map((row) => row.primary_endpoint).filter(Boolean))]);
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

// --- choosing a saved protocol, the JSON fold, the holdout fold ----------------------------------------

const sectionOf = (element, title) => byTag(element, "section").find((node) => byTag(node, "h2")[0]?.textContent === title);
const foldOf = (node) => byTag(node, "details").find((el) => byTag(el, "summary")[0]?.textContent === en["forms.advanced"]);
const posts = (ctx, path) => ctx.api.calls.filter((call) => call.method === "POST" && call.path === path);

test("saving as a saved protocol sends its id with the next version, through the page", async () => {
  const { element, ctx } = await renderPage("project", { projectId: PROJECT.project_id }, { lang: "en" });
  const section = sectionOf(element, en["project.protocols.title"]);
  const form = byTag(section, "form")[0];
  const choose = named(form, "save_as")[0];
  assert.deepEqual(optionsOf(choose), ["", "protocol-lettuce-light"]);
  assert.equal(choose.value, "", "it starts on a new protocol");
  assert.ok(visibleText(section).includes(en["protocol.form.saveAsNew"]));
  change(choose, "protocol-lettuce-light");
  assert.match(visibleText(section), /saved as version 2/);
  fill(form);
  await submit(form);
  const [post] = posts(ctx, "/protocols");
  assert.equal(post.body.protocol.id, "protocol-lettuce-light");
  assert.equal(post.body.protocol.version, 2);
});

test("the save-as choice and the saved notice call a protocol the console saved by its number, never its id", async () => {
  const id = `protocol-2-${TAIL}`;
  const fixtures = { "project.json": { ...PROJECT, protocols: [{ ...PROJECT.protocols[0], protocol_id: id }] } };
  const answers = { "/protocols": (body) => ({ protocol_id: body.protocol.id, version: body.protocol.version, digest: "d".repeat(64) }) };
  const cases = [
    ["en", en, "A new version of Protocol 2 (now version 1)", "Protocol 2, version 2 was saved."],
    ["zh", zh, "协议 2 的新版本（现在是第 1 版）", "已保存协议 2，第 2 版。"],
  ];
  for (const [lang, table, item, saved] of cases) {
    const { element, ctx } = await renderPage("project", { projectId: PROJECT.project_id }, { lang, fixtures, answers });
    const notices = [];
    ctx.notify = (message) => notices.push(message);
    const form = byTag(sectionOf(element, table["project.protocols.title"]), "form")[0];
    const choose = named(form, "save_as")[0];
    assert.deepEqual(byTag(choose, "option").map((option) => option.textContent), [table["protocol.form.saveAsNew"], item]);
    change(choose, id);
    fill(form);
    await submit(form);
    assert.deepEqual(notices, [saved]);
  }
});

test("the endpoint hint offers suggestions only when saved protocols give some", async () => {
  const hintOf = (form) => {
    const ids = named(form, "primary_endpoint")[0].getAttribute("aria-describedby").split(" ");
    return byClass(form, "field-hint").find((hint) => ids.includes(hint.getAttribute("id"))).textContent;
  };
  const saved = await open();
  assert.equal(hintOf(saved.form), en["protocol.form.endpointHint"]);
  const none = await open({ project: { ...PROJECT, protocols: [] } });
  assert.equal(hintOf(none.form), en["protocol.form.endpointHintNone"]);
  for (const table of [en, zh]) assert.doesNotMatch(table["protocol.form.endpointHintNone"], /suggestion|建议/i);
});

test("a new protocol is the default choice and gets a new id at version 1", async () => {
  const { element, ctx } = await renderPage("project", { projectId: PROJECT.project_id }, { lang: "en" });
  const form = byTag(sectionOf(element, en["project.protocols.title"]), "form")[0];
  fill(form);
  await submit(form);
  const [post] = posts(ctx, "/protocols");
  assert.equal(post.body.protocol.id, `protocol-2-${TAIL}`);
  assert.equal(post.body.protocol.version, 1);
});

test("the JSON fold starts from an empty skeleton and invents nothing", async () => {
  const { element } = await renderPage("project", { projectId: PROJECT.project_id }, { lang: "en" });
  const fold = foldOf(sectionOf(element, en["project.protocols.title"]));
  const value = JSON.parse(byTag(fold, "textarea")[0].value);
  assert.deepEqual(value.allocations, []);
  assert.deepEqual(value.treatments, []);
  assert.deepEqual(value.stages, []);
  for (const key of ["crop", "crop_taxon", "cultivar", "batch", "question", "hypothesis"]) assert.equal(value[key], "", key);
  for (const key of ["randomization_seed", "rounds", "blocks"]) assert.equal(value[key], null, key);
  assert.equal(value.analysis.target_effect, null);
  assert.equal(value.version, 1);
  assert.equal(value.id, `protocol-2-${TAIL}`);
});

test("the JSON fold refuses a version that is not above the saved ones, before sending", async () => {
  const { element, ctx } = await renderPage("project", { projectId: PROJECT.project_id }, { lang: "en" });
  const fold = foldOf(sectionOf(element, en["project.protocols.title"]));
  const jsonForm = byTag(fold, "form")[0];
  const area = byTag(fold, "textarea")[0];
  const edited = (version) => JSON.stringify({ ...JSON.parse(area.value), id: "protocol-lettuce-light", version });
  area.value = edited(1);
  await submit(jsonForm);
  assert.equal(posts(ctx, "/protocols").length, 0);
  assert.ok(visibleText(jsonForm).includes("Version 1 of this protocol is already saved. Use version 2 or higher."), visibleText(jsonForm));
  area.value = edited(2);
  await submit(jsonForm);
  assert.equal(posts(ctx, "/protocols").length, 1);
});

test("the holdout fold keeps an Advanced (JSON) editor that posts the same body", async () => {
  const { ctx, fold } = holdoutForm();
  const advanced = foldOf(fold);
  assert.ok(advanced);
  const area = byTag(advanced, "textarea")[0];
  assert.deepEqual(JSON.parse(area.value), { project_id: PROJECT.project_id, batch_ids: [], development_batch_ids: [], outcome_fields: [] });
  area.value = JSON.stringify({ project_id: PROJECT.project_id, batch_ids: ["b"], development_batch_ids: ["d"], outcome_fields: ["f"] });
  await submit(byTag(advanced, "form")[0]);
  assert.deepEqual(posts(ctx, "/holdouts")[0].body, { project_id: PROJECT.project_id, batch_ids: ["b"], development_batch_ids: ["d"], outcome_fields: ["f"] });
});

test("the form asks no more than the server: blank crop, batch, unit and stages go through", async () => {
  const { form, sent } = await open();
  fill(form);
  formControls(form).set({ crop: "", batch: "", experimental_unit: "", stages: [] });
  await submit(form);
  assert.equal(sent.length, 1, errorsIn(form).join(","));
  const { protocol } = sent[0];
  assert.deepEqual([protocol.crop, protocol.batch, protocol.stages, protocol.experimental_unit], ["", "", [], "tent"]);
  formControls(form).set({ crop: "c".repeat(300) });
  await submit(form);
  assert.equal(sent.length, 2);
});

// --- the choices follow the treatment rows ---------------------------------------------------------

test("allocation choices follow a treatment rename and clear when it is removed", async () => {
  const { form } = await open();
  fill(form);
  const [treatments, allocations] = groups(form);
  const picked = () => rowsOf(allocations).map((row) => named(row, "treatment_id")[0].value);
  assert.deepEqual(picked(), ["high", "control"]);
  change(named(rowsOf(treatments)[1], "id")[0], "strong");
  assert.deepEqual(picked(), ["strong", "control"]);
  assert.deepEqual(optionsOf(named(rowsOf(allocations)[0], "treatment_id")[0]), ["", "control", "strong"]);
  byTag(rowsOf(treatments)[0], "button").at(-1).dispatchEvent(new Event("click"));
  assert.deepEqual(picked(), ["strong", ""]);
  assert.equal(named(form, "control_treatment_id")[0].value, "");
});

test("a kept draft brings back the rows first, then the control and allocation choices", async () => {
  const first = await open();
  fill(first.form);
  document.body.append(first.element); // only a form on the page is kept
  saveAllDrafts();
  const again = await open();
  const [treatments, allocations] = groups(again.form);
  assert.deepEqual(rowsOf(treatments).map((row) => named(row, "id")[0].value), ["control", "high"]);
  assert.equal(named(again.form, "control_treatment_id")[0].value, "control");
  assert.deepEqual(rowsOf(allocations).map((row) => named(row, "treatment_id")[0].value), ["high", "control"]);
  assert.deepEqual(optionsOf(named(again.form, "control_treatment_id")[0]), ["", "control", "high"]);
});

test("a treatment code typed twice is refused beside the second row", async () => {
  const { form, sent } = await open();
  fill(form);
  const [treatments] = groups(form);
  change(named(rowsOf(treatments)[1], "id")[0], "control");
  await submit(form);
  assert.equal(sent.length, 0);
  assert.deepEqual(errorsIn(rowsOf(treatments)[0]), []);
  assert.deepEqual(errorsIn(rowsOf(treatments)[1]), [en["protocol.form.tidTwice"]]);
});

test("only plain decimals in a factor value become numbers; 0x10, 1e3 and 007 stay text", async () => {
  const { form, sent } = await open();
  fill(form);
  const [treatments] = groups(form);
  change(named(rowsOf(treatments)[0], "factors")[0], "a=40\nb=-1.5\nc=0x10\nd=1e3\ne=007\nf=0.5\ng=0");
  await submit(form);
  assert.deepEqual(sent[0].protocol.treatments[0].factors, { a: 40, b: -1.5, c: "0x10", d: "1e3", e: "007", f: 0.5, g: 0 });
});

test("a factor value a number cannot hold as typed stays text: no lost digits, no dropped zeros", async () => {
  const { form, sent } = await open();
  fill(form);
  const [treatments] = groups(form);
  change(named(rowsOf(treatments)[0], "factors")[0], "a=1.50\nb=12345678901234567890\nc=9007199254740993\nd=-0\ne=2.0\nf=1.25");
  await submit(form);
  assert.deepEqual(sent[0].protocol.treatments[0].factors, { a: "1.50", b: "12345678901234567890", c: "9007199254740993", d: "-0", e: "2.0", f: 1.25 });
  for (const table of [en, zh]) assert.match(table["protocol.form.tfactorsHint"], /1\.50/, "the hint says which values stay text");
});

test("the control and allocation choices show the treatment's name; a code only tells equal names apart or stands in for no name", async () => {
  const { form } = await open();
  const [treatments] = groups(form);
  const [first, second] = rowsOf(treatments);
  change(named(first, "id")[0], "control");
  change(named(first, "name")[0], "light 40 %");
  change(named(second, "id")[0], "high");
  const labels = () => byTag(named(form, "control_treatment_id")[0], "option").map((option) => option.textContent);
  assert.deepEqual(labels(), [en["form.choose"], "light 40 %", "(high)"], "no name yet: the code stands in, in parentheses");
  change(named(second, "name")[0], "light 40 %");
  assert.deepEqual(labels(), [en["form.choose"], "light 40 % (control)", "light 40 % (high)"], "equal names are told apart by code");
  change(named(second, "name")[0], "light 70 %");
  assert.deepEqual(labels(), [en["form.choose"], "light 40 %", "light 70 %"]);
  assert.deepEqual(optionsOf(named(form, "control_treatment_id")[0]), ["", "control", "high"], "values stay the codes");
});
