import assert from "node:assert/strict";
import test from "node:test";

import en from "../../src/growbridge/web/workbench/i18n/en.js";
import zh from "../../src/growbridge/web/workbench/i18n/zh.js";
import {
  conversationSection,
  groupToolEntries,
  openRounds,
  roundPicker,
  statusText,
  statusView,
  toolGroupView,
} from "../../src/growbridge/web/workbench/pages/conversation.js";
import { visibleText, visibleTextIncludingDetails } from "./support/leaks.mjs";
import { FIXTURES, testCtx } from "./support/render-page.mjs";

const ctx = { t: (key, vars) => (vars ? `${key}${JSON.stringify(vars)}` : key) };

test("a message can only be about an open round, newest first as listed", () => {
  const project = {
    rounds: [
      { round_id: "r3", state: "stage_review" },
      { round_id: "r2", state: "delivered" },
      { round_id: "r1", state: "aborted" },
      { round_id: "r0", state: "designing" },
    ],
  };
  assert.deepEqual(
    openRounds(project).map((r) => r.round_id),
    ["r3", "r0"],
  );
  assert.deepEqual(openRounds({}), []);
});

test("a status line says who ended and how; the server's reason is not part of it", () => {
  const back = { role: "planner", text: "needs_attention", detail: { reason: "ended without saving" } };
  const done = { role: "orchestrator", text: "done", detail: { reason: "run finished" } };
  assert.doesNotMatch(statusText(ctx, back), /ended without saving/);
  assert.doesNotMatch(statusText(ctx, done), /run finished/);
  assert.match(statusText(ctx, { role: "planner", text: "follow_up", detail: {} }), /^chat.followUp/);
});

test("every conversation string exists in both languages", () => {
  const keys = (table) => Object.keys(table).filter((key) => key.startsWith("chat."));
  assert.deepEqual(keys(zh).sort(), keys(en).sort());
  assert.ok(keys(en).length > 10);
});

// Fills {placeholders} the way the console's translator does, so labels can be read in each language.
const tFor = (table) => (key, vars) => (table[key] ?? key).replace(/\{(\w+)\}/g, (_, name) => vars[name]);

test("an auditor entry is labelled as the auditor in both languages, not as system", () => {
  const followUp = { role: "auditor", text: "follow_up", detail: {} };
  assert.match(statusText({ t: tFor(en) }, followUp), /^Auditor /);
  assert.match(statusText({ t: tFor(zh) }, followUp), /^监察 Agent/);
  assert.doesNotMatch(statusText({ t: tFor(zh) }, followUp), /系统/);
});

// --- tools, status entries, the round picker and sending ------------------------------------------

function elements(node, name) {
  const own = node.localName === name ? [node] : [];
  return [...own, ...[...(node.children || [])].flatMap((child) => elements(child, name))];
}
const hasClass = (node, name) => (node.getAttribute("class") || "").split(/\s+/).includes(name);
const settle = () => new Promise((resolve) => setImmediate(resolve));
// Entries of an earlier task unless a task id is given; the goal sent in these tests becomes "task_new".
const tool = (seq, name, extra = {}, task = "task_old") => ({
  seq,
  task_id: task,
  role: "planner",
  kind: "tool",
  text: name,
  detail: { is_error: false, input: '{"stage_id": "stage-dev"}', result: '{"ok": true}', ...extra },
  at: 1796594700 + seq,
});
const reply = (seq, role = "planner", task = "task_old") => ({ seq, task_id: task, role, kind: "reply", text: `reply ${seq}`, detail: { final: true }, at: 1796594700 + seq });
const message = (seq) => ({ seq, task_id: "task_new", role: "user", kind: "message", text: "Please check the data.", detail: { operator: "dev", round_id: null }, at: 1796594700 + seq });

test("adjacent tool calls fold into one group", () => {
  const out = groupToolEntries([{ kind: "reply" }, { kind: "tool", text: "a" }, { kind: "tool", text: "b" }, { kind: "reply" }, { kind: "tool", text: "c" }]);
  assert.deepEqual(
    out.map((e) => (e.kind === "toolGroup" ? `g${e.items.length}` : e.kind)),
    ["reply", "g2", "reply", "g1"],
  );
  assert.deepEqual(groupToolEntries([]), []);
});

test("one tool call reads as what it did; its name, input and result are in the details", () => {
  const view = toolGroupView(testCtx({ lang: "zh" }), [tool(1, "validate_run_sheet")]);
  const text = visibleText(view);
  assert.equal(text, "计划 Agent · 检查运行单");
  const all = visibleTextIncludingDetails(view);
  for (const part of ["validate_run_sheet", "stage-dev", '"ok": true']) assert.ok(all.includes(part), part);
  assert.equal(elements(view, "details").length, 1);
  assert.ok(hasClass(elements(view, "details")[0], "tech-details"));
});

