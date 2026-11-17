import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { activityLog } from "../../src/growbridge/web/workbench/pages/stage-actions.js";
import { AHEAD_SECONDS, irrigationNotice, irrigationPrompt, plannedIrrigation, rowActions, tasksView, visibleRows } from "../../src/growbridge/web/workbench/pages/stage-tasks.js";
import { answerNextDialog, assertNoPendingDialogAnswers, openDialogs, resetDialogs } from "./support/dialogs.mjs";
import { assertNoLeaks, visibleText, visibleTextIncludingDetails } from "./support/leaks.mjs";
import { installFakeDom, testCtx } from "./support/render-page.mjs";

installFakeDom();

afterEach(() => {
  assertNoPendingDialogAnswers();
  resetDialogs();
});

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
  return [...own, ...[...(node.children || [])].flatMap((child) => elements(child, name))];
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
  assert.equal(lead.textContent, "列出到明天为止的人工任务，最新的在上。");
  const rules = elements(element, "details").find((d) => !(d.getAttribute("class") || "").includes("tech-details"));
  assert.equal(elements(rules, "summary")[0].textContent, "计分规则");
  assert.match(rules.textContent, /两小时/);
  const english = view("en").element;
  const en = elements(english, "summary").map((s) => s.textContent);
  assert.ok(en.includes("How tasks are scored"), en.join(", "));
  assert.ok(elements(english, "p").some((p) => p.textContent === "Manual tasks up to tomorrow, newest first."));
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

test("the water button and its confirmation write the pump time the way the row does", () => {
  const { element, ctx } = view();
  const labels = elements(element, "button").map((button) => button.textContent);
  assert.ok(labels.includes("立即浇水（10 分钟）"), labels.join(", "));
  const prompt = irrigationPrompt(ctx, row({ seconds: 600 }));
  assert.equal(prompt.title, "立即浇水（10 分钟）");
  assert.equal(prompt.lines[0], "水泵运行 10 分钟后关闭，阶段继续运行。");
  const en = irrigationPrompt(testCtx({ lang: "en" }), row({ seconds: 600 }));
  assert.equal(en.title, "Water now (10 min)");
  assert.match(en.lines[0], /^The pump runs for 10 min and/);
});

test("a planned watering that reached no device keeps its request id in the activity log's details", async () => {
  const requestId = "planned-0123456789abcdef0123456789abcdef-1";
  const notices = [];
  const posted = [];
  const base = testCtx({ lang: "zh", now: NOW });
  const answer = { action: { request_id: requestId, state: "failed", created_at: NOW, error: null }, task: null };
  const api = { ...base.api, post: async (path, sent, options) => (posted.push({ path, sent, options }), answer) };
  const ctx = { ...base, api, notify: (message, tone) => notices.push({ message, tone }) };
  const log = activityLog(ctx, { signal: new AbortController().signal, alive: () => true });
  let changed = 0;
  const env = { ctx, stage: { stage_id: "stage-1" }, log, onChanged: async () => (changed += 1) };
  await plannedIrrigation(env, row({ task_id: "irrigate-daily", seconds: 600 }));
  await settle();
  assert.deepEqual(posted.map((call) => [call.path, call.sent]), [["/stages/stage-1/manual-tasks/irrigate", { task_id: "irrigate-daily", due_at: NOW }]]);
  assert.equal(notices.length, 1);
  assert.match(notices[0].message, /^浇水（.+ 到期） 没有到达设备，未记录。/);
  assert.ok(!notices[0].message.includes(requestId));
  const shown = visibleText(log.element);
  assert.match(shown, /你的操作结果 .*浇水（.+ 到期）/);
  assert.ok(!shown.includes(requestId), shown);
  assertNoLeaks(log.element);
  assert.ok(visibleTextIncludingDetails(log.element).includes(requestId));
  assert.equal(changed, 1);
});

// --- final review: a planned pump run keeps its tenths of a second (F5) --------------------------
test("a planned 2.5 s irrigation asks to run the pump 2.5 s, and 0.4 s is not 0 s", () => {
  const ctx = testCtx({ lang: "zh" });
  const said = (seconds) => [irrigationPrompt(ctx, row({ seconds })).title, ...irrigationPrompt(ctx, row({ seconds })).lines].join(" ");
  assert.match(said(2.5), /2\.5 秒/);
  assert.doesNotMatch(said(2.5), /3 秒/);
  assert.match(said(0.4), /0\.4 秒/);
  assert.doesNotMatch(said(0.4), /(^|[^.\d])0 秒/);
});

const partialRecord = (fields) => ({ ...RECORD, outcome: "partial", irrigation_request_id: "planned-aa-1", ...fields });
const partialView = (record, lang = "zh") => {
  const ctx = { ...testCtx({ lang, now: NOW }), notify: () => {} };
  const env = { ctx, stage: { stage_id: "stage-1" }, onChanged: async () => {} };
  return tasksView(env, body({ occurrences: [row({ task_id: "irrigate-daily", seconds: 600, status: "partial", record })] }));
};

