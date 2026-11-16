import test from "node:test";
import assert from "node:assert/strict";
import { minutePrecision } from "../../src/growbridge/web/workbench/ui/forms.js";
import { STATE_GROUPS, stateGroup } from "../../src/growbridge/web/workbench/ui/status.js";
import {
  KIND_ORDER,
  DESCRIBERS,
  describe,
  draw,
  pageView,
  groupByKind,
  groupView,
  inboxCounts,
  inboxTarget,
  normalizeInbox,
} from "../../src/growbridge/web/workbench/pages/inbox.js";

test("every state from the plan's table lands in its colour group", () => {
  const table = {
    waiting: ["pending_review", "manual", "paused", "needs_attention", "needs_review", "awaiting_choice", "prepared"],
    onsite: ["recovery_check", "failed"],
    active: ["running", "stage_running", "designing", "stage_review", "data_verification", "analysis",
      "in_progress", "computing", "fetching", "remote_queued", "reconcile", "queued"],
    done: ["ended", "stopped", "delivered", "aborted", "done", "cancelled"],
  };
  assert.deepEqual(STATE_GROUPS, table);
  for (const [group, states] of Object.entries(table)) {
    for (const state of states) assert.equal(stateGroup(state), group, state);
  }
  assert.equal(stateGroup("brand_new_state"), "other");
  assert.equal(stateGroup("constructor"), "other");
});

test("datetime inputs drop only zero seconds, never the minutes", () => {
  assert.equal(minutePrecision("2025-11-13T16:00"), "2025-11-13T16:00");
  assert.equal(minutePrecision("2025-11-13T16:00:00"), "2025-11-13T16:00");
  assert.equal(minutePrecision("2025-11-13T16:05:00.000"), "2025-11-13T16:05");
  assert.equal(minutePrecision("2025-11-13T16:05:30"), "2025-11-13T16:05:30");
});

test("each inbox kind links to its page", () => {
  const item = (kind, extra = {}) => ({ kind, id: "x/1", project_id: "p1", round_id: "r1", ...extra });
  for (const kind of ["stage_review", "stage_manual", "stage_recovery", "stage_paused"]) {
    assert.equal(inboxTarget(item(kind)), "#/stages/x%2F1");
  }
  assert.equal(inboxTarget(item("round_choice")), "#/rounds/x%2F1");
  assert.equal(inboxTarget(item("alert")), "#/alerts?focus=x%2F1");
  assert.equal(inboxTarget(item("compute_stuck")), "#/compute");
  assert.equal(inboxTarget(item("task")), "#/projects/p1");
  assert.equal(inboxTarget(item("task", { project_id: null })), "#/projects");
  assert.equal(inboxTarget(item("something_new")), null);
});

test("inbox counts include what the server cut", () => {
  const data = {
    items: [
      { kind: "alert", id: "a1" },
      { kind: "stage_review", id: "s1" },
    ],
    truncated: { alert: 3, task: 2 },
  };
  assert.deepEqual(inboxCounts(data), { inbox: 7, alerts: 4 });
  assert.deepEqual(inboxCounts({}), { inbox: 0, alerts: 0 });
});

test("groups follow the urgency order and keep kinds that only have cut items", () => {
  const inbox = normalizeInbox({
    items: [
      { kind: "task", id: "t1" },
      { kind: "brand_new", id: "n1" },
      { kind: "stage_recovery", id: "s1" },
      { kind: "alert" },
      null,
    ],
    truncated: { compute_stuck: 4, alert: 0, stage_review: "2" },
  });
  const groups = groupByKind(inbox);
  assert.deepEqual(
    groups.map((group) => [group.kind, group.items.length, group.hidden]),
    [
      ["stage_recovery", 1, 0],
      ["compute_stuck", 0, 4],
      ["task", 1, 0],
      ["brand_new", 1, 0],
    ],
  );
  assert.equal(KIND_ORDER[0], "stage_recovery");
});

// --- inbox titles, durations and "more" links (Task 14) -----------------------------------------
import { findLeaks, visibleText, visibleTextIncludingDetails } from "./support/leaks.mjs";
import { testCtx } from "./support/render-page.mjs";

const NOW = 1_800_000_000;
const findAll = (node, test) => [...(test(node) ? [node] : []), ...[...(node.children || [])].flatMap((child) => findAll(child, test))];
const withClass = (name) => (node) => (node.getAttribute?.("class") || "").split(/\s+/).includes(name);
const queryOne = (node, selector) => {
  const [cls, tag] = selector.replace(/^\./, "").split(" ");
  const parent = findAll(node, withClass(cls.replace(".", "")))[0];
  return tag ? findAll(parent, (n) => n.localName === tag)[0] : parent;
};

