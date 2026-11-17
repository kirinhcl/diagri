import assert from "node:assert/strict";
import test, { afterEach } from "node:test";

import { actionsView, activityLog, differenceLines, logItem, manualGroup, manualHeading, outcomeLines, plainActionLines } from "../../src/growbridge/web/workbench/pages/stage-actions.js";
import { statusView } from "../../src/growbridge/web/workbench/pages/stage.js";
import { installFakeDom, FIXTURES, testCtx } from "./support/render-page.mjs";
import { answerNextDialog, assertNoPendingDialogAnswers, openDialogs, resetDialogs } from "./support/dialogs.mjs";
import { assertNoLeaks, visibleText, visibleTextIncludingDetails } from "./support/leaks.mjs";

installFakeDom();

afterEach(() => {
  assertNoPendingDialogAnswers();
  resetDialogs();
});

const stage = { ...FIXTURES["stage.json"], paused_at: null, end_pending: false, right_number: 4, care_right: 2, manual_right: 1 };

test("status hides empty rows and keeps write rights in the details", () => {
  const ctx = testCtx({ lang: "zh" });
  const view = statusView(ctx, stage);
  const text = visibleText(view);
  assert.doesNotMatch(text, /暂停时间|写入权|结束条件/);
  assert.match(text, /Lettuce light series/);
  assert.match(text, /第 1 轮/);
  assert.doesNotMatch(text, new RegExp(stage.experiment_id));
  assertNoLeaks(view);
  const all = visibleTextIncludingDetails(view);
  assert.ok(!all.includes(stage.experiment_id), "ids stay in the page header fold");
  assert.ok(all.includes("阶段写入权"));
});

test("a pending end shows a banner and a pause time shows its row", () => {
  const ctx = testCtx({ lang: "zh" });
  const text = visibleText(statusView(ctx, { ...stage, end_pending: true, paused_at: 1000 }));
  assert.match(text, /已到结束条件，正在确认结束动作。/);
  assert.match(text, /暂停时间/);
});

const settle = () => new Promise((resolve) => setImmediate(resolve));

function elements(node, name) {
  const own = node.tagName && node.tagName.toLowerCase() === name ? [node] : [];
  return [...own, ...[...(node.children || [])].flatMap((child) => elements(child, name))];
}

test("a level is written against its full scale", () => {
  const ctx = testCtx({ lang: "zh" });
  assert.equal(manualHeading(ctx, "fan", 3), "风扇调到 3 / 10");
  assert.equal(manualHeading(ctx, "light", 50), "灯光调到 50 %");
});

test("the manual form sends the level and the log heading carries the scale", async () => {
  const ctx = testCtx({ lang: "zh" });
  const sent = [];
  ctx.api = { post: async (path, body) => (sent.push([path, body]), { request_id: "wb-1", created_at: 1000, state: "pending" }) };
  const tracked = [];
  const env = { ctx, stage, log: { track: (heading, record) => tracked.push([heading, record]) }, onChanged: async () => {} };
  const form = [...manualGroup(env).children].find((child) => child.tagName && child.tagName.toLowerCase() === "form");
  elements(form, "select")[0].value = "fan";
  const level = elements(form, "input").find((input) => input.getAttribute("name") === "level");
  level.value = "3";
  answerNextDialog(true);
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  await settle();
  assert.equal(sent[0][0], "/manual/fan");
  assert.equal(tracked[0][0], "风扇调到 3 / 10");
});

test("receipt outcomes write levels, durations and no request id", () => {
  const ctx = testCtx({ lang: "zh" });
  const applied = (level) => ({ outcome: "applied", record: { confirmed_level: level } });
  assert.match(outcomeLines(ctx, applied(3), "fan").join(" "), /3 \/ 10/);
  assert.match(outcomeLines(ctx, applied(1), "pump").join(" "), /开/);
  const unsettled = outcomeLines(ctx, { outcome: "timeout", record: { request_id: "wb-9" } }, "fan").join(" ");
  assert.match(unsettled, /\d+ 秒|\d+ 分钟/);
  assert.doesNotMatch(unsettled, /wb-|请求编号/);
});

