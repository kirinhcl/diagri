import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import en from "../../src/growbridge/web/workbench/i18n/en.js";
import zh from "../../src/growbridge/web/workbench/i18n/zh.js";
import { makeT } from "../../src/growbridge/web/workbench/i18n.js";
import { formatterFor, messageParts, messageView } from "../../src/growbridge/web/workbench/messages.js";
import { testCtx } from "./support/render-page.mjs";

const CODES = JSON.parse(readFileSync(new URL("./fixtures/message-codes.json", import.meta.url), "utf8"));
const FAMILIES = ["alert", "finding", "receipt", "task_end", "compute_error", "compute_stuck", "chat_end", "estimate", "denial"];
const SAMPLE = "{sensor} {op} {value} for {duration_seconds}, {level}";
const PLACEHOLDER = /\{(\w+)\}/g;
const names = (text) => [...text.matchAll(PLACEHOLDER)].map((m) => m[1]);

// A ctx whose t answers the extra test key without touching the real catalogs.
function ctxWithSample(lang, options) {
  const ctx = testCtx({ lang, ...options });
  const base = makeT(lang);
  const t = (key, vars) => (key === "msg.test.sample" ? SAMPLE : base(key, vars));
  return { ...ctx, t };
}

test("the code file names exactly the 9 families", () => {
  assert.deepEqual(Object.keys(CODES).sort(), [...FAMILIES].sort());
});

test("every code the server can send has a text in both languages, and an action exactly when it declares one", () => {
  for (const [family, codes] of Object.entries(CODES)) {
    for (const [code, spec] of Object.entries(codes)) {
      for (const [lang, table] of [["en", en], ["zh", zh]]) {
        const key = `msg.${family}.${code}`;
        assert.equal(typeof table[key], "string", `${lang} ${key}`);
        assert.equal(`${key}.action` in table, spec.action, `${lang} ${key}.action`);
      }
    }
  }
});

test("a text names only params its code declares and the console can format", () => {
  for (const [family, codes] of Object.entries(CODES)) {
    for (const [code, spec] of Object.entries(codes)) {
      for (const table of [en, zh]) {
        const texts = [table[`msg.${family}.${code}`], table[`msg.${family}.${code}.action`]].filter(Boolean);
        for (const name of texts.flatMap(names)) {
          assert.ok(spec.params.includes(name), `${family}.${code} {${name}} not declared`);
          assert.notEqual(formatterFor(name), null, `${family}.${code} {${name}} has no formatter`);
          assert.ok(!/_ids?$/.test(name), `${family}.${code} {${name}} is an id`);
        }
      }
    }
  }
});

test("every message text in the catalogs belongs to a registered code", () => {
  for (const table of [en, zh]) {
    for (const key of Object.keys(table).filter((k) => k.startsWith("msg."))) {
      const base = key.replace(/\.action$/, "");
      const family = Object.keys(CODES).find((f) => base.startsWith(`msg.${f}.`));
      assert.ok(family, key);
      assert.ok(base.slice(`msg.${family}.`.length) in CODES[family], key);
    }
  }
});

test("durations, sensors, levels, operators and times are written for people", () => {
  const params = { sensor: "temp", op: ">", value: 30, duration_seconds: 300, channel: "fan", level: 3 };
  const en1 = messageParts(ctxWithSample("en"), "test", "sample", params);
  assert.match(en1.text, /^Air temperature above 30\.0 °C for 5 min/);
  assert.match(en1.text, /, 3 \/ 10$/);
  const zh1 = messageParts(ctxWithSample("zh"), "test", "sample", params);
  assert.match(zh1.text, /^空气温度 高于 30\.0 °C /);
  assert.match(zh1.text, / 3 \/ 10$/);
});

test("a missing or malformed param shows a dash, never a brace", () => {
  const bad = messageParts(ctxWithSample("en"), "test", "sample", { sensor: "temp", op: ">", value: null, duration_seconds: "x" });
  assert.match(bad.text, /^Air temperature above — for —, —$/);
  assert.ok(!bad.text.includes("{"));
  assert.ok(!messageParts(ctxWithSample("zh"), "test", "sample", undefined).text.includes("{"));
});

test("an unknown code says unknown and keeps code and params in the details", () => {
  const ctx = testCtx({ lang: "en" });
  const parts = messageParts(ctx, "alert", "no.such", { a: 1 });
  assert.equal(parts.known, false);
  assert.equal(parts.text, ctx.t("common.unknown"));
  assert.equal(parts.action, null);
  assert.deepEqual(parts.details[0], [ctx.t("tech.code"), "no.such"]);
  assert.deepEqual(parts.details.at(-1), [ctx.t("tech.params"), { a: 1 }]);
});

test("ids go to the details, never into the text", () => {
  const ctx = ctxWithSample("en");
  const parts = messageParts(ctx, "test", "sample", { stage_id: "s:1", task_ids: ["a", "b"] });
  assert.ok(!parts.text.includes("s:1"));
  const labels = parts.details.map(([label]) => label);
  assert.ok(labels.includes("stage_id") && labels.includes("task_ids"));
});

