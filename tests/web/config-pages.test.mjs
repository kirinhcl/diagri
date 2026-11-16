import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { configDiff } from "../../src/growbridge/web/workbench/diff.js";
import { ApiError } from "../../src/growbridge/web/workbench/api.js";
import { isNotMounted } from "../../src/growbridge/web/workbench/pages/not-mounted.js";
import { baselineChanged, diffLines, formatValue, visibleChanges } from "../../src/growbridge/web/workbench/pages/safety-diff.js";
import { ruleSentence } from "../../src/growbridge/web/workbench/pages/safety.js";
import { makeT } from "../../src/growbridge/web/workbench/i18n.js";
import { safetySkeleton } from "../../src/growbridge/web/workbench/pages/safety-skeleton.js";

const MODELS = new URL("../../src/growbridge/archive/models.py", import.meta.url);

// Field names of a pydantic class: the annotated lines at class-body depth.
function fieldsOf(className) {
  const lines = readFileSync(MODELS, "utf8").split("\n");
  const start = lines.findIndex((line) => line.startsWith(`class ${className}(`));
  assert.ok(start >= 0, `class ${className} not found`);
  const names = [];
  for (const line of lines.slice(start + 1)) {
    if (line !== "" && !line.startsWith(" ")) break; // the next top-level statement
    const match = /^ {4}(\w+):\s/.exec(line);
    if (match) names.push(match[1]);
  }
  return names;
}

const sorted = (keys) => [...keys].sort();

test("the safety skeleton has exactly the fields of SafetyConfig and what it nests", () => {
  const skeleton = safetySkeleton();
  assert.deepEqual(sorted(Object.keys(skeleton)), sorted(fieldsOf("SafetyConfig")));
  assert.ok(Array.isArray(skeleton.rules) && skeleton.rules.length === 1);
  const [rule] = skeleton.rules;
  assert.deepEqual(sorted(Object.keys(rule)), sorted(fieldsOf("ProtectionRule")));
  assert.deepEqual(sorted(Object.keys(rule.trigger)), sorted(fieldsOf("Condition")));
  assert.deepEqual(sorted(Object.keys(rule.action)), sorted(fieldsOf("RuleAction")));
  assert.deepEqual(sorted(Object.keys(skeleton.frozen)), sorted(fieldsOf("FrozenCheck")));
});

test("every value of the skeleton is null, so submitting it unchanged cannot be approved", () => {
  const leaves = [];
  const walk = (value) => {
    if (Array.isArray(value)) value.forEach(walk);
    else if (value !== null && typeof value === "object") Object.values(value).forEach(walk);
    else leaves.push(value);
  };
  walk(safetySkeleton());
  assert.ok(leaves.length >= 10);
  assert.ok(leaves.every((leaf) => leaf === null));
});

test("each call returns a fresh skeleton", () => {
  const first = safetySkeleton();
  first.rules[0].id = "changed";
  assert.equal(safetySkeleton().rules[0].id, null);
});

const t = (key) => (key === "safety.absent" ? "(none)" : key);

test("formatValue shows JSON for values and a placeholder for an absent one", () => {
  assert.equal(formatValue(5, t), "5");
  assert.equal(formatValue("a", t), '"a"');
  assert.equal(formatValue(null, t), "null");
  assert.equal(formatValue(undefined, t), "(none)");
  assert.equal(formatValue({ a: 1 }, t), '{"a":1}');
});

test("diffLines writes one line per change as path: old → new", () => {
  const changes = [
    { path: "rules[0].trigger.value", before: 30, after: 35 },
    { path: "rules[1]", before: undefined, after: { id: "x" } },
  ];
  assert.deepEqual(diffLines(changes, t), ["rules[0].trigger.value: 30 → 35", 'rules[1]: (none) → {"id":"x"}']);
});

test("visibleChanges leaves out the fields the server stamps itself", () => {
  const changes = [
    { path: "approved_by", before: "a", after: "b" },
    { path: "approved_at", before: 1, after: 2 },
    { path: "version", before: 1, after: 2 },
  ];
  assert.deepEqual(visibleChanges(changes), [{ path: "version", before: 1, after: 2 }]);
});

test("baselineChanged: same version and time is unchanged", () => {
  const a = { version: 1, approved_at: 10, rules: [] };
  assert.equal(baselineChanged(a, { ...a }), false);
  assert.equal(baselineChanged(null, null), false);
});

