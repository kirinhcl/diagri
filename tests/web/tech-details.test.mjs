// The technical-details fold (ids, hashes and raw values, each copyable) and errors that keep only the
// plain lines in view, with the server's own text folded underneath.
import assert from "node:assert/strict";
import test from "node:test";

import { ApiError } from "../../src/growbridge/web/workbench/api.js";
import { describeDenial } from "../../src/growbridge/web/workbench/denials.js";
import { makeT } from "../../src/growbridge/web/workbench/i18n.js";
import { errorDetail, errorLines, simpleForm } from "../../src/growbridge/web/workbench/ui/forms.js";
import { copyText, errorBox, errorParts, replaceParts, showErrors, techDetails } from "../../src/growbridge/web/workbench/ui/section.js";
import { countButtons, visibleText, visibleTextIncludingDetails } from "./support/leaks.mjs";
import { FIXTURES, installFakeDom, renderPage } from "./support/render-page.mjs";

const RAW = "stage st_91c2 is recovery_check; it cannot pause";

// Every pending promise job, then one turn of the event loop.
const settle = () => new Promise((resolve) => setImmediate(resolve));

function elements(node, name) {
  const own = node.localName === name ? [node] : [];
  return [...own, ...[...(node.children || [])].flatMap((child) => elements(child, name))];
}

function clipboardOf(writeText) {
  const written = [];
  return { written, clipboard: { writeText: (text) => (written.push(text), writeText(text)) } };
}

async function click(button) {
  button.dispatchEvent(new Event("click"));
  await settle();
}

test("techDetails lists each value with a copy button and drops empties", () => {
  installFakeDom();
  const el = techDetails(makeT("zh"), [["轮次 id", "round_1"], ["空", null], ["事件", { a: 1 }]]);
  assert.equal(el.getAttribute("class"), "tech-details");
  assert.match(visibleTextIncludingDetails(el), /round_1/); // 展开后能看到
  assert.equal(countButtons(el), 3); // 两项各一个，加一个复制全部
  assert.equal(techDetails(makeT("zh"), [["x", ""]]), null);
});

test("the fold is closed, titled, and holds a dt and a code per value", () => {
  installFakeDom();
  const t = makeT("en");
  const el = techDetails(t, [["Round id", "round_1"], ["Missing", undefined], ["Event", { a: 1, b: [2] }], ["Count", 0]]);
  assert.equal(el.localName, "details");
  assert.equal(el.hasAttribute("open"), false);
  assert.equal(elements(el, "summary")[0].textContent, "Technical details");
  assert.deepEqual(elements(el, "dt").map((dt) => dt.textContent), ["Round id", "Event", "Count"]);
  assert.deepEqual(elements(el, "code").map((code) => code.textContent), ["round_1", JSON.stringify({ a: 1, b: [2] }, null, 2), "0"]);
  assert.deepEqual(elements(el, "button").map((button) => button.textContent), ["Copy", "Copy", "Copy", "Copy all"]);
  assert.equal(visibleText(el), "", "nothing inside the fold counts as page text");
  assert.equal(techDetails(t, []), null);
  assert.equal(techDetails(t, [["a", null], ["b", undefined]]), null);
});

test("copy without a clipboard says so and does not throw", async () => {
  installFakeDom({ clipboard: undefined });
  assert.equal(await copyText("abc"), false);
});

test("copyText is false when writeText is missing or refused, true when it writes", async () => {
  installFakeDom({ clipboard: {} });
  assert.equal(await copyText("abc"), false);
  installFakeDom({ clipboard: { writeText: () => Promise.reject(new Error("NotAllowedError")) } });
  assert.equal(await copyText("abc"), false);
  installFakeDom({ clipboard: { writeText: () => { throw new Error("no"); } } });
  assert.equal(await copyText("abc"), false);
  const { written, clipboard } = clipboardOf(() => Promise.resolve());
  installFakeDom({ clipboard });
  assert.equal(await copyText("abc"), true);
  assert.deepEqual(written, ["abc"]);
});

test("each copy button copies its value; copy all copies label: value lines; the button says how it went", async () => {
  const { written, clipboard } = clipboardOf(() => Promise.resolve());
  installFakeDom({ clipboard });
  const t = makeT("zh");
  const el = techDetails(t, [["轮次 id", "round_1"], ["事件", { a: 1 }]]);
  const [first, , all] = elements(el, "button");
  await click(first);
  await click(all);
  assert.deepEqual(written, ["round_1", `轮次 id: round_1\n事件: ${JSON.stringify({ a: 1 }, null, 2)}`]);
  assert.equal(first.textContent, "已复制");
  assert.equal(all.textContent, "已复制");
  installFakeDom({ clipboard: undefined });
  const refused = techDetails(t, [["轮次 id", "round_1"]]);
  const [button] = elements(refused, "button");
  await click(button);
  assert.equal(button.textContent, "复制失败，请手动选择");
  assert.equal(elements(refused, "code")[0].textContent, "round_1", "the value stays on the page to select by hand");
});

