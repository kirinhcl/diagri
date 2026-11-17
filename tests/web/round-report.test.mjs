import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { ApiError } from "../../src/growbridge/web/workbench/api.js";
import en from "../../src/growbridge/web/workbench/i18n/en.js";
import zh from "../../src/growbridge/web/workbench/i18n/zh.js";
import MESSAGES_EN from "../../src/growbridge/web/workbench/i18n/messages.en.js";
import MESSAGES_ZH from "../../src/growbridge/web/workbench/i18n/messages.zh.js";
import { makeT } from "../../src/growbridge/web/workbench/i18n.js";
import { analysisSection, analysisState, runView } from "../../src/growbridge/web/workbench/pages/round-analysis.js";
import { abortLines, estimateText, render, reportLists, reportView } from "../../src/growbridge/web/workbench/pages/round.js";
import { bindFormContext, formControls } from "../../src/growbridge/web/workbench/ui/forms.js";
import { displayName } from "../../src/growbridge/web/workbench/ui/names.js";
import { answerNextDialog, assertNoPendingDialogAnswers, openDialogs, resetDialogs } from "./support/dialogs.mjs";
import { visibleText, visibleTextIncludingDetails } from "./support/leaks.mjs";
import { FIXTURES, renderPage, testCtx } from "./support/render-page.mjs";

afterEach(() => {
  assertNoPendingDialogAnswers();
  resetDialogs();
});

const ctx = { t: makeT("en") };
const ROUND = FIXTURES["round.json"];
const REPORT = FIXTURES["report.json"];
const ANALYSIS = FIXTURES["analysis.json"];

function elements(node, name) {
  const own = node.localName === name ? [node] : [];
  return [...own, ...[...(node.children || [])].flatMap((child) => elements(child, name))];
}
const hasClass = (node, name) => (node.getAttribute("class") || "").split(/\s+/).includes(name);
const techFolds = (node) => elements(node, "details").filter((details) => hasClass(details, "tech-details"));
const plainFolds = (node) => elements(node, "details").filter((details) => !hasClass(details, "tech-details"));
const count = (text, part) => text.split(part).length - 1;
// Every pending promise job, then one turn of the event loop.
const settle = () => new Promise((resolve) => setImmediate(resolve));
const summaryOf = (root) => elements(root, "summary")[0].textContent;
// The <section> of a page whose heading reads `title`.
const sectionTitled = (root, title) => elements(root, "section").find((node) => elements(node, "h2")[0]?.textContent === title);

test("an estimate reads as effect, p value and blocks, or says why there is none", () => {
  assert.equal(estimateText(ctx, { estimable: true, effect: 0.42, p_value: 0.0312, blocks: 2 }), "Effect 0.420, p = 0.031, over 2 complete blocks");
  const coded = { estimable: false, note: "fewer than 2 complete blocks; no treatment effect can be estimated", note_code: "too_few_blocks", note_params: { blocks: 0, min_blocks: 2 } };
  assert.equal(estimateText(ctx, coded), "Fewer than 2 complete blocks (0 so far), so no treatment effect can be estimated.");
  assert.equal(estimateText(ctx, { estimable: false }), en["report.notEstimable"]);
  assert.equal(estimateText(ctx, null), "—");
});

test("estimateText rounds the effect", () => {
  const estimate = { estimable: true, effect: 0.231234, p_value: 0.034, blocks: 2 };
  assert.match(estimateText(testCtx({ lang: "en" }), estimate), /0\.231\b/);
  assert.doesNotMatch(estimateText(testCtx({ lang: "en" }), estimate), /0\.2312/);
});

test("every label and conclusion the server writes has a text", () => {
  for (const label of ["confirmatory", "exploratory", "descriptive"]) assert.ok(en[`report.labels.${label}`], label);
  for (const c of ["supported", "not_supported", "uncertain"]) assert.ok(en[`report.conclusions.${c}`], c);
});

