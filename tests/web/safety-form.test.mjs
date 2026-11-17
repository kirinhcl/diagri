import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { ApiError } from "../../src/growbridge/web/workbench/api.js";
import { clearDrafts, hasDraft, saveDraft } from "../../src/growbridge/web/workbench/drafts.js";
import { answerNextDialog, assertNoPendingDialogAnswers, openDialogs, resetDialogs } from "./support/dialogs.mjs";
import { findLeaks, visibleText } from "./support/leaks.mjs";
import { saveAllDrafts } from "../../src/growbridge/web/workbench/ui/forms.js";
import { FIXTURES, renderPage } from "./support/render-page.mjs";

afterEach(() => {
  assertNoPendingDialogAnswers();
  resetDialogs();
  clearDrafts();
});

const settle = () => new Promise((resolve) => setImmediate(resolve));
const submit = async (form) => {
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  await settle();
};

function find(node, match) {
  const own = match(node) ? [node] : [];
  return [...own, ...[...(node.children || [])].flatMap((child) => find(child, match))];
}
const byTag = (node, tag) => find(node, (el) => el.tagName && el.tagName.toLowerCase() === tag);
const byClass = (node, name) => find(node, (el) => el.classList && el.classList.contains(name));
const named = (node, name) => find(node, (el) => el.getAttribute && el.getAttribute("name") === name);

const NONE = { fixtures: { "safety.json": FIXTURES["safety-none.json"] } };
const NO_CAPS = { "capabilities.json": undefined };
const open = (options = {}) => renderPage("safety", {}, { lang: "en", ...options });
const formOf = (element) => byTag(element, "form")[0];
const rowsOf = (element) => byClass(element, "row-group-row");
const addRule = (element) => [...byClass(element, "row-group")[0].children].at(-1).dispatchEvent(new Event("click"));
const change = (input, value) => {
  input.value = value;
  input.dispatchEvent(new Event("change"));
};
const post = (ctx) => ctx.api.calls.find((call) => call.method === "POST");
const errorsIn = (node) => byClass(node, "field-error").map((error) => error.textContent).filter(Boolean);
const DEFAULTS = /(?<![\d.])(35|60|120|240|600)(?![\d.])/;

// One filled rule on a new row: humidity below 30 for 10 s, valid 20 s, fan to the given level.
function fillRow(row, { level = "3", id = "" } = {}) {
  change(named(row, "id")[0], id);
  change(named(row, "sensor")[0], "humi");
  change(named(row, "op")[0], "<");
  change(named(row, "value")[0], "30");
  change(named(row, "duration_seconds")[0], "10");
  change(named(row, "validity_seconds")[0], "20");
  change(named(row, "channel")[0], "fan");
  change(named(row, "level")[0], level);
}

test("with an approved set the form is prefilled from it and nothing else", async () => {
  const { element } = await open();
  const approved = FIXTURES["safety.json"].safety;
  const form = formOf(element);
  const rows = rowsOf(form);
  assert.equal(rows.length, 1);
  const [rule] = approved.rules;
  const value = (name, scope = rows[0]) => named(scope, name)[0].value;
  assert.deepEqual(
    ["id", "sensor", "op", "value", "duration_seconds", "validity_seconds", "channel", "level"].map((name) => value(name)),
    [rule.id, rule.sensor, rule.trigger.op, String(rule.trigger.value), String(rule.duration_seconds), String(rule.validity_seconds), rule.action.channel, String(rule.action.level)],
  );
  for (const [sensor, minutes] of Object.entries(approved.frozen.minutes)) assert.equal(value(sensor, form), String(minutes));
  assert.equal(value("max_gap_seconds", form), String(approved.frozen.max_gap_seconds));
  assert.equal(value("vpd", form), "", "a sensor the approved set does not check stays empty");
  assert.match(visibleText(element), /Version 2/);
});

test("with nothing approved every rule and frozen field starts empty and shows its allowed range; no safety number appears", async () => {
  const { element } = await open(NONE);
  const form = formOf(element);
  assert.equal(rowsOf(form).length, 0);
  const frozen = byTag(form, "input").filter((input) => input.getAttribute("name"));
  assert.ok(frozen.length >= 7);
  assert.ok(frozen.every((input) => input.value === ""));
  assert.ok(named(form, "max_gap_seconds")[0].hasAttribute("required"));
  const text = visibleText(element);
  assert.match(text, /Nothing is approved yet/);
  assert.match(text, /at most 1440/);
  assert.match(text, /at most 3600/);
  assert.doesNotMatch(text, DEFAULTS);
  addRule(form);
  const [row] = rowsOf(form);
  assert.ok(["id", "sensor", "op", "value", "duration_seconds", "validity_seconds", "channel", "level"].every((name) => named(row, name)[0].value === ""));
  assert.match(visibleText(row), /Fan 0 to 10/, "the level range of every output is beside the level field");
  assert.doesNotMatch(visibleText(element), DEFAULTS);
});

