// Messages the server sends as a code plus params. The text lives in the catalogs under
// msg.<family>.<code> (and .action for the next step); the placeholders are filled here by
// parameter name, with the rules of the params contract (formatterFor). A missing or ill-typed
// param shows a dash; a key or a code is never printed as text.
import { METRICS } from "./chart-math.js";
import { formatDuration, formatNumber, levelText } from "./format.js";
import { labelOr, textOr } from "./i18n.js";
import { unitText } from "./pages/safety-text.js";
import { h } from "./ui/dom.js";
import { roleLabel } from "./ui/names.js";
import { techDetails, timeText } from "./ui/section.js";

const DASH = "—";
const PERCENT = 100;
const ID_NAME = /_ids?$/;

const isText = (v) => typeof v === "string" && v !== "";
const isNum = (v) => typeof v === "number" && Number.isFinite(v);
const guarded = (ok, show) => (ctx, v, params) => (ok(v) ? show(ctx, v, params) : DASH);
const labelled = (prefix) => guarded(isText, (ctx, v) => labelOr(ctx.t, prefix, v));
const listOf = (item) => guarded(
  (v) => Array.isArray(v) && v.length > 0,
  (ctx, v, params) => {
    const shown = v.map((x) => item(ctx, x, params));
    return shown.includes(DASH) ? DASH : shown.join(ctx.t("common.listSep"));
  },
);

const quote = guarded(isText, (ctx, v) => ctx.t("common.quoted", { text: v }));
const count = guarded(isNum, (ctx, v) => formatNumber(v, 0, ctx.lang));
const level = guarded(isNum, (ctx, v, params) => levelText(ctx.t, params?.channel, v));
const duration = guarded(isNum, (ctx, v) => formatDuration(ctx.t, v));
const clock = guarded(isNum, (ctx, v) => timeText(ctx, v));
const MAX_DECIMALS = 6;
const AMOUNT_DECIMALS = 2;

// A bound as it is: as many decimals as the number itself has, up to six.
const plainNumber = guarded(isNum, (ctx, v) => {
  const decimals = Math.min(MAX_DECIMALS, (String(v).split(".")[1] || "").length);
  return formatNumber(v, decimals, ctx.lang);
});
const amount = guarded(isNum, (ctx, v, params) => `${formatNumber(v, AMOUNT_DECIMALS, ctx.lang)} ${labelOr(ctx.t, "computeUnit", params?.resource)}`);

function sensorValue(ctx, v, params) {
  if (!isNum(v)) return DASH;
  const metric = METRICS.find((m) => m.key === params?.sensor);
  if (!metric) return String(v);
  return `${formatNumber(v, metric.precision, ctx.lang)} ${metric.unit}`;
}

function problem(ctx, p) {
  if (!p) return DASH;
  const vars = {
    channel: labelOr(ctx.t, "channel", p.channel),
    level: level(ctx, p.level, p),
    other: level(ctx, p.other, p),
  };
  return textOr(ctx.t, "findingProblem", p.kind, vars) ?? DASH;
}

// The next step for a citation of a replaced card: its replacement while that is in force, otherwise
// a new card or a user input, naming the replacement's own status (design §5.3).
function replacementStep(ctx, v) {
  if (v === "active") return ctx.t("evidence.citeReplacement");
  if (!isText(v)) return ctx.t("evidence.noReplacementStep");
  return ctx.t("evidence.replacementInactive", { validity: labelOr(ctx.t, "evidence.validity", v) });
}