test("a stage waiting for review is titled by names", () => {
  const ctx = testCtx({ now: NOW });
  const item = { kind: "stage_review", id: "stage-dev", project_id: "p1", round_id: "round_1", project_name: "Lettuce", round_number: 1, stage_index: 2, phase: "vegetative", since: NOW - 60, detail: { state: "pending_review" } };
  const { title } = describe(ctx, item);
  assert.match(title, /Lettuce/);
  assert.match(title, /第 1 轮/);
  assert.match(title, /第 2 阶段/);
  assert.ok(!title.includes("stage-dev") && !title.includes("round_1"));
  assert.deepEqual(findLeaks(title), []);
});

test("an old stage item falls back to the generic names", () => {
  const ctx = testCtx({ now: NOW });
  const { title } = describe(ctx, { kind: "stage_review", id: "s1", since: NOW, detail: { state: "pending_review" } });
  assert.match(title, /未命名项目/);
  assert.match(title, /未命名轮次/);
  assert.match(title, /未命名阶段/);
});

test("the other stage kinds and round choice and compute are titled by names", () => {
  const ctx = testCtx({ now: NOW });
  const stage = describe(ctx, { kind: "stage_paused", id: "s1", project_name: "Lettuce", round_number: 3, stage_index: 1, since: NOW, detail: { state: "paused" } });
  assert.equal(stage.title, "第 1 阶段：已暂停");
  assert.ok(stage.meta.join(" ").includes("Lettuce") && stage.meta.join(" ").includes("第 3 轮"));
  const choice = describe(ctx, { kind: "round_choice", id: "r1", project_name: "Lettuce", round_number: 3, since: NOW, detail: {} });
  assert.equal(choice.title, "Lettuce 第 3 轮：等待你选择下一步");
  const stuck = describe(ctx, { kind: "compute_stuck", id: "att1", since: NOW, detail: { phase: "running", reason: "r" } });
  assert.equal(stuck.title, "计算尝试卡住：运行中");
});

test("an alert kind shows its label; an unknown kind says unknown", () => {
  const ctx = testCtx({ now: NOW });
  const meta = (kind) => describe(ctx, { kind: "alert", id: "a1", since: NOW, detail: { alert_kind: kind, message: "m", severity: "warning" } }).meta.join(" ");
  assert.match(meta("data_gap"), /数据空档/);
  assert.match(meta("brand_new"), /未知（技术详情）/);
  assert.ok(!meta("brand_new").includes("brand_new"));
});

test("a task item is titled by its question and shows the owner role", () => {
  const ctx = testCtx({ now: NOW });
  const d = describe(ctx, { kind: "task", id: "t1", project_name: "Lettuce", since: NOW, detail: { question: "Why?", state: "needs_review", owner_role: "researcher" } });
  assert.equal(d.title, "Why?");
  assert.ok(d.meta.join(" ").includes("Lettuce"));
  assert.ok(!d.meta.join(" ").includes("researcher"));
  const long = describe(ctx, { kind: "task", id: "t1", since: NOW, detail: { question: "word ".repeat(80) } });
  assert.equal(typeof long.title, "object");
});

test("the waiting time is a duration with the exact time in the title", () => {
  const ctx = testCtx({ now: NOW });
  const view = groupView(ctx, { kind: "alert", hidden: 0, items: [{ kind: "alert", id: "a1", since: NOW - 12000, detail: { message: "m", alert_kind: "data_gap" } }] });
  assert.match(visibleText(view), /已等待 3 小时 20 分钟/);
  const time = queryOne(view, ".inbox-time");
  assert.ok(time.getAttribute("title"));
  assert.equal(testCtx({ lang: "en", now: NOW }).t("inbox.waiting", { duration: "3 h" }), "Waiting 3 h");
});

test("the 'more' line links to the full list", () => {
  const ctx = testCtx({ now: NOW });
  const href = (kind) => queryOne(groupView(ctx, { kind, items: [], hidden: 12 }), ".inbox-more a").getAttribute("href");
  assert.equal(href("alert"), "#/alerts");
  assert.equal(href("stage_review"), "#/projects");
  assert.equal(href("round_choice"), "#/projects");
  assert.equal(href("task"), "#/projects");
  assert.equal(href("compute_stuck"), "#/compute");
  assert.match(visibleText(groupView(ctx, { kind: "alert", items: [], hidden: 12 })), /还有 12 项，去 告警 查看/);
});

test("each item's ids go into its own technical details", () => {
  const ctx = testCtx({ now: NOW });
  const view = groupView(ctx, { kind: "stage_review", hidden: 0, items: [{ kind: "stage_review", id: "stage-dev", project_id: "p1", round_id: "r1", since: NOW, detail: { state: "pending_review" } }] });
  const details = queryOne(view, ".tech-details");
  assert.ok(details);
  assert.match(details.textContent, /stage-dev/);
  assert.match(details.textContent, /p1/);
});

test("DESCRIBERS is exported", () => {
  assert.deepEqual(Object.keys(DESCRIBERS).sort(), ["alert", "compute_stuck", "round_choice", "stage", "task"]);
});