test("server notes follow the console language; old reports keep their plain text", () => {
  const report = {
    reasons: ["缺少独立的处理重复"],
    limitations: ["one cultivar", "第 1 轮…", "缺少独立的处理重复"],
    model_limitations: ["one cultivar"],
    notes: [
      { code: "no_replicates", kind: "reason", params: {}, text: { en: "No independent replicate", zh: "缺少独立的处理重复" } },
      { code: "treatment_unverified", kind: "limitation", params: { round: 1 }, text: { en: "Round 1 …", zh: "第 1 轮…" } },
    ],
  };
  assert.deepEqual(reportLists(report, "en"), { reasons: ["No independent replicate"], limitations: ["Round 1 …", "one cultivar"] });
  assert.deepEqual(reportLists(report, "zh"), { reasons: ["缺少独立的处理重复"], limitations: ["第 1 轮…", "one cultivar"] });
  const old = { reasons: ["a"], limitations: ["b"] };
  assert.deepEqual(reportLists(old, "en"), { reasons: ["a"], limitations: ["b"] });
});

// --- the report ----------------------------------------------------------------------------------

test("a missing label or conclusion says 'not stated'", () => {
  const view = reportView(testCtx(), { label: undefined, report: {} });
  const text = visibleText(view);
  assert.equal(count(text, "未说明"), 2);
  assert.ok(!text.includes("report.labels"), text);
  assert.ok(!text.includes(zh["report.conclusions.uncertain"]), "a missing conclusion is not quietly 'uncertain'");
  assert.equal(count(visibleText(reportView(testCtx({ lang: "en" }), { report: {} })), "Not stated"), 2);
});

test("a label or conclusion the catalog lacks is 'unknown', its code in the details", () => {
  const view = reportView(testCtx(), { label: "novel", report: { conclusion: "maybe_later" } });
  const text = visibleText(view);
  assert.equal(count(text, zh["common.unknown"]), 2);
  assert.ok(!text.includes("novel") && !text.includes("maybe_later"), text);
  const details = visibleTextIncludingDetails(view);
  assert.ok(details.includes("novel") && details.includes("maybe_later"), details);
});

test("each label says under it what it allows", () => {
  assert.equal(zh["report.labelHelp.descriptive"], "只描述看到的情况，不能据此对处理下结论。");
  for (const label of ["confirmatory", "exploratory", "descriptive"]) {
    for (const lang of ["zh", "en"]) {
      const c = testCtx({ lang });
      const text = visibleText(reportView(c, { label, report: { label } }));
      assert.ok(text.includes(c.t(`report.labelHelp.${label}`)), `${lang} ${label}`);
    }
  }
  assert.ok(!visibleText(reportView(testCtx(), { report: {} })).includes("只描述"), "no help line for a missing label");
});

test("the report shows a short fingerprint and keeps ids in the details", () => {
  const view = reportView(testCtx(), REPORT);
  const text = visibleText(view);
  assert.match(text, /报告指纹 [0-9a-f]{8}…/);
  for (const id of [REPORT.sha256, REPORT.report.snapshot_id, REPORT.artifact_id]) assert.ok(!text.includes(id), id);
  assert.equal(techFolds(view).length, 1, "one fold for the report");
  const all = visibleTextIncludingDetails(view);
  for (const id of [REPORT.sha256, REPORT.report.snapshot_id, REPORT.artifact_id]) assert.equal(count(all, id), 1, id);
  assert.match(visibleText(reportView(testCtx({ lang: "en" }), REPORT)), /Report fingerprint [0-9a-f]{8}…/);
});

test("limitations show three and fold the rest", () => {
  const report = { notes: [], model_limitations: ["a1", "a2", "a3", "a4", "a5"] };
  const view = reportView(testCtx(), { label: "descriptive", report });
  const [more, ...others] = plainFolds(view);
  assert.equal(others.length, 0);
  assert.equal(more.getAttribute("open"), null, "closed by default");
  assert.equal(elements(more, "summary")[0].textContent, "还有 2 条");
  assert.deepEqual(elements(more, "li").map((li) => li.textContent), ["a4", "a5"]);
  assert.deepEqual(elements(view, "li").map((li) => li.textContent), ["a1", "a2", "a3", "a4", "a5"], "three in view, then the fold");
  const enView = reportView(testCtx({ lang: "en" }), { label: "descriptive", report });
  assert.equal(elements(plainFolds(enView)[0], "summary")[0].textContent, "2 more");
  const three = reportView(testCtx(), { label: "descriptive", report: { notes: [], model_limitations: ["a1", "a2", "a3"] } });
  assert.equal(plainFolds(three).length, 0, "three or fewer: no fold");
});

