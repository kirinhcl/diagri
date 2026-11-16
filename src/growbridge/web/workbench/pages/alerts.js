// Open alerts: how bad, how often, since when, and who has read them.
import { labelOr } from "../i18n.js";
import { h } from "../ui/dom.js";
import { errorBox, note, pageHead, section, showErrors, timeText } from "../ui/section.js";
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

function readLine(ctx, alert) {
  const read = { name: alert.read_by, time: timeText(ctx, alert.read_at) };
  if (!alertWaiting(alert, nowSeconds())) return ctx.t("alerts.readBy", read);
  if (!alert.read_severity) return ctx.t("alerts.readBefore", read);
  if (SEVERITY_ORDER.indexOf(alert.severity) <= SEVERITY_ORDER.indexOf(alert.read_severity)) {
    return ctx.t("alerts.readStale", { ...read, last: timeText(ctx, alert.last_at) });
  }
  const severity = labelOr(ctx.t, "severity", alert.severity);
  return ctx.t("alerts.readWorsened", { ...read, severity, last: timeText(ctx, alert.last_at) });
}

function readCell(ctx, alert) {
  const said = alert.read_by ? readLine(ctx, alert) : null;
  if (!alertWaiting(alert, nowSeconds())) return said;
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
  return h("div", { class: "action" }, said ? h("p", { class: "block-note", text: said }) : null, button, box);
}

function alertsTable(ctx, alerts) {
  const columns = [
    { label: ctx.t("alerts.severity"), cell: (row) => severityPill(ctx.t, row.severity) },
    { label: ctx.t("alerts.message"), cell: (row) => row.message },
    { label: ctx.t("alerts.count"), cell: (row) => String(row.count) },
    { label: ctx.t("alerts.first"), cell: (row) => timeText(ctx, row.first_at) },
    { label: ctx.t("alerts.last"), cell: (row) => timeText(ctx, row.last_at) },
    { label: ctx.t("alerts.read"), cell: (row) => readCell(ctx, row) },
  ];
  return table(columns, alerts, { label: ctx.t("alerts.title") });
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

export async function render(ctx) {
  const { alerts, mounted } = await loadAlerts(ctx);
  const zone = (ctx.me && ctx.me.timezone) || "UTC";
  let body = alertsTable(ctx, alerts);
  if (!mounted) body = note(ctx.t("alerts.unavailable"));
  else if (!alerts.length) body = note(ctx.t("alerts.empty"));
  const element = h(
    "div",
    { class: "page alerts" },
    pageHead(ctx.t("nav.alerts"), ctx.t("alerts.lead", { zone })),
    section(ctx.t("alerts.title"), body),
  );
  return { element };
}