const EXACT = {
  at_local: guarded(isText, (ctx, v) => v),
  sensor: labelled("metric"),
  channel: labelled("channel"),
  value: sensorValue,
  op: labelled("safety.op"),
  state: labelled("state"),
  phase: labelled("state"),
  needed_state: labelled("state"),
  status: labelled("tasks.status"),
  from_status: labelled("tasks.status"),
  to_status: labelled("tasks.status"),
  record_kind: labelled("recordKind"),
  resource: labelled("computeUnit"),
  expected_kind: labelled("paramKind"),
  need_amount: amount,
  available_amount: amount,
  minimum: plainNumber,
  maximum: plainNumber,
  bound: plainNumber,
  field: quote,
  file: quote,
  names: listOf((ctx, x) => quote(ctx, x)),
  choices: listOf((ctx, x) => quote(ctx, x)),
  sensors: listOf((ctx, x) => (isText(x) ? labelOr(ctx.t, "metric", x) : DASH)),
  action_state: labelled("receipt"),
  event: labelled("history.event"),
  role: guarded(isText, (ctx, v) => roleLabel(ctx.t, v)),
  task_kind: labelled("tasks.kind"),
  source_kind: labelled("findingSource"),
  step: labelled("tickStep"),
  signal: labelled("heartbeat"),
  failures: listOf((ctx, x) => (isText(x) ? labelOr(ctx.t, "probe", x) : DASH)),
  channels: listOf((ctx, x) => (isText(x) ? labelOr(ctx.t, "channel", x) : DASH)),
  problems: listOf(problem),
  treatments: listOf((ctx, x) => quote(ctx, x)),
  fraction: guarded(isNum, (ctx, v) => `${formatNumber(v * PERCENT, 0, ctx.lang)}%`),
  device_unit: guarded(isText, (ctx, v) => unitText(v)),
  rule_unit: guarded(isText, (ctx, v) => unitText(v)),
  card_unit: guarded(isText, (ctx, v) => unitText(v)),
  label: labelled("report.labels"),
  replacement_validity: replacementStep,
};
const LEVEL_NAMES = ["level", "min", "max", "expected", "protection_level"];
const QUOTED_NAMES = ["source", "rule", "rule_a", "rule_b", "protection", "treatment", "control", "block", "metric", "name",
  "reason", "rule_variable", "card_variable", "card_taxon", "protocol_taxon"];
// counts: these names, every name ending in "_count" (e.g. file_count, limit_count), and max_*/min_*
const COUNT_NAMES = ["version", "current_version", "attempts", "depth", "count", "blocks", "min_blocks", "flips", "failed", "priority", "round", "mode", "top_rowid", "cursor"];
const BYTE_NAMES = ["bytes", "limit"];
const TIME_NAMES = ["window_start", "window_end"];

const bytes = guarded(isNum, (ctx, v) => ctx.t("common.bytes", { n: formatNumber(v, 0, ctx.lang) }));

// The formatter for a placeholder name, or null when the name may not be a placeholder.
export function formatterFor(name) {
  if (typeof name !== "string" || ID_NAME.test(name)) return null;
  if (name === "seconds" || name.endsWith("_seconds")) return duration;
  if (name.endsWith("_at") || TIME_NAMES.includes(name)) return clock;
  if (name.endsWith("_count") || /^(max|min)_/.test(name) || COUNT_NAMES.includes(name)) return count;
  if (LEVEL_NAMES.includes(name)) return level;
  if (QUOTED_NAMES.includes(name)) return quote;
  if (BYTE_NAMES.includes(name)) return bytes;
  return Object.hasOwn(EXACT, name) ? EXACT[name] : null;
}

function fill(ctx, template, params) {
  return template.replace(/\{(\w+)\}/g, (whole, name) => {
    const format = formatterFor(name);
    return format ? format(ctx, params[name], params) : DASH;
  });
}

function idDetails(params) {
  return Object.entries(params).filter(([name]) => ID_NAME.test(name)).map(([name, value]) => [name, value]);
}

// The text and next step of a message, and the entries for its technical details.
export function messageParts(ctx, family, code, params = {}) {
  const t = ctx.t;
  const safe = params && typeof params === "object" && !Array.isArray(params) ? params : {};
  const prefix = ["msg", family];
  const template = textOr(t, prefix, code);
  const actionTemplate = template === null ? null : textOr(t, [...prefix, code], "action");
  const details = [[t("tech.code"), code], ...idDetails(safe), [t("tech.params"), safe]];
  return {
    known: template !== null,
    text: template === null ? t("common.unknown") : fill(ctx, template, safe),
    action: actionTemplate === null ? null : fill(ctx, actionTemplate, safe),
    details,
  };
}

// The nodes of a message: its text, the next step when there is one, then the technical details.
export function messageView(ctx, family, code, params, { extra = [] } = {}) {
  const parts = messageParts(ctx, family, code, params);
  const nodes = [h("p", { class: "message-text", text: parts.text })];
  if (parts.action) nodes.push(h("p", { class: "message-action", text: parts.action }));
  const fold = techDetails(ctx.t, parts.details.concat(extra));
  if (fold) nodes.push(fold);
  return nodes;
}