test("the irrigation heading shows a formatted duration", async () => {
  const ctx = testCtx({ lang: "zh" });
  ctx.me = { ...ctx.me, entry: "lan" };
  ctx.api = { post: async () => ({ request_id: "wb-2", created_at: 1000, state: "pending" }) };
  const tracked = [];
  const env = { ctx, stage, log: { track: (heading) => tracked.push(heading) }, onChanged: async () => {}, capabilities: { max_pump_seconds: 120 } };
  const view = actionsView({ ...env, stage: { ...stage, state: "manual" } });
  const form = elements(view, "form").find((f) => elements(f, "input").some((i) => i.getAttribute("name") === "seconds"));
  elements(form, "input").find((i) => i.getAttribute("name") === "seconds").value = "90";
  answerNextDialog(true);
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  await settle();
  assert.match(tracked[0], /浇水 1 分钟 30 秒|浇水 2 分钟|浇水 90 秒/);
});

test("a resent write is said so in a line under the heading, not in it", async () => {
  const ctx = testCtx({ lang: "zh" });
  let n = 0;
  ctx.api = { post: async () => { if (++n === 1) throw Object.assign(new Error("network"), { status: 0 }); return { request_id: "wb-3", created_at: 1000, state: "pending" }; } };
  const calls = [];
  const env = { ctx, stage, log: { track: (heading, record, opts) => calls.push([heading, opts]) }, onChanged: async () => {} };
  const form = [...manualGroup(env).children].find((child) => child.tagName && child.tagName.toLowerCase() === "form");
  elements(form, "select")[0].value = "light";
  elements(form, "input").find((i) => i.getAttribute("name") === "level").value = "50";
  for (let i = 0; i < 2; i += 1) {
    answerNextDialog(true);
    form.dispatchEvent(new Event("submit", { cancelable: true }));
    await settle();
  }
  assert.equal(calls[0][0], "灯光调到 50 %");
  assert.equal(calls.at(-1)[0], "灯光调到 50 %");
  assert.equal(calls[0][1].lost, true);
  assert.equal(calls.at(-1)[1].resent, true);
});

test("a log item says when it was sent and keeps the request id in the details", () => {
  const ctx = testCtx({ lang: "zh" });
  const item = logItem(ctx, "灯光调到 50 %", { request_id: "wb-abc123", created_at: 1000 });
  assert.doesNotMatch(visibleText(item.element), /wb-/);
  assert.match(visibleText(item.element), /发送于/);
  assert.ok(visibleTextIncludingDetails(item.element).includes("wb-abc123"));
});

test("hand-back differences use labels and units", () => {
  const ctx = testCtx({ lang: "zh" });
  const lines = differenceLines(ctx, [{ channel: "light", field: "level", expected: 50, actual: 0 }]);
  assert.ok(lines.includes("灯光档位：应为 50 %，实际 0 %"));
});

// --- final review: the stop and take-over dialogs name the stage, not its id (F2) --------------
test("the stop and take-over dialogs name the stage and never its id", () => {
  const named = { ...stage, stage_id: "stage-round_9d38ffa4ca3049948194e0b60315c650-1", stage_index: 1, phase: "vegetative" };
  for (const lang of ["zh", "en"]) {
    const ctx = testCtx({ lang });
    for (const name of ["stop", "takeover"]) {
      const lines = plainActionLines(ctx, name, named).join(" ");
      assert.ok(!lines.includes(named.stage_id), `${lang} ${name}: ${lines}`);
      assert.match(lines, lang === "zh" ? /第 1 阶段/ : /Stage 1/);
    }
  }
  const zh = testCtx({ lang: "zh" });
  assert.deepEqual(plainActionLines(zh, "stop", { stage_id: "stage-x-1" }), ["未命名阶段 将永久停止，不能再次启动。"]);
});

