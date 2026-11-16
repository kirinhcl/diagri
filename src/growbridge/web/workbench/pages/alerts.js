// Open alerts: how bad, how often, since when, and who has read them.
import { labelOr } from "../i18n.js";
import { h } from "../ui/dom.js";
import { errorBox, note, pageHead, section, showErrors, timeCell, timeText } from "../ui/section.js";
import { severityPill } from "../ui/status.js";
import { table } from "../ui/table.js";
import { isNotMounted } from "./not-mounted.js";

const SEVERITY_ORDER = ["info", "warning", "critical"]; // mildest first
const nowSeconds = () => Date.now() / 1000;
export const REASK_SECONDS = 24 * 3600; // observer/alerts.py REASK_SECONDS

// The inbox's rule (observer/alerts.py awaits_reading): unread, or worse than the severity it was
// read at, or read more than a day ago by the clock (`now`, in seconds); a clock behind the reading or the
// last raise counts as unread (the browser clock is taken as trusted). A read recorded without its severity waits once more.
export function alertWaiting(alert, now) {
  if (!alert || alert.read_at === null || alert.read_at === undefined) return true;
  const readAt = SEVERITY_ORDER.indexOf(alert.read_severity);
  if (readAt < 0 || SEVERITY_ORDER.indexOf(alert.severity) > readAt) return true;
  return now < Math.max(alert.read_at, alert.last_at || 0) || now - alert.read_at > REASK_SECONDS;
}

// One phrase about the reading: unread, who read it and when, or read before it got worse.
export function readLine(ctx, alert) {
  if (!alert.read_by) return ctx.t("alerts.unread");
  const worse = !alert.read_severity || SEVERITY_ORDER.indexOf(alert.severity) > SEVERITY_ORDER.indexOf(alert.read_severity);
  if (worse) return ctx.t("alerts.readWorse");
  return ctx.t("alerts.readBy", { who: alert.read_by, time: timeText(ctx, alert.read_at) });
}

// The first line is the summary; the lines after it are what the alert found, one list item each.
function messageCell(message) {
  const lines = String(message ?? "").split("\n").map((line) => line.trim()).filter(Boolean);
  const [summary = "", ...rest] = lines;
  const items = rest.map((line) => h("li", { text: line.replace(/^-\s+/, "") }));
  return h("div", { class: "cell-stack" }, h("p", { text: summary }), items.length ? h("ul", {}, items) : null);
}

function readCell(ctx, alert) {
  const said = readLine(ctx, alert);
  if (!alertWaiting(alert, nowSeconds())) return h("p", { class: "block-note", text: said });
  const box = errorBox();
  const label = ctx.t("alerts.markRead");
  const button = h("button", { class: "button button-quiet", attrs: { type: "button" }, text: label });
  button.addEventListener("click", async () => {
    box.hidden = true;
    button.disabled = true;
    try {
      await ctx.api.post(`/alerts/${encodeURIComponent(alert.event_id)}/read`, {}, { action: label });
    } catch (error) {
      showErrors(box, error, ctx);
      button.disabled = false;
      return;
    }
    // The list and the sidebar count are read again; nothing is shown as read before the server agrees.
    ctx.notify(ctx.t("alerts.wasRead"), "ok");
    ctx.reload();
  });
  return h("div", { class: "action" }, h("p", { class: "block-note", text: said }), button, box);
}

function alertsTable(ctx, alerts, focus) {
  const columns = [
    { label: ctx.t("alerts.severity"), cell: (row) => severityPill(ctx.t, row.severity) },
    { label: ctx.t("alerts.kind"), cell: (row) => labelOr(ctx.t, "alert.kind", row.kind) },
    { label: ctx.t("alerts.message"), cell: (row) => messageCell(row.message) },
    { label: ctx.t("alerts.count"), cell: (row) => String(row.count) },
    { label: ctx.t("alerts.first"), cell: (row) => timeCell(ctx, row.first_at) },
    { label: ctx.t("alerts.last"), cell: (row) => timeCell(ctx, row.last_at) },
    { label: ctx.t("alerts.read"), cell: (row) => readCell(ctx, row) },
  ];
  const rowProps = (row) => ({
    class: focus && row.event_id === focus ? "alert-focused" : undefined,
    attrs: { id: `alert-${row.event_id}` },
  });
  return table(columns, alerts, { label: ctx.t("alerts.title"), rowProps });
}

// Once the page is in the document: bring the linked alert's row into view (a no-op without scrollIntoView).
function scrollToAlert(element, focus) {
  const rows = (node) => [...(node.children || [])].flatMap((child) => [child, ...rows(child)]);
  const row = rows(element).find((el) => el.localName === "tr" && el.getAttribute("id") === `alert-${focus}`);
  if (!row || typeof row.scrollIntoView !== "function") return;
  setTimeout(() => row.scrollIntoView({ block: "center" }), 0);
}

async function loadAlerts(ctx) {
  try {
    const data = await ctx.api.get("/alerts");
    return { alerts: Array.isArray(data && data.alerts) ? data.alerts : [], mounted: true };
  } catch (error) {
    if (!isNotMounted(error)) throw error;
    return { alerts: [], mounted: false };
  }
}

export async function render(ctx, params = {}) {
  const { alerts, mounted } = await loadAlerts(ctx);
  let body = alertsTable(ctx, alerts, params.focus);
  if (!mounted) body = note(ctx.t("alerts.unavailable"));
  else if (!alerts.length) body = note(ctx.t("alerts.empty"));
  const element = h(
    "div",
    { class: "page alerts" },
    pageHead(ctx.t("nav.alerts"), ctx.t("alerts.lead")),
    section(ctx.t("alerts.title"), body),
  );
  if (params.focus) scrollToAlert(element, params.focus);
  return { element };
}
