// "My inbox": everything that waits for a person, grouped by kind and refreshed every 15 seconds.
import { singleFlight } from "../api.js";
import { formatTime } from "../format.js";
import { labelOr } from "../i18n.js";
import { hrefFor } from "../router.js";
import { clear, h } from "../ui/dom.js";
import { errorParts, replaceParts } from "../ui/section.js";
import { severityPill, statePill } from "../ui/status.js";

const POLL_SECONDS = 15;
// Most urgent first: on-site checks and alerts, then decisions waiting on a person, then the rest.
export const KIND_ORDER = [
  "stage_recovery",
  "alert",
  "stage_review",
  "stage_manual",
  "stage_paused",
  "round_choice",
  "compute_stuck",
  "task",
];
const STAGE_KINDS = new Set(["stage_review", "stage_manual", "stage_recovery", "stage_paused"]);
const ONSITE_KINDS = new Set(["stage_recovery", "alert"]);

export function inboxTarget(item) {
  if (STAGE_KINDS.has(item.kind)) return hrefFor("stage", { stageId: item.id });
  if (item.kind === "round_choice") return hrefFor("round", { roundId: item.id });
  if (item.kind === "alert") return hrefFor("alerts");
  if (item.kind === "compute_stuck") return hrefFor("compute");
  if (item.kind === "task") {
    return item.project_id ? hrefFor("project", { projectId: item.project_id }) : hrefFor("projects");
  }
  return null;
}

// The server's answer, with anything malformed dropped rather than trusted.
export function normalizeInbox(data) {
  const usable = (item) => item && typeof item.kind === "string" && item.id !== null && item.id !== undefined;
  const items = data && Array.isArray(data.items) ? data.items.filter(usable) : [];
  const raw = data && data.truncated && typeof data.truncated === "object" ? data.truncated : {};
  const truncated = Object.fromEntries(Object.entries(raw).filter(([, count]) => Number.isInteger(count) && count > 0));
  return { items, truncated };
}

export function inboxCounts(data) {
  const { items, truncated } = normalizeInbox(data);
  const hidden = Object.values(truncated).reduce((sum, count) => sum + count, 0);
  const alerts = items.filter((item) => item.kind === "alert").length + (truncated.alert || 0);
  return { inbox: items.length + hidden, alerts };
}

// Kinds in KIND_ORDER first, then any kind this console does not know yet, in arrival order.
export function groupByKind({ items, truncated }) {
  const kinds = [...new Set([...KIND_ORDER, ...items.map((item) => item.kind), ...Object.keys(truncated)])];
  return kinds
    .map((kind) => ({ kind, items: items.filter((item) => item.kind === kind), hidden: truncated[kind] || 0 }))
    .filter((group) => group.items.length > 0 || group.hidden > 0);
}

function timeText(ctx, epoch) {
  if (typeof epoch !== "number" || !Number.isFinite(epoch)) return "—";
  const zone = (ctx.me && ctx.me.timezone) || "UTC";
  return `${formatTime(epoch, zone, ctx.lang)} ${zone}`;
}

// The text for key, or null when one of its values is missing.
function say(t, key, vars) {
  const present = Object.values(vars).every((value) => value !== undefined && value !== null && value !== "");
  return present ? t(key, vars) : null;
}

function where(ctx, item) {
  const round = item.kind === "round_choice" ? null : say(ctx.t, "inbox.round", { id: item.round_id });
  return [say(ctx.t, "inbox.project", { id: item.project_id }), round];
}

const DESCRIBERS = {
  stage: (ctx, item, d) => ({
    title: ctx.t("inbox.stage", { id: item.id }),
    pill: statePill(ctx.t, d.state),
    meta: [say(ctx.t, "inbox.device", { id: d.device_id }), ...where(ctx, item)],
  }),
  round_choice: (ctx, item, d) => ({
    title: ctx.t("inbox.round", { id: item.id }),
    pill: statePill(ctx.t, "awaiting_choice"),
    lines: [
      say(ctx.t, "inbox.roundChoice", { stage: d.awaiting_choice }),
      d.since_from === "round_created" ? ctx.t("inbox.sinceRoundCreated") : null,
    ],
    meta: where(ctx, item),
  }),
  alert: (ctx, item, d) => ({
    title: d.message || String(item.id),
    pill: severityPill(ctx.t, d.severity),
    meta: [d.alert_kind, say(ctx.t, "inbox.alertCount", { count: d.count }), d.last_at ? ctx.t("inbox.lastAt", { time: timeText(ctx, d.last_at) }) : null],
  }),
  compute_stuck: (ctx, item, d) => ({
    title: ctx.t("inbox.attempt", { id: item.id }),
    pill: statePill(ctx.t, d.phase),
    lines: [d.reason],
    meta: [say(ctx.t, "inbox.task", { id: d.task_id })],
  }),
  task: (ctx, item, d) => ({
    title: d.question || ctx.t("inbox.task", { id: item.id }),
    pill: statePill(ctx.t, d.state),
    meta: [say(ctx.t, "inbox.owner", { role: d.owner_role }), ...where(ctx, item)],
  }),
};