test("several tool calls in a row fold into one line that counts them", () => {
  const items = [tool(1, "query_evidence"), tool(2, "validate_run_sheet", { is_error: true }), tool(3, "no_such_tool")];
  const view = toolGroupView(testCtx({ lang: "zh" }), items);
  const group = elements(view, "details").find((node) => !hasClass(node, "tech-details"));
  assert.equal(group.open, false);
  assert.equal(elements(group, "summary")[0].textContent, "计划 Agent · 用了 3 个工具 （出错）");
  const text = visibleText(view);
  for (const part of ["查询证据卡", "检查运行单", "未知（技术详情）"]) assert.ok(text.includes(part), part);
  for (const part of ["query_evidence", "no_such_tool", "stage-dev"]) assert.ok(!text.includes(part), part);
  assert.ok(visibleTextIncludingDetails(view).includes("no_such_tool"));
  const english = visibleText(toolGroupView(testCtx({ lang: "en" }), items.slice(0, 2)));
  assert.match(english, /^Planner · Used 2 tools \(error\)/);
});

test("a status entry keeps the raw reason in the details", () => {
  const zhCtx = testCtx({ lang: "zh" });
  const failed = { role: "orchestrator", kind: "status", text: "needs_attention", detail: { reason: "model unavailable: APIStatusError: overloaded" } };
  assert.equal(statusText(zhCtx, failed), "编排 Agent 的任务结束：需要关注");
  assert.doesNotMatch(statusText(zhCtx, failed), /APIStatusError/);
  const view = statusView(zhCtx, failed);
  assert.ok(!visibleText(view).includes("APIStatusError"), visibleText(view));
  assert.ok(visibleTextIncludingDetails(view).includes("model unavailable: APIStatusError: overloaded"));
  const odd = statusView(zhCtx, { role: "planner", kind: "status", text: "half_done", detail: {} });
  assert.equal(visibleText(odd), "计划 Agent 的任务结束：未知（技术详情）");
  assert.ok(visibleTextIncludingDetails(odd).includes("half_done"));
});

test("the round picker starts at no round and names rounds", () => {
  const project = {
    rounds: [
      { round_id: "round_b2", state: "stage_review", round_number: 2 },
      { round_id: "round_a1", state: "delivered", round_number: 1 },
      { round_id: "round_old", state: "designing" },
    ],
  };
  const select = roundPicker(testCtx({ lang: "zh" }), project);
  assert.equal(select.value, "");
  const options = elements(select, "option").map((option) => option.textContent);
  assert.deepEqual(options, ["不指定轮次", "第 2 轮 · 阶段审阅中", "未命名轮次 · 设计中"]);
  assert.match(options[1], /第 \d+ 轮/);
  assert.deepEqual(elements(select, "option").map((option) => option.value), ["", "round_b2", "round_old"]);
});

// A conversation section whose server answers each read with the next batch of entries.
function chatWith(batches, post = async () => ({ task_id: "task_new" })) {
  const base = testCtx({ lang: "zh" });
  const reads = [];
  const get = async (path) => (reads.push(path), { entries: batches.shift() || [] });
  const ctx = { ...base, api: { get, post } };
  const chat = conversationSection(ctx, { project_id: "project_1", rounds: [] });
  const log = elements(chat.element, "ol")[0];
  const form = elements(chat.element, "form")[0];
  const send = async (text) => {
    elements(form, "textarea")[0].value = text;
    form.dispatchEvent(new Event("submit"));
    await settle();
  };
  return { chat, log, form, reads, send };
}

const kindOf = (li) => {
  if (hasClass(li, "chat-pending")) return "pending";
  if (hasClass(li, "chat-tool")) return `tools:${Math.max(1, elements(li, "li").filter((item) => hasClass(item, "chat-tool-item")).length)}`;
  if (hasClass(li, "chat-user")) return "message";
  if (hasClass(li, "chat-agent")) return "reply";
  return "status";
};

test("a tool call that arrives after a tool group joins that group", async () => {
  const batches = [[reply(1), tool(2, "query_evidence")], [tool(3, "validate_run_sheet"), tool(4, "save_plan_draft")], [tool(5, "query_evidence")], [reply(6), tool(7, "query_evidence")]];
  const { chat, log, reads } = chatWith(batches);
  await chat.refresh();
  assert.deepEqual([...log.children].map(kindOf), ["reply", "tools:1"]);
  await chat.refresh();
  assert.deepEqual([...log.children].map(kindOf), ["reply", "tools:3"]);
  log.children[1].firstChild.open = true; // the reader opened the group
  await chat.refresh();
  assert.deepEqual([...log.children].map(kindOf), ["reply", "tools:4"]);
  assert.equal(log.children[1].firstChild.open, true);
  await chat.refresh();
  assert.deepEqual([...log.children].map(kindOf), ["reply", "tools:4", "reply", "tools:1"]);
  assert.deepEqual(reads.map((path) => path.split("after=")[1]), ["0", "2", "4", "5"]);
});