// --- final review: the approval gate's mismatch path (F7) --------------------------------------
test("an approval of another run sheet than the one reviewed keeps both digests folded and sends the reviewed one", async () => {
  const ctx = testCtx({ lang: "zh" });
  const reviewed = "a1".repeat(32);
  const approved = "b2".repeat(32);
  const pending = FIXTURES["stage-pending.json"];
  const posts = [];
  const notices = [];
  ctx.api = {
    get: async () => ({ run_sheet_digest: reviewed }),
    post: async (path, body) => (posts.push([path, body]), { run_sheet_version: 3, run_sheet_digest: approved, approved_at: 1796594700 }),
  };
  ctx.notify = (message, tone) => notices.push([message, tone]);
  const log = activityLog(ctx, { signal: new AbortController().signal, alive: () => true });
  const view = actionsView({ ctx, stage: pending, review: { run_sheet_digest: reviewed, blocking: false }, log, onChanged: async () => {} });
  const approveGroup = elements(view, "div").find((node) => node.getAttribute("data-action") === "approve");
  elements(approveGroup, "button")[0].dispatchEvent(new Event("click"));
  await settle();
  await settle();
  assert.deepEqual(posts, [[`/stages/${encodeURIComponent(pending.stage_id)}/approve`, { expected_digest: reviewed }]]);
  const shown = [visibleText(log.element), visibleText(approveGroup), ...notices.map(([message]) => message)].join(" ");
  assert.match(shown, /已审批，但不是你审阅的那份运行单/);
  for (const digest of [reviewed, approved]) assert.ok(!shown.includes(digest), `digest ${digest.slice(0, 4)} in view`);
  assert.deepEqual(notices.map(([, tone]) => tone), ["error"]);
  const [mismatch, approval] = elements(log.element, "li");
  const folded = visibleTextIncludingDetails(mismatch);
  assert.ok(folded.includes(`服务器批准的指纹 ${approved}`) && folded.includes(`你审阅的指纹 ${reviewed}`), folded);
  assert.ok(visibleTextIncludingDetails(approval).includes(approved));
  assert.match(visibleText(approval), /指纹 b2b2b2b2…/);
});

test("the title pill keeps an open unknown-state fold open across polls", async () => {
  const { renderPage } = await import("./support/render-page.mjs");
  const foldsIn = (node) => [...(node.localName === "details" ? [node] : []), ...[...(node.children || [])].flatMap(foldsIn)];
  const stageId = FIXTURES["stage.json"].stage_id;
  const { element, ctx, refresh } = await renderPage("stage", { stageId }, { fixtures: { "stage.json": { ...FIXTURES["stage.json"], state: "mystery" } } });
  const holder = (node) => {
    const pill = (n) => (n.getAttribute?.("class") || "") === "stage-pill" ? [n] : [...(n.children || [])].flatMap(pill);
    return pill(node)[0];
  };
  const slot = holder(element);
  const [fold] = foldsIn(slot);
  assert.ok(fold, "an unknown state has a fold");
  fold.setAttribute("open", "");
  await refresh();
  assert.equal(foldsIn(holder(element))[0], fold);
  assert.ok(fold.hasAttribute("open"));
  const get = ctx.api.get;
  ctx.api.get = async (path, ...rest) => {
    const answer = await get(path, ...rest);
    return /\/stages\/[^/]+$/.test(path.split("?")[0]) ? { ...answer, state: "enigma" } : answer;
  };
  await refresh();
  assert.notEqual(foldsIn(holder(element))[0], fold);
});

function installHolder(lines) {
  const holder = document.createElement("div");
  for (const line of lines.filter(Boolean)) {
    if (typeof line === "string") {
      const p = document.createElement("p");
      p.textContent = line;
      holder.append(p);
    } else holder.append(...(Array.isArray(line) ? line : [line]));
  }
  return holder;
}
const foldCount = (node) => elements(node, "details").length;

test("a failed receipt says what happened and what to do, without the server's words", () => {
  const ctx = testCtx({ lang: "zh" });
  const record = { request_id: "wb-9", error_code: "not_sent", error_params: {}, error: "ConnectionRefusedError: [Errno 61]" };
  const lines = outcomeLines(ctx, { outcome: "failed", record }, "fan");
  const holder = installHolder(lines);
  const text = visibleText(holder);
  assert.match(text, /指令没有发出去，设备没有变化。/);
  assert.match(text, /检查连接后重试。/);
  assert.doesNotMatch(text, /ConnectionRefused|原因：|wb-9/);
  const all = visibleTextIncludingDetails(holder);
  assert.match(all, /ConnectionRefusedError/);
  assert.match(all, /wb-9/);
  assert.equal(foldCount(holder), 1);
});

