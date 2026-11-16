// The technical-details fold (ids, hashes and raw values, each copyable) and errors that keep only the
// plain lines in view, with the server's own text folded underneath.
import assert from "node:assert/strict";
import test from "node:test";

import { ApiError } from "../../src/growbridge/web/workbench/api.js";
import { describeDenial } from "../../src/growbridge/web/workbench/denials.js";
import { makeT } from "../../src/growbridge/web/workbench/i18n.js";
import { errorDetail, errorLines, simpleForm } from "../../src/growbridge/web/workbench/ui/forms.js";
import { copyText, errorBox, showErrors, techDetails } from "../../src/growbridge/web/workbench/ui/section.js";
import { countButtons, visibleText, visibleTextIncludingDetails } from "./support/leaks.mjs";
import { FIXTURES, installFakeDom, renderPage } from "./support/render-page.mjs";

const RAW = "stage st_91c2 is recovery_check; it cannot pause";

// Every pending promise job, then one turn of the event loop.
const settle = () => new Promise((resolve) => setImmediate(resolve));

function elements(node, name) {
  const own = node.localName === name ? [node] : [];
  return [...own, ...(node.children || []).flatMap((child) => elements(child, name))];
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
  assert.deepEqual(errorDetail(new ApiError(404, null, "HTTP 404"), zh), [["HTTP 状态", 404], ["服务器原文", "HTTP 404"]]);
  assert.deepEqual(errorDetail(new ApiError(422, "validation", "validation"), zh), [["HTTP 状态", 422], ["代码", "validation"]]);
  const network = errorDetail(new ApiError(0, "network", "Failed to fetch"), zh); // no answer: the browser's words
  assert.deepEqual(network, [["HTTP 状态", 0], ["代码", "network"], ["错误信息", "Failed to fetch"]]);
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
