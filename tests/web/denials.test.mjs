import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DENIALS, describeDenial } from "../../src/growbridge/web/workbench/denials.js";
import { ApiError } from "../../src/growbridge/web/workbench/api.js";
import { makeT } from "../../src/growbridge/web/workbench/i18n.js";
import { messageParts, formatterFor } from "../../src/growbridge/web/workbench/messages.js";
import { errorDetail, errorLines, simpleForm } from "../../src/growbridge/web/workbench/ui/forms.js";
import { findLeaks, visibleTextIncludingDetails } from "./support/leaks.mjs";
import { installFakeDom, testCtx } from "./support/render-page.mjs";

// Codes the console makes itself: a 422 body, no answer, an unreadable answer, a wrong secret.
const CLIENT_CODES = ["validation", "network", "server_error", "reauth_failed"];

function wikiCodes() {
  const src = readFileSync(new URL("../../docs/wiki/en/Denial-Codes-and-Events.md", import.meta.url), "utf8");
  const section = src.split(/^## Denial codes\s*$/m)[1].split(/^## /m)[0];
  return [...section.matchAll(/^\| `([a-z_]+)` \|/gm)].map((m) => m[1]);
}

test("every wiki denial code is described in both languages", () => {
  const codes = wikiCodes();
  assert.equal(codes.length, 38);
  for (const code of [...codes, ...CLIENT_CODES]) {
    for (const lang of ["zh", "en"]) {
      const d = describeDenial(code, lang);
      assert.ok(d, `${code}/${lang}`);
      assert.ok(d.text.trim() && d.advice.trim(), `${code}/${lang}`);
    }
  }
  assert.deepEqual(Object.keys(DENIALS).sort(), [...codes, ...CLIENT_CODES].sort());
});

test("a server error does not claim the server was unreachable, and says the action may have run", () => {
  assert.notEqual(describeDenial("server_error", "en").text, describeDenial("network", "en").text);
  assert.match(describeDenial("server_error", "en").text, /may or may not have been carried out/);
  assert.match(describeDenial("server_error", "zh").text, /可能已经执行，也可能没有/);
});

test("an unknown code is null", () => {
  assert.equal(describeDenial("nope", "en"), null);
  assert.equal(describeDenial(null, "zh"), null);
});

test("the re-authentication and lock-out denials say password, and a lock-out says how long", () => {
  for (const code of ["reauth_required", "reauth_failed", "locked"]) {
    const zh = describeDenial(code, "zh");
    const en = describeDenial(code, "en");
    assert.doesNotMatch(`${zh.text}${zh.advice}`, /口令/, code);
    assert.doesNotMatch(`${en.text}${en.advice}`, /secret/i, code);
  }
  assert.match(describeDenial("locked", "zh").text, /已锁定 15 分钟/);
  assert.match(describeDenial("locked", "en").text, /locked for 15 minutes/);
});

test("the sign-in, re-authentication and lock-out reasons shown on screen say password, and a lock-out says how long", () => {
  const REASONS = ["not_signed_in", "bad_credentials", "session_expired", "login_locked", "reauth_required"];
  for (const lang of ["zh", "en"]) {
    const c = testCtx({ lang });
    const wording = lang === "zh" ? /密码/ : /password/i;
    const old = lang === "zh" ? /口令|密钥/ : /secret/i;
    for (const reason of REASONS) {
      const parts = messageParts(c, "denial", reason, { window_seconds: 900 });
      const said = `${parts.text} ${parts.action}`;
      assert.doesNotMatch(said, old, `${lang} ${reason}`);
      if (["not_signed_in", "bad_credentials", "reauth_required"].includes(reason)) assert.match(said, wording, `${lang} ${reason}`);
    }
    const locked = messageParts(c, "denial", "login_locked", { window_seconds: 900 });
    assert.match(locked.action, lang === "zh" ? /15 分钟/ : /15 min/);
  }
});

const CODES = JSON.parse(readFileSync(new URL("./fixtures/message-codes.json", import.meta.url), "utf8"));
const DEMO = {
  "msg.denial.demo_paused": "阶段现在是{state}，不能再暂停。",
  "msg.denial.demo_paused.action": "只有运行中的阶段能暂停。",
};
const base = makeT("zh");
const t = (key, vars) => (key in DEMO ? DEMO[key].replace(/\{(\w+)\}/g, (_, n) => vars?.[n] ?? `{${n}}`) : base(key, vars));
const ctx = { t, lang: "zh", me: { timezone: "UTC" }, notify: () => {}, reload: () => {} };
const settle = () => new Promise((resolve) => setImmediate(resolve));

test("a refusal with a known reason reads as its text and next step, with its params filled", () => {
  const error = new ApiError(409, "state", "stage s1 is paused; it cannot pause", [], { reason: "demo_paused", params: { state: "paused", stage_id: "s1" } });
  assert.deepEqual(errorLines(error, "zh", t, ctx), [`阶段现在是${t("state.paused")}，不能再暂停。`, "只有运行中的阶段能暂停。"]);
});

test("a refusal without a reason, or with a reason the catalog lacks, falls back to the code's text", () => {
  for (const reason of [null, "not_in_catalog"]) {
    const lines = errorLines(new ApiError(409, "state", "m", [], { reason }), "zh", t, ctx);
    assert.deepEqual(lines, [DENIALS.state.zh.text, DENIALS.state.zh.advice]);
  }
});

test("a known reason with no action text is one line", () => {
  const only = { ...ctx, t: (key, vars) => (key === "msg.denial.demo_only" ? "只有正文。" : base(key, vars)) };
  const error = new ApiError(409, "state", "m", [], { reason: "demo_only" });
  assert.deepEqual(errorLines(error, "zh", only.t, only), ["只有正文。"]);
});

test("a refusal's reason and params are in the technical details, beside the server's words", () => {
  const error = new ApiError(409, "state", "m", [], { reason: "demo_paused", params: { state: "paused" } });
  assert.deepEqual(errorDetail(error, t), [
    ["HTTP 状态", 409], ["代码", "state"], ["原因代码", "demo_paused"], ["参数", { state: "paused" }], ["服务器原文", "m"],
  ].map(([label, value]) => [label === "HTTP 状态" ? t("tech.httpStatus") : label, value]));
  const bare = errorDetail(new ApiError(409, "state", "m"), t).map(([label]) => label);
  assert.ok(!bare.includes(t("tech.reason")) && !bare.includes(t("tech.params")));
});

test("a refused form still reloads the page on a state refusal, and says the reason's text", async () => {
  installFakeDom();
  const notices = [];
  let reloads = 0;
  const own = { ...ctx, notify: (text) => notices.push(text), reload: () => { reloads += 1; } };
  const onSubmit = async () => {
    throw new ApiError(409, "state", "m", [], { reason: "demo_paused", params: { state: "paused" } });
  };
  const form = simpleForm({ fields: [{ name: "reason", label: "原因" }], submitLabel: "暂停", onSubmit, ctx: own });
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  await settle();
  assert.equal(reloads, 1);
  assert.match(visibleTextIncludingDetails(form), /阶段现在是/);
  assert.ok(notices.some((n) => n.includes("阶段现在是")));
});

const SAMPLES = [
  [/_seconds$|^seconds$/, 600], [/_at$/, 1794821400], [/_count$|^count$/, 3], [/^(state|phase|needed_state)$/, "running"],
  [/^(names|choices|sensors|failures|channels)$/, ["a"]], [/^(minimum|maximum|bound)$/, 0.25], [/_amount$/, 2.5],
];
function sampleFor(name, spec) {
  const hit = SAMPLES.find(([pattern]) => pattern.test(name));
  if (hit) return hit[1];
  return { resource: "cpu_hours", record_kind: "stage", expected_kind: "int", status: "open", from_status: "open", to_status: "open" }[name] ?? 3;
}

test("every registered reason, filled with sample params, shows no code, id, hash or epoch outside the details", () => {
  for (const lang of ["zh", "en"]) {
    const c = testCtx({ lang });
    for (const [reason, spec] of Object.entries(CODES.denial)) {
      const params = Object.fromEntries(spec.params.map((name) => [name, sampleFor(name, spec)]));
      const parts = messageParts(c, "denial", reason, params);
      for (const text of [parts.text, parts.action].filter(Boolean)) assert.deepEqual(findLeaks(text), [], `${lang} ${reason}: ${text}`);
    }
  }
});

test("the 2b param names format as the contract says", () => {
  const c = testCtx({ lang: "zh", timezone: "UTC" });
  const show = (name, value, params = {}) => formatterFor(name)(c, value, params);
  assert.equal(show("phase", "running"), c.t("state.running"));
  assert.equal(show("needed_state", "paused"), c.t("state.paused"));
  assert.equal(show("from_status", "open"), c.t("tasks.status.open"));
  assert.equal(show("record_kind", "stage"), c.t("recordKind.stage"));
  assert.notEqual(show("record_kind", "stage"), c.t("common.unknown"));
  assert.equal(show("max_retries", 3), "3");
  assert.equal(show("minimum", 0.25), "0.25");
  assert.equal(show("minimum", 4), "4");
  assert.equal(show("field", "temp"), "「temp」");
  assert.equal(show("names", ["a", "b"]), "「a」、「b」");
  assert.equal(show("sensors", ["temp", "co2"]), `${c.t("metric.temp")}、${c.t("metric.co2")}`);
  assert.equal(show("need_amount", 2.5, { resource: "cpu_hours" }), `2.50 ${c.t("computeUnit.cpu_hours")}`);
  assert.equal(show("expected_kind", "int"), c.t("paramKind.int"));
  assert.equal(show("record_kind", null), "—");
  for (const name of ["x_digest", "diffs", "paths", "choice", "detail", "error"]) assert.equal(formatterFor(name), null);
});

// The run-sheet form has no version box: it raises the version itself, so the advice cannot be to raise it.
test("a run-sheet version conflict says to reload the page and make the change again", () => {
  const advice = (lang) => messageParts(testCtx({ lang }), "denial", "run_sheet_version_conflict", { run_sheet_id: "sheet-1", version: 3 }).action;
  assert.match(advice("en"), /reload the page/i);
  assert.match(advice("en"), /change again/i);
  assert.doesNotMatch(advice("en"), /^raise/i);
  assert.match(advice("zh"), /刷新页面/);
  assert.match(advice("zh"), /重新/);
  assert.doesNotMatch(advice("zh"), /^请把版本号提高/);
});

test("the budget advice speaks to the reader, not about an operator", () => {
  assert.doesNotMatch(DENIALS.budget.zh.advice, /操作员/);
  assert.doesNotMatch(DENIALS.budget.en.advice, /an operator/i);
});
