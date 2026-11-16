// The projects list and the project page: names instead of ids, the page's order and folds, the
// budget's numbers, and save notices that say what was saved.
import assert from "node:assert/strict";
import test from "node:test";

import { saveDraft } from "../../src/growbridge/web/workbench/drafts.js";
import en from "../../src/growbridge/web/workbench/i18n/en.js";
import zh from "../../src/growbridge/web/workbench/i18n/zh.js";
import { budgetView } from "../../src/growbridge/web/workbench/pages/project.js";
import { analysisSection } from "../../src/growbridge/web/workbench/pages/round-analysis.js";
import { bindFormContext, formControls } from "../../src/growbridge/web/workbench/ui/forms.js";
import { visibleText, visibleTextIncludingDetails } from "./support/leaks.mjs";
import { FIXTURES, renderPage, testCtx } from "./support/render-page.mjs";

const PROJECT = FIXTURES["project.json"];
const ROUND = PROJECT.rounds[0];
const PARAMS = { projectId: PROJECT.project_id };

function elements(node, name) {
  const own = node.localName === name ? [node] : [];
  return [...own, ...[...(node.children || [])].flatMap((child) => elements(child, name))];
}
const hasClass = (node, name) => (node.getAttribute("class") || "").split(/\s+/).includes(name);
const settle = () => new Promise((resolve) => setImmediate(resolve));
const sectionTitled = (root, title) => elements(root, "section").find((node) => elements(node, "h2")[0]?.textContent === title);
const formIn = (root, title) => elements(sectionTitled(root, title), "form")[0];

// A page rendered as main.js does, with the notices it gives kept.
async function withNotices(page, params, options = {}) {
  const notices = [];
  const ctx = { ...testCtx(options), notify: (message, tone) => notices.push({ message, tone }) };
  bindFormContext(ctx);
  const module = await import(`../../src/growbridge/web/workbench/pages/${page}.js`);
  const { element } = await module.render(ctx, params);
  return { element, ctx, notices };
}

async function submit(form, values = {}) {
  if (Object.keys(values).length) formControls(form).set(values);
  form.dispatchEvent(new Event("submit"));
  await settle();
  await settle();
}

// --- the projects list -------------------------------------------------------------------------

test("the projects list has no id column and names the latest round", async () => {
  const { element } = await renderPage("projects", {}, { lang: "zh" });
  const heads = elements(element, "th").map((th) => th.textContent);
  assert.deepEqual(heads, ["名称", "轮次数", "最近一轮", "创建时间"]);
  const links = elements(element, "a").map((a) => a.textContent);
  assert.deepEqual(links, ["Lettuce light series", "第 1 轮", "dev light stage", "第 1 轮"]);
  const all = visibleTextIncludingDetails(element);
  for (const project of FIXTURES["projects.json"].projects) {
    assert.ok(!visibleText(element).includes(project.project_id));
    assert.ok(all.includes(project.project_id) && all.includes(project.latest_round.round_id));
  }
});

test("a new project is announced by its name", async () => {
  const { element, notices } = await withNotices("projects", {}, { lang: "zh" });
  await submit(formIn(element, zh["projects.new"]), { name: "Basil trial" });
  assert.deepEqual(notices, [{ message: "已创建项目 Basil trial。", tone: "ok" }]);
});

// --- the project page ----------------------------------------------------------------------------

test("the project page puts the conversation and rounds first, then tasks, protocols, budget and holdouts", async () => {
  const { element } = await renderPage("project", PARAMS, { lang: "zh" });
  const titles = elements(element, "h2").map((h2) => h2.textContent);
  assert.deepEqual(titles, ["对话", "轮次", "目标与任务", "研究协议", "模型调用预算", "留出批次"]);
  const tasks = sectionTitled(element, "目标与任务");
  const region = elements(tasks, "div").find((node) => hasClass(node, "table-wrap"));
  assert.equal(region.getAttribute("aria-label"), "目标与任务");
});

test("the four editors are closed folds titled Edit…", async () => {
  const { element } = await renderPage("project", PARAMS, { lang: "zh" });
  for (const title of ["研究协议", "模型调用预算", "目标与任务", "留出批次"]) {
    const folds = elements(sectionTitled(element, title), "details").filter((node) => !hasClass(node, "tech-details"));
    const editor = folds.find((node) => elements(node, "form").length > 0);
    assert.ok(editor, title);
    assert.equal(editor.open, false, title);
    assert.equal(elements(editor, "summary")[0].textContent, "编辑…", title);
  }
  const rounds = sectionTitled(element, "轮次");
  assert.equal(elements(rounds, "details").filter((node) => elements(node, "form").length > 0).length, 0);
  const english = await renderPage("project", PARAMS, { lang: "en" });
  const summaries = elements(sectionTitled(english.element, en["project.budget.title"]), "summary").map((s) => s.textContent);
  assert.ok(summaries.includes("Edit…"), summaries.join(", "));
});