test("the server's own limitation notes come before the model's and stay in view", () => {
  const note = { code: "treatment_unverified", kind: "limitation", params: { round: 1 }, text: { en: "Round 1 unverified", zh: "第 1 轮未核实" } };
  const report = { model_limitations: ["m1", "m2", "m3", "m4"], notes: [note] };
  const view = reportView(testCtx(), { label: "descriptive", report });
  const folded = elements(plainFolds(view)[0], "li").map((li) => li.textContent);
  const shown = elements(view, "li").map((li) => li.textContent).filter((text) => !folded.includes(text));
  assert.deepEqual(shown, ["第 1 轮未核实", "m1", "m2"]);
  assert.deepEqual(folded, ["m3", "m4"]);
});

test("report items and the next round keep the model's light markup", () => {
  const report = { reasons: ["the **main** reason"], unresolved: ["see `x`"], next_round: "Two steps:\n- one\n- two" };
  const view = reportView(testCtx(), { label: "descriptive", report });
  assert.deepEqual(elements(view, "strong").map((node) => node.textContent), ["main"]);
  assert.ok(elements(view, "code").some((node) => node.textContent === "x"));
  const [rich] = elements(view, "div").filter((node) => hasClass(node, "rich-text"));
  assert.ok(rich, "the next round is rich text");
  assert.deepEqual(elements(rich, "li").map((li) => li.textContent), ["one", "two"]);
});

test("an estimable effect says what its p value means", () => {
  const estimable = { estimable: true, effect: 0.231234, p_value: 0.034, blocks: 2 };
  assert.equal(zh["report.pHelp"], "p 值越小，越不像是偶然造成的差异。");
  assert.ok(visibleText(reportView(testCtx(), { label: "confirmatory", report: { estimate: estimable } })).includes(zh["report.pHelp"]));
  assert.ok(!visibleText(reportView(testCtx(), REPORT)).includes(zh["report.pHelp"]), "no p value, no line about it");
});

test("a report that could not be read shows the plain lines and folds the server's words", async () => {
  const words = "report file research_report_x.json is missing";
  const c = testCtx();
  bindFormContext(c);
  const get = c.api.get;
  c.api.get = async (path) => {
    if (path.endsWith("/report")) throw new ApiError(500, null, words);
    return get(path);
  };
  const { element } = await render(c, { roundId: ROUND.round_id });
  const box = sectionTitled(element, zh["report.title"]);
  assert.ok(visibleText(box).includes(zh["error.title"]));
  assert.ok(!visibleText(box).includes(words));
  assert.ok(visibleTextIncludingDetails(box).includes(words));
  for (const id of [ROUND.report_artifact_id, ROUND.snapshot_id]) {
    assert.ok(!visibleText(box).includes(id), id);
    assert.ok(visibleTextIncludingDetails(box).includes(id), id);
  }
});

test("a report answer without its own id keeps the round's report id in the details", () => {
  const { artifact_id: _a, ...withoutId } = REPORT;
  const all = visibleTextIncludingDetails(reportView(testCtx(), withoutId, ROUND));
  assert.equal(count(all, ROUND.report_artifact_id), 1);
});

// --- the round summary and stages -----------------------------------------------------------------

test("the summary names the project and the protocol version, and lists no snapshot or report id", async () => {
  const { element } = await renderPage("round", { roundId: ROUND.round_id }, { lang: "zh" });
  const summary = sectionTitled(element, zh["round.summary"]);
  assert.equal(elements(summary, "a")[0].textContent, ROUND.project_name);
  const text = visibleTextIncludingDetails(summary);
  assert.ok(text.includes("protocol-lettuce-light 第 1 版"), text);
  for (const id of [ROUND.snapshot_id, ROUND.report_artifact_id]) assert.ok(!text.includes(id), id);
  const enPage = await renderPage("round", { roundId: ROUND.round_id }, { lang: "en" });
  assert.ok(visibleText(sectionTitled(enPage.element, en["round.summary"])).includes("protocol-lettuce-light version 1"));
});

