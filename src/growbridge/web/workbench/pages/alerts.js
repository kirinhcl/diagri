// Open alerts: how bad, how often, since when, and who has read them.
import { h } from "../ui/dom.js";
import { errorBox, note, pageHead, section, showErrors, timeText } from "../ui/section.js";
import { severityPill } from "../ui/status.js";
import { table } from "../ui/table.js";
import { isNotMounted } from "./not-mounted.js";

function readCell(ctx, alert) {
  if (alert.read_by) return ctx.t("alerts.readBy", { name: alert.read_by, time: timeText(ctx, alert.read_at) });
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
  return h("div", { class: "action" }, button, box);
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