test("baselineChanged: a different version or approval time is a change", () => {
  const a = { version: 1, approved_at: 10 };
  assert.equal(baselineChanged(a, { version: 2, approved_at: 10 }), true);
  assert.equal(baselineChanged(a, { version: 1, approved_at: 11 }), true);
});

test("baselineChanged: none to some and some to none are changes", () => {
  assert.equal(baselineChanged(null, { version: 1, approved_at: 1 }), true);
  assert.equal(baselineChanged({ version: 1, approved_at: 1 }, null), true);
});

test("baselineChanged compares the whole config when version and time are absent", () => {
  assert.equal(baselineChanged({ rules: [1] }, { rules: [1] }), false);
  assert.equal(baselineChanged({ rules: [1] }, { rules: [2] }), true);
});

test("isNotMounted is true only for a plain 404 without a refusal code", () => {
  assert.equal(isNotMounted(new ApiError(404, null, "HTTP 404")), true);
  assert.equal(isNotMounted(new ApiError(404, "state", "unknown")), false);
  assert.equal(isNotMounted(new ApiError(403, null, "HTTP 403")), false);
  assert.equal(isNotMounted(new Error("x")), false);
});

const HEAT = { id: "heat-cut", sensor: "temp", unit: "°C", trigger: { op: ">", value: 30 }, duration_seconds: 300, validity_seconds: 600, action: { channel: "fan", level: 0 } };

test("a rule reads as one sentence", () => {
  const s = ruleSentence(makeT("zh"), HEAT);
  assert.match(s, /高于 30 °C 持续 5 分钟/);
  assert.match(s, /10 分钟/);
  assert.doesNotMatch(s, /heat-cut|gt|300|600|>/);
});

test("a rule unit C is shown as °C and the English sentence reads too", () => {
  assert.match(ruleSentence(makeT("zh"), { ...HEAT, unit: "C" }), /30 °C/);
  const en = ruleSentence(makeT("en"), HEAT);
  assert.match(en, /above 30 °C for 5 min/);
  assert.doesNotMatch(en, /heat-cut|300|600/);
});

const zh = makeT("zh");
const COLD = { ...HEAT, id: "cold-cut", sensor: "humi", unit: "%" };
const lines = (before, after, t = zh) => diffLines(visibleChanges(configDiff(before, after)), t, { before, after });
const withRule = (patch) => ({ ...HEAT, ...patch });

test("the approval dialog describes changes by rule and unit", () => {
  const out = lines({ rules: [HEAT] }, { rules: [withRule({ trigger: { op: ">", value: 35 } })] });
  assert.deepEqual(out, ["规则 heat-cut：触发值 30 °C → 35 °C"]);
});

test("dialog lines write durations, levels, frozen limits and gaps as words", () => {
  const before = { rules: [HEAT], frozen: { minutes: { temp: 120 }, max_gap_seconds: 600 } };
  const after = { rules: [withRule({ duration_seconds: 600, action: { channel: "fan", level: 3 } })], frozen: { minutes: { temp: 60 }, max_gap_seconds: 660 } };
  assert.deepEqual(lines(before, after), [
    "规则 heat-cut：持续时间 5 分钟 → 10 分钟",
    "规则 heat-cut：动作档位 0 / 10 → 3 / 10",
    "空气温度 冻结判定：2 小时 → 60 分钟",
    "最长空档：10 分钟 → 11 分钟",
  ]);
});

test("a rounded duration carries its exact seconds; a hidden change falls back to the raw line", () => {
  const gap = (a, b) => lines({ frozen: { max_gap_seconds: a } }, { frozen: { max_gap_seconds: b } });
  assert.deepEqual(gap(600, 620), ["最长空档：10 分钟 → 10 分钟（620 秒）"]);
  assert.deepEqual(gap(600, 930), ["最长空档：10 分钟 → 16 分钟（930 秒）"]);
  assert.deepEqual(gap(600, 600.4), ["最长空档：10 分钟 → 10 分钟（600.4 秒）"]);
  assert.deepEqual(gap(600, "600"), ['frozen.max_gap_seconds: 600 → "600"']);
  assert.deepEqual(gap(600, -5), ["frozen.max_gap_seconds: 600 → -5"]);
  const frozen = lines({ frozen: { minutes: { temp: 120 } } }, { frozen: { minutes: { temp: 120.4 } } });
  assert.match(frozen[0], /2 小时（7224 秒）/);
  assert.deepEqual(lines({ rules: [HEAT] }, { rules: [withRule({ duration_seconds: 300.2 })] }).length, 1);
});