test("each alert row has an id and the focused one is highlighted", async () => {
  const { renderPage } = await import("./support/render-page.mjs");
  const id = "alert_a71084164435490a9d4344321ed49313";
  const { element } = await renderPage("alerts", { focus: id });
  const rows = findAll(element, (node) => node.localName === "tr" && (node.getAttribute("id") || "").startsWith("alert-"));
  assert.ok(rows.length >= 2);
  const focused = rows.filter(withClass("alert-focused"));
  assert.deepEqual(focused.map((row) => row.getAttribute("id")), [`alert-${id}`]);
});

test("alerts page survives a hostile or unknown focus and highlights nothing", async () => {
  const { renderPage } = await import("./support/render-page.mjs");
  for (const focus of ['a"b', "a\\b", "nope", "]"]) {
    const { element } = await renderPage("alerts", { focus });
    assert.equal(findAll(element, withClass("alert-focused")).length, 0, focus);
    assert.ok(visibleText(element).length > 20);
  }
});

const LONG_TASK = { kind: "task", id: "t1", project_id: "p1", since: NOW - 60, detail: { question: `${"word ".repeat(80)}end`, state: "needs_review", owner_role: "researcher" } };
const keyed = (view, key) => findAll(view.list, (n) => n.getAttribute?.("data-key") === key)[0];

test("an open fold stays open across a redraw of the same item", () => {
  const ctx = testCtx({ now: NOW });
  const view = pageView(ctx);
  draw(view, ctx, { items: [LONG_TASK], truncated: {} });
  const open = (node) => findAll(node, (n) => n.localName === "details");
  const before = open(keyed(view, "task:t1"));
  assert.ok(before.length >= 2);
  before.forEach((fold) => fold.setAttribute("open", ""));
  draw(view, ctx, { items: [{ ...LONG_TASK, since: NOW - 120 }, { kind: "alert", id: "a1", since: NOW, detail: { message: "m", alert_kind: "data_gap" } }], truncated: {} });
  assert.ok(open(keyed(view, "task:t1")).every((fold) => fold.hasAttribute("open")));
  assert.ok(open(keyed(view, "alert:a1")).every((fold) => !fold.hasAttribute("open")));
});

test("the open link of a folded row names the item", () => {
  const ctx = testCtx({ now: NOW });
  const view = pageView(ctx);
  draw(view, ctx, { items: [LONG_TASK], truncated: {} });
  const link = findAll(view.list, withClass("inbox-open"))[0];
  assert.match(link.getAttribute("aria-label"), /^打开: word word word/);
});

// --- final review: no stage or device ids in the inbox's text (F1) ------------------------------
const CHOICE_ROUND = "round_9d38ffa4ca3049948194e0b60315c650";
const CHOICE_STAGE = `stage-${CHOICE_ROUND}-1`;

test("a round choice names no stage id and keeps it in the item's details", () => {
  const ctx = testCtx({ now: NOW });
  const item = { kind: "round_choice", id: CHOICE_ROUND, project_name: "Lettuce", round_number: 3, since: NOW, detail: { awaiting_choice: CHOICE_STAGE } };
  const view = groupView(ctx, { kind: "round_choice", hidden: 0, items: [item] });
  assert.ok(!visibleText(view).includes(CHOICE_STAGE), visibleText(view));
  assert.match(visibleText(view), /本轮有一个阶段已停止，请选择这一轮接下来怎么做/);
  assert.match(visibleTextIncludingDetails(view), new RegExp(`阶段 id ${CHOICE_STAGE}`));
  const en = groupView(testCtx({ lang: "en", now: NOW }), { kind: "round_choice", hidden: 0, items: [item] });
  assert.match(visibleText(en), /A stage of this round stopped; choose how this round goes on\./);
});

test("the simulator reads as a simulated device; any device id stays in the item's details", () => {
  const ctx = testCtx({ now: NOW });
  const stageItem = (device) => ({ kind: "stage_paused", id: "s1", project_name: "Lettuce", round_number: 3, stage_index: 1, since: NOW, detail: { state: "paused", device_id: device } });
  const simulated = groupView(ctx, { kind: "stage_paused", hidden: 0, items: [stageItem("SIMULATED")] });
  assert.match(visibleText(simulated), /设备：模拟设备/);
  assert.ok(!visibleText(simulated).includes("SIMULATED"));
  assert.match(visibleTextIncludingDetails(simulated), /设备 SIMULATED/);
  const real = groupView(ctx, { kind: "stage_paused", hidden: 0, items: [stageItem("chamber-2")] });
  assert.match(visibleText(real), /设备：chamber-2/);
  assert.match(visibleTextIncludingDetails(real), /设备 chamber-2/);
  const en = groupView(testCtx({ lang: "en", now: NOW }), { kind: "stage_paused", hidden: 0, items: [stageItem("SIMULATED")] });
  assert.match(visibleText(en), /Device: Simulated device/);
});