test("an old receipt without a code keeps its reason in the details", () => {
  const ctx = testCtx({ lang: "zh" });
  const record = { request_id: "wb-9", error: "relay timed out" };
  const holder = installHolder(outcomeLines(ctx, { outcome: "failed", record }, "fan"));
  assert.match(visibleText(holder), /没有执行，原因见技术详情。/);
  assert.doesNotMatch(visibleText(holder), /relay timed out/);
  assert.match(visibleTextIncludingDetails(holder), /relay timed out/);
  assert.equal(foldCount(holder), 1);
  const en = installHolder(outcomeLines(testCtx({ lang: "en" }), { outcome: "failed", record }, "fan"));
  assert.match(visibleText(en), /Not carried out; the reason is in the technical details\./);
});

test("an unknown receipt code is shown as unknown, never as the code", () => {
  const ctx = testCtx({ lang: "zh" });
  const record = { request_id: "wb-9", error_code: "brand_new_code", error_params: {} };
  const holder = installHolder(outcomeLines(ctx, { outcome: "failed", record }, "fan"));
  assert.match(visibleText(holder), /未知（技术详情）/);
  assert.doesNotMatch(visibleText(holder), /brand_new_code/);
});

test("a failed receipt in the activity log has one fold", () => {
  const ctx = testCtx({ lang: "zh" });
  const record = { request_id: "wb-9", created_at: 1000, error_code: "not_sent", error_params: {} };
  const item = logItem(ctx, "风扇调到 3 / 10", record);
  item.show("failed", outcomeLines(ctx, { outcome: "failed", record }, "fan"));
  assert.equal(foldCount(item.element), 1);
  assert.match(visibleTextIncludingDetails(item.element), /wb-9/);
});

test("an unknown receipt with a code says what happened and what to do, in an item with one fold", () => {
  const ctx = testCtx({ lang: "zh" });
  const record = { request_id: "wb-9", created_at: 1000, error_code: "no_receipt", error_params: {}, error: "no receipt: timed out" };
  const item = logItem(ctx, "风扇调到 3 / 10", record);
  item.show("unknown", outcomeLines(ctx, { outcome: "unknown", record }, "fan"));
  const text = visibleText(item.element);
  assert.match(text, /没有收到设备的回执，结果不明。/);
  assert.match(text, /到现场核对设备，并记一次现场检查。/);
  assert.ok(!text.includes(ctx.t("receipt.unknownNote")));
  assert.doesNotMatch(text, /no receipt: timed out|wb-9/);
  const all = visibleTextIncludingDetails(item.element);
  assert.match(all, /no receipt: timed out/);
  assert.match(all, /wb-9/);
  assert.equal(foldCount(item.element), 1);
  assertNoLeaks(item.element);
});

test("an unknown receipt without a code keeps the general note and its request id fold", () => {
  const ctx = testCtx({ lang: "zh" });
  const record = { request_id: "wb-9", created_at: 1000, error: "no receipt: timed out" };
  const item = logItem(ctx, "风扇调到 3 / 10", record);
  item.show("unknown", outcomeLines(ctx, { outcome: "unknown", record }, "fan"));
  assert.ok(visibleText(item.element).includes(ctx.t("receipt.unknownNote")));
  assert.equal(foldCount(item.element), 1);
  assert.match(visibleTextIncludingDetails(item.element), /wb-9/);
});

// --- task 8: start, manual levels and irrigation ------------------------------------------------
const findAction = (view, name) => elements(view, "div").find((node) => node.getAttribute("data-action") === name);
const byName = (node, name) => elements(node, "input").find((i) => i.getAttribute("name") === name);
const buttonsOf = (node) => elements(node, "button");
const CAPS = FIXTURES["capabilities.json"];

function startView(lang, approval) {
  const ctx = testCtx({ lang });
  ctx.me = { ...ctx.me, entry: "lan" };
  const sent = [];
  ctx.api = { post: async (path, body) => (sent.push([path, body]), {}) };
  const pending = FIXTURES["stage-pending.json"];
  const review = { run_sheet_digest: "a1".repeat(32), blocking: false, approval };
  const view = actionsView({ ctx, stage: pending, review, log: { track() {} }, onChanged: async () => {} });
  return { view, sent, group: findAction(view, "start"), pending };
}