test("the form builds the same config the JSON editor would send, and the approval dialog still lists the changes", async () => {
  const { element, ctx } = await open();
  const form = formOf(element);
  addRule(form);
  fillRow(rowsOf(form)[1]);
  await submit(form);
  const [dialog] = openDialogs();
  assert.ok(dialog, "the approval dialog opened");
  assert.match(dialog.textContent, /Version: 1 → 2/);
  assert.match(dialog.textContent, /Rule added: Humidity below 30/);
  assert.doesNotMatch(dialog.textContent, /[{}"\[]|humi-fan/, "no raw JSON or path in the dialog");
  answerNextDialog(true);
  await settle();
  const approved = FIXTURES["safety.json"].safety;
  const { approved_by: _by, approved_at: _at, ...kept } = approved;
  const added = {
    id: "humi-fan-1", sensor: "humi", unit: "%", validity_seconds: 20, trigger: { op: "<", value: 30 }, duration_seconds: 10, action: { channel: "fan", level: 3 },
  };
  const sent = post(ctx);
  assert.equal(sent.path, "/safety/approve");
  assert.deepEqual(sent.body, { config: { ...kept, version: 2, rules: [...approved.rules, added] } });
});

test("cancelling the approval sends nothing", async () => {
  const { element, ctx } = await open();
  await submit(formOf(element));
  assert.ok(openDialogs().length);
  answerNextDialog(false);
  await settle();
  assert.equal(post(ctx), undefined);
  assert.equal(byClass(element, "form-status")[0].textContent, "", "a plain cancel says nothing");
  assert.ok(!byTag(formOf(element), "button").at(-1).disabled, "the button is usable again");
});

test("a level outside the channel's range is refused beside the field", async () => {
  const { element, ctx } = await open();
  const form = formOf(element);
  addRule(form);
  const row = rowsOf(form)[1];
  fillRow(row, { level: "11" });
  await submit(form);
  assert.equal(openDialogs().length, 0);
  assert.equal(post(ctx), undefined);
  assert.deepEqual(errorsIn(row), ["Enter 10 or less."]);
  assert.match(visibleText(row), /Allowed: 0 to 10\./);
  change(named(row, "level")[0], "2.5");
  await submit(form);
  assert.deepEqual(errorsIn(row), ["Enter a whole number."]);
});

test("a frozen limit of zero or above its ceiling is refused beside the field", async () => {
  const { element, ctx } = await open();
  const form = formOf(element);
  change(named(form, "temp")[0], "0");
  change(named(form, "humi")[0], "1441");
  change(named(form, "max_gap_seconds")[0], "");
  await submit(form);
  assert.equal(post(ctx), undefined);
  assert.deepEqual(errorsIn(form).sort(), ["Enter 1440 or less.", "Enter a number greater than 0.", "This field is required."]);
});

test("the unit follows the sensor and is not typed", async () => {
  const { element } = await open(NONE);
  const form = formOf(element);
  addRule(form);
  const [row] = rowsOf(form);
  assert.equal(named(row, "unit").length, 0);
  const unit = () => byClass(named(row, "value")[0].parentNode, "field-unit")[0].textContent;
  assert.equal(unit(), "");
  change(named(row, "sensor")[0], "temp");
  assert.equal(unit(), "°C");
  change(named(row, "sensor")[0], "humi");
  assert.equal(unit(), "%");
  change(named(row, "sensor")[0], "co2");
  assert.equal(unit(), "ppm");
});

test("the level range follows the chosen output", async () => {
  const { element } = await open(NONE);
  const form = formOf(element);
  addRule(form);
  const [row] = rowsOf(form);
  change(named(row, "channel")[0], "light");
  assert.equal(named(row, "level")[0].getAttribute("max"), "100");
  assert.match(visibleText(row), /Allowed: 0 to 100\./);
  change(named(row, "channel")[0], "fan");
  assert.equal(named(row, "level")[0].getAttribute("max"), "10");
});

test("when capabilities cannot be read the form still submits and shows no invented range", async () => {
  const { element, ctx } = await open({ fixtures: NO_CAPS });
  const form = formOf(element);
  const text = visibleText(element);
  assert.match(text, /could not be read/);
  assert.doesNotMatch(text, /Allowed: \d/);
  assert.doesNotMatch(text, /Fan 0 to/);
  const sensors = byTag(named(rowsOf(form)[0], "sensor")[0], "option").map((option) => option.value);
  assert.deepEqual(sensors, ["", "temp"], "only the sensors of the approved set");
  assert.equal(named(rowsOf(form)[0], "level")[0].hasAttribute("max"), false);
  await submit(form);
  answerNextDialog(true);
  await settle();
  assert.equal(post(ctx).path, "/safety/approve");
  assert.equal(post(ctx).body.config.version, 2);
});

test("with no capabilities and nothing approved the form points to the advanced JSON fold", async () => {
  const { element } = await open({ fixtures: { ...NONE.fixtures, ...NO_CAPS } });
  assert.match(visibleText(element), /Use the Advanced \(JSON\) fold/);
  assert.equal(byTag(element, "form").length, 1, "only the JSON editor remains");
  assert.equal(byClass(element, "edit-fold").length, 1);
});

test("the JSON editor sits closed in an Advanced (JSON) fold and sends through the same approval", async () => {
  const { element, ctx } = await open();
  const [fold] = byClass(element, "edit-fold");
  assert.ok(!fold.hasAttribute("open"));
  const area = byTag(fold, "textarea")[0];
  area.value = JSON.stringify({ ...JSON.parse(area.value), version: 5 });
  await submit(byTag(fold, "form")[0]);
  assert.match(openDialogs()[0].textContent, /5/);
  answerNextDialog(true);
  await settle();
  assert.equal(post(ctx).body.config.version, 5);
});

const approvedWith = (rules) => ({ "safety.json": { safety: { ...FIXTURES["safety.json"].safety, rules } } });
const rule = (id, sensor, channel) => ({
  id, sensor, unit: sensor === "temp" ? "C" : "%", validity_seconds: 20, trigger: { op: ">", value: 40 }, duration_seconds: 30, action: { channel, level: 1 },
});
const removeRow = (row) => byTag(row, "button").at(-1).dispatchEvent(new Event("click"));
const approveNow = async (form) => {
  await submit(form);
  answerNextDialog(true);
  await settle();
};

test("two approvals in a row never send the same version", async () => {
  const { element, ctx } = await open();
  let approved = FIXTURES["safety.json"].safety;
  const read = ctx.api.get;
  const write = ctx.api.post;
  ctx.api.get = async (path) => (path === "/safety" ? { safety: structuredClone(approved) } : read(path));
  ctx.api.post = async (path, body, options) => {
    approved = { ...body.config, approved_by: "dev", approved_at: 1794800000 };
    return write(path, body, options);
  };
  const form = formOf(element);
  change(named(form, "temp")[0], "100");
  await approveNow(form);
  change(named(form, "temp")[0], "110");
  await approveNow(form);
  const [first, second] = ctx.api.calls.filter((call) => call.method === "POST");
  assert.equal(first.body.config.version, 2);
  assert.equal(second.body.config.version, 3);
  assert.match(visibleText(element), /Version 4/, "the shown version follows the approved set");
});

test("submitting from nothing approved sends version 1 with only the limits that were typed", async () => {
  const { element, ctx } = await open(NONE);
  const form = formOf(element);
  change(named(form, "max_gap_seconds")[0], "30");
  await approveNow(form);
  assert.deepEqual(post(ctx).body, { config: { version: 1, rules: [], frozen: { minutes: {}, max_gap_seconds: 30 } } });
});

test("a generated rule name never repeats another rule's name", async () => {
  const { element, ctx } = await open({ fixtures: approvedWith([rule("temp-light-1", "temp", "light"), rule("humi-fan-2", "humi", "fan")]) });
  const form = formOf(element);
  removeRow(rowsOf(form)[0]);
  addRule(form);
  fillRow(rowsOf(form)[1], { id: "" });
  await approveNow(form);
  assert.deepEqual(post(ctx).body.config.rules.map((r) => r.id), ["humi-fan-2", "humi-fan-1"]);
});

test("a typed rule name that another rule already has is refused beside the field", async () => {
  const { element, ctx } = await open();
  const form = formOf(element);
  addRule(form);
  const row = rowsOf(form)[1];
  fillRow(row, { id: FIXTURES["safety.json"].safety.rules[0].id });
  await submit(form);
  assert.equal(post(ctx), undefined);
  assert.deepEqual(errorsIn(row), ["Another rule already has this name."]);
  assert.equal(openDialogs().length, 0);
});

test("adding a rule and removing a middle one lists plain sentences only, in both languages", async () => {
  for (const lang of ["zh", "en"]) {
    const rules = [rule("one-a", "temp", "light"), rule("two-b", "humi", "fan"), rule("three-c", "temp", "exhaust")];
    const { element } = await open({ lang, fixtures: approvedWith(rules) });
    const form = formOf(element);
    removeRow(rowsOf(form)[1]);
    addRule(form);
    fillRow(rowsOf(form)[2]);
    await submit(form);
    const text = openDialogs()[0].textContent;
    assert.deepEqual(findLeaks(text), [], lang);
    assert.doesNotMatch(text, /rules\[|[{}]/, lang);
    const lines = byTag(openDialogs()[0], "li").map((li) => li.textContent);
    assert.equal(lines.length, 3, `${lang}: version, one removed, one added; the later rule is unchanged: ${lines.join(" | ")}`);
    answerNextDialog(false);
    await settle();
    resetDialogs();
  }
});

test("a server refusal of a rule's whole action lands beside the level field", async () => {
  const { element, ctx } = await open();
  const form = formOf(element);
  const problem = { loc: ["body", "config", "rules", 0, "action"], msg: "level 7 is outside the range", type: "value_error", limits: {} };
  ctx.api.post = async () => {
    throw new ApiError(422, "validation", "invalid", [problem]);
  };
  await approveNow(form);
  assert.equal(errorsIn(rowsOf(form)[0]).length, 1);
});

test("rule rows survive a lost session", async () => {
  const first = await open(NONE);
  const form = formOf(first.element);
  addRule(form);
  fillRow(rowsOf(form)[0]);
  document.body.append(first.element);
  assert.ok(saveAllDrafts() >= 1);
  first.element.remove();
  const second = await open(NONE);
  const [row] = rowsOf(formOf(second.element));
  assert.equal(named(row, "sensor")[0].value, "humi");
  assert.equal(named(row, "level")[0].value, "3");
  assert.equal(named(row, "channel")[0].value, "fan");
});

test("the empty choice of a select says Choose, and the level takes whole steps", async () => {
  const { element } = await open(NONE);
  addRule(formOf(element));
  const [row] = rowsOf(element);
  for (const name of ["sensor", "op", "channel"]) assert.equal(byTag(named(row, name)[0], "option")[0].textContent, "Choose…");
  assert.equal(named(row, "level")[0].getAttribute("step"), "1");
});

const foldOf = (element) => byClass(element, "edit-fold")[0];
const sendFold = async (element, edit) => {
  const area = byTag(foldOf(element), "textarea")[0];
  area.value = JSON.stringify(edit(JSON.parse(area.value)));
  await submit(byTag(foldOf(element), "form")[0]);
};

test("a raw dialog line names the rule that changed, not the first one", async () => {
  const { element } = await open({ fixtures: approvedWith([rule("one-a", "temp", "light"), rule("two-b", "humi", "fan")]) });
  await sendFold(element, (config) => {
    config.rules[1].sensor = "mystery";
    config.rules[1].extra = 2;
    return config;
  });
  const text = openDialogs()[0].textContent;
  assert.match(text, /rules\[1\]\.sensor/);
  assert.match(text, /rules\[1\]\.extra/);
  assert.doesNotMatch(text, /rules\[0\]/);
  answerNextDialog(false);
  await settle();
});

// A page whose approved set follows every approval, as the server's would.
async function pageWithState(options = {}) {
  const page = await open(options);
  const { ctx } = page;
  let approved = FIXTURES["safety.json"].safety;
  const read = ctx.api.get;
  const write = ctx.api.post;
  ctx.api.get = async (path) => (path === "/safety" ? { safety: structuredClone(approved) } : read(path));
  ctx.api.post = async (path, body, options2) => {
    approved = { ...body.config, approved_by: "dev", approved_at: 1794800000 };
    return write(path, body, options2);
  };
  return page;
}
const posted = (ctx) => ctx.api.calls.filter((call) => call.method === "POST").map((call) => call.body.config.version);
const foldForm = (element) => byTag(foldOf(element), "form")[0];

test("two edited approvals in a row through the fold: the second must raise the version", async () => {
  const { element, ctx } = await pageWithState();
  const area = byTag(foldOf(element), "textarea")[0];
  assert.equal(JSON.parse(area.value).version, 2, "the fold starts from the approved set with the next version");
  await submit(foldForm(element));
  answerNextDialog(true);
  await settle();
  assert.deepEqual(posted(ctx), [2]);
  await submit(foldForm(element)); // still carries version 2
  assert.equal(openDialogs().length, 0, "refused before the dialog");
  assert.deepEqual(posted(ctx), [2]);
  const status = byClass(foldOf(element), "form-status")[0];
  assert.ok(status.textContent.includes(ctx.t("safety.form.versionTooLow", { current: "2", next: "3" })), status.textContent);
  area.value = JSON.stringify({ ...JSON.parse(area.value), version: 3 });
  await submit(foldForm(element));
  answerNextDialog(true);
  await settle();
  assert.deepEqual(posted(ctx), [2, 3]);
});

test("the version message is in both languages and names the version needed", async () => {
  for (const lang of ["zh", "en"]) {
    const { element, ctx } = await open({ lang });
    const area = byTag(foldOf(element), "textarea")[0];
    area.value = JSON.stringify({ ...JSON.parse(area.value), version: 1 });
    await submit(foldForm(element));
    assert.equal(post(ctx), undefined);
    const status = byClass(foldOf(element), "form-status")[0].textContent;
    assert.ok(status.includes(ctx.t("safety.form.versionTooLow", { current: "1", next: "2" })), `${lang}: ${status}`);
    assert.match(status, /2/);
  }
});

test("a restored fold draft survives a form approval and a cancelled fold submission", async () => {
  const draft = JSON.stringify({ version: 9, rules: [], frozen: { minutes: {}, max_gap_seconds: 5 } });
  saveDraft("safety", { text: draft });
  const { element, ctx } = await pageWithState();
  assert.ok(foldOf(element).hasAttribute("open"));
  const area = byTag(foldOf(element), "textarea")[0];
  assert.equal(area.value, draft);
  await approveNow(formOf(element));
  assert.equal(area.value, draft, "an approval through the form leaves the draft alone");
  await submit(foldForm(element));
  answerNextDialog(false);
  await settle();
  assert.equal(area.value, draft);
  assert.deepEqual(posted(ctx), [2]);
});

test("the fold leaves no draft unless the operator typed in it", async () => {
  const { element } = await pageWithState();
  document.body.append(element);
  try {
    await approveNow(formOf(element));
    saveAllDrafts();
    assert.equal(hasDraft("safety"), false);
    byTag(foldOf(element), "textarea")[0].value = "{ typed";
    saveAllDrafts();
    assert.equal(hasDraft("safety"), true);
  } finally {
    element.remove();
  }
});

// After a recovery nothing is in force, yet the server refuses any version it approved before.
const AFTER_RECOVERY = { fixtures: { "safety.json": { safety: null, highest_version: 4 } } };

test("with nothing in force the form numbers the new set above the highest version approved before", async () => {
  const { element, ctx } = await open(AFTER_RECOVERY);
  assert.match(visibleText(element), /Version 5/);
  const form = formOf(element);
  change(named(form, "max_gap_seconds")[0], "30");
  await approveNow(form);
  assert.equal(post(ctx).body.config.version, 5);
});

test("the fold refuses a version not above the highest approved, also when nothing is in force", async () => {
  const { element, ctx } = await open(AFTER_RECOVERY);
  const area = byTag(foldOf(element), "textarea")[0];
  area.value = JSON.stringify({ ...JSON.parse(area.value), version: 4 });
  await submit(foldForm(element));
  assert.equal(openDialogs().length, 0, "refused before the dialog");
  assert.equal(post(ctx), undefined);
  const status = byClass(foldOf(element), "form-status")[0];
  assert.ok(status.textContent.includes(ctx.t("safety.form.versionTooLow", { current: "4", next: "5" })), status.textContent);
});

test("a set that changed between the two reads is never overwritten, and the refusal is shown", async () => {
  const { element, ctx } = await open();
  const read = ctx.api.get;
  let reads = 0;
  ctx.api.get = async (path) => {
    const body = await read(path);
    if (path !== "/safety") return body;
    reads += 1;
    return reads >= 2 ? { safety: { ...body.safety, version: 9, approved_at: 1794900000 } } : body;
  };
  const form = formOf(element);
  await submit(form);
  answerNextDialog(true);
  await settle();
  assert.equal(post(ctx), undefined);
  const status = byClass(element, "form-status")[0];
  assert.ok(!status.hidden);
  assert.ok(status.textContent.includes(ctx.t("safety.changedMeanwhile")));
});
