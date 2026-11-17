// The change list shown before safety limits are approved: one line per change, "path: old → new" (rules and frozen limits in words when both sides are given).
import { configDiff } from "../diff.js";
import { describeChange, ruleSentence } from "./safety-text.js";

const SERVER_STAMPED = new Set(["approved_by", "approved_at"]);

// Has the approved set changed since `before` was read? Version and approval time decide; without them the whole config does.
export function baselineChanged(before, after) {
  if (!before || !after) return Boolean(before) !== Boolean(after);
  if (before.version !== undefined || before.approved_at !== undefined) {
    return before.version !== after.version || before.approved_at !== after.approved_at;
  }
  return JSON.stringify(before) !== JSON.stringify(after);
}

export function formatValue(value, t) {
  return value === undefined ? t("safety.absent") : JSON.stringify(value);
}

// Who approved and when are written by the server, so an edit of them changes nothing.
export function visibleChanges(changes) {
  return changes.filter((change) => !SERVER_STAMPED.has(change.path));
}

const isRulePath = (change) => change.path.startsWith("rules[");
const rulesOf = (config) => (Array.isArray(config?.rules) ? config.rules : []);
const uniqueIds = (rules) => rules.every((rule) => typeof rule?.id === "string") && new Set(rules.map((rule) => rule.id)).size === rules.length;

// Rules are matched by name, not by position: a rule added or removed is one sentence, and the
// rules after it are not reported as changed. A rule whose fields changed lists those fields.
function ruleLines(sides, t) {
  const was = rulesOf(sides.before);
  const now = rulesOf(sides.after);
  const lines = now.filter((rule) => !was.some((old) => old.id === rule.id)).map((rule) => t("safety.diff.ruleAdded", { rule: ruleSentence(t, rule) }));
  lines.push(...was.filter((rule) => !now.some((fresh) => fresh.id === rule.id)).map((rule) => t("safety.diff.ruleRemoved", { rule: ruleSentence(t, rule) })));
  const common = (rules, other) => rules.filter((rule) => other.some((x) => x.id === rule.id)).map((rule) => rule.id);
  if (common(was, now).join("\n") !== common(now, was).join("\n")) lines.push(t("safety.diff.order"));
  for (const rule of now) {
    const old = was.find((candidate) => candidate.id === rule.id);
    if (!old) continue;
    const alone = { before: { rules: [old] }, after: { rules: [rule] } };
    for (const change of configDiff(old, rule)) {
      lines.push(describeChange({ ...change, path: `rules[0].${change.path}` }, t, alone, formatValue));
    }
  }
  return lines;
}

const versionLine = (change, t) => {
  const say = (value) => (value === undefined || value === null ? t("safety.absent") : String(value));
  return t("safety.diff.version", { before: say(change.before), after: say(change.after) });
};

// `sides` ({ before, after } configs) lets a rule be named; without it every line is "path: old → new".
export function diffLines(changes, t, sides) {
  if (!sides) return changes.map((change) => describeChange(change, t, sides, formatValue));
  const byName = uniqueIds(rulesOf(sides.before)) && uniqueIds(rulesOf(sides.after));
  const lines = [];
  let ruleDone = false;
  for (const change of changes) {
    if (change.path === "version") lines.push(versionLine(change, t));
    else if (!byName || !isRulePath(change)) lines.push(describeChange(change, t, sides, formatValue));
    else if (!ruleDone) {
      ruleDone = true;
      lines.push(...ruleLines(sides, t));
    }
  }
  return lines;
}