test("a partial irrigation says how long the pump ran and why it stopped", () => {
  const record = partialRecord({ ran_seconds: 90, ended_early_code: "pump_off_interlock", ended_early_params: {}, ended_early: "pump off by interlock" });
  const element = partialView(record);
  const text = visibleText(element);
  assert.match(text, /水泵运行了 90 秒/);
  assert.match(text, /联锁关了水泵，浇水提前结束。/);
  assert.match(text, /查一下联锁为什么动作。/);
  assert.doesNotMatch(text, /pump off by interlock/);
  assert.match(visibleTextIncludingDetails(element), /pump off by interlock/);
  assert.equal(elements(element, "details").filter((d) => (d.getAttribute("class") || "").includes("tech-details")).length, 1);
  assertNoLeaks(element);
});

test("an old partial record without a code reads as 'ended early' and keeps its English in the details", () => {
  const record = partialRecord({ ran_seconds: 30, ended_early: "stopped by operator" });
  const element = partialView(record);
  assert.match(visibleText(element), /浇水提前结束。/);
  assert.doesNotMatch(visibleText(element), /stopped by operator/);
  assert.match(visibleTextIncludingDetails(element), /stopped by operator/);
});

test("a partial irrigation whose pump run is unconfirmed says so", () => {
  const element = partialView(partialRecord({ ended_early_code: "not_confirmed", ended_early_params: { action_state: "failed" } }));
  assert.match(visibleText(element), /水泵运行未得到确认/);
  assert.match(visibleText(element), /浇水没有确认完成/);
});

test("a planned irrigation whose pump was not confirmed off says the pump may still be on and to switch it off on site", () => {
  const record = partialRecord({ ran_seconds: 20, ended_early_code: "pump_off_unconfirmed", ended_early_params: {}, ended_early: "hand-over: paused" });
  for (const [lang, said, todo] of [["zh", /水泵可能还开着/, /到现场手动关泵。/], ["en", /may still be on/, /Switch the pump off by hand on site\./]]) {
    const element = partialView(record, lang);
    const text = visibleText(element);
    assert.match(text, said, lang);
    assert.match(text, todo, lang);
    assert.doesNotMatch(text, /未知（技术详情）|Unknown|hand-over: paused/, lang);
    assert.match(visibleTextIncludingDetails(element), /hand-over: paused/, lang);
    assertNoLeaks(element);
  }
});

test("irrigation notices name the task, not the request", async () => {
  const notices = [];
  const ctx = { ...testCtx({ lang: "zh", now: NOW }), notify: (message, tone) => notices.push({ message, tone }) };
  ctx.api = { post: async () => ({ task: { status: "done" }, action: { request_id: "wb-77" } }), get: async () => ({}) };
  const env = { ctx, stage: { stage_id: "stage-1" }, log: { track: () => {} }, onChanged: async () => {} };
  await plannedIrrigation(env, row({ task_id: "irrigate-daily", seconds: 600 }));
  assert.match(notices[0].message, /^已浇水并记录：浇水（.+ 到期）$/);
  assert.ok(!notices[0].message.includes("wb-77"));
});

// --- skipping asks, with an optional reason (TSK-03) ----------------------------------------------
const skipButton = (element) => elements(element, "button").find((button) => ["跳过", "Skip"].includes(button.textContent));

test("skipping asks for an optional reason and sends it as the note; cancelling sends nothing", async () => {
  const { element, ctx, notices } = view("en");
  const posts = () => ctx.api.calls.filter((call) => call.method === "POST");
  skipButton(element).dispatchEvent(new Event("click"));
  await settle();
  const [dialog] = openDialogs();
  assert.ok(dialog.textContent.includes("A later record replaces this one"), dialog.textContent);
  assert.ok(elements(dialog, "input").some((input) => input.getAttribute("maxlength") === "200"));
  answerNextDialog(false);
  await settle();
  await settle();
  assert.equal(posts().length, 0);
  assert.equal(notices.length, 0);
  skipButton(element).dispatchEvent(new Event("click"));
  await settle();
  answerNextDialog("  pump is broken  ");
  await settle();
  await settle();
  assert.deepEqual(posts().map((call) => call.body), [{ task_id: "irrigate-daily", due_at: NOW, outcome: "skipped", note: "pump is broken" }]);
  assert.equal(notices.length, 1);
  skipButton(element).dispatchEvent(new Event("click"));
  await settle();
  answerNextDialog("");
  await settle();
  await settle();
  assert.deepEqual(posts()[1].body, { task_id: "irrigate-daily", due_at: NOW, outcome: "skipped" });
});

test("a done row offers no skip", () => {
  const { element } = view("en");
  const rows = elements(element, "tr").slice(1);
  const done = rows.find((tr) => tr.textContent.includes("Done"));
  assert.ok(done, "the done row");
  assert.ok(!elements(done, "button").some((button) => button.textContent === "Skip"));
  assert.ok(elements(rows.find((tr) => tr !== done), "button").some((button) => button.textContent === "Skip"));
});

test("the task row shows the reason given", () => {
  const record = { ...RECORD, outcome: "skipped", note: "pump <b>broken</b>" };
  const skipped = body({ occurrences: [row({ status: "skipped", record })] });
  const ctx = testCtx({ lang: "en", now: NOW });
  const element = tasksView({ ctx, stage: { stage_id: "stage-1" }, onChanged: async () => {} }, skipped);
  assert.ok(visibleText(element).includes("pump <b>broken</b>"), visibleText(element));
  assert.equal(elements(element, "b").length, 0, "escaped as text");
});