test("an editor that brings back an unsent draft opens by itself", async () => {
  saveDraft(`budget:${PROJECT.project_id}`, { max_calls: "5", max_cost: "1" });
  const { element } = await renderPage("project", PARAMS, { lang: "zh" });
  const fold = (title) => elements(sectionTitled(element, title), "details").find((node) => hasClass(node, "edit-fold"));
  assert.equal(fold("模型调用预算").open, true);
  assert.equal(formControls(formIn(element, "模型调用预算")).get("max_calls"), "5");
  assert.equal(fold("研究协议").open, false);
});

test("rounds are named and their protocol read as a version; the round id is in the row's details", async () => {
  const { element } = await renderPage("project", PARAMS, { lang: "zh" });
  const rounds = sectionTitled(element, "轮次");
  assert.deepEqual(elements(rounds, "a").map((a) => a.textContent), ["第 1 轮"]);
  const text = visibleText(rounds);
  assert.ok(text.includes("protocol-lettuce-light 第 1 版"), text);
  assert.ok(!text.includes(ROUND.round_id), text);
  assert.ok(visibleTextIncludingDetails(rounds).includes(ROUND.round_id));
  const options = elements(rounds, "option").map((option) => option.textContent);
  assert.deepEqual(options, ["protocol-lettuce-light 第 1 版"]);
});

test("a round waiting for a choice says a stage stopped, with the stage id in the row's details", async () => {
  const stageId = `stage-${ROUND.round_id}-1`;
  const waiting = { ...PROJECT, rounds: [{ ...ROUND, state: "running", awaiting_choice: stageId }] };
  const { element } = await renderPage("project", PARAMS, { lang: "zh", fixtures: { "project.json": waiting } });
  const rounds = sectionTitled(element, "轮次");
  const text = visibleText(rounds);
  assert.ok(text.includes("阶段已停止，等待选择"), text);
  assert.ok(!text.includes(stageId), text);
  const folds = elements(rounds, "details").filter((node) => hasClass(node, "tech-details"));
  assert.equal(folds.length, 1);
  assert.ok(visibleTextIncludingDetails(folds[0]).includes(stageId));
  const english = await renderPage("project", PARAMS, { lang: "en", fixtures: { "project.json": waiting } });
  assert.ok(visibleText(english.element).includes(en["project.rounds.awaiting"]));
});

test("a round from before rounds had numbers is called an unnamed round", async () => {
  const unnumbered = (round) => Object.fromEntries(Object.entries(round).filter(([key]) => key !== "round_number"));
  const projects = { projects: FIXTURES["projects.json"].projects.map((row) => ({ ...row, latest_round: unnumbered(row.latest_round) })) };
  const list = await renderPage("projects", {}, { lang: "zh", fixtures: { "projects.json": projects } });
  assert.deepEqual(elements(list.element, "a").map((a) => a.textContent).filter((text) => text.includes("轮")), ["未命名轮次", "未命名轮次"]);
  const old = { ...PROJECT, rounds: [unnumbered(ROUND)] };
  const { element } = await renderPage("project", PARAMS, { lang: "en", fixtures: { "project.json": old } });
  assert.deepEqual(elements(sectionTitled(element, en["project.rounds.title"]), "a").map((a) => a.textContent), [en["name.round.unnamed"]]);
});

test("the task table names the owner role", async () => {
  const { element } = await renderPage("project", PARAMS, { lang: "zh" });
  const tasks = elements(sectionTitled(element, "目标与任务"), "table")[0];
  const owners = elements(tasks, "tr").slice(1).map((tr) => elements(tr, "td")[1].textContent);
  assert.deepEqual(owners, PROJECT.tasks.map((task) => zh[`chat.role.${task.owner_role}`] ?? "missing"));
});

test("budget numbers carry no float noise", () => {
  const ctx = testCtx({ lang: "zh" });
  const view = budgetView(ctx, { budget: { calls_left: 1234, cost_left: 1.8300000000000001 } });
  const text = visibleText(view);
  assert.ok(text.includes("1.83") && !text.includes("1.8300000000000001"), text);
  assert.ok(text.includes("1,234"), text);
  assert.ok(text.includes(zh["project.budget.help"]), text);
  const english = visibleText(budgetView(testCtx({ lang: "en" }), { budget: { calls_left: 37, cost_left: 97.06714 } }));
  assert.ok(english.includes("37") && english.includes("97.07") && !english.includes("97.06714"), english);
  assert.equal(visibleText(budgetView(ctx, {})), zh["project.budget.none"]);
});