test("a treatment finding names the treatments and keeps their ids in the details", () => {
  const ctx = testCtx({ lang: "en" });
  const params = { round: 1, treatment: "light 70 %", treatment_id: "t-high-7", treatments: ["light 40 %"], treatment_ids: ["t-ctl-9"], control: "light 40 %", control_id: "t-ctl-9" };
  for (const code of ["treatment_not_applied", "treatment_not_applied.none", "no_replication", "missing_control.unallocated"]) {
    const parts = messageParts(ctx, "finding", code, params);
    assert.match(parts.text, /“light [47]0 %”/, code);
    assert.ok(!/t-high-7|t-ctl-9/.test(parts.text), `${code}: ${parts.text}`);
    const labels = parts.details.map(([label]) => label);
    assert.ok(["treatment_id", "treatment_ids", "control_id"].every((name) => labels.includes(name)), labels.join());
  }
});

test("a time param is a date and time in the site's zone", () => {
  const epoch = Date.UTC(2026, 5, 1, 10, 0) / 1000;
  const format = formatterFor("due_at");
  const helsinki = testCtx({ lang: "en", timezone: "Europe/Helsinki", now: epoch });
  const utc = testCtx({ lang: "en", timezone: "UTC", now: epoch });
  assert.match(format(helsinki, epoch, {}), /13:00$/);
  assert.match(format(utc, epoch, {}), /10:00$/);
  assert.equal(format(utc, "x", {}), "—");
});

// Params shown as a label the console writes title-cased ("Air temperature", "Light", "Measurement",
// "Planner", "Paused", "Result unknown") or as a whole sentence (a history event).
const TITLE_CASED = ["sensor", "channel", "state", "task_kind", "role", "action_state", "source_kind", "event"];

test("an English text puts a title-cased label first or after a colon, never mid-sentence", () => {
  const mid = [];
  for (const [key, text] of Object.entries(en).filter(([k]) => k.startsWith("msg."))) {
    for (const match of text.matchAll(PLACEHOLDER)) {
      const before = text.slice(0, match.index);
      if (TITLE_CASED.includes(match[1]) && before !== "" && !/[:.] $/.test(before)) mid.push(`${key}: ${text}`);
    }
  }
  assert.deepEqual(mid, []);
});

test("a treatment problem whose level or other level is not a number shows a dash", () => {
  const ctx = testCtx({ lang: "en" });
  const problems = (list) => formatterFor("problems")(ctx, list, {});
  const good = problems([{ kind: "other_levels", channel: "fan", level: 3, other: 5 }]);
  assert.match(good, /5 \/ 10$/);
  const pump = problems([{ kind: "no_action", channel: "pump", level: "0", other: null }]);
  assert.match(pump, / —$/);
  assert.doesNotMatch(pump, /\b(on|off)\b/);
  const fan = problems([{ kind: "no_action", channel: "fan", level: "3", other: null }]);
  assert.match(fan, / —$/);
  assert.doesNotMatch(fan, /\/ 10/);
  const other = problems([{ kind: "other_levels", channel: "fan", level: 3, other: "5" }]);
  assert.match(other, / —$/);
  assert.doesNotMatch(other, /\/ 10/);
});

test("too many output files reads as two counts, never as dashes", () => {
  for (const lang of ["en", "zh"]) {
    const parts = messageParts(testCtx({ lang }), "compute_error", "too_many_files", { file_count: 1001, limit_count: 1000 });
    assert.equal(parts.known, true, lang);
    assert.ok(parts.text.includes("1,001") && parts.text.includes("1,000"), parts.text);
    assert.ok(!parts.text.includes("—") && !parts.text.includes("{"), parts.text);
    assert.ok(parts.action, lang);
  }
});

test("formatterFor follows the contract table, and everything else is not a placeholder", () => {
  const ctx = testCtx({ lang: "en" });
  const f = (name, v, p = {}) => formatterFor(name)(ctx, v, p);
  assert.equal(f("count", 3), "3");
  assert.equal(f("file_count", 1001), "1,001");
  assert.equal(f("limit_count", 1000), "1,000");
  assert.equal(f("fraction", 0.256), "26%");
  assert.equal(f("name", "A"), "“A”");
  assert.equal(f("channels", ["fan", "light"]), `${f("channel", "fan")}, ${f("channel", "light")}`);
  assert.equal(f("limit", 1024), "1,024 bytes");
  assert.equal(f("rule_unit", "C"), "°C");
  assert.equal(f("at_local", "08:30"), "08:30");
  assert.equal(f("value", 400, { sensor: "co2" }), "400 ppm");
  assert.equal(f("value", 4, {}), "4");
  assert.equal(f("min", 2, { channel: "fan" }), "2 / 10");
  assert.equal(f("treatments", ["a", "b"]), "“a”, “b”");
  assert.equal(f("failures", "x"), "—");
  for (const name of ["stage_id", "task_ids", "summary", "evidence", "detail", "timezone", "denied_code", "stop_reason", "error_code", "error_params", "whatever"]) {
    assert.equal(formatterFor(name), null, name);
  }
});

test("messageView gives the text, then the details fold", () => {
  const nodes = messageView(ctxWithSample("en"), "test", "sample", { stage_id: "s1" }, { extra: [["Extra", "x"]] });
  assert.equal(nodes[0].className ?? nodes[0].getAttribute?.("class"), "message-text");
  assert.equal(nodes.length, 2);
  assert.match(nodes[1].className ?? nodes[1].getAttribute?.("class"), /tech-details/);
});