test("start is disabled with the reason while the run sheet is not approved", () => {
  const reasons = { zh: "运行单还没有批准，先在上面批准运行单。", en: "The run sheet is not approved yet; approve it above first." };
  for (const lang of ["zh", "en"]) {
    const { group } = startView(lang, null);
    const [button] = buttonsOf(group);
    assert.ok(button.hasAttribute("disabled"), `${lang}: disabled`);
    const why = elements(group, "p").find((p) => p.getAttribute("id") === button.getAttribute("aria-describedby"));
    assert.ok(why, `${lang}: described by the reason`);
    assert.equal(visibleText(why), reasons[lang]);
  }
});

test("start asks first once the run sheet is approved", async () => {
  const approval = { approved_at: 1796594700, run_sheet_version: 3 };
  const { group, sent, pending } = startView("zh", approval);
  const [button] = buttonsOf(group);
  assert.ok(!button.hasAttribute("disabled"));
  button.dispatchEvent(new Event("click"));
  await settle();
  const [dialog] = openDialogs();
  assert.match(visibleText(dialog), /启动这个阶段？/);
  assert.match(visibleText(dialog), /设备会立即按已批准的运行单运行/);
  answerNextDialog(false);
  await settle();
  assert.deepEqual(sent, []);
  button.dispatchEvent(new Event("click"));
  await settle();
  answerNextDialog(true);
  await settle();
  assert.deepEqual(sent, [[`/stages/${encodeURIComponent(pending.stage_id)}/start`, {}]]);
});

function manualEnv(lang = "zh", capabilities = CAPS) {
  const ctx = testCtx({ lang });
  const sent = [];
  ctx.api = { post: async (path, body) => (sent.push([path, body]), { request_id: "wb-1", created_at: 1000, state: "pending" }) };
  const tracked = [];
  return { env: { ctx, stage, log: { track: (heading) => tracked.push(heading) }, onChanged: async () => {}, capabilities }, sent, tracked };
}

test("the level field's range follows the chosen channel", async () => {
  const { env, sent } = manualEnv();
  const group = manualGroup(env);
  const form = elements(group, "form")[0];
  const select = elements(form, "select")[0];
  const level = byName(form, "level");
  assert.deepEqual([...select.children].map((o) => o.getAttribute("value")), ["", "light", "exhaust", "fan"]);
  assert.equal(level.getAttribute("max"), null, "no channel chosen, no range");
  select.value = "light";
  select.dispatchEvent(new Event("change"));
  assert.equal(level.getAttribute("max"), "100");
  assert.match(visibleText(group), /灯光取 0 到 100。/);
  select.value = "fan";
  select.dispatchEvent(new Event("change"));
  assert.equal(level.getAttribute("min"), "0");
  assert.equal(level.getAttribute("max"), "10");
  const hint = visibleText(group);
  assert.match(hint, /风扇取 0 到 10。/);
  assert.doesNotMatch(hint, /0 到 100/);
  const hintNode = elements(group, "p").find((p) => visibleText(p) === "风扇取 0 到 10。");
  assert.ok(level.getAttribute("aria-describedby").split(" ").includes(hintNode.getAttribute("id")));
  level.value = "11";
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  await settle();
  assert.deepEqual(sent, []);
  assert.match(visibleText(form), /请输入不大于 10 的数/);
  level.value = "2.5";
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  await settle();
  assert.deepEqual(sent, []);
  assert.match(visibleText(form), /请输入整数/);
  const open = manualEnv("zh", null);
  const bare = manualGroup(open.env);
  chooseFan(bare);
  assert.equal(byName(bare, "level").getAttribute("max"), null);
  assert.ok(!elements(bare, "p").some((p) => /取 \d/.test(visibleText(p))));
});

function chooseFan(group) {
  const select = elements(group, "select")[0];
  select.value = "fan";
  select.dispatchEvent(new Event("change"));
}

test("the manual form asks first, and a channel must be chosen", async () => {
  const { env, sent } = manualEnv();
  const notices = [];
  env.ctx.notify = (message) => notices.push(message);
  const form = elements(manualGroup(env), "form")[0];
  const level = byName(form, "level");
  level.value = "3";
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  await settle();
  assert.deepEqual(sent, [], "no channel, nothing sent");
  assert.equal(openDialogs().length, 0);
  elements(form, "select")[0].value = "fan";
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  await settle();
  const text = visibleText(openDialogs()[0]);
  assert.match(text, /把风扇调到 3 \/ 10？/);
  assert.match(text, /设备会立即切换到这个档位/);
  answerNextDialog(false);
  await settle();
  assert.deepEqual(sent, []);
  assert.deepEqual(notices, []);
  assert.doesNotMatch(visibleText(form), /已完成|失败|错误/);
});

