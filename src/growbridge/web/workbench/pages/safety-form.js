// The safety limits as a form: protection rules as rows, a frozen-reading check per sensor. It never
// invents a safety value: it starts from the latest approved set, or empty, and builds the same
// config the JSON editor would send (the approver, with its confirmation, takes it unchanged).
import { labelOr } from "../i18n.js";
import { h } from "../ui/dom.js";
import { rowGroup } from "../ui/field-forms.js";
import { simpleForm } from "../ui/forms.js";
import { unitText } from "./safety-text.js";

const OPS = [">", ">=", "<", "<="];
const CHANNELS = ["light", "exhaust", "fan"];
// The server's own limits for the frozen-reading check (archive/models.py); rules have none to mirror.
const MAX_FROZEN_MINUTES = 1440;
const MAX_FROZEN_GAP_SECONDS = 3600;

const array = (value) => (Array.isArray(value) ? value : []);
const unique = (values) => [...new Set(values)];

// sensor -> unit for the rule sensors on offer: the device's sensors, and any sensor an approved rule already uses.
function sensorUnits(current, capabilities) {
  const fromRules = Object.fromEntries(array(current?.rules).filter((rule) => rule?.sensor).map((rule) => [rule.sensor, rule.unit]));
  return { ...fromRules, ...(capabilities?.sensors || {}) };
}

const frozenSensors = (current, units) => unique([...Object.keys(units), ...Object.keys(current?.frozen?.minutes || {})]).sort();

// A number above 0 and at most `max`.
const positive = (max) => (text, t) => {
  const number = Number(text);
  if (!Number.isFinite(number) || number <= 0) return { error: t("safety.form.positive") };
  return number > max ? { error: t("form.tooBig", { max }) } : { value: number };
};

const levelParse = (range) => (text, t) => {
  const number = Number(text);
  if (!Number.isInteger(number)) return { error: t("safety.form.levelWhole") };
  if (range && number < range[0]) return { error: t("form.tooSmall", { min: range[0] }) };
  if (range && number > range[1]) return { error: t("form.tooBig", { max: range[1] }) };
  return { value: number };
};

function frozenFields(ctx, sensors, current) {
  const { t } = ctx;
  const gap = {
    name: "max_gap_seconds", type: "number", required: true, label: t("safety.frozenGap"), unit: t("safety.form.seconds"),
    hint: t("safety.form.gapHint", { max: MAX_FROZEN_GAP_SECONDS }), value: current?.frozen?.max_gap_seconds, parse: positive(MAX_FROZEN_GAP_SECONDS),
  };
  const perSensor = sensors.map((sensor) => ({
    name: sensor, type: "number", label: t("safety.form.frozenMinutes", { sensor: labelOr(t, "metric", sensor) }), unit: t("safety.form.minutes"),
    hint: t("safety.form.frozenHint", { max: MAX_FROZEN_MINUTES }), value: current?.frozen?.minutes?.[sensor], parse: positive(MAX_FROZEN_MINUTES),
  }));
  return [gap, ...perSensor];
}

function levelOverview(t, capabilities, channels) {
  const ranges = channels.filter((channel) => capabilities?.level_ranges?.[channel]).map((channel) => {
    const [min, max] = capabilities.level_ranges[channel];
    return t("safety.form.rangeItem", { channel: labelOr(t, "channel", channel), min, max });
  });
  return ranges.length ? t("safety.form.levelRanges", { ranges: ranges.join("; ") }) : undefined;
}

function ruleFields(ctx, { sensors, channels, capabilities }) {
  const { t } = ctx;
  const choice = (name, label, options) => ({ name, label, type: "select", required: true, options: [{ value: "", label: "—" }, ...options] });
  const seconds = (name, label) => ({ name, label, type: "number", required: true, min: 0, unit: t("safety.form.seconds"), hint: t("safety.form.secondsHint") });
  return [
    { name: "id", label: t("safety.form.ruleName"), hint: t("safety.form.ruleNameHint") },
    choice("sensor", t("safety.sensor"), sensors.map((value) => ({ value, label: labelOr(t, "metric", value) }))),
    choice("op", t("safety.form.op"), OPS.map((value) => ({ value, label: labelOr(t, "safety.op", value) }))),
    { name: "value", label: t("safety.form.value"), type: "number", required: true, unit: "" },
    seconds("duration_seconds", t("safety.form.duration")),
    seconds("validity_seconds", t("safety.form.validity")),
    choice("channel", t("safety.form.channel"), channels.map((value) => ({ value, label: labelOr(t, "channel", value) }))),
    { name: "level", label: t("safety.form.level"), type: "number", required: true, hint: levelOverview(t, capabilities, channels) },
  ];
}