test("deleting or reordering rules never names the wrong rule", () => {
  const deleted = lines({ rules: [HEAT, COLD] }, { rules: [COLD] });
  assert.ok(deleted.length >= 1);
  assert.ok(deleted.every((line) => !line.startsWith("规则 ")));
  const reordered = lines({ rules: [HEAT, COLD] }, { rules: [COLD, HEAT] });
  assert.ok(reordered.length >= 1);
  assert.ok(reordered.every((line) => !line.startsWith("规则 ")));
  assert.equal(new Set(reordered).size, reordered.length);
});

test("an unknown code is listed raw, and so is every path without the rules", () => {
  assert.match(lines({ rules: [HEAT] }, { rules: [withRule({ sensor: "mystery" })] })[0], /^rules\[0\]\.sensor: /);
  const changes = visibleChanges(configDiff({ frozen: { max_gap_seconds: 600 } }, { frozen: { max_gap_seconds: 660 } }));
  assert.deepEqual(diffLines(changes, zh), ["frozen.max_gap_seconds: 600 → 660"]);
});

test("an unknown path is still listed", () => {
  const out = lines({ rules: [HEAT], extra: {} }, { rules: [withRule({ mystery: 2 })], extra: { flag: "x" } });
  assert.ok(out.some((line) => line.includes("extra.flag")));
  assert.ok(out.some((line) => line.includes("rules[0].mystery")));
});

test("a duration in the days band shows its exact seconds when hours do not hold it", () => {
  const rule = (n) => lines({ rules: [HEAT] }, { rules: [withRule({ validity_seconds: n })] });
  assert.equal(rule(172800).length, 1);
  const out = lines({ rules: [withRule({ validity_seconds: 172800 })] }, { rules: [withRule({ validity_seconds: 174600 })] });
  assert.equal(out[0], "规则 heat-cut：读数有效期 2 天 → 2 天 1 小时（174600 秒）");
  const gap = lines({ frozen: { max_gap_seconds: 7200 } }, { frozen: { max_gap_seconds: 171000 } });
  assert.equal(gap[0], "最长空档：2 小时 → 2 天（171000 秒）");
});

test("changes that read the same fall back to the raw line", () => {
  const pump = { ...HEAT, action: { channel: "pump", level: 1 } };
  const level = lines({ rules: [pump] }, { rules: [{ ...pump, action: { channel: "pump", level: 2 } }] });
  assert.deepEqual(level, ["rules[0].action.level: 1 → 2"]);
  const unit = lines({ rules: [withRule({ unit: "C" })] }, { rules: [withRule({ unit: "°C" })] });
  assert.deepEqual(unit, ["rules[0].unit: \"C\" → \"°C\""]);
});

// --- final review: a rule's durations say the exact seconds when the words round them (F5, R18) ---
test("a rule's duration and validity say the exact seconds when the words round them", () => {
  const s = ruleSentence(makeT("zh"), { ...HEAT, duration_seconds: 150, validity_seconds: 630 });
  assert.match(s, /持续 3 分钟（150 秒）/);
  assert.match(s, /11 分钟（630 秒）/);
  const en = ruleSentence(makeT("en"), { ...HEAT, duration_seconds: 150, validity_seconds: 630 });
  assert.match(en, /for 3 min \(150 s\)/);
  assert.match(en, /11 min \(630 s\)/);
  assert.match(ruleSentence(makeT("zh"), HEAT), /持续 5 分钟[^（]/);
  assert.match(ruleSentence(makeT("zh"), { ...HEAT, duration_seconds: undefined }), /持续 —/);
});

test("the frozen threshold and the longest gap say the exact seconds when the words round them", async () => {
  const { renderPage, FIXTURES } = await import("./support/render-page.mjs");
  const { visibleText } = await import("./support/leaks.mjs");
  const shown = async (seconds) => {
    const base = FIXTURES["safety.json"];
    const safety = { ...base.safety, frozen: { minutes: { temp: seconds / 60 }, max_gap_seconds: seconds } };
    const { element } = await renderPage("safety", {}, { fixtures: { "safety.json": { ...base, safety } } });
    const text = visibleText(element);
    return { exact: text.match(new RegExp(`${seconds} 秒`, "g")) || [] };
  };
  const rounded = await shown(150);
  assert.equal(rounded.exact.length, 2, "the threshold line and the longest gap both carry the seconds");
  const whole = await shown(120);
  assert.equal(whole.exact.length, 0);
});