test("holdouts keep their id in the details and say how often they were read", async () => {
  const holdout = {
    holdout_id: "holdout_5c987768a8b544ad80c4af4c0af9a962",
    project_id: PROJECT.project_id,
    batch_ids: ["batch-3"],
    development_batch_ids: ["batch-1", "batch-2"],
    outcome_fields: ["canopy area"],
    registered_at: 1796594700,
    registered_by: "dev",
    reads: [
      { reader: "dev", at: 1796594710, label: "confirmatory", model_sha: "" },
      { reader: "dev", at: 1796594720, label: "exploratory", model_sha: "" },
    ],
  };
  const fixtures = { "holdouts.json": { holdouts: [holdout] } };
  const { element } = await renderPage("project", PARAMS, { lang: "zh", fixtures });
  const block = sectionTitled(element, "留出批次");
  const text = visibleText(block);
  assert.ok(text.includes("已读取 2 次"), text);
  assert.ok(text.includes(zh["project.holdouts.readsHelp"]), text);
  assert.ok(zh["project.holdouts.readsHelp"].includes("只有第一次读取（不论哪个模型）算确认性，之后都算探索性。"));
  assert.match(en["project.holdouts.readsHelp"], /only the first read, by any model, is confirmatory/i);
  assert.ok(!text.includes(holdout.holdout_id), text);
  assert.ok(visibleTextIncludingDetails(block).includes(holdout.holdout_id));
  assert.ok(!elements(block, "th").some((th) => th.textContent === zh["col.id"]));
});

// --- save notices that say what was saved (P-08) -------------------------------------------------

test("saving the budget, a goal or a holdout says what was saved", async () => {
  const { element, notices } = await withNotices("project", PARAMS, { lang: "zh" });
  await submit(formIn(element, "模型调用预算"), { max_calls: 50, max_cost: 20 });
  await submit(formIn(element, "目标与任务"));
  await submit(formIn(element, "留出批次"));
  assert.deepEqual(
    notices.map((notice) => notice.message),
    ["已设置预算：50 次调用，费用上限 20.00", "已提交目标", "已登记留出批次"],
  );
  const english = await withNotices("project", PARAMS, { lang: "en" });
  await submit(formIn(english.element, en["project.budget.title"]), { max_calls: 1500, max_cost: 2.5 });
  assert.equal(english.notices[0].message, "Budget set: 1,500 calls, cost limit 2.50");
});

test("starting a round does not name it by id", async () => {
  const { element, notices } = await withNotices("project", PARAMS, { lang: "zh" });
  await submit(formIn(element, "轮次"));
  assert.equal(notices.length, 1);
  assert.ok(!/round_|undefined/.test(notices[0].message), notices[0].message);
  assert.equal(notices[0].message, zh["project.roundStarted"]);
});

test("compute, round and analysis writes say what was done", async () => {
  const compute = await withNotices("compute", {}, { lang: "zh" });
  const forms = elements(compute.element, "form");
  const withButton = (label) => forms.find((form) => elements(form, "button").some((b) => b.textContent === label));
  await submit(withButton(zh["compute.balance.record"]), { cpu_hours: 120 });
  await submit(withButton(zh["compute.budget.set"]), { task_id: "task-1", cpu_hours: 10, storage_gb: 5 });
  assert.deepEqual(compute.notices.map((n) => n.message), ["已记录计算余额", "已设置任务预算"]);

  const stage = FIXTURES["round.json"].stages[0];
  const waiting = { ...FIXTURES["round.json"], state: "running", awaiting_choice: stage.stage_id };
  const round = await withNotices("round", { roundId: waiting.round_id }, { lang: "zh", fixtures: { "round.json": waiting } });
  await submit(formIn(round.element, zh["round.choiceTitle"]), { choice: "redo" });
  assert.deepEqual(round.notices.map((n) => n.message), [`已选择：${zh["round.choice.redo"]}`]);

  const notices = [];
  const ctx = { ...testCtx({ lang: "zh" }), notify: (message) => notices.push(message) };
  bindFormContext(ctx);
  const [freeze, run] = elements(await analysisSection(ctx, FIXTURES["round.json"]), "form");
  await submit(freeze);
  await submit(run);
  assert.deepEqual(notices, ["已锁定分析脚本", "已运行确认性分析"]);
});

test("every new save notice exists in both languages", () => {
  const keys = ["project.budget.saved", "project.goals.saved", "project.holdouts.saved", "compute.balance.saved", "compute.budget.saved", "analysis.frozen", "analysis.ran", "round.chosen", "round.aborted"];
  for (const key of keys) assert.ok(zh[key] && en[key], key);
  assert.equal(zh["analysis.frozen"], "已锁定分析脚本");
  assert.equal(zh["analysis.ran"], "已运行确认性分析");
  assert.equal(zh["round.aborted"], "已中止本轮");
});