test("errorLines keeps only the human lines; the server text goes to the details", () => {
  const t = makeT("zh");
  const err = new ApiError(409, "state", RAW);
  assert.equal(errorLines(err, "zh", t).length, 2);
  assert.deepEqual(errorDetail(err).map(([, v]) => v), [409, "state", RAW]);
  assert.deepEqual(errorLines(new ApiError(404, null, "HTTP 404"), "zh", t), [t("error.notFound")]);
  assert.deepEqual(errorLines(new ApiError(0, "network", "Failed to fetch"), "zh", t), [t("error.network")]);
});

test("errorLines: a network failure is one line whatever its status; anything else unknown is the title", () => {
  const t = makeT("en");
  assert.deepEqual(errorLines(new ApiError(undefined, "network", "Load failed"), "en", t), [t("error.network")]);
  assert.deepEqual(errorLines(new ApiError(404, "member", "not a member"), "en", t), Object.values(describeDenial("member", "en")));
  assert.deepEqual(errorLines(new ApiError(400, null, "HTTP 400"), "en", t), [t("error.title")]);
  assert.deepEqual(errorLines(new ApiError(409, "brand_new_code", "raw words"), "en", t), [t("error.title")]);
  assert.deepEqual(errorLines(new TypeError("x is undefined"), "en", t), [t("error.title")]);
  assert.deepEqual(errorLines(null, "en", t), [t("error.title")]);
  for (const error of [new ApiError(500, "server_error", "HTTP 500"), new ApiError(409, "state", RAW)]) {
    assert.ok(errorLines(error, "en", t).length <= 2);
  }
});

test("no answer may still mean the write arrived: the network line says to reload and look, not to resend", () => {
  const network = new ApiError(0, "network", "Failed to fetch");
  assert.deepEqual(errorLines(network, "zh", makeT("zh")), ["连不上服务器，或没有收到答复。请检查网络后刷新页面再看。"]);
  assert.deepEqual(errorLines(network, "en", makeT("en")), [
    "The server could not be reached, or no answer came back. Check the network, then reload the page to see what happened.",
  ]);
});

test("errorParts: the plain lines as paragraphs, then the fold with the server's words", () => {
  installFakeDom();
  const ctx = { t: makeT("en"), lang: "en" };
  const parts = errorParts(ctx, new ApiError(409, "state", RAW));
  const { text, advice } = describeDenial("state", "en");
  assert.deepEqual(parts.map((node) => node.localName), ["p", "p", "details"]);
  assert.deepEqual(parts.slice(0, 2).map((node) => node.textContent), [text, advice]);
  assert.match(visibleTextIncludingDetails(parts[2]), /recovery_check; it cannot pause/);
  assert.deepEqual(errorParts(ctx, null).map((node) => node.localName), ["p"], "nothing to fold, no fold");
});

test("replaceParts leaves an opened fold open when a poll brings the same error again", () => {
  installFakeDom();
  const ctx = { t: makeT("en"), lang: "en" };
  const box = errorBox();
  replaceParts(box, errorParts(ctx, new ApiError(409, "state", RAW)));
  const [fold] = elements(box, "details");
  fold.setAttribute("open", "");
  replaceParts(box, errorParts(ctx, new ApiError(409, "state", RAW)));
  assert.equal(elements(box, "details")[0], fold);
  assert.equal(fold.hasAttribute("open"), true);
  replaceParts(box, errorParts(ctx, new ApiError(409, "state", "other words")));
  assert.notEqual(elements(box, "details")[0], fold, "different words: shown afresh");
  box.replaceChildren();
  replaceParts(box, errorParts(ctx, new ApiError(409, "state", "other words")));
  assert.equal(elements(box, "details").length, 1, "an emptied box is filled again");
});

test("the console's own refusals (not_approved) keep their catalog line in view", () => {
  const t = makeT("en");
  const line = t("safety.changedMeanwhile");
  assert.deepEqual(errorLines(new ApiError(0, "not_approved", line), "en", t), [t("error.title"), line]);
});