test("a sent message shows a pending line until its own task answers", async () => {
  let answer;
  const answered = new Promise((resolve) => (answer = resolve));
  const batches = [[], [tool(1, "query_evidence")], [message(2)], [tool(3, "validate_run_sheet")], [reply(4, "orchestrator", "task_new")]];
  const { chat, log, send } = chatWith(batches, () => answered);
  await chat.refresh();
  await send("Please check the data.");
  assert.deepEqual([...log.children].map(kindOf), ["pending"]);
  assert.equal(visibleText(log.children[0]), "已发送，编排 Agent 稍后接手。");
  await chat.refresh(); // a poll while the goal is on its way brings another task's call
  assert.deepEqual([...log.children].map(kindOf), ["tools:1", "pending"]);
  answer({ task_id: "task_new" });
  await settle();
  await settle();
  assert.deepEqual([...log.children].map(kindOf), ["tools:1", "message", "pending"]);
  await chat.refresh(); // another task is still working
  assert.deepEqual([...log.children].map(kindOf), ["tools:1", "message", "tools:1", "pending"]);
  await chat.refresh(); // the orchestrator takes up the new goal
  assert.deepEqual([...log.children].map(kindOf), ["tools:1", "message", "tools:1", "reply"]);
});

test("tool calls join an open group in place, keeping open folds open", async () => {
  const { chat, log } = chatWith([[tool(1, "query_evidence")], [tool(2, "validate_run_sheet")], [tool(3, "save_plan_draft")]]);
  const techFolds = (node) => elements(node, "details").filter((details) => hasClass(details, "tech-details"));
  await chat.refresh();
  const first = techFolds(log.children[0])[0];
  first.open = true; // the reader opened the single call's details
  await chat.refresh();
  const group = log.children[0];
  const fold = elements(group, "details")[0];
  assert.equal(techFolds(group)[0], first, "the first call's details are the same element");
  assert.equal(first.open, true);
  assert.equal(elements(fold, "summary")[0].textContent, "计划 Agent · 用了 2 个工具");
  fold.open = true;
  const second = techFolds(group)[1];
  second.open = true;
  await chat.refresh();
  assert.equal(log.children[0], group, "the group is the same element");
  assert.equal(elements(group, "details")[0], fold);
  assert.ok(fold.open && first.open && second.open);
  assert.equal(elements(fold, "summary")[0].textContent, "计划 Agent · 用了 3 个工具");
  assert.deepEqual([...log.children].map(kindOf), ["tools:3"]);
});

test("a group that gets a call from another role names the role on each call", () => {
  const view = toolGroupView(testCtx({ lang: "zh" }), [tool(1, "query_evidence"), { ...tool(2, "delegate_task"), role: "orchestrator" }]);
  assert.equal(elements(view, "summary").find((node) => !node.parentNode || !hasClass(node.parentNode, "tech-details")).textContent, "用了 2 个工具");
  const lines = elements(view, "p").filter((node) => hasClass(node, "chat-tool-line")).map((node) => node.textContent);
  assert.deepEqual(lines, ["计划 Agent · 查询证据卡", "编排 Agent · 委派任务"]);
});

test("two reads that overlap show each entry once", async () => {
  const same = [reply(1), tool(2, "query_evidence")];
  const { chat, log } = chatWith([same, same]);
  await Promise.all([chat.refresh(), chat.refresh()]);
  assert.deepEqual([...log.children].map(kindOf), ["reply", "tools:1"]);
});

test("a refused message takes its pending line away and says why", async () => {
  const refuse = async () => {
    throw new Error("network down");
  };
  const { chat, log, send } = chatWith([[reply(1)]], refuse);
  await chat.refresh();
  await send("Please check the data.");
  await settle();
  assert.deepEqual([...log.children].map(kindOf), ["reply"]);
  const problem = elements(chat.element, "div").find((node) => hasClass(node, "form-status-error"));
  assert.equal(problem.hidden, false);
  assert.equal(elements(chat.element, "textarea")[0].value, "Please check the data.");
});

test("the hint under the message box is one sentence", () => {
  for (const table of [zh, en]) assert.equal(table["chat.hint"].split(/[。.](?:\s|$)/).filter(Boolean).length, 1, table["chat.hint"]);
  assert.equal(zh["chat.pending"], "已发送，编排 Agent 稍后接手。");
  assert.equal(en["chat.pending"], "Sent. The orchestrator will pick it up shortly.");
});

test("the captured conversation shows no tool name, input or result outside the details", () => {
  const ctx = testCtx({ lang: "zh" });
  const items = groupToolEntries(FIXTURES["conversation.json"].entries).filter((item) => item.kind === "toolGroup");
  assert.deepEqual(items.map((item) => item.items.length), [1, 3, 1, 1, 2, 1, 1, 1, 1, 1, 1]);
  for (const item of items) {
    const text = visibleText(toolGroupView(ctx, item.items));
    for (const entry of item.items) assert.ok(!text.includes(entry.text), entry.text);
    assert.ok(!text.includes("{"), text);
  }
});
