// Safety limits written as words: a rule as one sentence, a change by rule name and unit. Pure: no DOM.
import { formatDuration, levelText } from "../format.js";
import { hasLabel, labelOr } from "../i18n.js";

const UNIT_NAMES = { C: "°C" };
const SECONDS_PER_MINUTE = 60;
const DURATION_EXACT_BELOW = 120; // seconds shown as whole seconds
const RULE_PATH = /^rules\[(\d+)\]\.(.+)$/;
const FROZEN_PATH = /^frozen\.minutes\.(.+)$/;

// Rule units are free strings ("C" in the real config); only the Celsius one is spelled with its degree sign.
export function unitText(unit) {
  if (unit === null || unit === undefined) return "";
  return UNIT_NAMES[unit] || String(unit);
}

const withUnit = (value, unit) => [String(value), unitText(unit)].filter(Boolean).join(" ");

export function ruleSentence(t, rule) {
  const action = rule?.action || {};
  return t("safety.ruleLine", {
    sensor: labelOr(t, "metric", rule?.sensor),
    op: labelOr(t, "safety.op", rule?.trigger?.op),
    value: withUnit(rule?.trigger?.value ?? "—", rule?.unit),
    duration: formatDuration(t, rule?.duration_seconds),
    channel: labelOr(t, "channel", action.channel),
    level: levelText(t, action.channel, action.level),
    validity: formatDuration(t, rule?.validity_seconds),
  });
}

export function frozenLine(t, sensor, minutes) {
  return t("safety.frozenLine", {
    sensor: labelOr(t, "metric", sensor),
    duration: formatDuration(t, minutes * SECONDS_PER_MINUTE),
  });
}

const isMissing = (value) => value === undefined || value === null;

// A change that cannot be written exactly is listed by its raw path instead.
class Unsayable extends Error {}
const unsayable = () => {
  throw new Unsayable();
};

// A code must have words in the catalog; the dialog has no technical details to send it to.
function knownLabel(t, prefix, value) {
  return hasLabel(t, prefix, value) ? labelOr(t, prefix, value) : unsayable();
}

// A duration in words; when the words round the value, the exact seconds follow.
function exactDuration(t, seconds) {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) return unsayable();
  const text = formatDuration(t, seconds);
  const whole = Number.isInteger(seconds);
  const exact = whole && (seconds < DURATION_EXACT_BELOW || seconds % SECONDS_PER_MINUTE === 0);
  return exact ? text : t("safety.exactSeconds", { text, n: seconds });
}

// Two renderings of a real change that read the same hide it, so the line is raw instead.
const differing = (from, to) => (from === to ? unsayable() : [from, to]);

const optional = (t, value, say) => (isMissing(value) ? t("safety.absent") : say(value));

// One value of a rule field as words; `rule` is the rule as it stood on the side being shown.
function ruleValue(t, field, value, rule) {
  const says = {
    "trigger.value": (v) => (typeof v === "number" ? withUnit(v, rule?.unit) : unsayable()),
    "trigger.op": (v) => knownLabel(t, "safety.op", v),
    sensor: (v) => knownLabel(t, "metric", v),
    "action.channel": (v) => knownLabel(t, "channel", v),
    "action.level": (v) => (typeof v === "number" ? levelText(t, rule?.action?.channel, v) : unsayable()),
    unit: (v) => unitText(v),
  };
  if (field.endsWith("_seconds")) return optional(t, value, (v) => exactDuration(t, v));
  const say = says[field] || ((v) => (typeof v === "string" ? v : JSON.stringify(v)));
  return optional(t, value, say);
}

function ruleLine(change, t, { before, after }) {
  const match = RULE_PATH.exec(change.path);
  if (!match) return null;
  const [, index, field] = match;
  const labelKey = `safety.field.${field}`;
  const label = t(labelKey);
  const was = before?.rules?.[index];
  const now = after?.rules?.[index];
  if (label === labelKey || !was || !now) return null; // an unknown field is listed by its path
  if (was.id !== now.id) return null; // rules were inserted, deleted or reordered: this index is two different rules
  const [from, to] = differing(ruleValue(t, field, change.before, was), ruleValue(t, field, change.after, now));
  return t("safety.diff.rule", { id: now.id ?? "—", field: label, before: from, after: to });
}

function frozenChange(change, t) {
  const minutes = FROZEN_PATH.exec(change.path);
  if (minutes) {
    const say = (value) => optional(t, value, (v) => exactDuration(t, v * SECONDS_PER_MINUTE));
    const [from, to] = differing(say(change.before), say(change.after));
    return t("safety.diff.frozen", { sensor: knownLabel(t, "metric", minutes[1]), before: from, after: to });
  }
  if (change.path !== "frozen.max_gap_seconds") return null;
  const say = (value) => optional(t, value, (v) => exactDuration(t, v));
  const [from, to] = differing(say(change.before), say(change.after));
  return t("safety.diff.gap", { before: from, after: to });
}

function sentence(change, t, sides) {
  try {
    return ruleLine(change, t, sides) || frozenChange(change, t);
  } catch (error) {
    if (error instanceof Unsayable) return null;
    throw error;
  }
}

// Without `sides` every change is the raw path line. A line whose before and after read the same is raw too.
export function describeChange(change, t, sides, formatValue) {
  const raw = `${change.path}: ${formatValue(change.before, t)} → ${formatValue(change.after, t)}`;
  if (!sides) return raw;
  return sentence(change, t, sides) || raw;
}
