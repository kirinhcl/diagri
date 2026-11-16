// Safety limits written as words: a rule as one sentence, a change by rule name and unit. Pure: no DOM.
import { formatDuration, levelText } from "../format.js";
import { labelOr } from "../i18n.js";

const UNIT_NAMES = { C: "°C" };
const SECONDS_PER_MINUTE = 60;
const RULE_PATH = /^rules\.(\d+)\.(.+)$/;
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

// One value of a rule field as words; `rule` is the rule as it stood on the side being shown.
function ruleValue(t, field, value, rule) {
  if (isMissing(value)) return t("safety.absent");
  if (field === "trigger.value") return withUnit(value, rule?.unit);
  if (field === "trigger.op") return labelOr(t, "safety.op", value);
  if (field === "sensor") return labelOr(t, "metric", value);
  if (field === "action.channel") return labelOr(t, "channel", value);
  if (field === "action.level") return levelText(t, rule?.action?.channel, value);
  if (field === "unit") return unitText(value);
  if (field.endsWith("_seconds")) return formatDuration(t, value);
  return typeof value === "string" ? value : JSON.stringify(value);
}

function ruleLine(change, t, { before, after }) {
  const match = RULE_PATH.exec(change.path);
  if (!match) return null;
  const [, index, field] = match;
  const labelKey = `safety.field.${field}`;
  const label = t(labelKey);
  const was = before?.rules?.[index];
  const now = after?.rules?.[index];
  if (label === labelKey || !(was || now)) return null; // an unknown field is listed by its path
  return t("safety.diff.rule", {
    id: (now || was).id ?? "—",
    field: label,
    before: ruleValue(t, field, change.before, was || now),
    after: ruleValue(t, field, change.after, now || was),
  });
}

function frozenChange(change, t) {
  const minutes = FROZEN_PATH.exec(change.path);
  const seconds = (value) => (isMissing(value) ? t("safety.absent") : formatDuration(t, value * SECONDS_PER_MINUTE));
  if (minutes) {
    return t("safety.diff.frozen", {
      sensor: labelOr(t, "metric", minutes[1]),
      before: seconds(change.before),
      after: seconds(change.after),
    });
  }
  if (change.path !== "frozen.max_gap_seconds") return null;
  const gap = (value) => (isMissing(value) ? t("safety.absent") : formatDuration(t, value));
  return t("safety.diff.gap", { before: gap(change.before), after: gap(change.after) });
}

export function describeChange(change, t, sides, formatValue) {
  const line = ruleLine(change, t, sides || {}) || frozenChange(change, t);
  return line || `${change.path}: ${formatValue(change.before, t)} → ${formatValue(change.after, t)}`;
}
