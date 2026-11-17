import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { clearDrafts } from "../../src/growbridge/web/workbench/drafts.js";
import { answerNextDialog, assertNoPendingDialogAnswers, openDialogs, resetDialogs } from "./support/dialogs.mjs";
import { visibleText } from "./support/leaks.mjs";
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
const DEFAULTS = /(?<![\d.])(35|120|600)(?![\d.])/;

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
  assert.match(dialog.textContent, /version: 1 → 2/);
  assert.match(dialog.textContent, /humi-fan-2/);
  answerNextDialog(true);
  await settle();
  const approved = FIXTURES["safety.json"].safety;
  const { approved_by: _by, approved_at: _at, ...kept } = approved;
  const added = {
    id: "humi-fan-2", sensor: "humi", unit: "%", validity_seconds: 20, trigger: { op: "<", value: 30 }, duration_seconds: 10, action: { channel: "fan", level: 3 },
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
