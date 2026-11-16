import assert from "node:assert/strict";
import test from "node:test";

import { enterFields } from "../../src/growbridge/web/workbench/pages/evidence.js";
import { visibleText, visibleTextIncludingDetails } from "./support/leaks.mjs";
import { renderPage, testCtx } from "./support/render-page.mjs";
import { versionMismatch } from "../../src/growbridge/web/workbench/pages/round-analysis.js";

const ctx = { t: (key) => `t:${key}` };

test("entering evidence makes the operator choose whether it was calibrated: no default", () => {
  const calibrated = enterFields(ctx).find((field) => field.name === "calibrated");
  assert.equal(calibrated.required, true);
  assert.equal(calibrated.value, undefined);
  assert.deepEqual(
    calibrated.options.map((option) => option.value),
    ["", "yes", "no"],
  );
});

test("the analysis block says when the protocol's latest version is not the round's", () => {
  assert.equal(versionMismatch({ version: 2 }, { protocol_version: 2 }), null);
  assert.deepEqual(versionMismatch({ version: 3 }, { protocol_version: 2 }), { latest: 3, round: 2 });
});

const walk = (node) => [node, ...[...(node.children || [])].flatMap(walk)];
const NOW = 1796594627;
const CARD = { id: "card_1a2b3c4d5e6f", source_class: "paper", citation: "Smith 2020", claim: "Blue light shortens lettuce", value: 12.5, unit: "cm", calibrated: false, source: "model:planner", added_at: NOW - 600, verified_by: null, verified_at: null, note: null };
const cards = (rows) => ({ "evidence.json": { cards: rows } });

test("an evidence card is titled by its claim and keeps its id in the details", async () => {
  const { element } = await renderPage("evidence", {}, { fixtures: cards([CARD, { ...CARD, id: "card_9", claim: "Second", source: "lab-b" }]), now: NOW });
  const heads = walk(element).filter((el) => el.localName === "h3" || (el.getAttribute("class") || "").includes("evidence-claim"));
  assert.equal(heads[0].textContent, CARD.claim);
  const text = visibleText(element);
  assert.match(text, /计划 Agent/);
  assert.match(text, /lab-b/);
  assert.doesNotMatch(text, / · /);
  assert.doesNotMatch(text, /card_1a2b3c4d5e6f/);
  assert.match(visibleTextIncludingDetails(element), /card_1a2b3c4d5e6f/);
});

test("an evidence card entered by the signed-in operator says you", async () => {
  const me = testCtx().me.operator;
  const { element } = await renderPage("evidence", {}, { fixtures: cards([{ ...CARD, source: me }]), now: NOW });
  assert.match(visibleText(element), /录入人.*你|你/);
});

test("compute usage reads as hours", async () => {
  const { element } = await renderPage("compute", {}, { now: NOW });
  const text = visibleText(element);
  assert.match(text, /已用 1\.00 小时，预留 2\.00 小时，共 10\.00 小时/);
  assert.match(text, /已用 0\.40 GB，预留 1\.00 GB，共 5\.00 GB/);
  assert.match(text, /my\.csc\.fi|修改预算/);
  assert.doesNotMatch(text, /att_7d2e4f6a|28471953/);
});

test("the change-budget button fills the task field", async () => {
  const { element } = await renderPage("compute", {}, { now: NOW });
  const button = walk(element).find((el) => el.localName === "button" && el.textContent === "修改预算");
  const field = () => walk(element).find((el) => el.getAttribute && el.getAttribute("name") === "task_id");
  assert.equal(field().value, "");
  button.dispatchEvent(new Event("click"));
  assert.match(field().value, /^task_3f1c/);
  assert.match(visibleText(element), /已选择任务 3f1c9a7e…/);
});

test("a task reads the same in every table, and a new budget row does not rename another", async () => {
  const base = (await renderPage("compute", {}, { now: NOW })).element;
  const label = /任务 3f1c9a7e…/;
  assert.equal((visibleText(base).match(/任务 3f1c9a7e…/g) || []).length >= 3, true);
  const { FIXTURES } = await import("./support/render-page.mjs");
  const compute = FIXTURES["compute.json"];
  const other = { ...compute.tasks[0], task_id: "task_0000aaaa1111bbbb2222cccc3333dddd" };
  const more = await renderPage("compute", {}, { now: NOW, fixtures: { "compute.json": { ...compute, tasks: [other, ...compute.tasks] } } });
  assert.match(visibleText(more.element), label);
  assert.match(visibleText(more.element), /任务 0000aaaa…/);
});

test("an evidence value is shown exactly as entered", async () => {
  for (const [value, shown] of [[0.0035, "0.0035"], [12.345, "12.345"]]) {
    const { element } = await renderPage("evidence", {}, { fixtures: cards([{ ...CARD, value, unit: "cm" }]), now: NOW, lang: "en" });
    assert.match(visibleText(element), new RegExp(`${shown} cm`));
    assert.match(visibleTextIncludingDetails(element), new RegExp(`Value as entered.*${shown}`, "s"));
  }
});