test("stages are linked by name, and the stopped stage is named in the choice", async () => {
  const stage = ROUND.stages[0];
  const waiting = { ...ROUND, state: "running", awaiting_choice: stage.stage_id };
  const { element } = await renderPage("round", { roundId: ROUND.round_id }, { lang: "zh", fixtures: { "round.json": waiting } });
  const stages = sectionTitled(element, zh["round.stages"]);
  assert.deepEqual(elements(stages, "a").map((a) => a.textContent), ["第 1 阶段 · vegetative"]);
  const choice = visibleText(sectionTitled(element, zh["round.choiceTitle"]));
  assert.ok(choice.includes("第 1 阶段 · vegetative 已停止"), choice);
  assert.ok(!choice.includes(stage.stage_id), choice);
  const lost = { ...waiting, awaiting_choice: "stage-elsewhere-9" };
  const other = await renderPage("round", { roundId: ROUND.round_id }, { lang: "zh", fixtures: { "round.json": lost } });
  const text = visibleText(sectionTitled(other.element, zh["round.choiceTitle"]));
  assert.ok(text.includes("未命名阶段 已停止") && !text.includes("stage-elsewhere-9"), text);
});

test("the abort question names the round, not its id", () => {
  const [line] = abortLines(testCtx(), ROUND);
  assert.ok(line.startsWith("第 1 轮") && !line.includes(ROUND.round_id), line);
  const [enLine] = abortLines(testCtx({ lang: "en" }), ROUND);
  assert.ok(enLine.startsWith("Round 1 ") && !enLine.includes(ROUND.round_id), enLine);
});

// --- the confirmatory analysis --------------------------------------------------------------------

test("the analysis block is folded by default", async () => {
  const root = await analysisSection(testCtx(), ROUND);
  assert.equal(root.localName, "details");
  assert.ok(!hasClass(root, "tech-details"));
  assert.equal(root.getAttribute("open"), null);
  assert.equal(summaryOf(root), "确认性分析（高级）· 未开始");
  const enRoot = await analysisSection(testCtx({ lang: "en" }), ROUND);
  assert.equal(summaryOf(enRoot), "Confirmatory analysis (advanced) · Not started");
});

test("the analysis says where it stands in one word", async () => {
  const frozen = { script_sha256: "ab".repeat(32), frozen_at: 1796590000, frozen_by: "dev", script: "x = 1" };
  assert.equal(analysisState(ANALYSIS), "notStarted");
  assert.equal(analysisState({ ...ANALYSIS, frozen }), "locked");
  const ran = { ...ANALYSIS, frozen, snapshots: [{ ...ANALYSIS.snapshots[0], run_status: "succeeded" }] };
  assert.equal(analysisState(ran), "ran");
  const failed = { ...ran, snapshots: [{ ...ANALYSIS.snapshots[0], run_status: "failed" }] };
  assert.equal(analysisState(failed), "ran");
  const running = { ...ran, snapshots: [...ran.snapshots, { ...ANALYSIS.snapshots[0], run_status: "running" }] };
  assert.equal(analysisState(running), "running");
  assert.equal(summaryOf(await analysisSection(testCtx({ fixtures: { "analysis.json": { ...ANALYSIS, frozen } } }), ROUND)), "确认性分析（高级）· 脚本已锁定");
  assert.equal(summaryOf(await analysisSection(testCtx({ fixtures: { "analysis.json": running } }), ROUND)), "确认性分析（高级）· 运行中");
  assert.equal(summaryOf(await analysisSection(testCtx({ fixtures: { "analysis.json": ran } }), ROUND)), "确认性分析（高级）· 已运行");
});

test("snapshots are named by date and completeness, their ids in the details", async () => {
  const c = testCtx();
  bindFormContext(c);
  const root = await analysisSection(c, ROUND);
  const [snapshot] = ANALYSIS.snapshots;
  const name = displayName(c, "snapshot", snapshot);
  const text = visibleText(root);
  assert.equal(count(text, name), 2, "the table row and the run form's option");
  assert.deepEqual(elements(root, "option").map((option) => option.textContent), ["请选择…", name]);
  assert.deepEqual(elements(root, "option").map((option) => option.getAttribute("value")), ["", snapshot.snapshot_id]);
  assert.ok(text.includes(zh["analysis.runState.none"]) && !/\bnone\b/.test(text), text);
  for (const id of [snapshot.snapshot_id, snapshot.experiment_id]) {
    assert.ok(!text.includes(id), id);
    assert.ok(visibleTextIncludingDetails(root).includes(id), id);
  }
  assert.ok(text.includes("已开始采集数据"), text);
});

