import assert from "node:assert/strict";
import test from "node:test";

import { AHEAD_SECONDS, irrigationNotice, rowActions, tasksView, visibleRows } from "../../src/growbridge/web/workbench/pages/stage-tasks.js";
import { visibleText, visibleTextIncludingDetails } from "./support/leaks.mjs";
import { installFakeDom, testCtx } from "./support/render-page.mjs";

installFakeDom();

const NOW = 100_000;
const row = (fields) => ({ task_id: "water", kind: "irrigation", seconds: 5, status: "open", record: null, due_at: NOW, ...fields });
const body = (fields = {}) => ({ now: NOW, early_seconds: 3600, stage_state: "running", occurrences: [], ...fields });

test("rows are listed newest first and at most a day ahead", () => {
  const rows = [row({ due_at: NOW - 10 }), row({ due_at: NOW + 10 }), row({ due_at: NOW + AHEAD_SECONDS + 1 })];
  assert.deepEqual(visibleRows(body({ occurrences: rows })).map((r) => r.due_at), [NOW + 10, NOW - 10]);
});

test("a planned irrigation can be started only while the stage runs and it is not done", () => {
  assert.deepEqual(rowActions(row(), body()), { record: true, irrigate: true });
  assert.deepEqual(rowActions(row({ status: "done" }), body()), { record: true, irrigate: false });
  assert.deepEqual(rowActions(row(), body({ stage_state: "paused" })), { record: true, irrigate: false });
  assert.deepEqual(rowActions(row({ seconds: null }), body()), { record: true, irrigate: false });
  assert.deepEqual(rowActions(row({ kind: "photo", seconds: null }), body()), { record: true, irrigate: false });
});

test("a planned irrigation is offered only while it is upcoming or open", () => {
  // the server runs the pump once per occurrence and never after its deadline ("missed")
  for (const status of ["missed", "skipped", "late"]) {
    assert.equal(rowActions(row({ status }), body()).irrigate, false, status);
  }
  assert.equal(rowActions(row({ status: "upcoming", due_at: NOW + 60 }), body()).irrigate, true);
});

test("a task more than an hour away cannot be recorded yet", () => {
  assert.deepEqual(rowActions(row({ due_at: NOW + 3601 }), body()), { record: false, irrigate: false });
  assert.deepEqual(rowActions(row({ due_at: NOW + 3600 }), body()).record, true);
});

test("the notice after a planned run says whether it was done, partial or not recorded", () => {
  const action = { request_id: "planned-x-1" };
  const answer = (task) => ({ action, task });
  assert.deepEqual(irrigationNotice(answer({ status: "done" })), { key: "tasks.irrigated", tone: "ok" });
  assert.deepEqual(irrigationNotice(answer({ status: "partial" })), { key: "tasks.irrigatePartial", tone: "error" });
  assert.deepEqual(irrigationNotice(answer(null)), { key: "tasks.irrigateUnconfirmed", tone: "error" });
});

// --- the table ------------------------------------------------------------------------------------
const settle = () => new Promise((resolve) => setImmediate(resolve));

function elements(node, name) {
  const own = node.tagName && node.tagName.toLowerCase() === name ? [node] : [];
  return [...own, ...(node.children || []).flatMap((child) => elements(child, name))];
}

const RECORD = { id: "taskrec_124f46e5ac284c2dbbb91a237e29bd1f", outcome: "done", done_at: NOW - 600, operator: "dev", irrigation_request_id: "planned-0123456789abcdef0123456789abcdef-1" };
const tableBody = () =>
  body({
    on_time_seconds: 7200,
    occurrences: [
      row({ task_id: "canopy-measure", kind: "measurement", seconds: null, status: "done", due_at: NOW - 3600, record: RECORD }),
      row({ task_id: "irrigate-daily", seconds: 600 }),
    ],
  });

function view(lang = "zh") {
  const notices = [];
  const ctx = { ...testCtx({ lang, now: NOW }), notify: (message, tone) => notices.push({ message, tone }) };
  let changed = 0;
  const env = { ctx, stage: { stage_id: "stage-1" }, onChanged: async () => (changed += 1) };
  return { element: tasksView(env, tableBody()), ctx, notices, changed: () => changed };
}

test("the task table has no task-id column and verbs on its buttons", () => {
  const { element } = view();
  assert.deepEqual(elements(element, "th").map((th) => th.textContent), ["到期时间", "类型", "状态", "记录"]);
  const labels = elements(element, "button").map((button) => button.textContent);
  assert.ok(labels.includes("标记完成") && labels.includes("跳过"), labels.join(", "));
  const text = visibleText(element);
  assert.ok(!text.includes("irrigate-daily") && !text.includes("canopy-measure"), text);
  assert.match(text, /浇水（水泵 10 分钟）/);
});

test("each task keeps its ids in its own technical details", () => {
  const all = visibleTextIncludingDetails(view().element);
  for (const id of ["irrigate-daily", "canopy-measure", RECORD.id, RECORD.irrigation_request_id]) assert.ok(all.includes(id), id);
});

test("the lead is one sentence and the scoring rules fold away", () => {
  const { element } = view();
  const lead = elements(element, "p").find((p) => p.textContent.startsWith("列出"));
  assert.equal(lead.textContent, "列出今天和明天的人工任务，最新的在上。");
  const rules = elements(element, "details").find((d) => !(d.getAttribute("class") || "").includes("tech-details"));
  assert.equal(elements(rules, "summary")[0].textContent, "计分规则");
  assert.match(rules.textContent, /两小时/);
  const en = elements(view("en").element, "summary").map((s) => s.textContent);
  assert.ok(en.includes("How tasks are scored"), en.join(", "));
});

test("recording a task names it, not its id", async () => {
  const { element, ctx, notices, changed } = view();
  const done = elements(element, "button").find((button) => button.textContent === "标记完成");
  done.dispatchEvent(new Event("click"));
  await settle();
  const sent = ctx.api.calls.find((call) => call.method === "POST");
  assert.deepEqual(sent.body, { task_id: "irrigate-daily", due_at: NOW, outcome: "done" });
  assert.equal(notices.length, 1);
  assert.match(notices[0].message, /^已记录：浇水（.+ 到期）$/);
  assert.ok(!notices[0].message.includes("irrigate-daily"));
  assert.equal(changed(), 1);
});
