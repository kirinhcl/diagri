// The stage's history: state changes and interventions on one timeline, told in sentences, newest first.
import { formatDuration, levelText, shortDigest } from "../format.js";
import { hasLabel, labelOr } from "../i18n.js";
import { h } from "../ui/dom.js";
import { note, techDetails, timeText } from "../ui/section.js";
import { statePill } from "../ui/status.js";
import { differenceText } from "./stage-diff.js";

export const HISTORY_SHOWN = 20;

// Intervention fields the line itself already shows; everything else is its detail.
const SAID_IN_LINE = new Set(["stage_id", "at", "kind", "operator"]);
// In the catalog, but only ever meaningful as raw values.
const ALWAYS_RAW = new Set(["right_number", "request_id", "request_ids", "period", "alert"]);

const listOf = (value) => (Array.isArray(value) ? value : []);
const isPlain = (value) => value !== null && typeof value === "object";

// Newest first: the stable ascending order (a transition before an intervention of the same
// second) reversed as a whole.
export function timeline(history, interventions) {
  const moves = listOf(history).map((row) => ({
    type: "transition",
    at: row.at,
    from: row.from,
    to: row.to,
    event: row.event,
    detail: row.detail || {},
  }));
  const acts = listOf(interventions).map((row) => ({
    type: "intervention",
    at: row.at,
    kind: row.kind,
    operator: row.operator,
    detail: Object.fromEntries(Object.entries(row).filter(([key]) => !SAID_IN_LINE.has(key))),
  }));
  return [...moves, ...acts].sort((a, b) => a.at - b.at).reverse(); // sort is stable
}

const isKnown = hasLabel;

// Value-writers by key; each returns text, or null when the value can only go to the details.
const CODE_FIELDS = { on_expiry: "history.onExpiry", channel: "channel" };
const FROZEN_RULE = /^frozen:(.+)$/;

function valueLine(ctx, key, value, detail) {
  const { t } = ctx;
  const join = (items) => items.join(t("history.listJoin"));
  if (typeof value === "boolean") return t(value ? "common.yes" : "common.no");
  if (key === "differences") return Array.isArray(value) ? join(value.map((item) => differenceText(t, item))) : null;
  if (key === "reasons") return Array.isArray(value) ? join(value.map((code) => labelOr(t, "history.reason", code))) : null;
  if (key === "reason") return isKnown(t, "history.reason", value) ? labelOr(t, "history.reason", value) : null;
  if (key in CODE_FIELDS) return typeof value === "string" ? labelOr(t, CODE_FIELDS[key], value) : null;
  if (key === "level") return typeof value === "number" ? levelText(t, detail.channel, value) : null;
  if (key === "rule" && typeof value === "string") return FROZEN_RULE.test(value) ? labelOr(t, "metric", value.match(FROZEN_RULE)[1]) : value; // else a rule name
  if (key === "note") return typeof value === "string" && value ? value : null; // the operator's own words
  if (key === "digest") return typeof value === "string" ? shortDigest(value) : null;
  if (/seconds$/.test(key)) return typeof value === "number" ? formatDuration(t, value) : null;
  if (/_at$/.test(key)) return typeof value === "number" ? timeText(ctx, value) : null;
  return typeof value === "number" ? String(value) : null; // other text has no catalog meaning
}

const fieldLabel = (t, key) => labelOr(t, "history.field", key);
const isKnownKey = (t, key) => !ALWAYS_RAW.has(key) && isKnown(t, "history.field", key);

// The labelled sentences for an entry's detail, and the values that belong in its technical
// details: unknown keys, ids, free text, the event code when unknown, and the whole original detail.
export function detailLines(ctx, entry) {
  const { t } = ctx;
  const detail = isPlain(entry.detail) && !Array.isArray(entry.detail) ? entry.detail : {};
  const lines = [];
  const raw = [];
  for (const [key, value] of Object.entries(detail)) {
    const line = isKnownKey(t, key) ? valueLine(ctx, key, value, detail) : null;
    if (line !== null) lines.push(t("history.line", { label: fieldLabel(t, key), value: line }));
    else raw.push([isKnown(t, "history.field", key) ? `${fieldLabel(t, key)} (${key})` : key, value]);
  }
  const transition = entry.type === "transition";
  const code = transition ? entry.event : entry.kind;
  if (code && !isKnown(t, transition ? "history.event" : "history.kind", code)) raw.unshift([t("tech.eventCode"), code]);
  if (Object.keys(detail).length) raw.push([t("tech.rawEvent"), detail]);
  return { lines, raw };
}

function pills(ctx, entry) {
  if (entry.type !== "transition" || entry.from === entry.to) return null;
  const arrow = h("span", { attrs: { "aria-hidden": "true" }, text: "→" });
  return h("span", { class: "timeline-states" }, statePill(ctx.t, entry.from), arrow, statePill(ctx.t, entry.to));
}

function title(ctx, entry) {
  if (entry.type === "intervention") return labelOr(ctx.t, "history.kind", entry.kind);
  return entry.event ? labelOr(ctx.t, "history.event", entry.event) : ctx.t("history.stateChange");
}

function entryView(ctx, entry) {
  const { lines, raw } = detailLines(ctx, entry);
  if (entry.type === "intervention" && entry.operator) lines.unshift(ctx.t("history.by", { operator: entry.operator }));
  const iso = Number.isFinite(entry.at) ? new Date(entry.at * 1000).toISOString() : null;
  return h(
    "li",
    { class: ["timeline-item", `timeline-${entry.type}`] },
    h("time", { class: "timeline-time", attrs: { datetime: iso }, text: timeText(ctx, entry.at) }),
    h("p", { class: "timeline-what" }, title(ctx, entry), pills(ctx, entry)),
    lines.map((line) => h("p", { class: "timeline-detail", text: line })),
    techDetails(ctx.t, raw),
  );
}

const list = (ctx, entries) => h("ol", { class: "timeline" }, entries.map((entry) => entryView(ctx, entry)));

export function historyView(ctx, data) {
  const entries = timeline(data && data.history, data && data.interventions);
  if (!entries.length) return note(ctx.t("history.empty"));
  const older = entries.slice(HISTORY_SHOWN);
  const fold = older.length
    ? h("details", { class: "timeline-older" }, h("summary", { text: ctx.t("history.earlier", { count: older.length }) }), list(ctx, older))
    : null;
  return h("div", { class: "timeline-wrap" }, list(ctx, entries.slice(0, HISTORY_SHOWN)), fold);
}