test("a frozen script keeps its fingerprint and text in folds", async () => {
  const frozen = { script_sha256: "ab".repeat(32), frozen_at: 1796590000, frozen_by: "dev", script: "import growth_model" };
  const root = await analysisSection(testCtx({ fixtures: { "analysis.json": { ...ANALYSIS, frozen } } }), ROUND);
  const text = visibleText(root);
  assert.ok(!text.includes(frozen.script_sha256) && !text.includes(frozen.script), text);
  const all = visibleTextIncludingDetails(root);
  assert.equal(count(all, frozen.script_sha256), 1);
  assert.equal(count(all, frozen.script), 1);
  assert.ok(text.includes("dev"));
});

test("a run's id, exit code and output are in the details; its status is a word", () => {
  const run = { run_id: "run_5c98", status: "failed", exit_code: 2, timed_out: false, stdout: "out_text", stderr: "err_text" };
  const view = runView(testCtx(), run);
  const text = visibleText(view);
  assert.ok(text.includes(zh["analysis.runState.failed"]), text);
  for (const raw of ["run_5c98", "out_text", "err_text", "failed"]) assert.ok(!text.includes(raw), raw);
  const all = visibleTextIncludingDetails(view);
  for (const raw of ["run_5c98", "out_text", "err_text"]) assert.ok(all.includes(raw), raw);
  assert.match(all, /退出码 2/);
});

test("a round planned on an older version says the analysis is not for it", async () => {
  const latest = { ...ANALYSIS, version: 3 };
  const text = visibleText(await analysisSection(testCtx({ fixtures: { "analysis.json": latest } }), ROUND));
  assert.ok(text.includes("本轮按第 1 版规划；第 3 版已存在。下面的分析针对第 3 版，不是本轮。"), text);
  const enText = visibleText(await analysisSection(testCtx({ lang: "en", fixtures: { "analysis.json": latest } }), ROUND));
  assert.ok(enText.includes("Data collection has started"), enText);
});

test("after a run the analysis opens again on its result, once", async () => {
  const frozen = { script_sha256: "ab".repeat(32), frozen_at: 1796590000, frozen_by: "dev", script: "x = 1" };
  const c = testCtx({ fixtures: { "analysis.json": { ...ANALYSIS, frozen } } });
  bindFormContext(c);
  c.api.post = async () => ({ run_id: "run_5c98", status: "succeeded", exit_code: 0, timed_out: false, stdout: "", stderr: "" });
  const first = await analysisSection(c, ROUND);
  const form = elements(first, "form").find((node) => elements(node, "select").length);
  formControls(form).set({ snapshot_id: ANALYSIS.snapshots[0].snapshot_id });
  answerNextDialog(true);
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  await settle();
  const again = await analysisSection(c, ROUND);
  assert.notEqual(again.getAttribute("open"), null, "open on the result");
  assert.equal(summaryOf(again), "确认性分析（高级）· 脚本已锁定");
  assert.ok(visibleText(again).includes(zh["analysis.runState.succeeded"]));
  const later = await analysisSection(c, ROUND);
  assert.equal(later.getAttribute("open"), null, "the result is shown once");
  assert.ok(!visibleText(later).includes(zh["analysis.runState.succeeded"]));
});

test("after a freeze the analysis opens again, for that round only", async () => {
  const c = testCtx();
  bindFormContext(c);
  c.api.post = async () => ({});
  const first = await analysisSection(c, ROUND);
  const form = elements(first, "form").find((node) => elements(node, "textarea").length);
  formControls(form).set({ script: "x = 1" });
  answerNextDialog(true);
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  await settle();
  const other = await analysisSection(c, { ...ROUND, round_id: "round_other" });
  assert.equal(other.getAttribute("open"), null, "another round stays closed");
  const again = await analysisSection(c, ROUND);
  assert.notEqual(again.getAttribute("open"), null);
  assert.equal((await analysisSection(c, ROUND)).getAttribute("open"), null, "opened once");
});