function findByClass(node, name) {
  if (node.classList && node.classList.contains(name)) return node;
  for (const child of node.children || []) {
    const found = findByClass(child, name);
    if (found) return found;
  }
  return null;
}

// A row's unit follows its sensor and its level range follows its output; the person types neither.
function linkRow(ctx, capabilities, units, channels) {
  return (entries) => {
    const named = (name) => entries.find((entry) => entry.field.name === name);
    const [sensor, channel, value, level] = ["sensor", "channel", "value", "level"].map(named);
    const unit = findByClass(value.row, "field-unit");
    const hint = findByClass(level.row, "field-hint");
    const sync = () => {
      unit.textContent = unitText(units[sensor.input.value]);
      const range = capabilities?.level_ranges?.[channel.input.value];
      level.field = { ...level.field, parse: levelParse(range) };
      for (const [attr, at] of [["min", 0], ["max", 1]]) {
        if (range) level.input.setAttribute(attr, String(range[at]));
        else level.input.removeAttribute(attr);
      }
      const overview = levelOverview(ctx.t, capabilities, channels);
      if (hint) hint.textContent = range ? ctx.t("safety.form.levelRange", { min: range[0], max: range[1] }) : overview || "";
    };
    sensor.input.addEventListener("change", sync);
    channel.input.addEventListener("change", sync);
    sync();
  };
}

const ruleRow = (rule) => ({
  id: rule?.id, sensor: rule?.sensor, op: rule?.trigger?.op, value: rule?.trigger?.value,
  duration_seconds: rule?.duration_seconds, validity_seconds: rule?.validity_seconds, channel: rule?.action?.channel, level: rule?.action?.level,
});

// Exactly the object the JSON editor would send for the same content (no approver, no time stamp).
export function buildConfig(current, values, units, frozen) {
  const minutes = Object.fromEntries(frozen.filter((sensor) => values[sensor] !== undefined).map((sensor) => [sensor, values[sensor]]));
  const rules = values.rules.map((row, index) => ({
    id: row.id?.trim() || `${row.sensor}-${row.channel}-${index + 1}`,
    sensor: row.sensor,
    unit: units[row.sensor],
    validity_seconds: row.validity_seconds,
    trigger: { op: row.op, value: row.value },
    duration_seconds: row.duration_seconds,
    action: { channel: row.channel, level: row.level },
  }));
  return { version: (current?.version ?? 0) + 1, rules, frozen: { minutes, max_gap_seconds: values.max_gap_seconds } };
}

function leadLines(ctx, current, capabilities) {
  const lines = [h("p", { class: "note", text: ctx.t("safety.form.version", { version: (current?.version ?? 0) + 1 }) })];
  if (!current) lines.push(h("p", { class: "note", text: ctx.t("safety.form.noneLead") }));
  if (!capabilities) lines.push(h("p", { class: "note", text: ctx.t("safety.form.noCaps") }));
  return lines;
}

// capabilities is null when they could not be read: then only the sensors of the approved set are offered, and no range is shown.
export function safetyForm(ctx, { current, capabilities, onSubmit }) {
  const units = sensorUnits(current, capabilities);
  const frozen = frozenSensors(current, units);
  if (frozen.length === 0) return h("p", { class: "note", text: ctx.t("safety.form.useJson") });
  const rules = array(current?.rules);
  const channels = unique([...CHANNELS, ...rules.map((rule) => rule?.action?.channel).filter(Boolean)]);
  const group = rowGroup({
    ctx, name: "rules", label: ctx.t("safety.form.rules"), fields: ruleFields(ctx, { sensors: Object.keys(units).sort(), channels, capabilities }),
    rows: rules.map(ruleRow), addLabel: ctx.t("safety.form.addRule"), removeLabel: ctx.t("safety.form.removeRule"),
    maxRows: Object.keys(units).length ? Infinity : 0, onRow: linkRow(ctx, capabilities, units, channels),
  });
  const form = simpleForm({
    fields: frozenFields(ctx, frozen, current), parts: [group], ctx, draftKey: "safety-form", submitLabel: ctx.t("safety.approve"),
    onSubmit: (values) => onSubmit(buildConfig(current, values, units, frozen)),
  });
  return h("div", { class: "safety-form" }, leadLines(ctx, current, capabilities), form);
}