function describe(ctx, item) {
  const detail = item.detail && typeof item.detail === "object" ? item.detail : {};
  const kind = STAGE_KINDS.has(item.kind) ? "stage" : item.kind;
  const fallback = () => ({ title: `${item.kind} ${item.id}`, meta: where(ctx, item) });
  const describer = Object.hasOwn(DESCRIBERS, kind) ? DESCRIBERS[kind] : fallback;
  return { pill: null, lines: [], meta: [], ...describer(ctx, item, detail) };
}

function itemView(ctx, item) {
  const { title, pill, lines, meta } = describe(ctx, item);
  const href = inboxTarget(item);
  const main = h(
    "div",
    { class: "inbox-main" },
    h("p", { class: "inbox-title", text: title }),
    lines.filter(Boolean).map((line) => h("p", { class: "inbox-text", text: line })),
    h("p", { class: "inbox-meta" }, meta.filter(Boolean).map((part) => h("span", { text: part }))),
  );
  const side = h("div", { class: "inbox-side" }, pill, h("span", { class: "inbox-time", text: timeText(ctx, item.since) }));
  const key = `${item.kind}:${item.id}`;
  const view = href
    ? h("a", { class: "inbox-item", attrs: { href, "data-key": key } }, main, side)
    : h("div", { class: "inbox-item", attrs: { "data-key": key } }, main, side);
  return h("li", {}, view);
}

function groupView(ctx, group) {
  const headingId = `inbox-group-${group.kind}`;
  const tone = ONSITE_KINDS.has(group.kind) ? "tone-onsite" : "tone-waiting";
  const count = group.items.length + group.hidden;
  return h(
    "section",
    { class: ["inbox-group", tone], attrs: { "aria-labelledby": headingId } },
    h(
      "header",
      { class: "inbox-group-head" },
      h("h2", { attrs: { id: headingId }, text: labelOr(ctx.t, "inbox.kind", group.kind) }),
      h("span", { class: "inbox-group-count", text: String(count) }),
    ),
    h("ul", { class: "inbox-list" }, group.items.map((item) => itemView(ctx, item))),
    group.hidden > 0 ? h("p", { class: "inbox-more", text: ctx.t("inbox.more", { count: group.hidden }) }) : null,
  );
}

function emptyView(ctx) {
  return h("div", { class: "inbox-empty" }, h("p", { text: ctx.t("inbox.empty") }));
}

// Redraws only when the answer changed, keeping keyboard focus on the same item when it is still there.
function draw(view, ctx, data) {
  const inbox = normalizeInbox(data);
  if (ctx.setCounts) ctx.setCounts(inboxCounts(inbox));
  view.updated.textContent = ctx.t("inbox.updated", { time: timeText(ctx, Date.now() / 1000), seconds: POLL_SECONDS });
  const signature = JSON.stringify(inbox);
  if (signature === view.signature) return;
  view.signature = signature;
  const focused = view.list.contains(document.activeElement) ? document.activeElement : null;
  const key = focused && focused.getAttribute("data-key");
  const groups = groupByKind(inbox);
  clear(view.list).append(...(groups.length ? groups.map((group) => groupView(ctx, group)) : [emptyView(ctx)]));
  const again = key ? [...view.list.querySelectorAll("[data-key]")].find((el) => el.getAttribute("data-key") === key) : null;
  if (again) again.focus();
}

function pageView(ctx) {
  const updated = h("p", { class: "page-sub" });
  const problem = h("div", { class: "form-status form-status-error", attrs: { role: "status", hidden: true } });
  const refreshButton = h("button", { class: "button button-quiet", attrs: { type: "button" }, text: ctx.t("inbox.refresh") });
  const list = h("div", { class: "inbox-groups" });
  const title = h("div", {}, h("h1", { text: ctx.t("nav.inbox") }), h("p", { class: "page-lead", text: ctx.t("inbox.lead") }), updated);
  const head = h("header", { class: "page-head" }, title, refreshButton);
  const element = h("div", { class: "page inbox" }, head, problem, list);
  return { element, updated, problem, refreshButton, list, signature: null };
}

export async function render(ctx) {
  const view = pageView(ctx);
  const load = async () => draw(view, ctx, await ctx.api.get("/inbox"));
  await load();
  const refresh = singleFlight(async () => {
    try {
      await load();
      view.problem.hidden = true;
    } catch (error) {
      replaceParts(view.problem, [h("p", { text: ctx.t("inbox.stale") }), ...errorParts(ctx, error)]);
      view.problem.hidden = false;
    }
  });
  view.refreshButton.addEventListener("click", () => refresh());
  return { element: view.element, refresh, pollSeconds: POLL_SECONDS };
}