test("freezing asks first and says it cannot be undone; cancelling sends nothing", async () => {
  const c = testCtx({ lang: "en" });
  bindFormContext(c);
  const posts = [];
  c.api.post = async (path, body) => {
    posts.push({ path, body });
    return {};
  };
  const form = elements(await analysisSection(c, ROUND), "form").find((node) => elements(node, "textarea").length);
  const area = elements(form, "textarea")[0];
  assert.equal(area.getAttribute("maxlength"), "20000");
  assert.ok(area.classList.contains("input-code"), "monospace");
  assert.ok(visibleText(form).includes("cannot be undone"), visibleText(form));
  assert.equal(elements(form, "details").length, 0, "no JSON fold");
  formControls(form).set({ script: "print(1)" });
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  await settle();
  const [dialog] = openDialogs();
  assert.ok(dialog.textContent.includes("Freeze this analysis script?"), dialog.textContent);
  assert.ok(dialog.textContent.includes("can no longer be changed"), dialog.textContent);
  answerNextDialog(false);
  await settle();
  await settle();
  assert.equal(posts.length, 0);
  assert.equal(visibleText(form).includes("Done"), false);
  assert.equal(elements(form, "button").every((b) => !b.disabled), true);
  answerNextDialog(true);
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  await settle();
  await settle();
  assert.equal(posts.length, 1);
  assert.deepEqual(posts[0].body, { project_id: ROUND.project_id, script: "print(1)" });
});

test("the run form starts on 'choose' and asks before the one run a snapshot allows", async () => {
  const frozen = { script_sha256: "ab".repeat(32), frozen_at: 1796590000, frozen_by: "dev", script: "x = 1" };
  const c = testCtx({ lang: "en", fixtures: { "analysis.json": { ...ANALYSIS, frozen } } });
  bindFormContext(c);
  const posts = [];
  c.api.post = async (path, body) => {
    posts.push({ path, body });
    return { run_id: "run_1", status: "succeeded", exit_code: 0, timed_out: false, stdout: "", stderr: "" };
  };
  const form = elements(await analysisSection(c, ROUND), "form").find((node) => elements(node, "select").length);
  const options = elements(form, "option");
  assert.equal(options[0].textContent, "Choose…");
  assert.equal(options[0].getAttribute("value"), "");
  const select = elements(form, "select")[0];
  assert.equal(select.value, "");
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  await settle();
  assert.equal(posts.length, 0, "a blank choice is refused");
  const [snapshot] = ANALYSIS.snapshots;
  formControls(form).set({ snapshot_id: snapshot.snapshot_id });
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  await settle();
  const [dialog] = openDialogs();
  assert.ok(dialog.textContent.includes("only one confirmatory analysis"), dialog.textContent);
  assert.ok(dialog.textContent.includes(displayName(c, "snapshot", snapshot)), dialog.textContent);
  assert.ok(!dialog.textContent.includes(snapshot.snapshot_id), "no id");
  answerNextDialog(false);
  await settle();
  await settle();
  assert.equal(posts.length, 0);
  answerNextDialog(true);
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  await settle();
  await settle();
  assert.deepEqual(posts.map((p) => p.path), ["/analysis/runs"]);
});

// --- final review: an effect of a thousand or more has no exponent (F13) -------------------------
test("a large effect and a tiny p value are written without an exponent, in the page's language", () => {
  const big = { estimable: true, effect: 1234.5, p_value: 0.00000012, blocks: 3 };
  assert.equal(estimateText(testCtx({ lang: "en" }), big), "Effect 1,230, p = 0.00000012, over 3 complete blocks");
  assert.equal(estimateText(testCtx({ lang: "zh" }), big), "效应 1,230，p = 0.00000012，基于 3 个完整区组");
  const small = { estimable: true, effect: 0.231234, p_value: 0.034, blocks: 2 };
  assert.equal(estimateText(testCtx({ lang: "en" }), small), "Effect 0.231, p = 0.034, over 2 complete blocks");
  for (const lang of ["en", "zh"]) assert.doesNotMatch(estimateText(testCtx({ lang }), big), /e[+-]/);
});

const TOO_FEW = { estimable: false, effect: 0, blocks: 0, p_value: null, note: "fewer than 2 complete blocks; no treatment effect can be estimated", note_code: "too_few_blocks", note_params: { blocks: 0, min_blocks: 2 } };
const withEstimate = (estimate, extra = {}) => ({ label: "descriptive", ...extra, report: { estimate } });

