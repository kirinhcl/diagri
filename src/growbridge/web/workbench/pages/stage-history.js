// The stage's history: state changes and interventions on one timeline, oldest first.
import { h } from "../ui/dom.js";
import { note, timeText } from "../ui/section.js";
import { statePill } from "../ui/status.js";

// Intervention fields the line itself already shows; everything else is its detail.
const SAID_IN_LINE = new Set(["stage_id", "at", "kind", "operator"]);

const listOf = (value) => (Array.isArray(value) ? value : []);

// New entries sorted by time; a transition stays before an intervention of the same moment.
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
  return [...moves, ...acts].sort((a, b) => a.at - b.at); // sort is stable
}

export function detailText(detail) {
  if (!detail || typeof detail !== "object") return "";
  return Object.entries(detail)
    .map(([key, value]) => `${key}: ${value !== null && typeof value === "object" ? JSON.stringify(value) : String(value)}`)
    .join(" · ");
}

function headline(ctx, entry) {
  if (entry.type === "transition") {
    return h("p", { class: "timeline-what" }, statePill(ctx.t, entry.from), h("span", { attrs: { "aria-hidden": "true" }, text: "→" }), statePill(ctx.t, entry.to));
  }
  return h("p", { class: "timeline-what", text: ctx.t("history.intervention", { kind: entry.kind }) });
}

function entryView(ctx, entry) {
  const lines = [];
  if (entry.type === "transition" && entry.event) lines.push(ctx.t("history.event", { event: entry.event }));
  if (entry.type === "intervention" && entry.operator) lines.push(ctx.t("history.by", { operator: entry.operator }));
  const detail = detailText(entry.detail);
  if (detail) lines.push(detail);
  const iso = Number.isFinite(entry.at) ? new Date(entry.at * 1000).toISOString() : null;
  return h(
    "li",
    { class: ["timeline-item", `timeline-${entry.type}`] },
    h("time", { class: "timeline-time", attrs: { datetime: iso }, text: timeText(ctx, entry.at) }),
    headline(ctx, entry),
    lines.map((line) => h("p", { class: "timeline-detail", text: line })),
  );
}

export function historyView(ctx, data) {
  const entries = timeline(data && data.history, data && data.interventions);
  if (!entries.length) return note(ctx.t("history.empty"));
  return h("ol", { class: "timeline" }, entries.map((entry) => entryView(ctx, entry)));
}
