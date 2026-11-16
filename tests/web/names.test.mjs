import assert from "node:assert/strict";
import test from "node:test";

import { displayName, nameDetails, roleLabel } from "../../src/growbridge/web/workbench/ui/names.js";
import { FIXTURES, renderPage, testCtx } from "./support/render-page.mjs";
import { findLeaks, visibleText } from "./support/leaks.mjs";

const NOW = Date.UTC(2026, 10, 21) / 1000;
const zh = testCtx({ lang: "zh", now: NOW, timezone: "UTC" });
const en = testCtx({ lang: "en", now: NOW, timezone: "UTC" });
const AT = Date.UTC(2026, 10, 20, 8, 5) / 1000;

test("displayName uses names and numbers, never ids", () => {
  assert.equal(displayName(zh, "round", { round_id: "round_9d38", round_number: 2 }), "第 2 轮");
  assert.equal(displayName(zh, "round", { round_id: "round_9d38" }), "未命名轮次");
  assert.equal(displayName(en, "round", { round_number: 2 }), "Round 2");
  assert.equal(displayName(zh, "stage", { stage_index: 1, phase: "vegetative" }), "第 1 阶段 · vegetative");
  assert.equal(displayName(zh, "stage", { stage_index: 2, phase: null }), "第 2 阶段");
  assert.equal(displayName(en, "stage", { stage_index: 2 }), "Stage 2");
  assert.equal(displayName(zh, "stage", { stage_id: "stage-x-1" }), "未命名阶段");
  assert.equal(displayName(en, "stage", { stage_id: "stage-x-1" }), "Unnamed stage");
  assert.equal(displayName(zh, "project", { project_id: "project_1" }), "未命名项目");
  assert.equal(displayName(zh, "project", { project_name: "生菜" }), "生菜");
  assert.equal(displayName(en, "project", { name: "Lettuce", project_name: "x" }), "Lettuce");
  assert.equal(displayName(zh, "researchTask", { question: "a".repeat(80) }), `${"a".repeat(60)}…`);
  assert.equal(displayName(zh, "researchTask", { question: "short" }), "short");
  assert.equal(displayName(en, "researchTask", {}), "Unnamed task");
});

test("displayName names snapshots, manual tasks and attempts by time", () => {
  assert.equal(displayName(zh, "snapshot", { created_at: AT, complete: true }), "11月20日 08:05 的数据快照（完整）");
  assert.equal(displayName(zh, "snapshot", { created_at: AT, complete: false }), "11月20日 08:05 的数据快照（不完整）");
  assert.equal(displayName(en, "snapshot", {}), "Data snapshot");
  assert.equal(displayName(zh, "manualTask", { kind: "photo", due_at: AT }), "拍照（11月20日 08:05 到期）");
  assert.equal(displayName(zh, "manualTask", { kind: "photo" }), "拍照");
  assert.equal(displayName(zh, "attempt", { created_at: AT }), "11月20日 08:05 提交的计算");
  assert.equal(displayName(zh, "attempt", { since: AT }), "11月20日 08:05 提交的计算");
  assert.equal(displayName(en, "attempt", {}), "Compute attempt");
});

test("displayName never shows a raw code for an unknown kind of manual task", () => {
  assert.equal(findLeaks(displayName(zh, "manualTask", { kind: "new_kind_x" })).length, 0);
  assert.equal(displayName(zh, "manualTask", { kind: "new_kind_x" }), "未知（技术详情）");
});

test("roleLabel keeps the old behaviour", () => {
  assert.equal(roleLabel(zh.t, "planner"), "计划 Agent");
  assert.equal(roleLabel(zh.t, "weird"), "系统");
});

test("nameDetails lists the ids that exist", () => {
  assert.deepEqual(nameDetails({ round_id: "r", stage_id: null, x: 1 }).map(([, v]) => v), ["r"]);
  const rows = nameDetails({ project_id: "p", round_id: "r", id: "i" });
  assert.deepEqual(rows.map(([, v]) => v), ["p", "r", "i"]);
  assert.ok(rows.every(([label]) => typeof label === "string"));
});

function find(node, match) {
  if (match(node)) return node;
  for (const child of node.childNodes || []) {
    const found = find(child, match);
    if (found) return found;
  }
  return null;
}
const heading = (element) => find(element, (n) => n.nodeName?.toLowerCase() === "h1").textContent;
const lead = (element) => find(element, (n) => n.getAttribute?.("class") === "page-lead");

const ROUND_ID = FIXTURES["round.json"].round_id;
const STAGE_ID = FIXTURES["stage.json"].stage_id;
const PROJECT_ID = FIXTURES["project.json"].project_id;

function crumbsClean(ctx) {
  assert.ok(ctx.crumbs.length > 0);
  for (const crumb of ctx.crumbs) assert.deepEqual(findLeaks(crumb.label), [], crumb.label);
}

test("round page title and crumbs carry no id", async () => {
  const { element, ctx } = await renderPage("round", { roundId: ROUND_ID }, { lang: "zh" });
  assert.match(visibleText(element), /第 1 轮/);
  assert.deepEqual(ctx.crumbs.map((c) => c.label), ["项目", "Lettuce light series", "第 1 轮"]);
  crumbsClean(ctx);
  assert.equal(heading(element), "第 1 轮");
});

test("stage page title and crumbs carry no id", async () => {
  const { element, ctx } = await renderPage("stage", { stageId: STAGE_ID }, { lang: "en" });
  assert.equal(heading(element), "Stage 1 · vegetative");
  assert.deepEqual(ctx.crumbs.map((c) => c.label), ["Projects", "Lettuce light series", "Round 1", "Stage 1 · vegetative"]);
  crumbsClean(ctx);
});

test("project page lead carries no id", async () => {
  const { element, ctx } = await renderPage("project", { projectId: PROJECT_ID }, { lang: "zh" });
  assert.equal(heading(element), "Lettuce light series");
  assert.ok(!visibleText(lead(element)).includes(PROJECT_ID));
  crumbsClean(ctx);
});

test("an old round without number or project name shows generic words", async () => {
  const { round_number: _n, project_name: _p, ...old } = FIXTURES["round.json"];
  const { element, ctx } = await renderPage("round", { roundId: ROUND_ID }, { lang: "zh", fixtures: { "round.json": old } });
  assert.deepEqual(ctx.crumbs.map((c) => c.label), ["项目", "未命名项目", "未命名轮次"]);
  assert.equal(heading(element), "未命名轮次");
});