test("a draft run sheet refused for blocking findings says so in the form, not only in the details", async () => {
  installFakeDom();
  const { element, ctx } = await renderPage("stage", { stageId: FIXTURES["stage-pending.json"].stage_id }, { lang: "en" });
  ctx.api.post = async () => ({ findings: [{ code: "pump_action", blocking: true, message: "pump on" }] });
  const group = elements(element, "div").find((div) => div.getAttribute("data-action") === "draft");
  const [form] = elements(group, "form");
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  await settle();
  const status = elements(form, "div").find((div) => (div.getAttribute("class") || "").includes("form-status"));
  assert.deepEqual(elements(status, "p").map((p) => p.textContent), [ctx.t("error.title"), ctx.t("stage.draft.refused")]);
});

test("errorDetail labels each fact in the page language and leaves out what is missing", () => {
  const zh = makeT("zh");
  assert.deepEqual(errorDetail(new ApiError(409, "state", RAW), zh), [["HTTP 状态", 409], ["代码", "state"], ["服务器原文", RAW]]);
  assert.deepEqual(errorDetail(new ApiError(404, null, "HTTP 404"), zh), [["HTTP 状态", 404], ["错误信息", "HTTP 404"]]);
  assert.deepEqual(errorDetail(new ApiError(422, "validation", "validation"), zh), [["HTTP 状态", 422], ["代码", "validation"]]);
  const network = errorDetail(new ApiError(0, "network", "Failed to fetch"), zh); // no answer: the browser's words
  assert.deepEqual(network, [["代码", "network"], ["错误信息", "Failed to fetch"]]);
  assert.deepEqual(errorDetail(new TypeError("x is undefined"), makeT("en")), [["Error message", "x is undefined"]]);
  assert.deepEqual(errorDetail(null, zh), []);
});

test("showErrors writes the plain lines and folds the server text underneath", () => {
  installFakeDom();
  const ctx = { t: makeT("en"), lang: "en" };
  const box = errorBox();
  showErrors(box, new ApiError(409, "state", RAW), ctx);
  assert.equal(box.hidden, false);
  assert.doesNotMatch(visibleText(box), /recovery_check/);
  assert.match(visibleTextIncludingDetails(box), /stage st_91c2 is recovery_check; it cannot pause/);
  assert.equal(elements(box, "details").length, 1);
  showErrors(box, null, ctx);
  assert.equal(elements(box, "details").length, 0, "nothing to fold, no fold; the old one is gone");
});

test("a form's refusal shows the plain lines with the technical details under them", async () => {
  installFakeDom();
  const notices = [];
  const ctx = { t: makeT("zh"), lang: "zh", me: { timezone: "UTC" }, notify: (text) => notices.push(text), reload: () => {} };
  const onSubmit = async () => {
    throw new ApiError(409, "state", RAW);
  };
  const form = simpleForm({ fields: [{ name: "reason", label: "原因" }], submitLabel: "暂停", onSubmit, ctx });
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  await settle();
  const status = elements(form, "div").find((div) => (div.getAttribute("class") || "").includes("form-status"));
  const { text, advice } = describeDenial("state", "zh");
  assert.deepEqual(elements(status, "p").map((p) => p.textContent), [text, advice]);
  assert.doesNotMatch(visibleText(form), /recovery_check/);
  assert.match(visibleTextIncludingDetails(status), /409/);
  assert.match(visibleTextIncludingDetails(status), /stage st_91c2 is recovery_check/);
  assert.deepEqual(notices, [`${text} ${advice}`]);
});

// --- final review: "unknown (technical details)" has the code in a fold right there (F3) ----------
import { codeLabel, severityPill, statePill } from "../../src/growbridge/web/workbench/ui/status.js";
import { makeT as catalogT } from "../../src/growbridge/web/workbench/i18n.js";

const UNKNOWN = "warp_drive";

test("a known state or severity is a bare pill; an unknown one keeps its code in a fold beside it", () => {
  installFakeDom();
  const t = catalogT("zh");
  assert.equal(visibleTextIncludingDetails(statePill(t, "running")), "运行中");
  assert.equal(visibleTextIncludingDetails(severityPill(t, "critical")), visibleText(severityPill(t, "critical")));
  for (const node of [statePill(t, UNKNOWN), severityPill(t, UNKNOWN), codeLabel(t, "alert.kind", UNKNOWN)]) {
    assert.match(visibleText(node), /未知（技术详情）/);
    assert.ok(!visibleText(node).includes(UNKNOWN));
    assert.match(visibleTextIncludingDetails(node), /代码 warp_drive/);
  }
  assert.equal(codeLabel(t, "alert.kind", "data_gap"), "数据空档");
  assert.equal(visibleText(statePill(t, null)), "—");
  assert.equal(visibleTextIncludingDetails(statePill(t, null)), "—");
});