test("the pump is switched off by its own button, after a confirmation", async () => {
  const { env, sent, tracked } = manualEnv();
  const notices = [];
  let changed = 0;
  env.ctx.notify = (message) => notices.push(message);
  env.onChanged = async () => { changed += 1; };
  const group = manualGroup(env);
  const button = buttonsOf(group).find((b) => visibleText(b) === "关闭水泵");
  assert.ok(button, "a switch-off button");
  button.dispatchEvent(new Event("click"));
  await settle();
  assert.match(visibleText(openDialogs()[0]), /关闭水泵/);
  answerNextDialog(false);
  await settle();
  assert.deepEqual(sent, []);
  assert.equal(notices.length, 0);
  button.dispatchEvent(new Event("click"));
  await settle();
  answerNextDialog(true);
  await settle();
  await settle();
  assert.equal(sent.length, 1);
  assert.equal(sent[0][0], "/manual/pump");
  const { request_id: requestId, ...rest } = sent[0][1];
  assert.match(requestId, /^wb-/);
  assert.deepEqual(rest, { stage_id: stage.stage_id, level: 0, note: "" });
  assert.equal(tracked.length, 1);
  assert.equal(notices.length, 0, "no generic done notice");
  assert.equal(changed, 1, "one refresh");
});

test("irrigation seconds are capped at the configured pump limit and asked first, like a task row", async () => {
  const { env, sent } = manualEnv("zh", { ...CAPS, max_pump_seconds: 5 });
  env.ctx.me = { ...env.ctx.me, entry: "lan" };
  const view = actionsView({ ...env, stage: { ...stage, state: "manual" } });
  const form = elements(findAction(view, "irrigation"), "form")[0];
  const seconds = byName(form, "seconds");
  assert.equal(seconds.getAttribute("max"), "5");
  const submit = async (value) => {
    seconds.value = value;
    form.dispatchEvent(new Event("submit", { cancelable: true }));
    await settle();
  };
  await submit("6");
  await submit("0");
  assert.deepEqual(sent, [], "out of range sends nothing and asks nothing");
  assert.equal(openDialogs().length, 0);
  await submit("3");
  const text = visibleText(openDialogs()[0]);
  assert.match(text, /3 秒/);
  assert.match(text, /只能在现场入口操作/);
  answerNextDialog(false);
  await settle();
  assert.deepEqual(sent, []);
  assert.doesNotMatch(visibleText(form), /已完成|失败|错误/);
  await submit("3");
  answerNextDialog(true);
  await settle();
  assert.deepEqual(sent.map(([path, body]) => [path, body.seconds]), [["/irrigation", 3]]);
  const open = manualEnv("zh", null);
  open.env.ctx.me = { ...open.env.ctx.me, entry: "lan" };
  const bare = actionsView({ ...open.env, stage: { ...stage, state: "manual" } });
  assert.equal(byName(findAction(bare, "irrigation"), "seconds").getAttribute("max"), "60");
  assert.doesNotMatch(visibleText(findAction(bare, "irrigation")), /最多/);
});

test("start with a review that could not be read stays enabled and asks first", async () => {
  const ctx = testCtx({ lang: "zh" });
  ctx.me = { ...ctx.me, entry: "lan" };
  const sent = [];
  ctx.api = { post: async (path, body) => (sent.push([path, body]), {}) };
  const view = actionsView({ ctx, stage: FIXTURES["stage-pending.json"], review: null, log: { track() {} }, onChanged: async () => {} });
  const [button] = buttonsOf(findAction(view, "start"));
  assert.ok(!button.hasAttribute("disabled"));
  button.dispatchEvent(new Event("click"));
  await settle();
  assert.match(visibleText(openDialogs()[0]), /启动这个阶段？/);
  answerNextDialog(false);
  await settle();
  assert.deepEqual(sent, []);
});