test("an estimate note follows the console language and says what to do", () => {
  for (const lang of ["en", "zh"]) {
    const text = visibleText(reportView(testCtx({ lang }), withEstimate(TOO_FEW)));
    const messages = lang === "en" ? MESSAGES_EN : MESSAGES_ZH;
    const filled = (template) => template.replace("{blocks}", "0").replaceAll("{min_blocks}", "2");
    assert.ok(text.includes(filled(messages["msg.estimate.too_few_blocks"])), lang);
    assert.ok(text.includes(filled(messages["msg.estimate.too_few_blocks.action"])), lang);
  }
  const zhText = visibleText(reportView(testCtx({ lang: "zh" }), withEstimate(TOO_FEW)));
  assert.doesNotMatch(zhText, /fewer than/i);
  const sampled = { estimable: true, effect: 1.5, blocks: 25, p_value: 0.001, note: "p-value approximated by sampled sign flips", note_code: "sampled_p", note_params: { flips: 20000, blocks: 25 } };
  const sampledText = visibleText(reportView(testCtx({ lang: "zh" }), withEstimate(sampled)));
  assert.ok(sampledText.includes("20,000") && !/sampled sign flips/.test(sampledText));
  assert.ok(!sampledText.includes("再跑几轮"), "an approximated p needs no action");
});

test("an old report's note stays in the details", () => {
  const old = { estimable: false, effect: 0, blocks: 0, p_value: null, note: "fewer than 2 complete blocks; no treatment effect can be estimated" };
  const view = reportView(testCtx({ lang: "zh" }), withEstimate(old));
  assert.ok(visibleText(view).includes(zh["report.notEstimable"]));
  assert.ok(!visibleText(view).includes(old.note), "the English sentence is not on the page");
  assert.ok(visibleTextIncludingDetails(view).includes(old.note), "but it is in the details");
});

test("an old estimable report's note on its sampled p value is folded, not shown", () => {
  const old = { estimable: true, effect: 1.5, blocks: 25, p_value: 0.001, note: "p-value approximated by sampled sign flips" };
  for (const lang of ["zh", "en"]) {
    const view = reportView(testCtx({ lang }), withEstimate(old));
    assert.ok(!visibleText(view).includes(old.note), `${lang}: the English sentence is not on the page`);
    assert.ok(visibleTextIncludingDetails(view).includes(old.note), `${lang}: but it is in the details`);
  }
  const none = reportView(testCtx({ lang: "zh" }), withEstimate({ ...old, note: "" }));
  assert.ok(!visibleTextIncludingDetails(none).includes(zh["report.estimateNote"]), "an empty note adds no row");
});

test("the estimate names the measured quantity", () => {
  const view = reportView(testCtx({ lang: "zh" }), withEstimate(TOO_FEW, { primary_endpoint: "canopy_area_growth" }));
  assert.ok(visibleText(view).includes("指标：「canopy_area_growth」"));
  const none = reportView(testCtx({ lang: "zh" }), withEstimate(TOO_FEW, { primary_endpoint: null }));
  assert.ok(!visibleText(none).includes("指标"));
});

// --- the round choice asks, every choice with its own consequence (RND-04) -----------------------
test("the round choice starts on 'choose' and every choice is asked with its consequence", async () => {
  const waiting = { ...ROUND, state: "running", awaiting_choice: ROUND.stages[0].stage_id };
  const { element, ctx: page } = await renderPage("round", { roundId: ROUND.round_id }, { lang: "en", fixtures: { "round.json": waiting } });
  const form = elements(sectionTitled(element, en["round.choiceTitle"]), "form")[0];
  const options = elements(form, "option");
  assert.equal(options[0].textContent, "Choose…");
  assert.equal(options[0].getAttribute("value"), "");
  assert.equal(elements(form, "select")[0].value, "");
  const posts = () => page.api.calls.filter((call) => call.method === "POST");
  const submit = async () => {
    form.dispatchEvent(new Event("submit", { cancelable: true }));
    await settle();
    await settle();
  };
  await submit();
  assert.equal(posts().length, 0, "a blank choice is refused");
  for (const choice of ["redo", "next", "verify", "abort"]) {
    formControls(form).set({ choice });
    form.dispatchEvent(new Event("submit", { cancelable: true }));
    await settle();
    const [dialog] = openDialogs();
    if (choice !== "abort") assert.ok(en[`round.choice.${choice}.line`], `${choice} has its own line`);
    assert.ok(dialog.textContent.includes(en[`round.choice.${choice}.line`] || displayName(page, "round", waiting)), `${choice}: ${dialog.textContent}`);
    answerNextDialog(false);
    await settle();
    await settle();
    assert.equal(posts().length, 0, `${choice}: cancelling sends nothing`);
    assert.equal(visibleText(form).includes("Chosen"), false);
  }
  formControls(form).set({ choice: "redo" });
  answerNextDialog(true);
  await submit();
  assert.deepEqual(posts().map((call) => call.body), [{ choice: "redo" }]);
});