test("the stage, round and alerts pages keep an unknown state or kind's code in the details", async () => {
  const stageId = FIXTURES["stage.json"].stage_id;
  const roundId = FIXTURES["round.json"].round_id;
  const [first, ...rest] = FIXTURES["alerts.json"].alerts;
  const pages = [
    ["stage", { stageId }, { "stage.json": { ...FIXTURES["stage.json"], state: UNKNOWN, prior_state: "warp_prior" } }, ["warp_drive", "warp_prior"]],
    ["round", { roundId }, { "round.json": { ...FIXTURES["round.json"], state: UNKNOWN } }, ["warp_drive"]],
    ["alerts", {}, { "alerts.json": { alerts: [{ ...first, kind: UNKNOWN, severity: "warp_level" }, ...rest] } }, ["warp_drive", "warp_level"]],
  ];
  for (const [page, params, fixtures, codes] of pages) {
    const { element } = await renderPage(page, params, { fixtures });
    for (const code of codes) {
      assert.ok(!visibleText(element).includes(code), `${page}: ${code} in view`);
      assert.ok(visibleTextIncludingDetails(element).includes(`代码 ${code}`), `${page}: ${code} not in a fold`);
    }
  }
});

// --- final review: without the Clipboard API, select the value and ask the browser to copy (F8) ---
// A stand-in for the Selection API and document.execCommand on the fake document.
function selectionStub(document, execResult) {
  const selection = { ranges: [], removeAllRanges() { this.ranges = []; }, addRange(range) { this.ranges.push(range); } };
  const commands = [];
  document.getSelection = () => selection;
  document.createRange = () => ({ node: null, selectNodeContents(node) { this.node = node; } });
  document.execCommand = (command) => {
    commands.push(command);
    if (execResult instanceof Error) throw execResult;
    return execResult;
  };
  return { selection, commands, selected: () => selection.ranges.map((range) => range.node) };
}

test("on plain http a copy button selects its value and copies the selection", async () => {
  installFakeDom({ clipboard: undefined });
  const stub = selectionStub(globalThis.document, true);
  const el = techDetails(makeT("zh"), [["轮次 id", "round_1"]]);
  const [button] = elements(el, "button");
  await click(button);
  assert.deepEqual(stub.commands, ["copy"]);
  assert.deepEqual(stub.selected(), [elements(el, "code")[0]]);
  assert.equal(button.textContent, "已复制");
});

test("when the browser will not copy, the value stays selected and the button says to copy by hand", async () => {
  for (const [clipboard, result] of [[undefined, false], [{ writeText: () => Promise.reject(new Error("NotAllowedError")) }, false], [undefined, new Error("SecurityError")]]) {
    installFakeDom({ clipboard });
    const stub = selectionStub(globalThis.document, result);
    const el = techDetails(makeT("zh"), [["轮次 id", "round_1"], ["阶段 id", "stage-1"]]);
    const [first, , all] = elements(el, "button");
    await click(first);
    assert.equal(first.textContent, "复制失败，请手动选择");
    assert.deepEqual(stub.selected(), [elements(el, "code")[0]], "the value is selected for Cmd/Ctrl+C");
    await click(all);
    assert.equal(all.textContent, "复制失败，请手动选择");
    assert.deepEqual(stub.selected(), [elements(el, "dl")[0]], "copy all selects the whole list");
  }
});

test("without the Selection API a copy still fails quietly", async () => {
  installFakeDom({ clipboard: undefined });
  const [button] = elements(techDetails(makeT("zh"), [["轮次 id", "round_1"]]), "button");
  await click(button);
  assert.equal(button.textContent, "复制失败，请手动选择");
});

// --- final review: the error fold says what each fact is (F9) ------------------------------------
test("an error made by the console has no HTTP status 0 and its text is not called the server's", () => {
  const zh = makeT("zh");
  assert.deepEqual(errorDetail(new ApiError(0, "network", "Failed to fetch"), zh), [["代码", "network"], ["错误信息", "Failed to fetch"]]);
  assert.deepEqual(errorDetail(new ApiError(0, "not_approved", "你审阅期间运行单变了"), zh), [["代码", "not_approved"], ["错误信息", "你审阅期间运行单变了"]]);
  assert.deepEqual(errorDetail(new ApiError(502, "server_error", "HTTP 502: not JSON"), zh), [["HTTP 状态", 502], ["代码", "server_error"], ["错误信息", "HTTP 502: not JSON"]]);
  assert.deepEqual(errorDetail(new ApiError(503, "server_error", "HTTP 503"), zh), [["HTTP 状态", 503], ["代码", "server_error"], ["错误信息", "HTTP 503"]]);
  assert.deepEqual(errorDetail(new ApiError(409, "state", "HTTP is not ready"), zh), [["HTTP 状态", 409], ["代码", "state"], ["服务器原文", "HTTP is not ready"]]);
});
