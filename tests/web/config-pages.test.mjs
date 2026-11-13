import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { ApiError } from "../../src/growbridge/web/workbench/api.js";
import { isNotMounted } from "../../src/growbridge/web/workbench/pages/not-mounted.js";
import { diffLines, formatValue, visibleChanges } from "../../src/growbridge/web/workbench/pages/safety-diff.js";
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

test("isNotMounted is true only for a plain 404 without a refusal code", () => {
  assert.equal(isNotMounted(new ApiError(404, null, "HTTP 404")), true);
  assert.equal(isNotMounted(new ApiError(404, "state", "unknown")), false);
  assert.equal(isNotMounted(new ApiError(403, null, "HTTP 403")), false);
  assert.equal(isNotMounted(new Error("x")), false);
});
